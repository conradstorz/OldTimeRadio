# Era Filtering and Runtime Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the listener cycle through decades at runtime like tuning a station: the radio announces the new era, stops the current show (recording an `Interruption`), and picks from that decade.

**Architecture:** `Catalog` pre-partitions shows by decade (same pattern as shows/commercials). A new `Controls` protocol (`NullControls`, `KeyboardControls`; GPIO later) feeds commands to `Radio`'s existing 1-second wait loop. `AlternatingScheduler` holds the era and filters show picks through `catalog.shows_for(era)`. Spec: `docs/superpowers/specs/2026-09-12-era-filtering-design.md`.

**Tech Stack:** Python 3.11 stdlib only (`enum`, `queue`, `threading`). Tests with pytest via `uv run pytest`.

## Global Constraints

- Run everything with `uv` (`uv run pytest`); never `pip` or bare `python`.
- Do not chain shell commands with `&&`; issue separate Bash calls.
- No new dependencies; no I/O at import time anywhere in `otradio` (thread starts and stdin reads must be lazy).
- The full suite must keep passing hardware-free on Windows. Baseline: 137 tests.
- The scheduler must never sample-until-match; buckets are pre-partitioned.
- Commercials are never era-filtered. Dateless shows play only in the all-eras setting (`era is None`).
- An era is `int | None`: a decade start year (e.g. `1940`) or `None` for all eras.
- CLI/env names exactly: `--era` / `OTRADIO_ERA` (a decade or `all`, default all), `--controls` / `OTRADIO_CONTROLS` (`keyboard` or `none`, default `none`). Malformed values exit via `parser.error()` (SystemExit 2).

---

### Task 1: decade_of and Catalog decade buckets

**Files:**
- Modify: `otradio/dates.py` (add `decade_of`)
- Modify: `otradio/catalog.py` (decade partitioning, `decades`, `shows_for`)
- Test: `tests/test_dates.py`, `tests/test_catalog.py` (append)

**Interfaces:**
- Consumes: `Recording.release_date: date | None`, `Recording.genre` (existing).
- Produces: `otradio.dates.decade_of(d: date) -> int`; `Catalog.decades -> tuple[int, ...]` (sorted, deduplicated, dated shows only); `Catalog.shows_for(era: int | None) -> tuple[Recording, ...]` (`None` → all shows including dateless; a decade → only shows dated in it; unknown decade → `()`). Tasks 4 and 5 rely on these exact names.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dates.py` (add `decade_of` to the existing `from otradio.dates import ...` line, and `from datetime import date` if not present):

```python
def test_decade_of_returns_the_decade_start_year():
    assert decade_of(date(1947, 7, 26)) == 1940


def test_decade_of_is_identity_on_a_decade_start():
    assert decade_of(date(1940, 1, 1)) == 1940


def test_decade_of_handles_the_end_of_a_decade():
    assert decade_of(date(1959, 12, 31)) == 1950


def test_decade_of_handles_a_century_boundary():
    assert decade_of(date(1900, 6, 15)) == 1900
```

Append to `tests/test_catalog.py` (reuse the file's existing imports; add `from datetime import date` and `from pathlib import Path` if missing):

```python
def make_recording(name, genre, release_date=None):
    return Recording(
        id=name,
        filename=name,
        path=Path(name),
        release_date=release_date,
        genre=genre,
    )


def test_decades_lists_the_dated_show_decades_sorted_and_deduplicated():
    catalog = Catalog(
        [
            make_recording("b.mp3", Genre.SHOW, date(1952, 1, 1)),
            make_recording("a.mp3", Genre.SHOW, date(1947, 1, 1)),
            make_recording("c.mp3", Genre.SHOW, date(1943, 1, 1)),
            make_recording("undated.mp3", Genre.SHOW),
        ]
    )
    assert catalog.decades == (1940, 1950)


def test_shows_for_none_returns_every_show_including_dateless():
    dated = make_recording("dated.mp3", Genre.SHOW, date(1947, 1, 1))
    undated = make_recording("undated.mp3", Genre.SHOW)
    catalog = Catalog([dated, undated])
    assert catalog.shows_for(None) == (dated, undated)


