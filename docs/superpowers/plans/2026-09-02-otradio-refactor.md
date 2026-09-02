# OldTimeRadio Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the single-file `play_radio.py` into a tested, installable `otradio` package with clear module boundaries and no import-time side effects.

**Architecture:** Pure logic modules (`dates`, `catalog`, `store`, `scheduler`, `config`) have no hardware dependency and are fully tested on Windows. Hardware lives behind two adapter protocols (`audio.Player`, `speech.Speaker`) with null implementations for tests and `--dry-run`. `app.Radio` wires them together and owns the run loop.

**Tech Stack:** Python 3.11+, `uv`, `pytest`, `python-dateutil`, `pygame` (lazily imported), `espeak-ng` (via subprocess).

**Spec:** `docs/superpowers/specs/2026-09-02-otradio-refactor-design.md`

## Global Constraints

- Python `>=3.11`. Do not use `from __future__ import ...`.
- All dependency and test commands go through `uv`. Never `pip install`, never `python -m venv`.
- Never chain shell commands with `&&`. One command per tool call.
- No module may perform I/O, hardware init, or filesystem access at import time.
- `pygame` must be imported **inside** `PygamePlayer.start()`, never at module top level, so the test suite runs without audio hardware.
- Only `otradio/audio.py` may reference `pygame`. Only `otradio/speech.py` may reference `espeak-ng`.
- Type hints use modern syntax: `date | None`, `list[datetime]`, `tuple[Recording, ...]`.
- Public names are exactly as given in the **Interfaces** block of each task. Later tasks depend on them verbatim.
- Work happens on branch `refactor/otradio-package`.

---

### Task 1: Project scaffolding and date parsing

Creates the package skeleton, `pyproject.toml`, and the first pure module. Fixes defect **D1** (startup crash on any 4-digit-year filename).

**Files:**
- Create: `pyproject.toml`
- Create: `otradio/__init__.py`
- Create: `otradio/dates.py`
- Create: `tests/__init__.py`
- Test: `tests/test_dates.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `otradio.dates.parse_release_date(filename: str) -> datetime.date | None`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "otradio"
version = "0.2.0"
description = "Old time radio player for a Raspberry Pi installed in a 1940s radio cabinet"
requires-python = ">=3.11"
dependencies = [
    "python-dateutil>=2.8",
    "pygame>=2.5",
]

[project.scripts]
otradio = "otradio.app:main"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["otradio"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create empty package markers**

Create `otradio/__init__.py` containing exactly:

```python
"""Old time radio player."""
```

Create `tests/__init__.py` as an empty file (zero bytes).

- [ ] **Step 3: Sync the environment**

Run: `uv sync`
Expected: creates `.venv` and resolves `python-dateutil`, `pygame`, `pytest`. Exit code 0.

- [ ] **Step 4: Write the failing test**

Create `tests/test_dates.py`:

```python
from datetime import date

import pytest

from otradio.dates import parse_release_date


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Gunsmoke 52-07-26 (014) Gentleman's Disagreement.mp3", date(1952, 7, 26)),
        ("Jb1953-09-13BackFromVacationInHawaii.mp3", date(1953, 9, 13)),
        ("Dragnet_51-07-26_111_The_Big_Late_Script.mp3", date(1951, 7, 26)),
        ("Suspense 470724 255 Murder by an Expert (128-44) 27864 29m02s.mp3", date(1947, 7, 24)),
        ("XMinusOne55-07-28011TheEmbassy.mp3", date(1955, 7, 28)),
        ("Some Commercial 19520726 spot.mp3", date(1952, 7, 26)),
        ("1959/08/02 Have Gun Will Travel.mp3", date(1959, 8, 2)),
    ],
)
def test_parses_known_filename_shapes(filename, expected):
    assert parse_release_date(filename) == expected


def test_four_digit_year_does_not_crash():
    """Regression: the old regex matched '1953-09-' and raised ParserError at startup."""
    assert parse_release_date("Jb1953-09-13BackFromVacationInHawaii.mp3") == date(1953, 9, 13)


@pytest.mark.parametrize(
    "filename",
    [
        "No date here at all.mp3",
        "Episode 128-44 27864 29m02s.mp3",
        "",
    ],
)
def test_returns_none_when_no_date_present(filename):
    assert parse_release_date(filename) is None


@pytest.mark.parametrize(
    "filename",
    [
        "Show 1953-0913 odd.mp3",
        "Show 999999 nope.mp3",
    ],
)
def test_returns_none_when_match_is_unparseable(filename):
    """Matches the pattern but dateutil rejects it. Must degrade, not raise."""
    assert parse_release_date(filename) is None


def test_two_digit_year_is_forced_into_the_twentieth_century():
    assert parse_release_date("Show 52-07-26.mp3").year == 1952
```

- [ ] **Step 5: Run the test to verify it fails**

Run: `uv run pytest tests/test_dates.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'otradio.dates'`

- [ ] **Step 6: Write the implementation**

Create `otradio/dates.py`:

```python
"""Extract release dates from recording filenames."""

import re
from datetime import date

from dateutil.parser import parse as _parse_datetime

# Ordered alternation: the four-digit-year form is tried first, anchored to
# "19" because every recording in this library predates 2000. The old pattern
# put the six-digit form first, so "1953-09-13" matched only "1953-09-" and
# raised ParserError at startup.
#
# There is deliberately no trailing (?!\d) boundary: OTR filenames routinely
# glue an episode number to the date, as in "XMinusOne55-07-28011TheEmbassy",
# and a trailing boundary would reject those.
_DATE_PATTERN = re.compile(
    r"(?<!\d)(?:19\d{2}[-/]?\d{2}[-/]?\d{2}|\d{2}[-/]?\d{2}[-/]?\d{2})"
)


def parse_release_date(filename: str) -> date | None:
    """Return the broadcast date encoded in a filename, or None.

    Returns None when the filename carries no date, or carries something that
    looks like one but cannot be parsed. Never raises: an undated recording is
    still playable.
    """
    match = _DATE_PATTERN.search(filename)
    if match is None:
        return None

    try:
        parsed = _parse_datetime(match.group(0), yearfirst=True)
    except (ValueError, OverflowError):
        # dateutil's ParserError subclasses ValueError.
        return None

    if parsed.year > 1999:
        # dateutil resolves two-digit years into the 21st century.
        parsed = parsed.replace(year=parsed.year - 100)
    return parsed.date()
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `uv run pytest tests/test_dates.py -v`
Expected: PASS — 14 passed.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml otradio/__init__.py otradio/dates.py tests/__init__.py tests/test_dates.py
git commit -m "feat: add otradio package skeleton and date parsing

