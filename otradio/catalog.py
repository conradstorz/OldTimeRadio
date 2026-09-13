"""The library of recordings available to play."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path

from otradio.config import DEFAULT_COMMERCIAL_MARKER
from otradio.dates import decade_of, parse_release_date

AUDIO_EXTENSIONS = frozenset(
    {".mp3", ".ogg", ".wav", ".m4a", ".aac", ".aif", ".aiff", ".flac", ".wma", ".mid"}
)


class LibraryNotFound(Exception):
    """The configured recordings directory does not exist."""


class Genre(Enum):
    SHOW = "show"
    COMMERCIAL = "commercial"


@dataclass(frozen=True)
class Recording:
    """One playable recording, derived from a file on disk.

    Identity and metadata only. Play history lives in a MetadataStore, keyed
    by `id`, so this object never changes once the library is scanned.
    """

    id: str
    filename: str
    path: Path
    release_date: date | None
    genre: Genre
    description: str | None = None
    length_seconds: int | None = None


class Catalog:
    """An indexed, pre-partitioned view of the recordings library."""

    def __init__(self, recordings: Iterable[Recording]) -> None:
        self._recordings = tuple(recordings)
        self._by_id = {recording.id: recording for recording in self._recordings}
        self._shows = tuple(r for r in self._recordings if r.genre is Genre.SHOW)
        self._commercials = tuple(
            r for r in self._recordings if r.genre is Genre.COMMERCIAL
        )
        by_decade: dict[int, list[Recording]] = {}
        for recording in self._shows:
            if recording.release_date is not None:
                by_decade.setdefault(
                    decade_of(recording.release_date), []
                ).append(recording)
        self._shows_by_decade = {
            decade: tuple(recordings)
            for decade, recordings in sorted(by_decade.items())
        }

    @classmethod
    def from_directory(
        cls,
        library_dir: Path,
        commercial_marker: str = DEFAULT_COMMERCIAL_MARKER,
    ) -> "Catalog":
        library_dir = Path(library_dir)
        if not library_dir.is_dir():
            raise LibraryNotFound(f"Recordings directory not found: {library_dir}")

        marker = commercial_marker.lower()
        recordings = []
        for path in sorted(library_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            filename = path.name
            genre = Genre.COMMERCIAL if marker in filename.lower() else Genre.SHOW
            recordings.append(
                Recording(
                    id=path.relative_to(library_dir).as_posix(),
                    filename=filename,
                    path=path,
                    release_date=parse_release_date(filename),
                    genre=genre,
                )
            )
        return cls(recordings)

    @property
    def all(self) -> tuple[Recording, ...]:
        return self._recordings

    @property
    def shows(self) -> tuple[Recording, ...]:
        return self._shows

    @property
    def commercials(self) -> tuple[Recording, ...]:
        return self._commercials

    @property
    def decades(self) -> tuple[int, ...]:
        """Decades with at least one dated show, ascending."""
        return tuple(self._shows_by_decade)

    def shows_for(self, era: int | None) -> tuple[Recording, ...]:
        """Shows for an era: a decade start year, or None for all shows."""
        if era is None:
            return self._shows
        return self._shows_by_decade.get(era, ())

    def get(self, recording_id: str) -> Recording | None:
        return self._by_id.get(recording_id)

    def __len__(self) -> int:
        return len(self._recordings)