def test_shows_for_a_decade_returns_only_shows_dated_in_it():
    forties = make_recording("forties.mp3", Genre.SHOW, date(1947, 1, 1))
    fifties = make_recording("fifties.mp3", Genre.SHOW, date(1952, 1, 1))
    undated = make_recording("undated.mp3", Genre.SHOW)
    catalog = Catalog([forties, fifties, undated])
    assert catalog.shows_for(1940) == (forties,)
    assert catalog.shows_for(1950) == (fifties,)


def test_shows_for_an_absent_decade_returns_empty():
    catalog = Catalog([make_recording("a.mp3", Genre.SHOW, date(1947, 1, 1))])
    assert catalog.shows_for(1930) == ()


def test_shows_for_never_returns_commercials_even_dated_ones():
    commercial = make_recording("commercial.mp3", Genre.COMMERCIAL, date(1947, 1, 1))
    show = make_recording("show.mp3", Genre.SHOW, date(1947, 1, 1))
    catalog = Catalog([commercial, show])
    assert catalog.shows_for(None) == (show,)
    assert catalog.shows_for(1940) == (show,)
    assert catalog.decades == (1940,)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_dates.py tests/test_catalog.py -v`
Expected: new tests FAIL (`ImportError: cannot import name 'decade_of'`, `AttributeError: 'Catalog' object has no attribute 'decades'`); existing tests PASS.

- [ ] **Step 3: Implement**

In `otradio/dates.py`, append:

```python
def decade_of(d: date) -> int:
    """Return the decade a date falls in, as its starting year (1947 -> 1940)."""
    return d.year - d.year % 10
```

In `otradio/catalog.py`, change the dates import to `from otradio.dates import decade_of, parse_release_date`, and extend `Catalog.__init__` after the `self._commercials` assignment:

```python
        by_decade: dict[int, list[Recording]] = {}
        for recording in self._shows:
            if recording.release_date is not None:
                by_decade.setdefault(
                    decade_of(recording.release_date), []
                ).append(recording)
        self._shows_by_decade = {
            decade: tuple(recordings)
            for decade, recordings in sorted(by_decade.items())
        }
```

Add after the `commercials` property:

```python
    @property
    def decades(self) -> tuple[int, ...]:
        """Decades with at least one dated show, ascending."""
        return tuple(self._shows_by_decade)

    def shows_for(self, era: int | None) -> tuple[Recording, ...]:
        """Shows for an era: a decade start year, or None for all shows."""
        if era is None:
            return self._shows
        return self._shows_by_decade.get(era, ())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_dates.py tests/test_catalog.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add otradio/dates.py otradio/catalog.py tests/test_dates.py tests/test_catalog.py
git commit -m "feat: partition catalog shows by decade"
```

---

### Task 2: Controls protocol with null and keyboard implementations

**Files:**
- Create: `otradio/controls.py`
- Test: `tests/test_controls.py` (new file)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `otradio.controls.Command` (enum, member `CYCLE_ERA`); `Controls` protocol with `poll() -> Command | None`; `NullControls()`; `KeyboardControls(stream=None)`. Task 5 imports `Command`, `Controls`, `NullControls`, `KeyboardControls`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_controls.py`:

```python
import io
import threading
import time

from otradio.controls import Command, KeyboardControls, NullControls


def test_null_controls_never_has_a_command():
    controls = NullControls()
    assert controls.poll() is None
    assert controls.poll() is None


def test_keyboard_controls_starts_no_thread_before_first_poll():
    controls = KeyboardControls(stream=io.StringIO(""))
    assert controls._reader is None


def drain(controls, tries=50):
    """Poll until a command appears or the injected stream is exhausted."""
    for _ in range(tries):
        command = controls.poll()
        if command is not None:
            return command
        time.sleep(0.01)
    return None


def test_keyboard_controls_maps_e_to_cycle_era():
    controls = KeyboardControls(stream=io.StringIO("e\n"))
    assert drain(controls) is Command.CYCLE_ERA


def test_keyboard_controls_is_case_insensitive_and_strips():
    controls = KeyboardControls(stream=io.StringIO("  E  \n"))
    assert drain(controls) is Command.CYCLE_ERA


def test_keyboard_controls_ignores_unknown_lines():
    controls = KeyboardControls(stream=io.StringIO("x\nquit\n"))
    assert drain(controls, tries=20) is None


def test_keyboard_controls_poll_maps_queued_lines_without_a_live_thread():
    controls = KeyboardControls(stream=io.StringIO(""))
    controls._reader = threading.current_thread()  # pretend already started
    controls._queue.put("e\n")
    controls._queue.put("noise\n")
    controls._queue.put("E\n")
    assert controls.poll() is Command.CYCLE_ERA
    assert controls.poll() is None
    assert controls.poll() is Command.CYCLE_ERA
    assert controls.poll() is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_controls.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'otradio.controls'`.

