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
