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
