"""Runtime settings, from command-line flags and environment variables."""

import argparse
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_LIBRARY_DIR = Path("./recordings/OTRadio")
DEFAULT_COMMERCIAL_MARKER = "commercial"

_FALSEY = {"", "0", "false", "no", "off"}


def _env_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in _FALSEY


def _optional_int(value: str | int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = value.strip()
    return int(text) if text else None


@dataclass(frozen=True)
class Config:
    """Everything the radio needs to know before it starts."""

    library_dir: Path = DEFAULT_LIBRARY_DIR
    volume: float = 1.0
    max_play_seconds: int | None = None
    commercial_marker: str = DEFAULT_COMMERCIAL_MARKER
    speech_enabled: bool = True
    dry_run: bool = False

    @classmethod
    def from_cli(
        cls,
        argv: Sequence[str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> "Config":
        env = os.environ if env is None else env

        parser = argparse.ArgumentParser(
            prog="otradio",
            description="Play old time radio recordings continuously.",
        )
        parser.add_argument(
            "--library",
            type=Path,
            help="Directory holding the recordings.",
        )
        parser.add_argument(
            "--volume",
            type=float,
            help="Playback volume, 0.0 to 1.0.",
        )
        parser.add_argument(
            "--max-play-seconds",
            type=_optional_int,
            help="Watchdog only: give up on a recording after this long. "
            "Unlimited by default.",
        )
        parser.add_argument(
            "--commercial-marker",
            help="Filenames containing this word are treated as commercials.",
        )
        parser.add_argument(
            "--no-speech",
            dest="speech_enabled",
            action="store_false",
            help="Do not announce anything through the speech synthesiser.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run the loop with silent audio and speech. For testing off-device.",
        )

        # Environment-derived defaults are computed after the parser exists so a
        # malformed value can be reported through parser.error() -- the same
        # SystemExit(2)-plus-usage-message path argparse uses for a bad flag,
        # rather than letting a raw ValueError escape.
        env_defaults = {
            "library": Path(env.get("OTRADIO_LIBRARY") or DEFAULT_LIBRARY_DIR),
            "commercial_marker": env.get("OTRADIO_COMMERCIAL_MARKER")
            or DEFAULT_COMMERCIAL_MARKER,
            "speech_enabled": _env_bool(env.get("OTRADIO_SPEECH"), True),
        }
        try:
            env_defaults["volume"] = float(env.get("OTRADIO_VOLUME") or 1.0)
        except ValueError:
            parser.error(
                f"OTRADIO_VOLUME: invalid float value: {env['OTRADIO_VOLUME']!r}"
            )
        try:
            env_defaults["max_play_seconds"] = _optional_int(
                env.get("OTRADIO_MAX_PLAY_SECONDS")
            )
        except ValueError:
            parser.error(
                "OTRADIO_MAX_PLAY_SECONDS: invalid int value: "
                f"{env['OTRADIO_MAX_PLAY_SECONDS']!r}"
            )
        parser.set_defaults(**env_defaults)

        args = parser.parse_args(argv)

        return cls(
            library_dir=args.library,
            volume=args.volume,
            max_play_seconds=args.max_play_seconds,
            commercial_marker=args.commercial_marker,
            speech_enabled=args.speech_enabled,
            dry_run=args.dry_run,
        )
