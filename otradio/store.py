"""Play history for recordings.

This module defines the persistence boundary. `InMemoryStore` keeps history
for one run only; `JsonMetadataStore` persists it to a JSON file beside the
recordings, flushing on every record because the appliance is normally
powered off at the wall rather than shut down cleanly.
"""

import json
import logging
import os
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


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
        """No-op by design: this store keeps history for one run only."""


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


def _require_int(value: object, field_name: str) -> int:
    # bool is a subclass of int; reject it explicitly so True/False never
    # silently pass as a play count or a duration.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an int, got {value!r}")
    return value


def _stats_from_json(entry: dict) -> PlayStats:
    num_of_plays = _require_int(entry["num_of_plays"], "num_of_plays")

    available = entry["available"]
    if available is not None and not isinstance(available, bool):
        raise ValueError(f"available must be a bool or None, got {available!r}")

    unavailable_at = entry["unavailable_at"]
    if not isinstance(unavailable_at, list):
        raise ValueError(f"unavailable_at must be a list, got {unavailable_at!r}")

    interruptions = entry["interruptions"]
    if not isinstance(interruptions, list):
        raise ValueError(f"interruptions must be a list, got {interruptions!r}")

    return PlayStats(
        num_of_plays=num_of_plays,
        last_played=(
            datetime.fromisoformat(entry["last_played"])
            if entry["last_played"] is not None
            else None
        ),
        available=available,
        unavailable_at=[datetime.fromisoformat(t) for t in unavailable_at],
        interruptions=[
            Interruption(
                at=datetime.fromisoformat(event["at"]),
                seconds_played=_require_int(
                    event["seconds_played"], "seconds_played"
                ),
            )
            for event in interruptions
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
        self._write_warned = False
        self._readonly = False
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
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return
        except OSError:
            if not self._quarantine():
                self._readonly = True
                logger.warning(
                    "%s could not be read or set aside; play history will not "
                    "be saved this run to avoid overwriting it.",
                    self._path,
                )
            return
        try:
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict) or data.get("version") != STATS_VERSION:
                raise ValueError("unrecognized stats file format")
            self._stats = {
                recording_id: _stats_from_json(entry)
                for recording_id, entry in data["recordings"].items()
            }
        # UnicodeDecodeError is a ValueError subclass, so an undecodable file
        # is quarantined the same way as unparseable or wrong-shaped JSON.
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            logger.warning(
                "%s is not a valid stats file (%s); discarding its history and "
                "setting it aside as %s.bad",
                self._path,
                exc,
                self._path,
            )
            self._stats = {}
            self._quarantine()

    def _flush(self) -> None:
        if self._readonly:
            if not self._write_warned:
                logger.warning(
                    "%s is read-only for this run (it could not be read or "
                    "set aside earlier); play history will not be saved.",
                    self._path,
                )
                self._write_warned = True
            return
        payload = {
            "version": STATS_VERSION,
            "recordings": {
                recording_id: _stats_to_json(stats)
                for recording_id, stats in self._stats.items()
            },
        }
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
            # os.replace() is atomic but not durable on its own: on POSIX the
            # rename must be fsynced via the containing directory's fd, or a
            # power cut can leave it unrecorded even though the write above
            # was fsynced. Windows has no O_DIRECTORY; a failure here falls
            # through to the same warn-once path as a write failure.
            if hasattr(os, "O_DIRECTORY"):
                dir_fd = os.open(self._path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
        except OSError as exc:
            # A stats file we cannot write must never stop the radio playing.
            if not self._write_warned:
                logger.warning(
                    "Could not write %s: %s. Play history will not be saved "
                    "until this is fixed.",
                    self._path,
                    exc,
                )
                self._write_warned = True

    def _quarantine(self) -> bool:
        """Set aside an unreadable stats file as `<path>.bad` and carry on.

        Returns True on success, False if the file could not be moved (it is
        left in place at self._path).
        """
        try:
            os.replace(self._path, self._path.with_name(self._path.name + ".bad"))
            return True
        except OSError as exc:
            logger.warning(
                "Could not set aside %s as %s.bad: %s",
                self._path,
                self._path,
                exc,
            )
            return False