- [ ] **Step 3: Implement**

Create `otradio/controls.py`:

```python
"""Runtime controls: how the listener changes what the radio plays.

`KeyboardControls` is for development and bench testing. The cabinet's real
input hardware (dial or buttons on GPIO) becomes another class behind the
same protocol when it is chosen.
"""

import queue
import sys
import threading
from enum import Enum
from typing import IO, Protocol


class Command(Enum):
    CYCLE_ERA = "cycle_era"


class Controls(Protocol):
    """A source of listener commands, polled by the run loop."""

    def poll(self) -> "Command | None":
        """Return one pending command, or None. Never blocks."""
        ...


class NullControls:
    """No input attached."""

    def poll(self) -> Command | None:
        return None


class KeyboardControls:
    """Line-based commands from a stream: 'e' + Enter cycles the era.

    A daemon thread reads the stream so poll() never blocks. The thread
    starts on the first poll, not in __init__, so construction does no I/O.
    The stream defaults to stdin at read time.
    """

    def __init__(self, stream: IO[str] | None = None) -> None:
        self._stream = stream
        self._queue: queue.Queue[str] = queue.Queue()
        self._reader: threading.Thread | None = None

    def poll(self) -> Command | None:
        if self._reader is None:
            self._reader = threading.Thread(target=self._read_lines, daemon=True)
            self._reader.start()
        try:
            line = self._queue.get_nowait()
        except queue.Empty:
            return None
        if line.strip().lower() == "e":
            return Command.CYCLE_ERA
        return None

    def _read_lines(self) -> None:
        stream = self._stream if self._stream is not None else sys.stdin
        for line in stream:
            self._queue.put(line)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_controls.py -v`
Expected: all PASS, no thread-exception noise in the output.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add otradio/controls.py tests/test_controls.py
git commit -m "feat: add Controls protocol with null and keyboard implementations"
```

---

### Task 3: --era and --controls configuration

**Files:**
- Modify: `otradio/config.py`
- Test: `tests/test_config.py` (append)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `Config.era: int | None` (default `None` = all eras, normalized to a decade start) and `Config.controls: str` (`"keyboard"` or `"none"`, default `"none"`). Task 5 reads both.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py` (it already imports `Config` and `pytest`):

```python
def test_era_defaults_to_all():
    config = Config.from_cli([], env={})
    assert config.era is None


def test_era_flag_parses_a_decade():
    config = Config.from_cli(["--era", "1940"], env={})
    assert config.era == 1940


def test_era_flag_normalizes_a_mid_decade_year():
    config = Config.from_cli(["--era", "1947"], env={})
    assert config.era == 1940


def test_era_flag_accepts_all():
    config = Config.from_cli(["--era", "all"], env={})
    assert config.era is None


def test_era_env_var_is_used_and_flag_wins():
    assert Config.from_cli([], env={"OTRADIO_ERA": "1950"}).era == 1950
    config = Config.from_cli(["--era", "all"], env={"OTRADIO_ERA": "1950"})
    assert config.era is None


def test_malformed_era_flag_exits_with_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        Config.from_cli(["--era", "forties"], env={})
    assert excinfo.value.code == 2


def test_malformed_era_env_var_exits_with_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        Config.from_cli([], env={"OTRADIO_ERA": "forties"})
    assert excinfo.value.code == 2


def test_controls_defaults_to_none():
    config = Config.from_cli([], env={})
    assert config.controls == "none"


def test_controls_flag_and_env_with_flag_precedence():
    assert Config.from_cli(["--controls", "keyboard"], env={}).controls == "keyboard"
    assert Config.from_cli([], env={"OTRADIO_CONTROLS": "keyboard"}).controls == "keyboard"
    config = Config.from_cli(
        ["--controls", "none"], env={"OTRADIO_CONTROLS": "keyboard"}
    )
    assert config.controls == "none"


def test_invalid_controls_value_exits_with_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        Config.from_cli(["--controls", "gpio"], env={})
    assert excinfo.value.code == 2
    with pytest.raises(SystemExit) as excinfo:
        Config.from_cli([], env={"OTRADIO_CONTROLS": "gpio"})
    assert excinfo.value.code == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: new tests FAIL (`unrecognized arguments: --era` / `AttributeError: era`); existing tests PASS.

- [ ] **Step 3: Implement**

In `otradio/config.py`:

Add a module-level helper next to `_optional_int`:

```python
def _parse_era(value: str) -> int | None:
    """A decade start year, or None for all eras. '1947' normalizes to 1940."""
    text = value.strip().lower()
    if text in ("", "all"):
        return None
    year = int(text)  # ValueError propagates to argparse / parser.error
    return year - year % 10