Fixes a startup crash: the old regex tried the six-digit branch first,
truncating four-digit-year dates to an unparseable prefix and raising
ParserError from the module-level build loop."
```

---

### Task 2: Recording model and catalog

Replaces the 12-key dict and its docstring schema. Fixes defect **D5** (unstable ids) and moves genre into the model.

**Files:**
- Create: `otradio/catalog.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: `otradio.dates.parse_release_date(filename: str) -> date | None`
- Produces:
  - `otradio.catalog.Genre` — `Enum` with members `SHOW` (value `"show"`) and `COMMERCIAL` (value `"commercial"`)
  - `otradio.catalog.LibraryNotFound(Exception)`
  - `otradio.catalog.AUDIO_EXTENSIONS: frozenset[str]`
  - `otradio.catalog.Recording` — frozen dataclass with fields `id: str`, `filename: str`, `path: Path`, `release_date: date | None`, `genre: Genre`, `description: str | None = None`, `length_seconds: int | None = None`
  - `otradio.catalog.Catalog(recordings: Iterable[Recording])`
  - `Catalog.from_directory(library_dir: Path, commercial_marker: str = "commercial") -> Catalog` (classmethod)
  - `Catalog.shows -> tuple[Recording, ...]` (property)
  - `Catalog.commercials -> tuple[Recording, ...]` (property)
  - `Catalog.all -> tuple[Recording, ...]` (property)
  - `Catalog.get(recording_id: str) -> Recording | None`
  - `Catalog.__len__() -> int`

- [ ] **Step 1: Write the failing test**

Create `tests/test_catalog.py`:

```python
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path

import pytest

from otradio.catalog import Catalog, Genre, LibraryNotFound, Recording


def make_library(tmp_path: Path, names: list[str]) -> Path:
    library = tmp_path / "OTRadio"
    library.mkdir()
    for name in names:
        (library / name).write_bytes(b"")
    return library


def test_indexes_audio_files(tmp_path):
    library = make_library(tmp_path, ["Gunsmoke 52-07-26.mp3", "Dragnet 51-07-26.ogg"])
    catalog = Catalog.from_directory(library)
    assert len(catalog) == 2
    assert {r.filename for r in catalog.all} == {
        "Gunsmoke 52-07-26.mp3",
        "Dragnet 51-07-26.ogg",
    }


def test_skips_non_audio_files_and_directories(tmp_path):
    library = make_library(tmp_path, ["Show 52-07-26.mp3", "notes.txt", "cover.jpg"])
    (library / "subdir").mkdir()
    catalog = Catalog.from_directory(library)
    assert len(catalog) == 1
    assert catalog.all[0].filename == "Show 52-07-26.mp3"


def test_partitions_shows_and_commercials(tmp_path):
    library = make_library(
        tmp_path,
        ["Gunsmoke 52-07-26.mp3", "Lucky Strike Commercial 1948.mp3"],
    )
    catalog = Catalog.from_directory(library)
    assert [r.filename for r in catalog.shows] == ["Gunsmoke 52-07-26.mp3"]
    assert [r.filename for r in catalog.commercials] == ["Lucky Strike Commercial 1948.mp3"]
    assert catalog.commercials[0].genre is Genre.COMMERCIAL
    assert catalog.shows[0].genre is Genre.SHOW


def test_commercial_detection_is_case_insensitive(tmp_path):
    library = make_library(tmp_path, ["pepsi commercial spot.mp3"])
    catalog = Catalog.from_directory(library)
    assert len(catalog.commercials) == 1


def test_honours_a_custom_commercial_marker(tmp_path):
    library = make_library(tmp_path, ["Ovaltine advert.mp3", "Gunsmoke 52-07-26.mp3"])
    catalog = Catalog.from_directory(library, commercial_marker="advert")
    assert [r.filename for r in catalog.commercials] == ["Ovaltine advert.mp3"]


def test_parses_release_dates(tmp_path):
    library = make_library(tmp_path, ["Gunsmoke 52-07-26.mp3"])
    catalog = Catalog.from_directory(library)
    assert catalog.all[0].release_date == date(1952, 7, 26)


def test_keeps_undated_recordings_as_distinct_entries(tmp_path):
    """The old parse_dates_in_library keyed by date, collapsing these onto one None key."""
    library = make_library(tmp_path, ["Mystery One.mp3", "Mystery Two.mp3"])
    catalog = Catalog.from_directory(library)
    assert len(catalog) == 2
    assert all(r.release_date is None for r in catalog.all)


def test_ids_are_stable_library_relative_paths(tmp_path):
    library = make_library(tmp_path, ["Gunsmoke 52-07-26.mp3"])
    first = Catalog.from_directory(library)
    second = Catalog.from_directory(library)
    assert first.all[0].id == "Gunsmoke 52-07-26.mp3"
    assert first.all[0].id == second.all[0].id


def test_get_returns_recording_by_id(tmp_path):
    library = make_library(tmp_path, ["Gunsmoke 52-07-26.mp3"])
    catalog = Catalog.from_directory(library)
    assert catalog.get("Gunsmoke 52-07-26.mp3").filename == "Gunsmoke 52-07-26.mp3"
    assert catalog.get("nope.mp3") is None


def test_missing_directory_raises_library_not_found(tmp_path):
    with pytest.raises(LibraryNotFound) as excinfo:
        Catalog.from_directory(tmp_path / "does-not-exist")
    assert "does-not-exist" in str(excinfo.value)


def test_recording_is_immutable(tmp_path):
    library = make_library(tmp_path, ["Gunsmoke 52-07-26.mp3"])
    recording = Catalog.from_directory(library).all[0]
    with pytest.raises(FrozenInstanceError):
        recording.filename = "other.mp3"


def test_empty_library_produces_empty_catalog(tmp_path):
    library = make_library(tmp_path, [])
    catalog = Catalog.from_directory(library)
    assert len(catalog) == 0
    assert catalog.shows == ()
    assert catalog.commercials == ()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'otradio.catalog'`

- [ ] **Step 3: Write the implementation**

Create `otradio/catalog.py`:

```python
"""The library of recordings available to play."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path

from otradio.dates import parse_release_date

AUDIO_EXTENSIONS = frozenset(
    {".mp3", ".ogg", ".wav", ".m4a", ".aac", ".aif", ".aiff", ".flac", ".wma", ".mid"}
)

DEFAULT_COMMERCIAL_MARKER = "commercial"


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

    def get(self, recording_id: str) -> Recording | None:
        return self._by_id.get(recording_id)

    def __len__(self) -> int:
        return len(self._recordings)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_catalog.py -v`
Expected: PASS — 12 passed.

- [ ] **Step 5: Commit**

```bash
git add otradio/catalog.py tests/test_catalog.py
git commit -m "feat: add Recording model and Catalog

Replaces the 12-key dict and its docstring schema. Ids are now stable
library-relative paths rather than a listdir-ordered counter, which would
have corrupted play counts once persistence lands."
```

---

### Task 3: Play statistics and metadata store

Defines the persistence boundary. Persistence itself is **not** implemented here — `InMemoryStore` is the honest current behavior, and a future `JsonMetadataStore` implements the same protocol.

