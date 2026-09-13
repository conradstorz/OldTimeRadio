# JsonMetadataStore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist play history across reboots by adding a `JsonMetadataStore` that implements the existing `MetadataStore` protocol and flushes to disk on every record.

**Architecture:** `JsonMetadataStore(path)` subclasses `InMemoryStore` in `otradio/store.py`; each `record_*` calls `super()` then atomically rewrites one JSON file (`<path>.tmp` + `os.replace`). Corrupt files are quarantined to `<path>.bad` and the store starts empty. `build_radio()` wires it in for normal runs and keeps `InMemoryStore` for `--dry-run`. Spec: `docs/superpowers/specs/2026-09-12-json-metadata-store-design.md`.

**Tech Stack:** Python 3.11 stdlib only (`json`, `os`, `pathlib`, `datetime`). Tests with pytest via `uv run pytest`.

## Global Constraints

- Run everything with `uv` (`uv run pytest`, `uv run python`); never `pip` or bare `python`.
- Do not chain shell commands with `&&`; issue separate commands.
- No I/O at import time anywhere in `otradio`.
- Recording identity is the library-relative path; it is the JSON key and must not be transformed.
- Datetimes serialize with `datetime.isoformat()` / parse with `datetime.fromisoformat()`.
- Stats filename is `otradio-stats.json` in the library directory; no new CLI flag or env var.
- File format: `{"version": 1, "recordings": {<id>: {...}}}` exactly as specified in the spec.

---

### Task 1: JsonMetadataStore — persistence happy path

**Files:**
- Modify: `otradio/store.py` (add imports, `STATS_VERSION`, serialization helpers, `JsonMetadataStore`)
- Test: `tests/test_store.py` (append a new section)

**Interfaces:**
- Consumes: `InMemoryStore`, `PlayStats`, `Interruption` from `otradio/store.py` (already exist).
- Produces: `class JsonMetadataStore(InMemoryStore)` with `__init__(self, path: Path) -> None`, satisfying `MetadataStore`. Task 2 extends its load-error behavior; Task 3 imports it in `otradio/app.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_store.py` (also add `import json` and the `JsonMetadataStore` import at the top of the file):

```python
# -- JsonMetadataStore ---------------------------------------------------


def make_json_store(tmp_path):
    from otradio.store import JsonMetadataStore

    return JsonMetadataStore(tmp_path / "otradio-stats.json")


def test_json_store_on_a_missing_file_starts_empty_and_creates_nothing(tmp_path):
    store = make_json_store(tmp_path)
    assert store.stats_for("gunsmoke.mp3") == PlayStats()
    assert not (tmp_path / "otradio-stats.json").exists()


def test_json_store_round_trips_history_across_instances(tmp_path):
    store = make_json_store(tmp_path)
    store.record_played("gunsmoke.mp3", datetime(1952, 7, 26, 19, 0))
    store.record_unavailable("broken.mp3", datetime(1952, 7, 27, 9, 30))
    store.record_interruption(
        "gunsmoke.mp3", datetime(1952, 7, 28, 20, 15), seconds_played=340
    )

    reloaded = make_json_store(tmp_path)
    stats = reloaded.stats_for("gunsmoke.mp3")
    assert stats.num_of_plays == 1
    assert stats.last_played == datetime(1952, 7, 26, 19, 0)
    assert stats.available is True
    assert stats.interruptions == [
        Interruption(at=datetime(1952, 7, 28, 20, 15), seconds_played=340)
    ]
    broken = reloaded.stats_for("broken.mp3")
    assert broken.available is False
    assert broken.unavailable_at == [datetime(1952, 7, 27, 9, 30)]


def test_json_store_flushes_each_record_without_save(tmp_path):
    """The appliance is powered off at the wall: save() usually never runs."""
    store = make_json_store(tmp_path)
    store.record_played("gunsmoke.mp3", datetime(1952, 7, 26))
    # No save(). A fresh instance must already see the play.
    assert make_json_store(tmp_path).stats_for("gunsmoke.mp3").num_of_plays == 1


def test_json_store_leaves_no_tmp_file_behind(tmp_path):
    store = make_json_store(tmp_path)
    store.record_played("gunsmoke.mp3", datetime(1952, 7, 26))
    store.save()
    leftovers = [p.name for p in tmp_path.iterdir()]
    assert leftovers == ["otradio-stats.json"]


def test_json_store_writes_the_documented_format(tmp_path):
    store = make_json_store(tmp_path)
    store.record_played("gunsmoke.mp3", datetime(1952, 7, 26, 19, 0))
    data = json.loads((tmp_path / "otradio-stats.json").read_text(encoding="utf-8"))
    assert data["version"] == 1
    entry = data["recordings"]["gunsmoke.mp3"]
    assert entry == {
        "num_of_plays": 1,
        "last_played": "1952-07-26T19:00:00",
        "available": True,
        "unavailable_at": [],
        "interruptions": [],
    }


def test_json_store_save_is_a_flush_and_does_not_raise(tmp_path):
    store = make_json_store(tmp_path)
    store.record_played("a.mp3", datetime(1952, 7, 26))
    store.save()
    assert make_json_store(tmp_path).stats_for("a.mp3").num_of_plays == 1


def test_json_store_inherits_snapshot_isolation(tmp_path):
    store = make_json_store(tmp_path)
    store.record_played("gunsmoke.mp3", datetime(1952, 7, 26))
    snapshot = store.stats_for("gunsmoke.mp3")
    snapshot.num_of_plays = 999
    assert store.stats_for("gunsmoke.mp3").num_of_plays == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_store.py -v`