```

Add fields to the `Config` dataclass after `dry_run`:

```python
    era: int | None = None
    controls: str = "none"
```

Add arguments in `from_cli` after `--dry-run`:

```python
        parser.add_argument(
            "--era",
            type=_parse_era,
            help="Only play shows from this decade (e.g. 1940), or 'all'.",
        )
        parser.add_argument(
            "--controls",
            choices=("keyboard", "none"),
            help="Where listener commands come from while playing.",
        )
```

Extend the env-defaults block (before `parser.set_defaults(**env_defaults)`):

```python
        controls_default = (env.get("OTRADIO_CONTROLS") or "none").strip().lower()
        if controls_default not in ("keyboard", "none"):
            parser.error(
                f"OTRADIO_CONTROLS: invalid value: {env['OTRADIO_CONTROLS']!r}"
            )
        env_defaults["controls"] = controls_default
        try:
            env_defaults["era"] = _parse_era(env.get("OTRADIO_ERA") or "all")
        except ValueError:
            parser.error(f"OTRADIO_ERA: invalid era value: {env['OTRADIO_ERA']!r}")
```

Extend the `cls(...)` return with:

```python
            era=args.era,
            controls=args.controls,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add otradio/config.py tests/test_config.py
git commit -m "feat: add --era and --controls configuration"
```

---

### Task 4: Era-aware scheduler

**Files:**
- Modify: `otradio/scheduler.py`
- Test: `tests/test_scheduler.py` (append)

**Interfaces:**
- Consumes: `Catalog.shows_for(era: int | None)`, `Catalog.decades` from Task 1.
- Produces: `AlternatingScheduler(catalog, rng=None, era: int | None = None)`; property `era -> int | None`; `cycle_era() -> int | None` (order: None → decades ascending → None). Task 5 calls `cycle_era()` and passes `era=` at construction.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scheduler.py` (it already has helpers to build recordings/catalogs — reuse them; the code below assumes a `make_recording(name, genre)`-style helper exists and shows the shape with explicit `Recording` construction in case it does not; add `from datetime import date` and `Recording`/`Genre`/`Path` imports if missing):