**Files:**
- Create: `otradio/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: nothing (keyed by `str` ids from Task 2, no import needed).
- Produces:
  - `otradio.store.Interruption` — frozen dataclass, fields `at: datetime`, `seconds_played: int`
  - `otradio.store.PlayStats` — dataclass, fields `num_of_plays: int = 0`, `last_played: datetime | None = None`, `available: bool | None = None`, `unavailable_at: list[datetime]`, `interruptions: list[Interruption]`
  - `otradio.store.MetadataStore` — `Protocol` with `stats_for(recording_id: str) -> PlayStats`, `record_played(recording_id: str, when: datetime) -> None`, `record_unavailable(recording_id: str, when: datetime) -> None`, `record_interruption(recording_id: str, when: datetime, seconds_played: int) -> None`, `save() -> None`
  - `otradio.store.InMemoryStore()` — implements `MetadataStore`

- [ ] **Step 1: Write the failing test**

Create `tests/test_store.py`:

```python
from datetime import datetime

from otradio.store import InMemoryStore, PlayStats


def test_unknown_recording_starts_with_blank_stats():
    store = InMemoryStore()
    stats = store.stats_for("gunsmoke.mp3")
    assert stats == PlayStats()
    assert stats.num_of_plays == 0
    assert stats.last_played is None
    assert stats.available is None


def test_record_played_increments_count_and_marks_available():
    store = InMemoryStore()
    when = datetime(1952, 7, 26, 19, 0)
    store.record_played("gunsmoke.mp3", when)
    stats = store.stats_for("gunsmoke.mp3")
    assert stats.num_of_plays == 1
    assert stats.last_played == when
    assert stats.available is True


def test_record_played_accumulates():
    store = InMemoryStore()
    store.record_played("gunsmoke.mp3", datetime(1952, 7, 26))
    store.record_played("gunsmoke.mp3", datetime(1952, 7, 27))
    stats = store.stats_for("gunsmoke.mp3")
    assert stats.num_of_plays == 2
    assert stats.last_played == datetime(1952, 7, 27)


def test_record_unavailable_appends_timestamp_and_marks_unavailable():
    store = InMemoryStore()
    when = datetime(1952, 7, 26)
    store.record_unavailable("broken.mp3", when)
    stats = store.stats_for("broken.mp3")
    assert stats.unavailable_at == [when]
    assert stats.available is False
    assert stats.num_of_plays == 0


def test_record_interruption_appends_event():
    store = InMemoryStore()
    when = datetime(1952, 7, 26)
    store.record_interruption("gunsmoke.mp3", when, seconds_played=42)
    interruptions = store.stats_for("gunsmoke.mp3").interruptions
    assert len(interruptions) == 1
    assert interruptions[0].at == when
    assert interruptions[0].seconds_played == 42


def test_stats_are_kept_per_recording():
    store = InMemoryStore()
    store.record_played("a.mp3", datetime(1952, 7, 26))
    assert store.stats_for("a.mp3").num_of_plays == 1
    assert store.stats_for("b.mp3").num_of_plays == 0


def test_save_is_a_no_op_that_does_not_raise():
    """Persistence is deliberately unimplemented; save() exists for the protocol."""
    store = InMemoryStore()
    store.record_played("a.mp3", datetime(1952, 7, 26))
    store.save()
    assert store.stats_for("a.mp3").num_of_plays == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'otradio.store'`

- [ ] **Step 3: Write the implementation**

Create `otradio/store.py`:

```python
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

    def stats_for(self, recording_id: str) -> PlayStats: ...

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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_store.py -v`
Expected: PASS — 8 passed.

- [ ] **Step 5: Commit**

```bash
git add otradio/store.py tests/test_store.py
git commit -m "feat: add PlayStats and the MetadataStore boundary

Persistence stays unimplemented by design; InMemoryStore is the honest
current behavior behind the protocol a JsonMetadataStore will implement."
```

---

### Task 4: Selection policy

Fixes defect **D2** (infinite loop). Rejection sampling is replaced by drawing from pre-partitioned lists, so the hang is structurally impossible.

**Files:**
- Create: `otradio/scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `otradio.catalog.Catalog`, `otradio.catalog.Recording`, `otradio.catalog.Genre`
- Produces:
  - `otradio.scheduler.EmptyLibrary(Exception)`
  - `otradio.scheduler.AlternatingScheduler(catalog: Catalog, rng: random.Random | None = None)`
  - `AlternatingScheduler.next() -> Recording`

Behavior: the first call returns a show, then alternates commercial, show, commercial. If the wanted bucket is empty, it logs once at WARNING and draws from the other bucket without toggling, so the radio plays continuously. If both buckets are empty, `next()` raises `EmptyLibrary`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scheduler.py`:

```python
import logging
import random
from datetime import date
from pathlib import Path

import pytest

from otradio.catalog import Catalog, Genre, Recording
from otradio.scheduler import AlternatingScheduler, EmptyLibrary


def make_recording(name: str, genre: Genre) -> Recording:
    return Recording(
        id=name,
        filename=name,
        path=Path("/library") / name,
        release_date=date(1952, 7, 26),
        genre=genre,
    )


def make_catalog(show_count: int, commercial_count: int) -> Catalog:
    recordings = [
        make_recording(f"show-{i}.mp3", Genre.SHOW) for i in range(show_count)
    ] + [
        make_recording(f"commercial-{i}.mp3", Genre.COMMERCIAL)
        for i in range(commercial_count)
    ]
    return Catalog(recordings)


def test_alternates_show_then_commercial():
    scheduler = AlternatingScheduler(make_catalog(3, 3), rng=random.Random(0))
    genres = [scheduler.next().genre for _ in range(6)]
    assert genres == [
        Genre.SHOW,
        Genre.COMMERCIAL,
        Genre.SHOW,
        Genre.COMMERCIAL,
        Genre.SHOW,
        Genre.COMMERCIAL,
    ]


def test_plays_shows_continuously_when_there_are_no_commercials():
    """Regression: the old rejection-sampling loop spun forever here."""
    scheduler = AlternatingScheduler(make_catalog(3, 0), rng=random.Random(0))
    genres = [scheduler.next().genre for _ in range(5)]
    assert genres == [Genre.SHOW] * 5


def test_plays_commercials_continuously_when_there_are_no_shows():
    scheduler = AlternatingScheduler(make_catalog(0, 3), rng=random.Random(0))
    genres = [scheduler.next().genre for _ in range(5)]
    assert genres == [Genre.COMMERCIAL] * 5


def test_degradation_is_logged_once(caplog):
    scheduler = AlternatingScheduler(make_catalog(3, 0), rng=random.Random(0))
    with caplog.at_level(logging.WARNING, logger="otradio.scheduler"):
        for _ in range(5):
            scheduler.next()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_empty_library_raises():
    scheduler = AlternatingScheduler(make_catalog(0, 0), rng=random.Random(0))
    with pytest.raises(EmptyLibrary):
        scheduler.next()