Expected: the new tests FAIL with `ImportError: cannot import name 'JsonMetadataStore'`; all existing tests PASS.

- [ ] **Step 3: Implement JsonMetadataStore**

In `otradio/store.py`, extend the module docstring's second paragraph if desired, add `import json`, `import os`, and `from pathlib import Path` to the imports, and append after `InMemoryStore`:

```python
STATS_VERSION = 1


def _stats_to_json(stats: PlayStats) -> dict:
    return {
        "num_of_plays": stats.num_of_plays,
        "last_played": (
            stats.last_played.isoformat() if stats.last_played is not None else None
        ),
        "available": stats.available,
        "unavailable_at": [when.isoformat() for when in stats.unavailable_at],
        "interruptions": [
            {"at": event.at.isoformat(), "seconds_played": event.seconds_played}
            for event in stats.interruptions
        ],
    }


def _stats_from_json(entry: dict) -> PlayStats:
    return PlayStats(
        num_of_plays=entry["num_of_plays"],
        last_played=(
            datetime.fromisoformat(entry["last_played"])
            if entry["last_played"] is not None
            else None
        ),
        available=entry["available"],
        unavailable_at=[datetime.fromisoformat(t) for t in entry["unavailable_at"]],
        interruptions=[
            Interruption(
                at=datetime.fromisoformat(event["at"]),
                seconds_played=event["seconds_played"],
            )
            for event in entry["interruptions"]
        ],
    )


class JsonMetadataStore(InMemoryStore):
    """Play history persisted to one JSON file, flushed on every record.

    The appliance is normally switched off at the wall, so save() cannot be
    the persistence point (see MetadataStore). Every record_* call rewrites
    the file atomically: serialize to `<path>.tmp` in the same directory,
    then os.replace() over the real file. A power cut mid-write loses at
    most the event being written, never the file.
    """

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        self._load()

    def record_played(self, recording_id: str, when: datetime) -> None:
        super().record_played(recording_id, when)
        self._flush()

    def record_unavailable(self, recording_id: str, when: datetime) -> None:
        super().record_unavailable(recording_id, when)
        self._flush()

    def record_interruption(
        self, recording_id: str, when: datetime, seconds_played: int
    ) -> None:
        super().record_interruption(recording_id, when, seconds_played)
        self._flush()

    def save(self) -> None:
        """Final flush on the rare clean exit."""
        self._flush()

    def _load(self) -> None:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError:
            self._quarantine()
            return
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get("version") != STATS_VERSION:
                raise ValueError("unrecognized stats file format")
            self._stats = {
                recording_id: _stats_from_json(entry)
                for recording_id, entry in data["recordings"].items()
            }
        except (ValueError, KeyError, TypeError, AttributeError):
            self._stats = {}
            self._quarantine()

    def _flush(self) -> None:
        payload = {
            "version": STATS_VERSION,
            "recordings": {
                recording_id: _stats_to_json(stats)
                for recording_id, stats in self._stats.items()
            },
        }
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    def _quarantine(self) -> None:
        """Set aside an unreadable stats file as `<path>.bad` and carry on."""
        try:
            os.replace(self._path, self._path.with_name(self._path.name + ".bad"))
        except OSError:
            pass
```

