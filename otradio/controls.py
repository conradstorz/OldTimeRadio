"""Runtime controls: how the listener changes what the radio plays.

`KeyboardControls` is for development and bench testing. The cabinet's real
input hardware (dial or buttons on GPIO) becomes another class behind the
same protocol when it is chosen.
"""

import logging
import queue
import sys
import threading
from enum import Enum
from typing import IO, Protocol

logger = logging.getLogger(__name__)


class Command(Enum):
    CYCLE_ERA = "cycle_era"
    SKIP = "skip"


class Controls(Protocol):
    """A source of listener commands, polled by the run loop."""

    def poll(self) -> Command | None:
        """Return one pending command, or None. Never blocks."""
        ...


class NullControls:
    """No input attached."""

    def poll(self) -> Command | None:
        return None


class KeyboardControls:
    """Line-based commands from a stream: 'e' + Enter cycles the era, 's' + Enter skips.

    A daemon thread reads the stream so poll() never blocks. The thread
    starts on the first poll, not in __init__, so construction does no I/O.
    The stream defaults to stdin at read time.
    """

    def __init__(self, stream: IO[str] | None = None) -> None:
        self._stream = stream
        self._queue: queue.Queue[str] = queue.Queue(maxsize=64)
        self._reader: threading.Thread | None = None

    def poll(self) -> Command | None:
        if self._reader is None:
            self._reader = threading.Thread(target=self._read_lines, daemon=True)
            self._reader.start()
        try:
            line = self._queue.get_nowait()
        except queue.Empty:
            return None
        text = line.strip().lower()
        if text == "e":
            return Command.CYCLE_ERA
        if text == "s":
            return Command.SKIP
        return None

    def _read_lines(self) -> None:
        stream = self._stream if self._stream is not None else sys.stdin
        try:
            if stream is None:  # e.g. a systemd unit with no stdin attached
                raise OSError("no stdin is attached")
            for line in stream:
                try:
                    self._queue.put_nowait(line)
                except queue.Full:
                    pass  # a stuck key must not grow memory without bound
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Keyboard controls stopped reading input: %s", exc)