def test_selection_is_deterministic_for_a_seeded_rng():
    first = AlternatingScheduler(make_catalog(5, 5), rng=random.Random(7))
    second = AlternatingScheduler(make_catalog(5, 5), rng=random.Random(7))
    assert [first.next().id for _ in range(6)] == [second.next().id for _ in range(6)]


def test_draws_only_from_the_catalog():
    catalog = make_catalog(2, 2)
    scheduler = AlternatingScheduler(catalog, rng=random.Random(1))
    ids = {r.id for r in catalog.all}
    for _ in range(10):
        assert scheduler.next().id in ids
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'otradio.scheduler'`

- [ ] **Step 3: Write the implementation**

Create `otradio/scheduler.py`:

```python
"""Decides what plays next."""

import logging
import random

from otradio.catalog import Catalog, Recording

logger = logging.getLogger(__name__)


class EmptyLibrary(Exception):
    """There is nothing at all to play."""


class AlternatingScheduler:
    """Alternates shows and commercials.

    Draws from the catalog's pre-partitioned lists rather than sampling at
    random until the right type turns up, so a library with only one kind of
    recording can never hang the radio.
    """

    def __init__(self, catalog: Catalog, rng: random.Random | None = None) -> None:
        self._catalog = catalog
        self._rng = rng if rng is not None else random.Random()
        self._want_commercial = False
        self._warned_about_missing: set[str] = set()

    def next(self) -> Recording:
        shows = self._catalog.shows
        commercials = self._catalog.commercials
        if not shows and not commercials:
            raise EmptyLibrary("The recordings library contains nothing playable.")

        wanted = commercials if self._want_commercial else shows
        if wanted:
            self._want_commercial = not self._want_commercial
            return self._rng.choice(wanted)

        # The bucket we wanted is empty. Play the other kind continuously
        # rather than stalling, and do not toggle: every later call lands here
        # too, which is the point.
        self._warn_once("commercials" if self._want_commercial else "shows")
        fallback = shows if shows else commercials
        return self._rng.choice(fallback)

    def _warn_once(self, missing: str) -> None:
        if missing in self._warned_about_missing:
            return
        self._warned_about_missing.add(missing)
        logger.warning(
            "No %s in the library; playing the remaining recordings continuously.",
            missing,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: PASS — 7 passed.

- [ ] **Step 5: Commit**

```bash
git add otradio/scheduler.py tests/test_scheduler.py
git commit -m "feat: add AlternatingScheduler

Replaces rejection sampling, which looped forever when the library held no
commercials. An empty bucket now degrades to continuous play."
```

---

### Task 5: Configuration

Removes the hardcoded relative `./recordings/OTRadio/` and the CWD dependency.

**Files:**
- Create: `otradio/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `otradio.config.DEFAULT_LIBRARY_DIR: Path` — `Path("./recordings/OTRadio")`
  - `otradio.config.Config` — frozen dataclass with fields `library_dir: Path`, `volume: float = 1.0`, `max_play_seconds: int | None = None`, `commercial_marker: str = "commercial"`, `speech_enabled: bool = True`, `dry_run: bool = False`
  - `Config.from_cli(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> Config` (classmethod)

Precedence is flag, then environment variable, then default.

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from otradio.config import DEFAULT_LIBRARY_DIR, Config


def test_defaults_when_no_flags_or_env():
    config = Config.from_cli([], env={})
    assert config.library_dir == DEFAULT_LIBRARY_DIR
    assert config.volume == 1.0
    assert config.max_play_seconds is None
    assert config.commercial_marker == "commercial"
    assert config.speech_enabled is True
    assert config.dry_run is False


def test_flags_are_parsed():
    config = Config.from_cli(
        [
            "--library", "/media/otr",
            "--volume", "0.6",
            "--max-play-seconds", "1800",
            "--commercial-marker", "advert",
            "--no-speech",
            "--dry-run",
        ],
        env={},
    )
    assert config.library_dir == Path("/media/otr")
    assert config.volume == 0.6
    assert config.max_play_seconds == 1800
    assert config.commercial_marker == "advert"
    assert config.speech_enabled is False
    assert config.dry_run is True


def test_environment_variables_are_used_when_flags_are_absent():
    config = Config.from_cli(
        [],
        env={
            "OTRADIO_LIBRARY": "/media/otr",
            "OTRADIO_VOLUME": "0.25",
            "OTRADIO_MAX_PLAY_SECONDS": "600",
            "OTRADIO_COMMERCIAL_MARKER": "advert",
            "OTRADIO_SPEECH": "0",
        },
    )
    assert config.library_dir == Path("/media/otr")
    assert config.volume == 0.25
    assert config.max_play_seconds == 600
    assert config.commercial_marker == "advert"
    assert config.speech_enabled is False


def test_flags_override_environment_variables():
    config = Config.from_cli(
        ["--library", "/from/flag", "--volume", "0.9"],
        env={"OTRADIO_LIBRARY": "/from/env", "OTRADIO_VOLUME": "0.1"},
    )
    assert config.library_dir == Path("/from/flag")
    assert config.volume == 0.9


@pytest.mark.parametrize("value", ["0", "false", "False", "no", "off", ""])
def test_speech_env_falsey_values_disable_speech(value):
    assert Config.from_cli([], env={"OTRADIO_SPEECH": value}).speech_enabled is False


@pytest.mark.parametrize("value", ["1", "true", "True", "yes", "on"])
def test_speech_env_truthy_values_enable_speech(value):
    assert Config.from_cli([], env={"OTRADIO_SPEECH": value}).speech_enabled is True


def test_blank_max_play_seconds_env_is_treated_as_unlimited():
    assert Config.from_cli([], env={"OTRADIO_MAX_PLAY_SECONDS": ""}).max_play_seconds is None


def test_config_is_immutable():
    config = Config.from_cli([], env={})
    with pytest.raises(FrozenInstanceError):
        config.volume = 0.5
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'otradio.config'`

- [ ] **Step 3: Write the implementation**

> **Amended during execution (approved):** the code below parses env values while building
> argparse `default=` arguments, so a malformed `OTRADIO_VOLUME` or `OTRADIO_MAX_PLAY_SECONDS`
> raises a raw `ValueError` instead of argparse's clean error. The shipped implementation
> computes env-derived defaults after constructing the parser and routes failures through
> `parser.error(...)`, giving `SystemExit(2)` with a message naming the variable. See
> `otradio/config.py` for the authoritative version.

Create `otradio/config.py`:

```python
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
            default=Path(env.get("OTRADIO_LIBRARY") or DEFAULT_LIBRARY_DIR),
            help="Directory holding the recordings.",
        )
        parser.add_argument(
            "--volume",
            type=float,
            default=float(env.get("OTRADIO_VOLUME") or 1.0),
            help="Playback volume, 0.0 to 1.0.",
        )
        parser.add_argument(
            "--max-play-seconds",
            type=_optional_int,
            default=_optional_int(env.get("OTRADIO_MAX_PLAY_SECONDS")),
            help="Watchdog only: give up on a recording after this long. "
            "Unlimited by default.",
        )
        parser.add_argument(
            "--commercial-marker",
            default=env.get("OTRADIO_COMMERCIAL_MARKER") or DEFAULT_COMMERCIAL_MARKER,
            help="Filenames containing this word are treated as commercials.",
        )
        parser.add_argument(
            "--no-speech",
            dest="speech_enabled",
            action="store_false",
            default=_env_bool(env.get("OTRADIO_SPEECH"), True),
            help="Do not announce anything through the speech synthesiser.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run the loop with silent audio and speech. For testing off-device.",
        )
        args = parser.parse_args(argv)

        return cls(
            library_dir=args.library,
            volume=args.volume,
            max_play_seconds=args.max_play_seconds,
            commercial_marker=args.commercial_marker,
            speech_enabled=args.speech_enabled,
            dry_run=args.dry_run,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS — 17 passed.

- [ ] **Step 5: Commit**

```bash
git add otradio/config.py tests/test_config.py
git commit -m "feat: add Config from CLI flags and environment

Removes the hardcoded relative library path and the CWD dependency."
```

---

### Task 6: Audio adapter

Fixes defects **D3** (bare `except:`) and moves `pygame.init()` out of import time.

**Files:**
- Create: `otradio/audio.py`
- Test: `tests/test_audio.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `otradio.audio.PlaybackError(Exception)`
  - `otradio.audio.Player` — `Protocol` with `start() -> None`, `play(path: Path) -> None`, `is_busy() -> bool`, `stop() -> None`, `close() -> None`
  - `otradio.audio.NullPlayer(busy_polls: int = 0, fail_on: set[str] | None = None)` — implements `Player`; records `started`, `closed`, `played: list[Path]`, `stopped: int`. `is_busy()` returns `True` for the first `busy_polls` calls after each `play()`, then `False`. `play()` raises `PlaybackError` when the path's name is in `fail_on`.
  - `otradio.audio.PygamePlayer(volume: float = 1.0)` — implements `Player`; imports `pygame` inside `start()`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audio.py`:

```python
from pathlib import Path

import pytest

from otradio.audio import NullPlayer, PlaybackError


def test_null_player_records_lifecycle():
    player = NullPlayer()
    player.start()
    player.play(Path("/library/gunsmoke.mp3"))
    player.close()
    assert player.started is True
    assert player.closed is True
    assert player.played == [Path("/library/gunsmoke.mp3")]


def test_null_player_is_not_busy_by_default():
    player = NullPlayer()
    player.play(Path("/library/gunsmoke.mp3"))
    assert player.is_busy() is False


def test_null_player_simulates_a_finite_duration():
    player = NullPlayer(busy_polls=3)
    player.play(Path("/library/gunsmoke.mp3"))
    assert [player.is_busy() for _ in range(5)] == [True, True, True, False, False]


def test_null_player_busy_counter_resets_for_each_recording():
    player = NullPlayer(busy_polls=2)
    player.play(Path("/library/a.mp3"))
    while player.is_busy():
        pass
    player.play(Path("/library/b.mp3"))
    assert player.is_busy() is True


def test_null_player_raises_playback_error_for_configured_failures():
    player = NullPlayer(fail_on={"broken.mp3"})
    with pytest.raises(PlaybackError):
        player.play(Path("/library/broken.mp3"))


def test_null_player_records_stops():
    player = NullPlayer(busy_polls=5)
    player.play(Path("/library/gunsmoke.mp3"))
    player.stop()
    assert player.stopped == 1
    assert player.is_busy() is False


def test_importing_the_module_does_not_require_pygame():
    """pygame must be imported inside PygamePlayer.start(), not at module level."""
    import otradio.audio as audio_module

    source = Path(audio_module.__file__).read_text(encoding="utf-8")
    module_level_lines = [
        line
        for line in source.splitlines()
        if line.startswith("import pygame") or line.startswith("from pygame")
    ]
    assert module_level_lines == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_audio.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'otradio.audio'`

- [ ] **Step 3: Write the implementation**

Create `otradio/audio.py`:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_audio.py -v`
Expected: PASS — 7 passed.

- [ ] **Step 5: Commit**

```bash
git add otradio/audio.py tests/test_audio.py
git commit -m "feat: add Player protocol with pygame and null implementations

pygame init moves out of import time and the bare except in play() becomes a
targeted pygame.error/OSError raised as PlaybackError."
```

---

### Task 7: Speech adapter

The previously ignored `gender`/`emphasis`/`speed` arguments become real `espeak-ng` flags.

**Files:**
- Create: `otradio/speech.py`
- Test: `tests/test_speech.py`

**Interfaces:**
- Consumes: `otradio.config.Config`
- Produces:
  - `otradio.speech.Speaker` — `Protocol` with `say(text: str) -> None`
  - `otradio.speech.NullSpeaker()` — implements `Speaker`; records `said: list[str]`
  - `otradio.speech.EspeakSpeaker(voice: str = "f3", amplitude: int = 150, speed: int = 150, command: str = "espeak-ng", runner: Callable[[list[str]], None] | None = None)` — implements `Speaker`
  - `EspeakSpeaker.is_available(command: str = "espeak-ng") -> bool` (staticmethod)
  - `otradio.speech.make_speaker(config: Config) -> Speaker`

`make_speaker` returns `NullSpeaker` when `config.dry_run` or not `config.speech_enabled`; otherwise `EspeakSpeaker` if the binary is on PATH; otherwise it logs a warning once and returns `NullSpeaker`, so a missing `espeak-ng` never stops the radio playing.

- [ ] **Step 1: Write the failing test**

Create `tests/test_speech.py`:

```python
import logging

from otradio.config import Config
from otradio.speech import EspeakSpeaker, NullSpeaker, Speaker, make_speaker


def test_null_speaker_records_what_it_was_told():
    speaker = NullSpeaker()
    speaker.say("welcome to the old time radio project")
    assert speaker.said == ["welcome to the old time radio project"]


def test_espeak_speaker_builds_the_expected_command():
    commands: list[list[str]] = []
    speaker = EspeakSpeaker(
        voice="f3", amplitude=150, speed=140, runner=commands.append
    )
    speaker.say("hello")
    assert commands == [["espeak-ng", "-v", "f3", "-a", "150", "-s", "140", "hello"]]


def test_espeak_speaker_honours_a_custom_command_name():
    commands: list[list[str]] = []
    speaker = EspeakSpeaker(command="espeak", runner=commands.append)
    speaker.say("hello")
    assert commands[0][0] == "espeak"


def test_espeak_speaker_swallows_runner_failures(caplog):
    """A broken synthesiser must not stop the radio."""

    def explode(_command):
        raise OSError("espeak-ng vanished")

    speaker = EspeakSpeaker(runner=explode)
    with caplog.at_level(logging.WARNING, logger="otradio.speech"):
        speaker.say("hello")
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_make_speaker_returns_null_speaker_when_speech_is_disabled():
    config = Config.from_cli(["--no-speech"], env={})
    assert isinstance(make_speaker(config), NullSpeaker)


def test_make_speaker_returns_null_speaker_for_dry_run():
    config = Config.from_cli(["--dry-run"], env={})
    assert isinstance(make_speaker(config), NullSpeaker)


def test_make_speaker_returns_a_speaker_when_speech_is_enabled():
    """Either EspeakSpeaker or, if espeak-ng is absent, NullSpeaker. Never raises."""
    config = Config.from_cli([], env={})
    speaker = make_speaker(config)
    assert isinstance(speaker, (EspeakSpeaker, NullSpeaker))
    speaker.say("smoke test")


def test_is_available_reports_a_missing_binary():
    assert EspeakSpeaker.is_available("definitely-not-a-real-binary-xyz") is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_speech.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'otradio.speech'`

- [ ] **Step 3: Write the implementation**

Create `otradio/speech.py`:

```python
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
    subprocess.run(command, check=False, capture_output=True)


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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_speech.py -v`
Expected: PASS — 8 passed.

- [ ] **Step 5: Commit**

```bash
git add otradio/speech.py tests/test_speech.py
git commit -m "feat: add Speaker protocol with espeak-ng and null implementations

The gender/emphasis/speed arguments the old speak() accepted and ignored now
map onto real espeak-ng flags."
```

---

### Task 8: The radio run loop

Fixes defect **D4** (every show truncated at ~5 minutes). Wiring only — this module holds no policy of its own.

**Files:**
- Create: `otradio/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: everything from Tasks 2–7.
- Produces:
  - `otradio.app.GREETING: str` — `"welcome to the old time radio project"`
  - `otradio.app.POLL_INTERVAL_SECONDS: float` — `1.0`
  - `otradio.app.Radio(config, catalog, scheduler, player, speaker, store, sleep=time.sleep, now=datetime.now, monotonic=time.monotonic)`
  - `Radio.run(max_iterations: int | None = None) -> None`
  - `otradio.app.build_radio(config: Config) -> Radio`
  - `otradio.app.main(argv: Sequence[str] | None = None) -> int`

`run()` calls `player.start()`, speaks `GREETING`, then loops: pick, play, wait for the end. `player.close()` runs in a `finally`. `max_iterations=None` means forever; tests pass an integer.

- [ ] **Step 1: Write the failing test**

Create `tests/test_app.py`:

```python
import logging
import random
from datetime import date, datetime
from pathlib import Path

import pytest

from otradio.app import GREETING, Radio
from otradio.audio import NullPlayer
from otradio.catalog import Catalog, Genre, Recording
from otradio.config import Config
from otradio.scheduler import AlternatingScheduler, EmptyLibrary
from otradio.speech import NullSpeaker
from otradio.store import InMemoryStore


def make_recording(name: str, genre: Genre) -> Recording:
    return Recording(
        id=name,
        filename=name,
        path=Path("/library") / name,
        release_date=date(1952, 7, 26),
        genre=genre,
    )


def make_radio(
    config: Config | None = None,
    player: NullPlayer | None = None,
    show_names: list[str] | None = None,
    commercial_names: list[str] | None = None,
) -> tuple[Radio, NullPlayer, NullSpeaker, InMemoryStore]:
    show_names = show_names if show_names is not None else ["show-a.mp3"]
    commercial_names = (
        commercial_names if commercial_names is not None else ["commercial-a.mp3"]
    )
    catalog = Catalog(
        [make_recording(n, Genre.SHOW) for n in show_names]
        + [make_recording(n, Genre.COMMERCIAL) for n in commercial_names]
    )
    config = config if config is not None else Config.from_cli([], env={})
    player = player if player is not None else NullPlayer()
    speaker = NullSpeaker()
    store = InMemoryStore()
    radio = Radio(
        config=config,
        catalog=catalog,
        scheduler=AlternatingScheduler(catalog, rng=random.Random(0)),
        player=player,
        speaker=speaker,
        store=store,
        sleep=lambda _seconds: None,
        now=lambda: datetime(1952, 7, 26, 19, 0),
        monotonic=lambda: 0.0,
    )
    return radio, player, speaker, store


def test_run_starts_and_closes_the_player():
    radio, player, _speaker, _store = make_radio()
    radio.run(max_iterations=1)
    assert player.started is True
    assert player.closed is True


def test_run_announces_the_greeting():
    radio, _player, speaker, _store = make_radio()
    radio.run(max_iterations=1)
    assert speaker.said[0] == GREETING


def test_run_plays_the_requested_number_of_recordings():
    radio, player, _speaker, _store = make_radio()
    radio.run(max_iterations=3)
    assert len(player.played) == 3


def test_run_alternates_shows_and_commercials():
    radio, player, _speaker, _store = make_radio()
    radio.run(max_iterations=4)
    assert [p.name for p in player.played] == [
        "show-a.mp3",
        "commercial-a.mp3",
        "show-a.mp3",
        "commercial-a.mp3",
    ]


def test_run_records_each_play_in_the_store():
    radio, _player, _speaker, store = make_radio()
    radio.run(max_iterations=2)
    assert store.stats_for("show-a.mp3").num_of_plays == 1
    assert store.stats_for("show-a.mp3").last_played == datetime(1952, 7, 26, 19, 0)
    assert store.stats_for("commercial-a.mp3").num_of_plays == 1


def test_run_waits_for_a_recording_to_finish():
    """Regression: the old loop stopped every show after 300 iterations."""
    player = NullPlayer(busy_polls=450)
    radio, player, _speaker, _store = make_radio(player=player)
    radio.run(max_iterations=1)
    assert player.stopped == 0
    assert player.is_busy() is False


def test_playback_failure_is_recorded_and_the_loop_continues():
    player = NullPlayer(fail_on={"show-a.mp3"})
    radio, player, _speaker, store = make_radio(player=player)
    radio.run(max_iterations=2)
    assert store.stats_for("show-a.mp3").unavailable_at != []
    assert store.stats_for("show-a.mp3").available is False
    assert store.stats_for("show-a.mp3").num_of_plays == 0
    assert [p.name for p in player.played] == ["commercial-a.mp3"]


def test_watchdog_stops_a_recording_that_never_ends():
    config = Config.from_cli(["--max-play-seconds", "5"], env={})
    clock = iter([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    catalog = Catalog([make_recording("show-a.mp3", Genre.SHOW)])
    player = NullPlayer(busy_polls=10_000)
    radio = Radio(
        config=config,
        catalog=catalog,
        scheduler=AlternatingScheduler(catalog, rng=random.Random(0)),
        player=player,
        speaker=NullSpeaker(),
        store=InMemoryStore(),
        sleep=lambda _seconds: None,
        now=lambda: datetime(1952, 7, 26, 19, 0),
        monotonic=lambda: next(clock),
    )
    radio.run(max_iterations=1)
    assert player.stopped == 1


def test_player_is_closed_even_when_the_loop_raises():
    radio, player, _speaker, _store = make_radio(
        show_names=[], commercial_names=[]
    )
    with pytest.raises(EmptyLibrary):
        radio.run(max_iterations=1)
    assert player.closed is True


def test_keyboard_interrupt_is_not_swallowed():
    """Regression: the old bare except: caught KeyboardInterrupt."""

    class InterruptingPlayer(NullPlayer):
        def play(self, path):
            raise KeyboardInterrupt

    radio, player, _speaker, _store = make_radio(player=InterruptingPlayer())
    with pytest.raises(KeyboardInterrupt):
        radio.run(max_iterations=1)
    assert player.closed is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'otradio.app'`

- [ ] **Step 3: Write the implementation**

Create `otradio/app.py`:

```python
"""Wires the pieces together and runs the radio."""

import logging
import time
from collections.abc import Callable, Sequence
from datetime import datetime

from otradio.audio import PlaybackError, Player, PygamePlayer, NullPlayer
from otradio.catalog import Catalog, Recording
from otradio.config import Config
from otradio.scheduler import AlternatingScheduler
from otradio.speech import Speaker, make_speaker
from otradio.store import InMemoryStore, MetadataStore

logger = logging.getLogger(__name__)

GREETING = "welcome to the old time radio project"
POLL_INTERVAL_SECONDS = 1.0


class Radio:
    """The run loop. Holds no policy of its own — it only wires and sequences."""

    def __init__(
        self,
        config: Config,
        catalog: Catalog,
        scheduler: AlternatingScheduler,
        player: Player,
        speaker: Speaker,
        store: MetadataStore,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = datetime.now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._catalog = catalog
        self._scheduler = scheduler
        self._player = player
        self._speaker = speaker
        self._store = store
        self._sleep = sleep
        self._now = now
        self._monotonic = monotonic

    def run(self, max_iterations: int | None = None) -> None:
        """Play recordings until interrupted.

        `max_iterations` exists so the loop can be tested; None means forever.
        """
        self._player.start()
        try:
            self._speaker.say(GREETING)
            logger.info("System time is %s", self._now())
            played = 0
            while max_iterations is None or played < max_iterations:
                played += 1
                self._play_once(self._scheduler.next())
        finally:
            self._store.save()
            self._player.close()

    def _play_once(self, recording: Recording) -> None:
        logger.info(
            "Playing %s (recorded %s)",
            recording.filename,
            recording.release_date or "date unknown",
        )
        try:
            self._player.play(recording.path)
        except PlaybackError as exc:
            logger.warning("%s", exc)
            self._store.record_unavailable(recording.id, self._now())
            return

        self._store.record_played(recording.id, self._now())
        self._wait_for_end(recording)

    def _wait_for_end(self, recording: Recording) -> None:
        """Wait for the recording to finish on its own.

        max_play_seconds is a watchdog against a wedged file, not the normal
        way a show ends. The old loop counted down from 300 and cut every show
        off after roughly five minutes.
        """
        limit = self._config.max_play_seconds
        deadline = None if limit is None else self._monotonic() + limit

        while self._player.is_busy():
            if deadline is not None and self._monotonic() >= deadline:
                logger.warning(
                    "%s exceeded the %s second limit; stopping it.",
                    recording.filename,
                    limit,
                )
                self._player.stop()
                return
            self._sleep(POLL_INTERVAL_SECONDS)


def build_radio(config: Config) -> Radio:
    """Assemble a Radio from configuration."""
    catalog = Catalog.from_directory(config.library_dir, config.commercial_marker)
    logger.info(
        "Library: %d recordings (%d shows, %d commercials) in %s",
        len(catalog),
        len(catalog.shows),
        len(catalog.commercials),
        config.library_dir,
    )
    player: Player = (
        NullPlayer() if config.dry_run else PygamePlayer(volume=config.volume)
    )
    return Radio(
        config=config,
        catalog=catalog,
        scheduler=AlternatingScheduler(catalog),
        player=player,
        speaker=make_speaker(config),
        store=InMemoryStore(),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Console entry point."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = Config.from_cli(argv)
    try:
        build_radio(config).run()
    except KeyboardInterrupt:
        logger.info("Goodbye.")
        return 0
    except Exception as exc:
        logger.error("%s", exc)
        return 1
    return 0
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_app.py -v`
Expected: PASS — 10 passed.

- [ ] **Step 5: Commit**

```bash
git add otradio/app.py tests/test_app.py
git commit -m "feat: add the Radio run loop

Waits on the player instead of counting down from 300, so shows are no longer
truncated at five minutes. max_play_seconds becomes a watchdog only."
```

---

### Task 9: Entry points, removal of the old script, and documentation

Replaces `play_radio.py` with a shim, deletes the dead code identified as **D6**, and brings the docs in line.

**Files:**
- Create: `otradio/__main__.py`
- Modify: `otradio/__init__.py` (currently a one-line docstring)
- Modify: `play_radio.py` (replace entire 190-line contents)
- Modify: `README.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: `otradio.app.main`, `otradio.app.Radio`, `otradio.app.build_radio`, `otradio.config.Config`
- Produces: `python -m otradio` and the `otradio` console script.

Deleted with this task, per the approved spec: `parse_dates_in_library()`, `filter_files()`, `load_datetime()`, `METADATA_FILE`, `Identifier`, and the module-level build loop. Git history preserves all of it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_entrypoints.py`:

```python
import subprocess
import sys
from pathlib import Path

import otradio


def test_package_exports_the_public_surface():
    assert hasattr(otradio, "Config")
    assert hasattr(otradio, "Radio")
    assert hasattr(otradio, "build_radio")
    assert hasattr(otradio, "main")


def test_module_entry_point_shows_help():
    result = subprocess.run(
        [sys.executable, "-m", "otradio", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--library" in result.stdout


def test_missing_library_exits_nonzero_with_a_clear_message(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "otradio", "--library", str(tmp_path / "nope"), "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "not found" in (result.stdout + result.stderr).lower()


def test_legacy_script_is_a_shim_with_no_logic():
    source = Path(__file__).resolve().parents[1] / "play_radio.py"
    text = source.read_text(encoding="utf-8")
    assert "from otradio.app import main" in text
    assert "pygame" not in text
    assert "Recording_dict" not in text
    assert len(text.splitlines()) < 20
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_entrypoints.py -v`
Expected: FAIL — `AttributeError: module 'otradio' has no attribute 'Config'`, and the `python -m otradio` cases fail with "No module named otradio.\_\_main\_\_".

- [ ] **Step 3: Write the package exports**

Replace the entire contents of `otradio/__init__.py` with:

```python
"""Old time radio player.

Plays recordings of old radio shows, interleaved with period commercials, on a
Raspberry Pi installed in a 1940s radio cabinet.
"""

from otradio.app import Radio, build_radio, main
from otradio.config import Config

__all__ = ["Config", "Radio", "build_radio", "main"]
```

- [ ] **Step 4: Write the module entry point**

Create `otradio/__main__.py`:

```python
"""Allows `python -m otradio`."""

from otradio.app import main

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Replace the legacy script with a shim**

Replace the **entire** contents of `play_radio.py` with:

```python
"""Deprecated entry point, kept so existing boot scripts keep working.

Prefer `python -m otradio` or the `otradio` command.
"""

from otradio.app import main

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/test_entrypoints.py -v`
Expected: PASS — 4 passed.

- [ ] **Step 7: Run the whole suite**

Run: `uv run pytest -v`
Expected: PASS — 87 passed, 0 failed.

- [ ] **Step 8: Verify the program runs end to end**

Run: `uv run python -c "import pathlib, sys; d = pathlib.Path('.smoke/OTRadio'); d.mkdir(parents=True, exist_ok=True); [(d / n).write_bytes(b'') for n in ['Gunsmoke 52-07-26.mp3', 'Lucky Strike Commercial 1948.mp3']]"`
Expected: exit code 0.

Run: `uv run otradio --library .smoke/OTRadio --dry-run --no-speech`
Expected: logs the library summary and "Playing ..." lines, alternating the show and the commercial. Press Ctrl-C; it must print "Goodbye." and exit 0, **not** a traceback.

Run: `uv run python -c "import shutil; shutil.rmtree('.smoke')"`
Expected: exit code 0.

- [ ] **Step 9: Update `README.md`**

Replace the requirements section at the end of `README.md` (the `sudo apt-get install espeak python-espeak` / `python-pygame` / `sudo pip install python-dateutil` lines) with:

```markdown
## Running

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

    uv sync
    uv run otradio --library /path/to/recordings

Spoken announcements need the `espeak-ng` command:

    sudo apt-get install espeak-ng

Without it the radio still plays; it just stays quiet between shows.

### Options

| Flag | Environment variable | Default |
|---|---|---|
| `--library` | `OTRADIO_LIBRARY` | `./recordings/OTRadio` |
| `--volume` | `OTRADIO_VOLUME` | `1.0` |
| `--max-play-seconds` | `OTRADIO_MAX_PLAY_SECONDS` | unlimited |
| `--commercial-marker` | `OTRADIO_COMMERCIAL_MARKER` | `commercial` |
| `--no-speech` | `OTRADIO_SPEECH` | speech on |
| `--dry-run` | — | off |

Recordings whose filename contains the commercial marker are treated as
commercials and interleaved between shows. Broadcast dates are read from the
filename where one is present.

## Tests

    uv run pytest

The whole suite runs without audio hardware. Only the `pygame` and `espeak-ng`
adapters need the Pi.
```

- [ ] **Step 10: Update `CLAUDE.md`**

Replace the "Running", "Audio library", and "Architecture" sections of `CLAUDE.md` — they describe the old single-file script and are now wrong — with:

```markdown
## Commands

| Task | Command |
|---|---|
| Install deps | `uv sync` |
| Run the radio | `uv run otradio --library <dir>` |
| Run off-device | `uv run otradio --library <dir> --dry-run --no-speech` |
| Run tests | `uv run pytest` |
| Run one test | `uv run pytest tests/test_dates.py::test_four_digit_year_does_not_crash -v` |

Target platform is Raspberry Pi OS Bookworm (Python 3.11). The full test suite
runs on Windows: only `otradio/audio.py` and `otradio/speech.py` touch
hardware, and both have null implementations.

## Architecture

`otradio` splits into pure logic and two hardware adapters. Nothing does I/O at
import time.

| Module | Responsibility |
|---|---|
| `config.py` | `Config` from CLI flags, then env vars, then defaults |
| `dates.py` | `parse_release_date(filename)` — pure |
| `catalog.py` | `Recording` model; `Catalog.from_directory()` scans and partitions |
| `store.py` | `PlayStats` and the `MetadataStore` protocol |
| `audio.py` | `Player` protocol; `PygamePlayer` (lazy pygame import) and `NullPlayer` |
| `speech.py` | `Speaker` protocol; `EspeakSpeaker` (subprocess) and `NullSpeaker` |
| `scheduler.py` | `AlternatingScheduler` — what plays next |
| `app.py` | `Radio` run loop, `build_radio()`, `main()` |

`pygame` must stay inside `PygamePlayer.start()`. Importing it at module level
breaks the hardware-free test suite; `tests/test_audio.py` asserts this.

**Recording identity is the library-relative path.** It must stay stable across
runs — `PlayStats` is keyed by it, and persistence will rely on that.

**Audio files are gitignored** (`*.mp3`, `*.wav`, …); the library lives on the
Pi. Tests build temporary libraries from empty files, which is enough because
nothing in the tested path reads audio data.

## Unimplemented, by design

`InMemoryStore.save()` is a deliberate no-op — play history does not survive a
reboot yet. The follow-on work, in order: a `JsonMetadataStore`, era/genre
filtering, a skip control that records an `Interruption`, and `load_datetime()`
(NTP → RTC → system clock). See
`docs/superpowers/specs/2026-09-02-otradio-refactor-design.md`.

Speech is an open item: `EspeakSpeaker` shells out to `espeak-ng` because the
`espeak` Python binding is Python 2-era. If the binding installs on the Pi, an
alternative behind the same protocol is a one-file change.
```

- [ ] **Step 11: Run the whole suite once more**

Run: `uv run pytest`
Expected: PASS — 87 passed.

- [ ] **Step 12: Commit**

```bash
git add otradio/__init__.py otradio/__main__.py play_radio.py tests/test_entrypoints.py README.md CLAUDE.md
git commit -m "feat: add entry points and retire the legacy script

play_radio.py becomes a shim so existing boot scripts keep working. Removes
parse_dates_in_library (which would crash if called), filter_files (a no-op),
load_datetime (empty), METADATA_FILE and the Identifier counter."
```

---

## Verification

After Task 9, all of the following must hold:

- [ ] `uv run pytest` — 87 passed, 0 failed
- [ ] `uv run otradio --help` — exit 0, lists every flag in the config table
- [ ] `uv run otradio --library <empty dir> --dry-run` — exit 1 with a clear message, no traceback
- [ ] `git grep -n "Recording_dict\|parse_dates_in_library\|filter_files\|METADATA_FILE"` — no matches outside `docs/`
- [ ] `git grep -n "^import pygame\|^from pygame" otradio/` — no matches
- [ ] `uv run python -c "import otradio"` — exit 0 with no filesystem or audio access

Pi-only, not verifiable on Windows: real playback through `PygamePlayer`, and real speech through `EspeakSpeaker`.