```python
def dated_show(name, year):
    return Recording(
        id=name,
        filename=name,
        path=Path(name),
        release_date=date(year, 1, 1),
        genre=Genre.SHOW,
    )


def commercial(name="commercial.mp3"):
    return Recording(
        id=name,
        filename=name,
        path=Path(name),
        release_date=None,
        genre=Genre.COMMERCIAL,
    )


def test_scheduler_with_an_era_picks_shows_only_from_that_decade():
    catalog = Catalog(
        [dated_show("forties.mp3", 1947), dated_show("fifties.mp3", 1952), commercial()]
    )
    scheduler = AlternatingScheduler(catalog, rng=random.Random(0), era=1950)
    picks = [scheduler.next() for _ in range(10)]
    show_ids = {r.id for r in picks if r.genre is Genre.SHOW}
    assert show_ids == {"fifties.mp3"}
    assert any(r.genre is Genre.COMMERCIAL for r in picks)


def test_scheduler_era_defaults_to_all():
    catalog = Catalog(
        [dated_show("forties.mp3", 1947), dated_show("fifties.mp3", 1952), commercial()]
    )
    scheduler = AlternatingScheduler(catalog, rng=random.Random(0))
    assert scheduler.era is None
    picks = {r.id for r in (scheduler.next() for _ in range(20)) if r.genre is Genre.SHOW}
    assert picks == {"forties.mp3", "fifties.mp3"}


def test_cycle_era_walks_all_then_decades_ascending_then_all():
    catalog = Catalog(
        [dated_show("thirties.mp3", 1935), dated_show("fifties.mp3", 1952), commercial()]
    )
    scheduler = AlternatingScheduler(catalog, rng=random.Random(0))
    assert scheduler.cycle_era() == 1930
    assert scheduler.cycle_era() == 1950
    assert scheduler.cycle_era() is None
    assert scheduler.cycle_era() == 1930


def test_cycle_era_from_an_era_not_in_the_cycle_goes_to_the_first_decade():
    catalog = Catalog([dated_show("fifties.mp3", 1952), commercial()])
    scheduler = AlternatingScheduler(catalog, rng=random.Random(0), era=1930)
    assert scheduler.cycle_era() == 1950


def test_cycle_era_with_no_dated_shows_stays_on_all():
    undated = Recording(
        id="undated.mp3",
        filename="undated.mp3",
        path=Path("undated.mp3"),
        release_date=None,
        genre=Genre.SHOW,
    )
    scheduler = AlternatingScheduler(Catalog([undated, commercial()]), rng=random.Random(0))
    assert scheduler.cycle_era() is None
    assert scheduler.cycle_era() is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: new tests FAIL (`TypeError: unexpected keyword argument 'era'` / `AttributeError: era` / `cycle_era`); existing tests PASS.

- [ ] **Step 3: Implement**

In `otradio/scheduler.py`, change `AlternatingScheduler.__init__` and `next()`, and add `era`/`cycle_era`:

```python
    def __init__(
        self,
        catalog: Catalog,
        rng: random.Random | None = None,
        era: int | None = None,
    ) -> None:
        self._catalog = catalog
        self._rng = rng if rng is not None else random.Random()
        self._era = era
        self._want_commercial = False
        self._warned_about_missing: set[str] = set()

    @property
    def era(self) -> int | None:
        return self._era

    def cycle_era(self) -> int | None:
        """Advance the era: all -> oldest decade -> ... -> newest -> all."""
        cycle: list[int | None] = [None, *self._catalog.decades]
        position = cycle.index(self._era) if self._era in cycle else 0
        self._era = cycle[(position + 1) % len(cycle)]
        return self._era
```

In `next()`, change the first line of the body from `shows = self._catalog.shows` to:

```python
        shows = self._catalog.shows_for(self._era)
```

(The rest of `next()` — the alternation, the empty-bucket fallback, and `_warn_once` — is unchanged; the fallback keeps the radio playing commercials if a constructed-with-absent-era scheduler has an empty show bucket.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: all PASS. (`EmptyLibrary` behavior is unaffected: it checks `shows and commercials` from the catalog's unfiltered buckets — verify no existing test broke.)

- [ ] **Step 6: Commit**

```bash
git add otradio/scheduler.py tests/test_scheduler.py
git commit -m "feat: make the scheduler era-aware with a cycling selector"
```

---

### Task 5: Radio loop integration, wiring, and docs

**Files:**
- Modify: `otradio/app.py`
- Modify: `CLAUDE.md`, `README.md`
- Test: `tests/test_app.py` (append)

**Interfaces:**
- Consumes: `Command`, `Controls`, `NullControls`, `KeyboardControls` (Task 2); `AlternatingScheduler(era=...)`, `cycle_era()` (Task 4); `Config.era`, `Config.controls` (Task 3); `Catalog.decades` (Task 1); `store.record_interruption(recording_id, when, seconds_played)` (existing).
- Produces: `Radio(..., controls: Controls | None = None)` (defaults to `NullControls`); era-change behavior in the wait loop; `build_radio` wiring.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app.py` (add imports: `from otradio.controls import Command, KeyboardControls, NullControls` and extend the existing catalog/config imports as needed; `date` is already imported):