Also update the module docstring's line "A future JsonMetadataStore implements the same protocol" — it is no longer future. Replace the docstring's second sentence block:

```python
"""Play history for recordings.

This module defines the persistence boundary. `InMemoryStore` keeps history
for one run only; `JsonMetadataStore` persists it to a JSON file beside the
recordings, flushing on every record because the appliance is normally
powered off at the wall rather than shut down cleanly.
"""
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_store.py -v`
Expected: all PASS. (Note: `test_json_store_on_a_missing_file_starts_empty_and_creates_nothing` exercises `_load`'s FileNotFoundError branch; quarantine branches are Task 2.)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add otradio/store.py tests/test_store.py
git commit -m "feat: add JsonMetadataStore persisting play history to JSON"
```

---

### Task 2: Corrupt-file quarantine

**Files:**
- Modify: `otradio/store.py` (behavior already written in Task 1's `_load`/`_quarantine`; this task proves it and fixes anything the tests flush out)
- Test: `tests/test_store.py` (append)

**Interfaces:**
- Consumes: `JsonMetadataStore(path: Path)` from Task 1.
- Produces: no new names; verified load-error behavior (missing → empty; corrupt/wrong shape/unknown version → `<path>.bad` + empty).

- [ ] **Step 1: Write the failing-or-passing tests**

Append to `tests/test_store.py`:

```python
def test_json_store_quarantines_unparseable_json(tmp_path):
    stats_path = tmp_path / "otradio-stats.json"
    stats_path.write_text("{not json", encoding="utf-8")

    store = make_json_store(tmp_path)

    assert store.stats_for("gunsmoke.mp3") == PlayStats()
    assert not stats_path.exists()
    bad = tmp_path / "otradio-stats.json.bad"
    assert bad.read_text(encoding="utf-8") == "{not json"


def test_json_store_quarantines_wrong_shape(tmp_path):
    stats_path = tmp_path / "otradio-stats.json"
    stats_path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    make_json_store(tmp_path)
    assert not stats_path.exists()
    assert (tmp_path / "otradio-stats.json.bad").exists()


def test_json_store_quarantines_unknown_version(tmp_path):
    stats_path = tmp_path / "otradio-stats.json"
    stats_path.write_text(
        json.dumps({"version": 999, "recordings": {}}), encoding="utf-8"
    )
    make_json_store(tmp_path)
    assert not stats_path.exists()
    assert (tmp_path / "otradio-stats.json.bad").exists()


def test_json_store_quarantines_malformed_entry(tmp_path):
    stats_path = tmp_path / "otradio-stats.json"
    stats_path.write_text(
        json.dumps({"version": 1, "recordings": {"a.mp3": {"num_of_plays": 1}}}),
        encoding="utf-8",
    )
    store = make_json_store(tmp_path)
    assert store.stats_for("a.mp3") == PlayStats()
    assert (tmp_path / "otradio-stats.json.bad").exists()


def test_json_store_quarantine_overwrites_a_previous_bad_file(tmp_path):
    (tmp_path / "otradio-stats.json.bad").write_text("older garbage", encoding="utf-8")
    stats_path = tmp_path / "otradio-stats.json"
    stats_path.write_text("newer garbage", encoding="utf-8")
    make_json_store(tmp_path)
    bad = tmp_path / "otradio-stats.json.bad"
    assert bad.read_text(encoding="utf-8") == "newer garbage"


def test_json_store_recovers_after_quarantine(tmp_path):
    stats_path = tmp_path / "otradio-stats.json"
    stats_path.write_text("garbage", encoding="utf-8")
    store = make_json_store(tmp_path)

    store.record_played("gunsmoke.mp3", datetime(1952, 7, 26))

    reloaded = make_json_store(tmp_path)
    assert reloaded.stats_for("gunsmoke.mp3").num_of_plays == 1
    assert (tmp_path / "otradio-stats.json.bad").exists()
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_store.py -v`
Expected: PASS if Task 1's `_load` is correct. If any FAIL, fix `_load`/`_quarantine` in `otradio/store.py` (not the tests) until they pass — the tests encode the spec.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add otradio/store.py tests/test_store.py
git commit -m "test: cover stats-file quarantine and recovery"
```

---

### Task 3: Wire JsonMetadataStore into build_radio

**Files:**
- Modify: `otradio/app.py` (import, `STATS_FILENAME` constant, store selection in `build_radio()`)
- Modify: `CLAUDE.md` ("Unimplemented, by design" section — persistence is done)
- Test: `tests/test_app.py` (append to the `build_radio` section)

**Interfaces:**
- Consumes: `JsonMetadataStore(path: Path)` from Task 1; `Config.dry_run`, `Config.library_dir`.
- Produces: `otradio.app.STATS_FILENAME = "otradio-stats.json"`; `build_radio()` returns a `Radio` whose `_store` is `JsonMetadataStore` normally, `InMemoryStore` under `--dry-run`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app.py`'s `build_radio` section (add `JsonMetadataStore` to the existing `from otradio.store import ...` line):

```python
def test_build_radio_uses_a_json_store_in_the_library_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("otradio.speech.shutil.which", lambda command: None)
    config = Config.from_cli(["--library", str(tmp_path)], env={})
    radio = build_radio(config)
    assert isinstance(radio._store, JsonMetadataStore)
    assert radio._store._path == tmp_path / "otradio-stats.json"


def test_build_radio_dry_run_keeps_history_out_of_the_library(tmp_path):
    config = Config.from_cli(["--library", str(tmp_path), "--dry-run"], env={})
    radio = build_radio(config)
    assert type(radio._store) is InMemoryStore


def test_build_radio_does_not_catalog_the_stats_file(tmp_path):
    (tmp_path / "show-a.mp3").touch()
    (tmp_path / "otradio-stats.json").write_text(
        '{"version": 1, "recordings": {}}', encoding="utf-8"
    )
    config = Config.from_cli(["--library", str(tmp_path), "--dry-run"], env={})
    radio = build_radio(config)
    assert [r.filename for r in radio._catalog] == ["show-a.mp3"]
```

Note: the first test builds a `PygamePlayer` (no `--dry-run`) but never calls `start()`, so pygame is not imported — same pattern as `test_build_radio_live_run_uses_a_pygame_player_with_the_configured_volume`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_app.py -v`
Expected: the two new store tests FAIL (`ImportError` for `JsonMetadataStore` until the import is added, then `AssertionError: isinstance` — `_store` is `InMemoryStore`); the catalog test PASSES already (`.json` is not an audio extension).

- [ ] **Step 3: Wire the store**

In `otradio/app.py`, change the store import line and `build_radio`:

```python
from otradio.store import InMemoryStore, JsonMetadataStore, MetadataStore
```

Below `POLL_INTERVAL_SECONDS` add:

```python
STATS_FILENAME = "otradio-stats.json"
```

In `build_radio()`, replace `store=InMemoryStore(),` with a selected store (mirroring the player selection above it):

```python
    # Dry runs keep history in memory so off-device testing never writes
    # into the library.
    store: MetadataStore = (
        InMemoryStore()
        if config.dry_run
        else JsonMetadataStore(config.library_dir / STATS_FILENAME)
    )
    return Radio(
        config=config,
        catalog=catalog,
        scheduler=AlternatingScheduler(catalog),
        player=player,
        speaker=make_speaker(config),
        store=store,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_app.py -v`
Expected: all PASS.

- [ ] **Step 5: Update CLAUDE.md**

In `CLAUDE.md`, rewrite the first paragraph of "## Unimplemented, by design":

```markdown
`InMemoryStore.save()` is a no-op; normal runs use `JsonMetadataStore`, which
persists play history to `otradio-stats.json` in the library directory,
flushing on every record because the appliance is powered off at the wall.
The follow-on work, in order: era/genre filtering, a skip control that
records an `Interruption`, and `load_datetime()` (NTP → RTC → system clock).
See `docs/superpowers/specs/2026-09-02-otradio-refactor-design.md`.
```

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add otradio/app.py tests/test_app.py CLAUDE.md
git commit -m "feat: persist play history via JsonMetadataStore in normal runs"
```
