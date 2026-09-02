# OldTimeRadio Refactor — Design

Date: 2026-09-02
Status: Approved
Branch: `refactor/otradio-package`

## Goal

Restructure the single-file `play_radio.py` into a tested, installable `otradio` package with clear
module boundaries, so the unfinished features (metadata persistence, era/genre filtering, skip
control) become straightforward follow-on work instead of edits to a tangled script.

**In scope:** package split, data model, config, adapters for audio and speech, selection policy,
test suite, correctness fixes to defects found during review.

**Out of scope:** implementing metadata persistence, filtering, or skip. Those land later against the
interfaces defined here.

## Why

`play_radio.py` runs its work at import time — `listdir()` on a hardcoded relative path, the full
catalog build loop, `pygame.init()`, and `mixer.init()` all execute on import. Nothing can be
imported, reused, or tested without a populated `./recordings/OTRadio/` and working audio hardware.
Seven concerns (date parsing, indexing, schema, playback, speech, selection policy, run loop) share
one module and one global namespace.

### Defects confirmed during review

**D1 — Startup crash on any 4-digit-year filename.** `parse_date()` uses
`([\d][-/]?){6}|([\d][-/]?){8}`. Regex alternation tries the left branch first, so an 8-digit date is
truncated to 6 characters: `Jb1953-09-13...` matches `'1953-09-'` and `19520726` matches `'195207'`.
Both raise `dateutil` `ParserError`. `parse_date()` is called from the module-level build loop with no
`try`, so the exception propagates and the program dies before playing anything. Verified empirically;
only 2-digit-year filenames work today.

**D2 — Infinite loop in `pick_a_random_file()`.** It rejection-samples with `while` until it draws the
requested type. A library with no commercials (or nothing but commercials) spins forever.

**D3 — Bare `except:` in `play()`** swallows `KeyboardInterrupt` and `SystemExit` along with load errors.

**D4 — Every show truncated at ~5 minutes.** The `__main__` loop counts down `playcount = 300`, and the
counter conflates loop iterations with seconds.

**D5 — Unstable identity.** `Identifier` counts up from 100000 in `listdir` order, so IDs shift between
runs. This would silently corrupt play counts once persistence lands.

**D6 — Dead code.** `parse_dates_in_library()` `open()`s a directory path as a file (would crash if
called) and keys its dict by date, collapsing every undated file onto a single `None` key.
`filter_files()` returns its input unchanged. `load_datetime()` is empty. `METADATA_FILE` is declared
and never used. `speak()` accepts `gender`/`emphasis`/`speed` and ignores all three.

## Architecture

Python 3.11+ (matches Raspberry Pi OS Bookworm). Dependencies managed with `uv`; `from __future__`
import dropped.

```
pyproject.toml
otradio/
  __init__.py       public surface: Config, Radio, main
  config.py         Config dataclass; Config.from_cli(argv)
  dates.py          parse_release_date(filename) — pure, no I/O
  catalog.py        Recording dataclass; Catalog.from_directory()
  store.py          MetadataStore protocol + InMemoryStore
  audio.py          Player protocol + PygamePlayer + NullPlayer
  speech.py         Speaker protocol + EspeakSpeaker + NullSpeaker
  scheduler.py      AlternatingScheduler — selection policy
  app.py            Radio — run loop, wiring only
  __main__.py       entry point
tests/
  conftest.py       temp-library fixtures, fake Player/Speaker
  test_dates.py  test_catalog.py  test_scheduler.py  test_config.py  test_app.py
play_radio.py       3-line shim calling otradio.main()
```

`play_radio.py` is kept as a shim so whatever currently boots the Pi keeps working.

### Module responsibilities

| Module | Does | Depends on |
|---|---|---|
| `config` | Parse argv and env into a `Config` | stdlib |
| `dates` | Extract a release date from a filename | `dateutil` |
| `catalog` | Scan a directory into `Recording` objects, partitioned | `dates` |
| `store` | Read/write `PlayStats` by recording id | `catalog` types |
| `audio` | Load and play a file, report busy, stop | `pygame` (adapter only) |
| `speech` | Speak a line of text | `espeak-ng` (adapter only) |
| `scheduler` | Decide what plays next | `catalog` |
| `app` | Wire the above and run the loop | all of the above |

