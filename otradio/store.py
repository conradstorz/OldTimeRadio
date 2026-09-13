"""Play history for recordings.

This module defines the persistence boundary. `InMemoryStore` keeps history
for one run only; `JsonMetadataStore` persists it to a JSON file beside the
recordings, flushing on every record because the appliance is normally
powered off at the wall rather than shut down cleanly.
"""

import json
import os
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
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


STATS_VERSION = 1


def _stats_to_json(stats: PlayStats) -> dict:
    return {
        "num_of_plays": stats.num_of_plays,
        "last_played": (
            stats.last_played.isoformat() if stats.last_played is not None else None
        ),
        "available": stats.available,
        "unavailable_at": [when.isoformat() for when in stats.unavailable_at],
        "interruptions": [
            {"at": event.at.isoformat(), "seconds_played": event.seconds_played}
            for event in stats.interruptions
        ],
    }


def _stats_from_json(entry: dict) -> PlayStats:
    return PlayStats(
        num_of_plays=entry["num_of_plays"],
        last_played=(
            datetime.fromisoformat(entry["last_played"])
            if entry["last_played"] is not None
            else None
        ),
        available=entry["available"],
        unavailable_at=[datetime.fromisoformat(t) for t in entry["unavailable_at"]],
        interruptions=[
            Interruption(
                at=datetime.fromisoformat(event["at"]),
                seconds_played=event["seconds_played"],
            )
            for event in entry["interruptions"]
        ],
    )


class JsonMetadataStore(InMemoryStore):
    """Play history persisted to one JSON file, flushed on every record.

    The appliance is normally switched off at the wall, so save() cannot be
    the persistence point (see MetadataStore). Every record_* call rewrites
    the file atomically: serialize to `<path>.tmp` in the same directory,
    then os.replace() over the real file. A power cut mid-write loses at
    most the event being written, never the file.
    """

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        self._load()

    def record_played(self, recording_id: str, when: datetime) -> None:
        super().record_played(recording_id, when)
        self._flush()

    def record_unavailable(self, recording_id: str, when: datetime) -> None:
        super().record_unavailable(recording_id, when)
        self._flush()

    def record_interruption(
        self, recording_id: str, when: datetime, seconds_played: int
    ) -> None:
        super().record_interruption(recording_id, when, seconds_played)
        self._flush()

    def save(self) -> None:
        """Final flush on the rare clean exit."""
        self._flush()

    def _load(self) -> None:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError:
            self._quarantine()
            return
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get("version") != STATS_VERSION:
                raise ValueError("unrecognized stats file format")
            self._stats = {
                recording_id: _stats_from_json(entry)
                for recording_id, entry in data["recordings"].items()
            }
        except (ValueError, KeyError, TypeError, AttributeError):
            self._stats = {}
            self._quarantine()

    def _flush(self) -> None:
        payload = {
            "version": STATS_VERSION,
            "recordings": {
                recording_id: _stats_to_json(stats)
                for recording_id, stats in self._stats.items()
            },
        }
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    def _quarantine(self) -> None:
        """Set aside an unreadable stats file as `<path>.bad` and carry on."""
        try:
            os.replace(self._path, self._path.with_name(self._path.name + ".bad"))
        except OSError:
            pass
