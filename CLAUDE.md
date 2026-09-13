# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A Raspberry Pi appliance that boots straight into an audio player, to be installed inside a 1940s radio cabinet. It shuffles old-time radio recordings from local disk, interleaving a commercial between shows, and speaks status through espeak.

The application is the `otradio` package. `play_radio.py` is a deprecated shim kept so existing boot scripts keep working; the real code lives under `otradio/`.

## Commands

| Task | Command |
|---|---|
| Install deps | `uv sync` |
| Run the radio | `uv run otradio --library <dir>` |
| Run off-device | `uv run otradio --library <dir> --dry-run --no-speech` |
| Run tests | `uv run pytest` |
| Run one test | `uv run pytest tests/test_dates.py::test_four_digit_year_does_not_crash -v` |

Target platform is Raspberry Pi OS Bookworm (Python 3.11). The full test suite
runs on Windows: only `otradio/audio.py` and `otradio/speech.py` touch
hardware, and both have null implementations.

## Architecture

`otradio` splits into pure logic and two hardware adapters. Nothing does I/O at
import time.

| Module | Responsibility |
|---|---|
| `config.py` | `Config` from CLI flags, then env vars, then defaults |
| `dates.py` | `parse_release_date(filename)` — pure |
| `catalog.py` | `Recording` model; `Catalog.from_directory()` scans and partitions |
| `store.py` | `PlayStats` and the `MetadataStore` protocol |
| `audio.py` | `Player` protocol; `PygamePlayer` (lazy pygame import) and `NullPlayer` |
| `speech.py` | `Speaker` protocol; `EspeakSpeaker` (subprocess) and `NullSpeaker` |
| `scheduler.py` | `AlternatingScheduler` — what plays next |
| `controls.py` | `Controls` protocol; `NullControls` and `KeyboardControls` (stdin) |
| `app.py` | `Radio` run loop, `build_radio()`, `main()` |

`pygame` must stay inside `PygamePlayer.start()`. Importing it at module level
breaks the hardware-free test suite; `tests/test_audio.py` asserts this.

**Recording identity is the library-relative path.** It must stay stable across
runs — `PlayStats` is keyed by it, and persistence will rely on that.

**Audio files are gitignored** (`*.mp3`, `*.wav`, …); the library lives on the
Pi. Tests build temporary libraries from empty files, which is enough because
nothing in the tested path reads audio data.

## Unimplemented, by design

`InMemoryStore.save()` is a no-op; normal runs use `JsonMetadataStore`, which
persists play history to `otradio-stats.json` in the library directory,
flushing on every record because the appliance is powered off at the wall.
The follow-on work, in order: genre filtering beyond show/commercial (needs
genre metadata in the library first), a GPIO `Controls` implementation for
the cabinet hardware, and `load_datetime()` (NTP → RTC → system clock).
See `docs/superpowers/specs/2026-09-02-otradio-refactor-design.md`.

Speech is an open item: `EspeakSpeaker` shells out to `espeak-ng` because the
`espeak` Python binding is Python 2-era. If the binding installs on the Pi, an
alternative behind the same protocol is a one-file change.

## `_reference/`

Untracked vendored copy of an unrelated third-party PHP website (`oldtimeradiodrama`), kept for design reference only. It downloads archive.org MP3s from a JSON schedule and serves a weekly episode page. Do not edit or commit it, and do not confuse its architecture with this project's.

## Git

`master` is the main branch. History includes merges from a collaborator's fork (`glyph250`).