Only `audio` and `speech` touch hardware. Everything else is pure and testable on Windows.

## Data model

The 12-key dict and its prose docstring become two dataclasses, split along the persistence boundary.

```python
@dataclass(frozen=True)
class Recording:
    id: str                      # library-relative path — stable across runs
    filename: str
    path: Path
    release_date: date | None
    genre: Genre                 # SHOW | COMMERCIAL
    description: str | None = None
    length_seconds: int | None = None   # None = unknown or stream

@dataclass
class PlayStats:
    num_of_plays: int = 0
    last_played: datetime | None = None
    available: bool | None = None
    unavailable_at: list[datetime] = field(default_factory=list)
    interruptions: list[Interruption] = field(default_factory=list)
```

`Recording` is derived from the file and immutable. `PlayStats` is the mutable history, held by the
store and keyed by `Recording.id`. This is exactly what a future `JsonMetadataStore` persists, so
adding persistence touches one module.

**Identity (fixes D5):** `Recording.id` is the library-relative path, stable across runs and across
`listdir` ordering. The `Identifier = 100000` counter is removed.

`Genre` is an enum with `SHOW` and `COMMERCIAL`. It replaces the ad-hoc filename substring test at the
point of use, so the schema's `Genre` field stops being dead.

## Component design

### `dates.parse_release_date(filename) -> date | None`

Fixes D1. Replacement pattern, validated against real filename shapes:

```python
_DATE = re.compile(r"(?<!\d)(?:19\d{2}[-/]?\d{2}[-/]?\d{2}|\d{2}[-/]?\d{2}[-/]?\d{2})")
```

The 4-digit-year branch is tried first and anchored to `19` — all content is 20th century, consistent
with the existing forced-20th-century behavior. The `(?<!\d)` lookbehind stops a match from starting
mid-digit-run. There is deliberately **no** trailing `(?!\d)` lookahead: OTR filenames routinely glue
an episode number to the date (`XMinusOne55-07-28011...`), and a trailing boundary would reject those.

Parsing is wrapped in `try/except (ValueError, OverflowError)` returning `None`, so a malformed
filename yields an undated recording instead of killing startup. The existing "subtract 100 years if
year > 1999" coercion is preserved.

Verified behavior:

| Filename shape | Result |
|---|---|
| `Gunsmoke 52-07-26 (014)...` | 1952-07-26 |
| `Jb1953-09-13BackFrom...` | 1953-09-13 (crashes today) |
| `Suspense 470724 255 ... (128-44) 27864 29m02s` | 1947-07-24 |
| `XMinusOne55-07-28011TheEmbassy` | 1955-07-28 |
| `Some Commercial 19520726 spot` | 1952-07-26 (crashes today) |
| `1959/08/02 Have Gun Will Travel` | 1959-08-02 |
| `No date here at all` | `None` |
| `Episode 128-44 27864 29m02s` | `None` |

### `catalog.Catalog`

`Catalog.from_directory(path, commercial_marker)` scans one directory, skips files whose suffix is not
a known audio extension, builds a `Recording` per file, and **partitions shows and commercials once at
construction**. Exposes `shows`, `commercials`, `all`, and `get(id)`.

Genre is assigned by a case-insensitive check for `commercial_marker` (default `"commercial"`) in the
filename — the same rule as today, minus the case sensitivity, and recorded in the model rather than
recomputed at selection time.

A missing library directory raises a clear `LibraryNotFound` at call time, not at import.

### `scheduler.AlternatingScheduler`

Fixes D2. Constructed from a `Catalog`; alternates show and commercial by drawing from the
pre-partitioned lists. No rejection sampling, so the infinite loop is structurally impossible.

Degradation rule: if a bucket is empty, log once and play from the non-empty bucket continuously. An
appliance must never hang and never crash on an odd library. If both are empty, `next()` raises
`EmptyLibrary`.

### `audio.Player` / `speech.Speaker`

Protocols, so `app` depends on an interface rather than on `pygame` or `espeak`.

```python
class Player(Protocol):
    def start(self) -> None: ...
    def play(self, path: Path) -> None: ...
    def is_busy(self) -> bool: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...
```

