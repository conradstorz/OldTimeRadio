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


def dated_show(name, year):
    return Recording(
        id=name,
        filename=name,
        path=Path(name),
        release_date=date(year, 1, 1),
        genre=Genre.SHOW,
    )


def commercial(name="commercial.mp3"):
    return Recording(
        id=name,
        filename=name,
        path=Path(name),
        release_date=None,
        genre=Genre.COMMERCIAL,
    )


def test_scheduler_with_an_era_picks_shows_only_from_that_decade():
    catalog = Catalog(
        [dated_show("forties.mp3", 1947), dated_show("fifties.mp3", 1952), commercial()]
    )
    scheduler = AlternatingScheduler(catalog, rng=random.Random(0), era=1950)
    picks = [scheduler.next() for _ in range(10)]
    show_ids = {r.id for r in picks if r.genre is Genre.SHOW}
    assert show_ids == {"fifties.mp3"}
    assert any(r.genre is Genre.COMMERCIAL for r in picks)


def test_scheduler_era_defaults_to_all():
    catalog = Catalog(
        [dated_show("forties.mp3", 1947), dated_show("fifties.mp3", 1952), commercial()]
    )
    scheduler = AlternatingScheduler(catalog, rng=random.Random(0))
    assert scheduler.era is None
    picks = {r.id for r in (scheduler.next() for _ in range(20)) if r.genre is Genre.SHOW}
    assert picks == {"forties.mp3", "fifties.mp3"}


def test_cycle_era_walks_all_then_decades_ascending_then_all():
    catalog = Catalog(
        [dated_show("thirties.mp3", 1935), dated_show("fifties.mp3", 1952), commercial()]
    )
    scheduler = AlternatingScheduler(catalog, rng=random.Random(0))
    assert scheduler.cycle_era() == 1930
    assert scheduler.cycle_era() == 1950
    assert scheduler.cycle_era() is None
    assert scheduler.cycle_era() == 1930


def test_cycle_era_from_an_era_not_in_the_cycle_goes_to_the_first_decade():
    catalog = Catalog([dated_show("fifties.mp3", 1952), commercial()])
    scheduler = AlternatingScheduler(catalog, rng=random.Random(0), era=1930)
    assert scheduler.cycle_era() == 1950


def test_cycle_era_with_no_dated_shows_stays_on_all():
    undated = Recording(
        id="undated.mp3",
        filename="undated.mp3",
        path=Path("undated.mp3"),
        release_date=None,
        genre=Genre.SHOW,
    )
    scheduler = AlternatingScheduler(Catalog([undated, commercial()]), rng=random.Random(0))
    assert scheduler.cycle_era() is None
    assert scheduler.cycle_era() is None


def test_force_show_next_overrides_a_pending_commercial():
    catalog = Catalog([dated_show("forties.mp3", 1947), commercial()])
    scheduler = AlternatingScheduler(catalog, rng=random.Random(0))
    assert scheduler.next().genre is Genre.SHOW  # alternation now wants a commercial
    scheduler.force_show_next()
    assert scheduler.next().genre is Genre.SHOW


def test_force_show_next_is_a_no_op_when_a_show_was_already_next():
    catalog = Catalog([dated_show("forties.mp3", 1947), commercial()])
    scheduler = AlternatingScheduler(catalog, rng=random.Random(0))
    scheduler.force_show_next()
    assert scheduler.next().genre is Genre.SHOW


def test_force_show_next_respects_the_era_filter():
    catalog = Catalog(
        [dated_show("forties.mp3", 1947), dated_show("fifties.mp3", 1952), commercial()]
    )
    scheduler = AlternatingScheduler(catalog, rng=random.Random(0), era=1950)
    scheduler.next()
    scheduler.force_show_next()
    assert scheduler.next().id == "fifties.mp3"
