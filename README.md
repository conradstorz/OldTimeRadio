# OldTimeRadio
A Python powered Raspberry Pi implemented project to play recordings of old radio shows, commercials and news.

The goal is to create a computer that boots directly to an audio player that can be installed into an
old radio cabinet. My preference is to have the audio to be played match the era that the original radio
was constructed in. I have several old radio cabinets that were built during the 1940s. This is an incredibly
interesting time for me. The last world war was underway, radio shows were the TV of the time, radio was loaded
with creative content.

This project will be able to access any time period or all time periods depending...



## Running

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

    uv sync
    uv run otradio --library /path/to/recordings

Spoken announcements need the `espeak-ng` command:

    sudo apt-get install espeak-ng

Without it the radio still plays; it just stays quiet between shows.

A normal run writes play history to `otradio-stats.json` (plus transient
`.tmp` and, after a corrupt file is quarantined, `.bad` siblings) inside the
`--library` directory. `--dry-run` keeps history in memory only and writes
nothing there.

### Options

| Flag | Environment variable | Default |
|---|---|---|
| `--library` | `OTRADIO_LIBRARY` | `./recordings/OTRadio` |
| `--volume` | `OTRADIO_VOLUME` | `1.0` |
| `--max-play-seconds` | `OTRADIO_MAX_PLAY_SECONDS` | unlimited |
| `--commercial-marker` | `OTRADIO_COMMERCIAL_MARKER` | `commercial` |
| `--no-speech` | `OTRADIO_SPEECH` | speech on |
| `--dry-run` | — | off |
| `--era 1940` | — | `all` |
| `--controls keyboard\|none` | — | `none` |

Recordings whose filename contains the commercial marker are treated as
commercials and interleaved between shows. Broadcast dates are read from the
filename where one is present.

`--era` limits playback to shows from one decade (`--era all` is the
default). With `--controls keyboard`, typing `e` + Enter at runtime cycles
through the eras present in the library.

## Tests

    uv run pytest

The whole suite runs without audio hardware. Only the `pygame` and `espeak-ng`
adapters need the Pi.
