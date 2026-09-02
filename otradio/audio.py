"""Audio playback, behind an interface the run loop can be tested against."""

import logging
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


class PlaybackError(Exception):
    """A recording could not be loaded or played."""


class Player(Protocol):
    """Plays one recording at a time."""

    def start(self) -> None:
        """Initialise the audio device. Called once before any play()."""
        ...

    def play(self, path: Path) -> None:
        """Begin playing a file. Raises PlaybackError if it cannot."""
        ...

    def is_busy(self) -> bool:
        """True while a recording is still playing."""
        ...

    def stop(self) -> None:
        """Stop the current recording."""
        ...

    def close(self) -> None:
        """Release the audio device."""
        ...


class NullPlayer:
    """A silent Player that records what it was asked to do.

    Used by the test suite and by --dry-run. `busy_polls` simulates a
    recording's duration: is_busy() reports True that many times after each
    play(), then False.
    """

    def __init__(self, busy_polls: int = 0, fail_on: set[str] | None = None) -> None:
        self.busy_polls = busy_polls
        self.fail_on = fail_on or set()
        self.started = False
        self.closed = False
        self.played: list[Path] = []
        self.stopped = 0
        self._remaining = 0

    def start(self) -> None:
        self.started = True

    def play(self, path: Path) -> None:
        if path.name in self.fail_on:
            raise PlaybackError(f"Simulated failure playing {path.name}")
        self.played.append(path)
        self._remaining = self.busy_polls

    def is_busy(self) -> bool:
        if self._remaining <= 0:
            return False
        self._remaining -= 1
        return True

    def stop(self) -> None:
        self.stopped += 1
        self._remaining = 0

    def close(self) -> None:
        self.closed = True


class PygamePlayer:
    """Plays recordings through pygame's mixer.

    pygame is imported inside start() rather than at module level, so the rest
    of the package — and the whole test suite — runs without audio hardware.
    """

    def __init__(self, volume: float = 1.0) -> None:
        self._volume = volume
        self._pygame = None

    def start(self) -> None:
        import pygame  # noqa: PLC0415 — deliberately deferred, see class docstring

        self._pygame = pygame
        pygame.init()
        pygame.mixer.init()
        pygame.mixer.music.set_volume(self._volume)

    def play(self, path: Path) -> None:
        if self._pygame is None:
            raise PlaybackError("Player.start() must be called before play().")
        try:
            self._pygame.mixer.music.load(str(path))
            self._pygame.mixer.music.play()
        except (self._pygame.error, OSError) as exc:
            raise PlaybackError(f"Could not play {path.name}: {exc}") from exc

    def is_busy(self) -> bool:
        if self._pygame is None:
            return False
        return bool(self._pygame.mixer.music.get_busy())

    def stop(self) -> None:
        if self._pygame is not None:
            self._pygame.mixer.music.stop()

    def close(self) -> None:
        if self._pygame is None:
            return
        self._pygame.mixer.music.stop()
        self._pygame.mixer.quit()
        self._pygame.quit()
        self._pygame = None
