"""Play history for recordings.

This module defines the persistence boundary. `InMemoryStore` is the current
behavior — history lives for one run and is lost on exit, exactly as before.
A future JsonMetadataStore implements the same protocol, and nothing else in
the package changes.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class Interruption:
    """A recording the listener skipped, and how far it got."""

    at: datetime
    seconds_played: int


@dataclass
class PlayStats:
    """Mutable play history for one recording."""

    num_of_plays: int = 0
    last_played: datetime | None = None
    available: bool | None = None
    unavailable_at: list[datetime] = field(default_factory=list)
    interruptions: list[Interruption] = field(default_factory=list)


class MetadataStore(Protocol):
    """Reads and writes PlayStats, keyed by Recording.id."""

    def stats_for(self, recording_id: str) -> PlayStats:
        """Pure read. Does not create an entry for an unknown recording_id."""
        ...

    def record_played(self, recording_id: str, when: datetime) -> None: ...

    def record_unavailable(self, recording_id: str, when: datetime) -> None: ...

    def record_interruption(
        self, recording_id: str, when: datetime, seconds_played: int
    ) -> None: ...

    def save(self) -> None: ...


class InMemoryStore:
    """Holds play history for the current run only."""

    def __init__(self) -> None:
        self._stats: dict[str, PlayStats] = {}

    def stats_for(self, recording_id: str) -> PlayStats:
        """Pure read. Does not create an entry."""
        return self._stats.get(recording_id, PlayStats())

    def _mutable_stats_for(self, recording_id: str) -> PlayStats:
        return self._stats.setdefault(recording_id, PlayStats())

    def record_played(self, recording_id: str, when: datetime) -> None:
        stats = self._mutable_stats_for(recording_id)
        stats.num_of_plays += 1
        stats.last_played = when
        stats.available = True

    def record_unavailable(self, recording_id: str, when: datetime) -> None:
        stats = self._mutable_stats_for(recording_id)
        stats.unavailable_at.append(when)
        stats.available = False

    def record_interruption(
        self, recording_id: str, when: datetime, seconds_played: int
    ) -> None:
        stats = self._mutable_stats_for(recording_id)
        stats.interruptions.append(Interruption(at=when, seconds_played=seconds_played))

    def save(self) -> None:
        """No-op. Nothing is persisted yet."""