`PygamePlayer` performs `pygame.init()` / `mixer.init()` / `set_volume()` inside `start()`, never at
import. Fixes D3 by catching `pygame.error` and `OSError` specifically and re-raising as
`PlaybackError`, which `app` records as unavailability.

`NullPlayer` and `NullSpeaker` are silent implementations used by tests and by `--dry-run`.

**Speech — open item.** `EspeakSpeaker` shells out to the `espeak-ng` binary via `subprocess`, needing
no Python binding and making the previously-ignored `gender`/`emphasis`/`speed` arguments real via
`-v` / `-a` / `-s`. If the `espeak` Python binding turns out to install cleanly on the target Pi, an
alternative implementation behind the same protocol is a one-file change. To be confirmed on the
device; does not block implementation.

### `app.Radio`

Holds `Config`, `Catalog`, `Scheduler`, `Player`, `Speaker`, `MetadataStore`. `run()` is the loop:
announce, then repeatedly pick, play, and wait.

Fixes D4: waiting is a wall-clock loop on `player.is_busy()`, so a show plays to its natural end.
`Config.max_play_seconds` defaults to `None` (unlimited) and exists only as a watchdog against a
wedged file — it is no longer the normal termination path.

Playback outcomes update `PlayStats` through the store, so persistence later needs no change here.

### `config.Config`

Frozen dataclass built by `Config.from_cli(argv)`: argparse flags, falling back to `OTRADIO_*`
environment variables, falling back to defaults. Kills the CWD dependency of `./recordings/OTRadio/`.

| Field | Flag | Env | Default |
|---|---|---|---|
| `library_dir` | `--library` | `OTRADIO_LIBRARY` | `./recordings/OTRadio` |
| `volume` | `--volume` | `OTRADIO_VOLUME` | `1.0` |
| `max_play_seconds` | `--max-play-seconds` | `OTRADIO_MAX_PLAY_SECONDS` | `None` |
| `commercial_marker` | `--commercial-marker` | `OTRADIO_COMMERCIAL_MARKER` | `commercial` |
| `speech_enabled` | `--no-speech` | `OTRADIO_SPEECH` | `True` |
| `dry_run` | `--dry-run` | — | `False` |

## Error handling

| Condition | Behavior |
|---|---|
| Library directory missing | `LibraryNotFound` with the resolved path, at call time |
| Library empty / both buckets empty | `EmptyLibrary` from the scheduler |
| One bucket empty | Log once, play the other continuously |
| Unparseable date in filename | `release_date = None`, recording still playable |
| File fails to load or play | `PlaybackError` caught in `app`; append to `unavailable_at`, continue to next |
| `espeak-ng` missing | Log once, fall back to `NullSpeaker`; radio still plays |
| Ctrl-C | Propagates (no longer swallowed), `player.close()` in a `finally` |

## Testing

`uv run pytest`, all hardware-free and runnable on Windows.

- `test_dates` — the eight verified shapes above, plus the >1999 coercion and malformed input
- `test_catalog` — indexing, extension filtering, show/commercial partitioning, undated files kept
  distinct, stable ids, missing directory
- `test_scheduler` — alternation order, empty-commercials degradation, empty-shows degradation, both
  empty raises
- `test_config` — flag parsing, env fallback, defaults, precedence
- `test_app` — the run loop against `NullPlayer`/`NullSpeaker` fakes, asserting call sequence and that
  a `PlaybackError` records unavailability and advances

Single test: `uv run pytest tests/test_dates.py::test_four_digit_year -q`

Pi-only verification is limited to `PygamePlayer` and `EspeakSpeaker`.

## Removals

Deleted outright, per approval: `parse_dates_in_library()` and `filter_files()` (both dead; one would
crash if called). `load_datetime()` is removed rather than left as an empty no-op that looks
implemented — its NTP → RTC → system-clock intent is recorded here as future work. `METADATA_FILE`
and `Identifier` are removed. Git history preserves all of it.

## Follow-on work (not this change)

1. `JsonMetadataStore` implementing `MetadataStore` — play counts and history survive reboot
2. Era/genre filtering — select by decade or genre, using `Recording.release_date` and `.genre`
3. Skip control — a button or key that stops the current show and records an `Interruption`
4. `load_datetime()` — NTP → RTC → system-clock precedence
5. Confirm the speech adapter choice on the Pi
