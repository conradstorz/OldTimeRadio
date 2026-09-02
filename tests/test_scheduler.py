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
