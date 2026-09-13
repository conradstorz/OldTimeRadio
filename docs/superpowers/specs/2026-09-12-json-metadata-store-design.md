# JsonMetadataStore design

Date: 2026-09-12
Status: approved

## Goal

Persist play history across reboots. `InMemoryStore.save()` is a deliberate no-op today; this
adds a `JsonMetadataStore` implementing the existing `MetadataStore` protocol so play counts,
availability history, and interruptions survive a power cycle. First item of the follow-on list
in `2026-09-02-otradio-refactor-design.md`.

**In scope:** the store class, its file format, wiring into `build_radio()`, tests.

**Out of scope:** era/genre filtering, skip control, `load_datetime()`, any new CLI flag for the
stats path.

## Constraints

- The appliance is switched off at the wall; `Radio.run()`'s `finally` (and therefore `save()`)
  usually never executes. Every `record_*` call must flush to disk itself — this is already
  mandated by the `MetadataStore` protocol docstring in `otradio/store.py`.
- A power cut can land mid-write. The file on disk must never be left half-written.
- A corrupt stats file must not brick the radio: it must still boot and play.
- Recording identity is the library-relative path (stable across runs); it is the JSON key.

## Design

### Class

`JsonMetadataStore(path: Path)` in `otradio/store.py`, subclassing `InMemoryStore`:

- `__init__` loads `path` into the inherited `self._stats` dict (empty if the file is missing).
- Each `record_played` / `record_unavailable` / `record_interruption` calls `super()` then
  `self._flush()`.
- `save()` is a final flush — same write path, nothing special.
- `stats_for` snapshot isolation and all mutation logic are inherited unchanged.

### File format

```json
{
  "version": 1,
  "recordings": {
    "shows/some-show-1948-05-01.mp3": {
      "num_of_plays": 3,
      "last_played": "2026-09-12T14:03:22",
      "available": true,
      "unavailable_at": ["2026-09-10T09:00:00"],
      "interruptions": [{"at": "2026-09-11T20:15:00", "seconds_played": 340}]
    }
  }
}
```

- Datetimes serialize via `datetime.isoformat()` and parse via `datetime.fromisoformat()`.
- `last_played` and `available` may be `null`, matching `PlayStats` defaults.
- `version` exists so a future format change can migrate instead of discarding.

### Atomic writes

`_flush()` serializes the whole dict to `<path>.tmp` (same directory, so `os.replace` stays on
one filesystem), then `os.replace(tmp, path)`. A power cut mid-write loses at most the event
being written; the previous file version stays intact. Write volume is one small file per
show (~every 30 minutes) — negligible for SD-card wear.

### Load errors

- File missing: start with empty history.
- File unreadable, unparseable JSON, or wrong shape (non-dict top level, unknown version,
  malformed entries): rename the file to `<path>.bad` via `os.replace` (overwriting any prior
  `.bad`) and start with empty history. The radio always boots; the evidence is kept for
  inspection.
- File exists but can neither be read nor quarantined (e.g. read-only filesystem mid-fault):
  the store goes read-only for the rest of the run — every `_flush()` is a logged no-op (once)
  and `self._path` is never touched — so the possibly-good file already on disk is never
  clobbered by a near-empty in-memory state.

### Wiring

`build_radio()` in `otradio/app.py`:

- Normal run: `JsonMetadataStore(config.library_dir / "otradio-stats.json")`.
- `--dry-run`: keep `InMemoryStore`, so off-device test runs never write into the library.

The filename is a module constant (`STATS_FILENAME = "otradio-stats.json"`). No CLI flag or
env var for the path — the library directory is already configurable, and the stats file
belongs with the recordings it describes.

## Alternatives considered

- **Append-only JSONL journal with startup replay** — more robust ordering and append-only
  writes, but needs replay and compaction; atomic replace already covers the power-cut case.
  Rejected as extra machinery for no practical gain.
- **SQLite** — dependency and opacity for a file that fits in a few kilobytes. Rejected.

## Testing

All tests use `tmp_path` libraries of empty files, as the existing suite does.

- Round-trip: record events in one store instance, construct a second on the same path,
  `stats_for` returns equal history.
- Flush-per-record: after a single `record_played` and no `save()`, a fresh instance already
  sees it.
- Atomicity: after any flush, no `<path>.tmp` remains.
- Missing file: constructing on a nonexistent path yields empty stats and no file until the
  first record.
- Corrupt file: garbage bytes at the path → store starts empty, `<path>.bad` holds the
  garbage, next flush writes a valid file.
- Datetime round-trip: `last_played`, `unavailable_at`, and `Interruption.at` survive
  serialization exactly.
- Wiring: `build_radio` uses `JsonMetadataStore` normally and `InMemoryStore` under
  `--dry-run`.