```python
# -- runtime controls ----------------------------------------------------


class ScriptedControls:
    def __init__(self, commands):
        self._commands = list(commands)

    def poll(self):
        return self._commands.pop(0) if self._commands else None


class RecordingSpeaker:
    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(text)


class BusyPlayer:
    """Reports busy for a fixed number of polls, counts stop() calls."""

    def __init__(self, busy_polls):
        self._busy_polls = busy_polls
        self.stopped = 0
        self.closed = False

    def start(self):
        pass

    def play(self, path):
        pass

    def stop(self):
        self.stopped += 1
        self._busy_polls = 0

    def is_busy(self):
        self._busy_polls -= 1
        return self._busy_polls >= 0

    def close(self):
        self.closed = True


def make_era_radio(controls, era=None):
    catalog = Catalog(
        [
            Recording(
                id="forties.mp3",
                filename="forties.mp3",
                path=Path("forties.mp3"),
                release_date=date(1947, 1, 1),
                genre=Genre.SHOW,
            ),
            Recording(
                id="fifties.mp3",
                filename="fifties.mp3",
                path=Path("fifties.mp3"),
                release_date=date(1952, 1, 1),
                genre=Genre.SHOW,
            ),
            Recording(
                id="commercial-a.mp3",
                filename="commercial-a.mp3",
                path=Path("commercial-a.mp3"),
                release_date=None,
                genre=Genre.COMMERCIAL,
            ),
        ]
    )
    config = Config.from_cli([], env={})
    player = BusyPlayer(busy_polls=5)
    speaker = RecordingSpeaker()
    store = InMemoryStore()
    scheduler = AlternatingScheduler(catalog, rng=random.Random(0), era=era)
    clock = itertools.count(start=0.0, step=1.0)
    radio = Radio(
        config=config,
        catalog=catalog,
        scheduler=scheduler,
        player=player,
        speaker=speaker,
        store=store,
        controls=controls,
        sleep=lambda _seconds: None,
        now=lambda: datetime(1952, 7, 26, 19, 0),
        monotonic=lambda: next(clock),
    )
    return radio, player, speaker, store, scheduler


def test_cycle_era_command_stops_the_show_and_records_an_interruption():
    radio, player, _speaker, store, scheduler = make_era_radio(
        ScriptedControls([Command.CYCLE_ERA])
    )
    radio.run(max_iterations=1)
    assert player.stopped == 1
    played_id = next(
        rid for rid in ("forties.mp3", "fifties.mp3")
        if store.stats_for(rid).num_of_plays == 1
    )
    interruptions = store.stats_for(played_id).interruptions
    assert len(interruptions) == 1
    assert interruptions[0].seconds_played >= 0
    assert scheduler.era == 1940  # None -> first decade


def test_cycle_era_command_announces_the_new_era():
    radio, _player, speaker, _store, _scheduler = make_era_radio(
        ScriptedControls([Command.CYCLE_ERA])
    )
    radio.run(max_iterations=1)
    assert "playing the 1940s" in speaker.said


def test_cycling_past_the_last_decade_announces_all_eras():
    radio, _player, speaker, _store, _scheduler = make_era_radio(
        ScriptedControls([Command.CYCLE_ERA]), era=1950
    )
    radio.run(max_iterations=1)
    assert "playing all eras" in speaker.said


def test_null_controls_change_nothing():
    radio, player, speaker, store, scheduler = make_era_radio(NullControls())
    radio.run(max_iterations=1)
    assert player.stopped == 0
    assert scheduler.era is None
    assert all("playing" not in said or said == GREETING for said in speaker.said)


# -- build_radio controls/era wiring -------------------------------------


def test_build_radio_wires_keyboard_controls_when_configured(tmp_path):
    config = Config.from_cli(
        ["--library", str(tmp_path), "--dry-run", "--controls", "keyboard"], env={}
    )
    radio = build_radio(config)
    assert isinstance(radio._controls, KeyboardControls)


def test_build_radio_defaults_to_null_controls(tmp_path):
    config = Config.from_cli(["--library", str(tmp_path), "--dry-run"], env={})
    radio = build_radio(config)
    assert isinstance(radio._controls, NullControls)


def test_build_radio_passes_the_configured_era_to_the_scheduler(tmp_path):
    (tmp_path / "show-1947-01-01.mp3").touch()
    config = Config.from_cli(
        ["--library", str(tmp_path), "--dry-run", "--era", "1940"], env={}
    )
    radio = build_radio(config)
    assert radio._scheduler.era == 1940


def test_build_radio_falls_back_to_all_eras_when_the_decade_is_absent(tmp_path):
    (tmp_path / "show-1947-01-01.mp3").touch()
    config = Config.from_cli(
        ["--library", str(tmp_path), "--dry-run", "--era", "1930"], env={}
    )
    radio = build_radio(config)
    assert radio._scheduler.era is None
```

