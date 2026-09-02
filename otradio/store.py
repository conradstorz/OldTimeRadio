"""Play history for recordings.

This module defines the persistence boundary. `InMemoryStore` is the current
behavior — history lives for one run and is lost on exit, exactly as before.
A future JsonMetadataStore implements the same protocol, and nothing else in
the package changes.
"""

from dataclasses import dataclass, field, replace
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
    """Reads and writes PlayStats, keyed by Recording.id.

    save() is called exactly once, from Radio.run()'s `finally`. Do not rely
    on it as the only persistence point: this appliance lives in a cabinet
    and is normally switched off at the wall, not shut down gracefully, so
    that `finally` block will typically never execute. A persistent
    implementation must flush each change as it is recorded (i.e. inside
    record_played / record_unavailable / record_interruption) and treat
    save() as, at best, a final flush on the rare clean exit.
    """

    def stats_for(self, recording_id: str) -> PlayStats:
        """Pure read. Does not create an entry for an unknown recording_id, and
        returns a snapshot the caller cannot use to mutate the store."""
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
        """Pure read. Does not create an entry, and returns a snapshot the
        caller cannot use to mutate the store."""
        stats = self._stats.get(recording_id, PlayStats())
        return replace(
            stats,
            unavailable_at=list(stats.unavailable_at),
            interruptions=list(stats.interruptions),
        )

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
