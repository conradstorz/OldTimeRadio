# Era filtering and runtime controls design

Date: 2026-09-12
Status: approved

## Goal

Let the listener choose an era (decade) at runtime, like tuning a station: turning the
(future) dial cycles through the decades present in the library, the radio announces the
selection, stops the current show, and plays from the chosen era. Second item of the
follow-on list in `2026-09-02-otradio-refactor-design.md`.

**In scope:** era (decade) filtering of shows; a `Controls` protocol with null and
keyboard implementations; scheduler and run-loop integration; `--era`/`--controls`
configuration; tests.

**Out of scope:** genre filtering beyond show/commercial (the library has no genre
metadata yet — revisit when it does); GPIO hardware adapter (one new class later);
persisting the selected era across reboots (boot default comes from config); a dedicated
skip control (later work item, though era changes reuse the `Interruption` machinery).

## Constraints

- No new dependencies; Python 3.11 stdlib only. No I/O at import time.
- The full test suite must keep running hardware-free on Windows.
- The scheduler must never sample-until-match; empty buckets must be impossible or
  handled without spinning (the refactor removed exactly that defect).
- Commercials are never era-filtered: they are mostly undated and always interleave.
- Dateless shows (no parseable release date) play only in the all-eras setting.

## Design

### Era model

- `dates.py` gains `decade_of(d: date) -> int` — pure; 1947 → 1940.
- An era is `int | None`: a decade start year, or `None` meaning all eras.
- `Catalog` pre-partitions shows by decade at construction, the same pattern as
  shows/commercials:
  - `decades -> tuple[int, ...]` — sorted decades present among dated shows.
  - `shows_for(era: int | None) -> tuple[Recording, ...]` — `None` returns all shows
    (dated and dateless); a decade returns only shows dated in it.

### Controls

New module `otradio/controls.py`, mirroring the `Player`/`Speaker` adapter pattern:

- `Command` enum: `CYCLE_ERA` (only member for now).
- `Controls` protocol: `poll() -> Command | None` — non-blocking; returns at most one
  pending command per call.
- `NullControls`: always `None`.
- `KeyboardControls`: a daemon thread reads stdin lines into a `queue.Queue`; `poll()`
  drains one entry. The line `e` (case-insensitive, stripped) maps to `CYCLE_ERA`;
  anything else is ignored. The thread starts lazily on first `poll()`, not in
  `__init__`, so construction does no I/O. Testable by injecting into the queue.
- A future `GpioControls` is one new class behind the same protocol.
- Selection: `--controls keyboard|none` / `OTRADIO_CONTROLS`, default `none` (the Pi
  boot service has no useful stdin).

### Scheduler

`AlternatingScheduler` gains era state:

- Constructor takes `era: int | None = None` (wired from config).
- `cycle_era() -> int | None` advances All → oldest decade → … → newest → All, built
  from `catalog.decades`, and returns the new era. Because the cycle only contains
  decades present in the library, a selected decade always has shows.
- If the configured `--era` decade is not in `catalog.decades`, `build_radio` logs a
  warning and starts on All rather than an empty bucket.
- Show picks draw from `catalog.shows_for(self._era)`; commercials, alternation, and
  the warn-once fallback behavior are unchanged.

### Run loop

- `Radio` takes a `controls: Controls` dependency (wired in `build_radio`).
- `_wait_for_end` polls `controls.poll()` once per existing 1-second tick. On
  `CYCLE_ERA`:
  1. `new_era = scheduler.cycle_era()`
  2. announce through the speaker: `"playing all eras"` or `"playing the 1940s"`
  3. `store.record_interruption(recording.id, now(), seconds_played)` — elapsed
     playback measured with `monotonic()` from when the show started
  4. `player.stop()` and return; the next pick comes from the new era.
- The poll between recordings costs nothing extra: the loop already ticks every
  `POLL_INTERVAL_SECONDS`.

### Configuration

- `--era` / `OTRADIO_ERA`: a decade like `1940`, or `all` (default). Malformed values
  route through `parser.error()` like the existing env validation.
- `--controls` / `OTRADIO_CONTROLS`: `keyboard` or `none` (default `none`); invalid
  values also `parser.error()`.

## Alternatives considered

- **Rebuild a filtered Catalog on era change** — keeps the scheduler era-ignorant, but
  Radio takes on catalog construction, scheduler state resets on every dial turn, and
  the catalog is rebuilt for no reason. Rejected.
- **Filter after picking (retry loop)** — reintroduces the sample-until-match hang the
  refactor removed. Rejected.

## Testing

- `decade_of`: century boundaries, exact decade starts.
- Catalog: decade buckets, dateless shows only under `None`, `decades` sorted and
  deduplicated, commercials never in `shows_for`.
- Scheduler: era filtering of show picks; cycle order All → decades ascending → All;
  configured-but-absent era handled in wiring; alternation unchanged under a filter.
- Radio loop with a scripted `Controls`: show stops on `CYCLE_ERA`; interruption
  recorded with correct `seconds_played`; announcement spoken; next pick honors the
  new era; `NullControls` changes nothing.
- Config: flag and env parsing, precedence, error paths.
- `KeyboardControls`: queue injection (no real stdin); `e`/`E` map to `CYCLE_ERA`,
  noise ignored; no thread until first poll.