Add `import itertools` to the test file's imports if missing.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_app.py -v`
Expected: new tests FAIL (`ImportError` for `otradio.controls` names until added, then `TypeError: unexpected keyword argument 'controls'`); existing tests PASS.

- [ ] **Step 3: Implement**

In `otradio/app.py`:

Add the import:

```python
from otradio.controls import Command, Controls, KeyboardControls, NullControls
```

Extend `Radio.__init__` — add a parameter after `store` and a matching assignment:

```python
        controls: Controls | None = None,
```

```python
        self._controls = controls if controls is not None else NullControls()
```

In `_wait_for_end`, insert a command check at the top of each busy iteration:

```python
        limit = self._config.max_play_seconds
        deadline = None if limit is None else self._monotonic() + limit
        started = self._monotonic()

        # At least one poll interval is spent per recording even if the
        # player is never busy (an instantly-finished or unplayable file),
        # so the outer loop can never spin faster than POLL_INTERVAL_SECONDS.
        self._sleep(POLL_INTERVAL_SECONDS)
        while self._player.is_busy():
            if self._handle_command(recording, started):
                return
            if deadline is not None and self._monotonic() >= deadline:
                logger.warning(
                    "%s exceeded the %s second limit; stopping it.",
                    recording.filename,
                    limit,
                )
                self._player.stop()
                return
            self._sleep(POLL_INTERVAL_SECONDS)
```

Add the handler method after `_wait_for_end`:

```python
    def _handle_command(self, recording: Recording, started: float) -> bool:
        """Act on one pending listener command. True if playback was stopped."""
        command = self._controls.poll()
        if command is not Command.CYCLE_ERA:
            return False
        era = self._scheduler.cycle_era()
        seconds_played = int(self._monotonic() - started)
        self._store.record_interruption(recording.id, self._now(), seconds_played)
        self._player.stop()
        announcement = "playing all eras" if era is None else f"playing the {era}s"
        logger.info("%s", announcement)
        self._speaker.say(announcement)
        return True
```

In `build_radio`, before the `return Radio(...)`:

```python
    era = config.era
    if era is not None and era not in catalog.decades:
        logger.warning(
            "No shows from the %ss in the library; starting with all eras.", era
        )
        era = None
    controls: Controls = (
        KeyboardControls() if config.controls == "keyboard" else NullControls()
    )
```

and change the `Radio(...)` construction to use them:

```python
        scheduler=AlternatingScheduler(catalog, era=era),
        ...
        controls=controls,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_app.py -v`
Expected: all PASS.

- [ ] **Step 5: Update docs**

`CLAUDE.md`:
- In the Architecture module table, add a row after `scheduler.py`:

```markdown
| `controls.py` | `Controls` protocol; `NullControls` and `KeyboardControls` (stdin) |
```

- In the "Unimplemented, by design" section, replace the sentence listing the follow-on work with:

```markdown
The follow-on work, in order: genre filtering beyond show/commercial (needs
genre metadata in the library first), a GPIO `Controls` implementation for
the cabinet hardware, a skip control that records an `Interruption`, and
`load_datetime()` (NTP → RTC → system clock).
```

`README.md`: in the options/flags section, add:

```markdown
- `--era 1940` — only play shows from one decade (`--era all` is the default);
  cycle at runtime with `--controls keyboard` and `e` + Enter.
- `--controls keyboard|none` — where listener commands come from (default `none`).
```

(Adjust list formatting to match the file's existing style.)

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add otradio/app.py tests/test_app.py CLAUDE.md README.md
git commit -m "feat: cycle eras at runtime from a pluggable control"
```
