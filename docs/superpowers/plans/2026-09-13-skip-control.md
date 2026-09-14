# Skip Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the listener skip the current recording: playback stops silently, one `Interruption` is recorded, and a show plays next.

**Architecture:** `Command` gains `SKIP` (keyboard line `s`); `AlternatingScheduler.force_show_next()` clears the existing alternation flag; `Radio._handle_command`'s drain-and-coalesce generalizes from CYCLE_ERA-only to mixed command bursts — one stop, one interruption, announcement only if the era changed. Spec: `docs/superpowers/specs/2026-09-13-skip-control-design.md`.

**Tech Stack:** Python 3.11 stdlib only. Tests with pytest via `uv run pytest`.

## Global Constraints

- Run everything with `uv` (`uv run pytest`); never `pip` or bare `python`.
- Do not chain shell commands with `&&`; issue separate Bash calls.
- No new dependencies, flags, or env vars; no I/O at import time. Baseline: 179 tests passing.
- No sample-until-match: the skip target comes from the existing pre-partitioned buckets.
- After any skip (show or commercial), the next pick is a show; the alternation resumes after that.
- Skips are silent to the listener — no speech — but still produce a `logger.info("Skipping %s", ...)` journal line for diagnosability. Era announcements stay exactly `"playing all eras"` / `f"playing the {era}s"` and are spoken only when the era changed.
- A command burst coalesces into exactly one recorded `Interruption`, one `player.stop()`, and at most one announcement.

---

### Task 1: SKIP command and keyboard mapping

**Files:**
- Modify: `otradio/controls.py`
- Test: `tests/test_controls.py` (append)

**Interfaces:**
- Consumes: existing `Command`, `KeyboardControls`.
- Produces: `Command.SKIP`; `KeyboardControls` maps stripped, lowercased line `s` → `Command.SKIP` (existing `e` → `CYCLE_ERA` unchanged). Task 3 imports `Command.SKIP`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_controls.py` (the file already imports `io`, `Command`, `KeyboardControls` and defines the `drain` helper):

```python
def test_keyboard_controls_maps_s_to_skip():
    controls = KeyboardControls(stream=io.StringIO("s\n"))
    assert drain(controls) is Command.SKIP


def test_keyboard_controls_skip_is_case_insensitive_and_strips():
    controls = KeyboardControls(stream=io.StringIO("  S  \n"))
    assert drain(controls) is Command.SKIP
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_controls.py -v`
Expected: the two new tests FAIL with `AttributeError: SKIP`; the rest PASS.

- [ ] **Step 3: Implement**

In `otradio/controls.py`:

```python
class Command(Enum):
    CYCLE_ERA = "cycle_era"
    SKIP = "skip"
```

In `KeyboardControls.poll()`, replace the mapping tail:

```python
        text = line.strip().lower()
        if text == "e":
            return Command.CYCLE_ERA
        if text == "s":
            return Command.SKIP
        return None
