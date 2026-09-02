# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A Raspberry Pi appliance that boots straight into an audio player, to be installed inside a 1940s radio cabinet. It shuffles old-time radio recordings from local disk, interleaving a commercial between shows, and speaks status through espeak.

The entire application is `play_radio.py`. There is no package, no test suite, no build step, and no dependency manifest — `README.md` lists the deps as raw apt/pip commands.

## Running

```
python play_radio.py
```

Target platform is Raspberry Pi / Linux. `pygame` and `python-espeak` are the hard dependencies; `espeak` has no Windows build, so the module import fails on the dev machine here. Anything that needs to actually run must run on the Pi. Static reasoning and edits work fine locally.

Deps per README: `apt-get install espeak python-espeak python-pygame`, `pip install python-dateutil`.

## Audio library

`DIRECTORY = './recordings/OTRadio/'` is read with `listdir` **at module import time**, so the script raises immediately if that directory does not exist. Media extensions (`*.mp3`, `*.wav`, …) are gitignored — the library lives on the Pi, never in the repo. Any script or test that imports `play_radio` inherits this import-time filesystem dependency.

## Architecture

**`Recording_dict`** is the in-memory database, built at import time and keyed by *URL* (`DIRECTORY + filename`), not by filename. Every producer of a key must apply the same `DIRECTORY +` prefix — `pick_a_random_file()` does this, which is why its return value can be passed straight to `play()`. `Identifier` is a module-level counter starting at 100000.

Each record carries the schema documented in the docstring near the top of the file: `ID`, `Filename`, `URL`, `Release_date`, `Description`, `Genre`, `Length`, `Num_of_plays`, `Last_played`, `Available`, `Unavailable_list`, `Was_interrupted`. Adding a field means updating both that docstring and the build loop.

**Dates come from filenames.** `parse_date()` regex-matches a 6- or 8-digit date (optionally `-`/`/` separated), parses it `yearfirst=True`, then subtracts 100 years from any result after 1999 — a workaround for dateutil resolving 2-digit years into the 21st century. Recordings are all pre-1950s, so 20th century is always the right answer here.

**Persistence is unimplemented.** `retrieve_recordings_data()` and `store_recordings_data()` are empty stubs; the plan noted in-file is `pickle`, and `METADATA_FILE = 'metadata/recordings.mtd'` is declared but unused. The commented-out retrieve/raise block in the module body is where loading is meant to hook in. This is the main open work item — play counts, interruptions, and availability history are all tracked in memory and lost on exit.

**Main loop** (`__main__`) alternates `we_should_play_a_commercial` on each iteration; "commercial" is detected purely by the substring `'Commercial'` in the filename, and `pick_a_random_file()` rejection-samples until it gets the right type — an empty or single-type library makes that loop spin forever. Playback is capped by a 300-second `playcount` countdown regardless of actual track length.

**Stubs and dead code to be aware of before "fixing" them:** `load_datetime()` (intended NTP → RTC → system-clock precedence) and `filter_files()` are declared but empty/pass-through. `parse_dates_in_library()` is unused and inconsistent with the rest — it `open()`s its argument as a file of names rather than listing a directory. `speak()` accepts `gender`/`emphasis`/`speed` and ignores them.

## `_reference/`

Untracked vendored copy of an unrelated third-party PHP website (`oldtimeradiodrama`), kept for design reference only. It downloads archive.org MP3s from a JSON schedule and serves a weekly episode page. Do not edit or commit it, and do not confuse its architecture with this project's.

## Git

`master` is the main branch. History includes merges from a collaborator's fork (`glyph250`).
