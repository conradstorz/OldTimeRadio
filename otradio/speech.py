"""Spoken announcements, behind an interface the run loop can be tested against.

Speech shells out to the espeak-ng binary rather than importing a Python
binding: nothing to install beyond the package your distribution already has,
and it works on any Python 3.

OPEN ITEM: if the `espeak` Python binding installs cleanly on the target Pi,
an alternative implementation behind the Speaker protocol is a change to this
file alone.
"""

import logging
import shutil
import subprocess
from collections.abc import Callable
from typing import Protocol

from otradio.config import Config

logger = logging.getLogger(__name__)

DEFAULT_COMMAND = "espeak-ng"


class Speaker(Protocol):
    """Says a line of text out loud."""

    def say(self, text: str) -> None: ...


class NullSpeaker:
    """A silent Speaker that records what it was told."""

    def __init__(self) -> None:
        self.said: list[str] = []

    def say(self, text: str) -> None:
        self.said.append(text)


def _run(command: list[str]) -> None:
    result = subprocess.run(command, check=False, capture_output=True)
    if result.returncode != 0:
        logger.debug(
            "%s exited with code %d", command[0], result.returncode
        )


class EspeakSpeaker:
    """Speaks by invoking the espeak-ng command."""

    def __init__(
        self,
        voice: str = "f3",
        amplitude: int = 150,
        speed: int = 150,
        command: str = DEFAULT_COMMAND,
        runner: Callable[[list[str]], None] | None = None,
    ) -> None:
        self._voice = voice
        self._amplitude = amplitude
        self._speed = speed
        self._command = command
        self._run = runner if runner is not None else _run

    @staticmethod
    def is_available(command: str = DEFAULT_COMMAND) -> bool:
        return shutil.which(command) is not None

    def say(self, text: str) -> None:
        command = [
            self._command,
            "-v", self._voice,
            "-a", str(self._amplitude),
            "-s", str(self._speed),
            "--",
            text,
        ]
        try:
            self._run(command)
        except OSError as exc:
            # A broken synthesiser must never stop the radio playing.
            logger.warning("Could not speak %r: %s", text, exc)


def make_speaker(config: Config) -> Speaker:
    """Pick a Speaker for this configuration."""
    if config.dry_run or not config.speech_enabled:
        return NullSpeaker()
    if not EspeakSpeaker.is_available():
        logger.warning(
            "%s is not on PATH; announcements are disabled. "
            "Install it with: sudo apt-get install espeak-ng",
            DEFAULT_COMMAND,
        )
        return NullSpeaker()
    return EspeakSpeaker()