```

Update the `KeyboardControls` class docstring's first line to:

```python
    """Line-based commands from a stream: 'e' + Enter cycles the era, 's' + Enter skips.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_controls.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add otradio/controls.py tests/test_controls.py
git commit -m "feat: add a SKIP command to the controls"
```

---

### Task 2: Scheduler force_show_next

**Files:**
- Modify: `otradio/scheduler.py`
- Test: `tests/test_scheduler.py` (append)

**Interfaces:**
- Consumes: existing `AlternatingScheduler` internals (`_want_commercial`).
- Produces: `AlternatingScheduler.force_show_next() -> None`. Task 3 calls it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scheduler.py` (the era tests already define `dated_show(name, year)` and `commercial()` helpers and import `Catalog`, `Genre`, `AlternatingScheduler`, `random`):

```python
def test_force_show_next_overrides_a_pending_commercial():
    catalog = Catalog([dated_show("forties.mp3", 1947), commercial()])
    scheduler = AlternatingScheduler(catalog, rng=random.Random(0))
    assert scheduler.next().genre is Genre.SHOW  # alternation now wants a commercial
    scheduler.force_show_next()
    assert scheduler.next().genre is Genre.SHOW


def test_force_show_next_is_a_no_op_when_a_show_was_already_next():
    catalog = Catalog([dated_show("forties.mp3", 1947), commercial()])
    scheduler = AlternatingScheduler(catalog, rng=random.Random(0))
    scheduler.force_show_next()
    assert scheduler.next().genre is Genre.SHOW


def test_force_show_next_respects_the_era_filter():
    catalog = Catalog(
        [dated_show("forties.mp3", 1947), dated_show("fifties.mp3", 1952), commercial()]
    )
    scheduler = AlternatingScheduler(catalog, rng=random.Random(0), era=1950)
    scheduler.next()
    scheduler.force_show_next()
    assert scheduler.next().id == "fifties.mp3"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: new tests FAIL with `AttributeError: force_show_next`; the rest PASS.

- [ ] **Step 3: Implement**

In `otradio/scheduler.py`, add after `cycle_era`:

```python
    def force_show_next(self) -> None:
        """After a skip, a show plays next regardless of the alternation."""
        self._want_commercial = False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add otradio/scheduler.py tests/test_scheduler.py
git commit -m "feat: let the scheduler force a show after a skip"
```

---

### Task 3: Generalized command handling in the run loop, and docs

**Files:**
- Modify: `otradio/app.py:112-138` (`Radio._handle_command`)
- Modify: `CLAUDE.md`, `README.md`
- Test: `tests/test_app.py` (append)

**Interfaces:**
- Consumes: `Command.SKIP` (Task 1); `AlternatingScheduler.force_show_next()` (Task 2); existing test helpers in `tests/test_app.py` — `make_era_radio(controls, era=None)` (returns `radio, player, speaker, store, scheduler`; catalog has shows `forties.mp3` (1947), `fifties.mp3` (1952) and `commercial-a.mp3`; fake monotonic counts 0,1,2,…), `ScriptedControls`, `BusyPlayer` (records played paths in `.played`, counts `.stopped`), `GREETING`.
- Produces: mixed-burst coalescing behavior; no new names.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app.py` (imports of `Command`, `Genre`, `date`, `Path`, `Recording` already exist; check the file's helpers before writing — the code below matches them):

```python
def test_skip_stops_the_show_silently_and_a_show_plays_next():
    radio, player, speaker, store, _scheduler = make_era_radio(
        ScriptedControls([Command.SKIP])
    )
    radio.run(max_iterations=2)
    assert player.stopped == 1
    assert speaker.said == [GREETING]  # a skip is silent
    skipped = player.played[0].name
    interruptions = store.stats_for(skipped).interruptions
    assert len(interruptions) == 1
    assert interruptions[0].seconds_played == 1
    # The pick after a skipped show is another show, not the commercial the
    # alternation would have chosen.
    assert player.played[1].name in ("forties.mp3", "fifties.mp3")


def test_skip_during_a_commercial_forces_a_show_next():
    radio, player, _speaker, _store, scheduler = make_era_radio(
        ScriptedControls([Command.SKIP])
    )
    commercial = Recording(
        id="commercial-a.mp3",
        filename="commercial-a.mp3",
        path=Path("commercial-a.mp3"),
        release_date=None,
        genre=Genre.COMMERCIAL,
    )
    stopped = radio._handle_command(commercial, started=0.0)
    assert stopped is True
    assert player.stopped == 1
    assert scheduler.next().genre is Genre.SHOW


def test_mixed_skip_and_cycle_burst_coalesces_into_one_stop():
    radio, player, speaker, store, scheduler = make_era_radio(
        ScriptedControls([Command.SKIP, Command.CYCLE_ERA])
    )
    radio.run(max_iterations=2)
    assert player.stopped == 1
    assert scheduler.era == 1940
    assert "playing the 1940s" in speaker.said
    skipped = player.played[0].name
    assert len(store.stats_for(skipped).interruptions) == 1
    # Era 1940 plus the forced show means the next pick is forties.mp3.
    assert player.played[1].name == "forties.mp3"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_app.py -v`
Expected: the three new tests FAIL (`_handle_command` returns False for SKIP, so nothing stops); existing tests PASS.

- [ ] **Step 3: Implement**

In `otradio/app.py`, replace `_handle_command` entirely:

```python
    def _handle_command(self, recording: Recording, started: float) -> bool:
        """Act on pending listener commands. True if playback was stopped.

        A burst of queued commands (e.g. a key held down) is drained to
        exhaustion once triggered and coalesced: every CYCLE_ERA step is
        applied, a SKIP forces a show next, and exactly one interruption
        is recorded, one stop issued, and at most one announcement spoken
        (only when the era changed — a pure skip is silent).
        """
        command = self._controls.poll()
        if command is None:
            return False
        cycles = 0
        skip = False
        for _ in range(101):  # bound the drain against a stuck key
            if command is Command.CYCLE_ERA:
                cycles += 1
            elif command is Command.SKIP:
                skip = True
            command = self._controls.poll()
            if command is None:
                break
        era = None
        for _ in range(cycles):
            era = self._scheduler.cycle_era()
        if skip:
            self._scheduler.force_show_next()
            logger.info("Skipping %s", recording.filename)
        seconds_played = int(self._monotonic() - started)
        reason = REASON_SKIP if skip else REASON_ERA_CHANGE
        self._store.record_interruption(
            recording.id, self._now(), seconds_played, reason=reason
        )
        self._player.stop()
        if cycles:
            announcement = "playing all eras" if era is None else f"playing the {era}s"
            logger.info("%s", announcement)
            self._speaker.say(announcement)
        return True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_app.py -v`
Expected: all PASS (including the pre-existing CYCLE_ERA tests, whose behavior is unchanged).

- [ ] **Step 5: Update docs**

`CLAUDE.md`, "Unimplemented, by design" section — remove the skip-control item from the follow-on list so it reads:

```markdown
The follow-on work, in order: genre filtering beyond show/commercial (needs
genre metadata in the library first), a GPIO `Controls` implementation for
the cabinet hardware, and `load_datetime()` (NTP → RTC → system clock).
```

`README.md` — in the sentence/row documenting `--controls keyboard`, mention the second key so it reads (adapt to the file's existing wording): cycle eras with `e` + Enter, skip the current recording with `s` + Enter.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add otradio/app.py tests/test_app.py CLAUDE.md README.md
git commit -m "feat: skip the current recording from the controls"
```
