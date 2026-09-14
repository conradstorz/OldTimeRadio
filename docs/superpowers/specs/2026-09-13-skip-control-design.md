# Skip control design

Date: 2026-09-13
Status: approved

## Goal

Let the listener skip the current recording: playback stops, an `Interruption` is
recorded, and another show starts — silently, the way turning past a station just moves
on. Third item of the follow-on list in `2026-09-02-otradio-refactor-design.md`, riding
the `Controls` machinery from `2026-09-12-era-filtering-design.md`.

**In scope:** a `SKIP` command through the existing `Controls` protocol; keyboard
mapping; scheduler and run-loop integration; tests.

**Out of scope:** GPIO hardware adapter (still one future class); any new CLI flag or
env var (skip rides the existing `--controls` selection); announcements for skips.

## Constraints

- No new dependencies; no I/O at import time; suite stays hardware-free on Windows.
- No sample-until-match anywhere: the skip target comes from the existing
  pre-partitioned buckets.
- After any skip — of a show or of a commercial — the next pick is a show. The
  commercial-between-shows rhythm resumes on the pick after that. (best-effort:
  with no eligible shows, the scheduler's existing empty-bucket fallback keeps
  playing commercials rather than stalling.)
- Skips are silent: no speech, no era change. The next show starting is the feedback.
  A skip is still logged to the journal (`logger.info`) so stopped playback is
  diagnosable; silence is about speech.
- A skip records exactly one `Interruption` (`recording.id`, wall-clock now, elapsed
  seconds from the same monotonic base the watchdog uses), same as an era change. The
  recorded `reason` is `"skip"` for a skip (a mixed burst counts as a skip — the
  listener explicitly rejected the recording) and `"era_change"` for a pure era change.

## Design

### Controls

- `Command` gains `SKIP`.
- `KeyboardControls` maps the line `s` (case-insensitive, stripped) to `SKIP`,
  alongside the existing `e` → `CYCLE_ERA`. Unknown lines stay ignored.
- The future `GpioControls` maps a second button to the same enum member.

### Scheduler

- `AlternatingScheduler.force_show_next()` — sets the existing `_want_commercial`
  flag to `False`. One line; alternation logic and era state untouched. Skipping a
  show yields another show; skipping a commercial yields the show that was coming
  anyway; either way the rule "after a skip, a show plays" holds.

### Run loop

`Radio._handle_command` generalizes its existing drain-and-coalesce:

- Poll once; on any command, drain the queue to exhaustion (existing 100-iteration
  bound), tallying `cycles` (count of `CYCLE_ERA`) and `skip` (any `SKIP` seen).
- Apply scheduler changes first: `cycle_era()` × cycles, then `force_show_next()` if
  a skip was seen.
- Record one `Interruption`, stop the player once, and announce only if the era
  changed (`"playing all eras"` / `"playing the 1940s"` — the final era). A pure skip
  is silent.
- Return so the run loop picks next — a show, from the (possibly new) era.

Mixed bursts (skip plus era turns queued together) therefore coalesce into a single
stop with both effects applied, matching the era-filtering spec's coalescing rule.

### Configuration

Nothing new. `--controls keyboard` already enables the keyboard; `none` stays inert.

## Alternatives considered

- **Pick-and-discard in the Radio** (call `scheduler.next()` until a show appears) —
  reintroduces the sample-until-match pattern the refactor removed. Rejected.
- **A distinct skip announcement** — rejected by decision: a real radio does not
  narrate; silence plus the next show is the feedback.

## Testing

- `KeyboardControls`: `s`/`S` map to `SKIP`; `e` still maps to `CYCLE_ERA`; noise
  ignored.
- Scheduler: `force_show_next()` after the toggle points at commercials → next pick
  is a show; calling it when a show was already next is a no-op; era filter still
  honored on the forced pick.
- Radio loop with scripted controls:
  - `SKIP` during a show: player stopped once, one `Interruption` with correct
    `seconds_played`, no announcement, next pick is a show (not the commercial the
    alternation would have chosen).
  - `SKIP` during a commercial: stopped, next pick is a show.
  - Mixed burst `[SKIP, CYCLE_ERA]`: one stop, one interruption, era advanced, era
    announcement spoken, next pick is a show from the new era.
  - `NullControls`: unchanged behavior.
