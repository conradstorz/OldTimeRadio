import logging
import random
from datetime import date, datetime
from pathlib import Path

import pytest

import otradio.app as app
from otradio.app import GREETING, Radio, build_radio, main
from otradio.audio import NullPlayer, PygamePlayer
from otradio.catalog import Catalog, Genre, LibraryNotFound, Recording
from otradio.config import Config
from otradio.scheduler import AlternatingScheduler, EmptyLibrary
from otradio.speech import NullSpeaker
from otradio.store import InMemoryStore, JsonMetadataStore


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


class SleepSpy:
    """Records every call to the injected sleep so tests can assert on it."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def test_playback_failure_still_yields_a_sleep():
    """Regression: a library pygame cannot decode must not spin the CPU."""
    sleep = SleepSpy()
    player = NullPlayer(fail_on={"show-a.mp3", "commercial-a.mp3"})
    radio, player, _speaker, _store = make_radio(player=player)
    radio._sleep = sleep
    radio.run(max_iterations=2)
    assert sleep.calls == [app.POLL_INTERVAL_SECONDS, app.POLL_INTERVAL_SECONDS]


def test_a_recording_that_is_never_busy_still_yields_a_sleep():
    """Regression: --dry-run produced tens of thousands of log lines in
    seconds because a recording that finishes instantly looped with no
    delay at all."""
    sleep = SleepSpy()
    player = NullPlayer(busy_polls=0)
    radio, player, _speaker, _store = make_radio(player=player)
    radio._sleep = sleep
    radio.run(max_iterations=2)
    assert sleep.calls == [app.POLL_INTERVAL_SECONDS, app.POLL_INTERVAL_SECONDS]


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


# -- build_radio -------------------------------------------------------


def test_build_radio_dry_run_uses_a_null_player(tmp_path):
    config = Config.from_cli(
        ["--library", str(tmp_path), "--dry-run"], env={}
    )
    radio = build_radio(config)
    assert isinstance(radio._player, NullPlayer)


def test_build_radio_live_run_uses_a_pygame_player_with_the_configured_volume(
    tmp_path, monkeypatch
):
    # Pin espeak-ng detection so this test's outcome does not depend on
    # whether the machine running it happens to have it on PATH.
    monkeypatch.setattr("otradio.speech.shutil.which", lambda command: None)
    config = Config.from_cli(
        ["--library", str(tmp_path), "--volume", "0.42"], env={}
    )
    radio = build_radio(config)
    assert isinstance(radio._player, PygamePlayer)
    assert radio._player._volume == 0.42


def test_build_radio_builds_the_catalog_from_the_configured_directory_and_marker(
    tmp_path,
):
    (tmp_path / "show-a.mp3").touch()
    (tmp_path / "promo-b.mp3").touch()
    config = Config.from_cli(
        [
            "--library", str(tmp_path),
            "--commercial-marker", "promo",
            "--dry-run",
        ],
        env={},
    )
    radio = build_radio(config)
    assert len(radio._catalog) == 2
    assert [r.filename for r in radio._catalog.shows] == ["show-a.mp3"]
    assert [r.filename for r in radio._catalog.commercials] == ["promo-b.mp3"]


def test_build_radio_missing_library_dir_raises_library_not_found(tmp_path):
    config = Config.from_cli(
        ["--library", str(tmp_path / "missing"), "--dry-run"], env={}
    )
    with pytest.raises(LibraryNotFound):
        build_radio(config)


def test_build_radio_uses_a_json_store_in_the_library_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("otradio.speech.shutil.which", lambda command: None)
    config = Config.from_cli(["--library", str(tmp_path)], env={})
    radio = build_radio(config)
    assert isinstance(radio._store, JsonMetadataStore)
    assert radio._store._path == tmp_path / "otradio-stats.json"


def test_build_radio_dry_run_keeps_history_out_of_the_library(tmp_path):
    config = Config.from_cli(["--library", str(tmp_path), "--dry-run"], env={})
    radio = build_radio(config)
    assert type(radio._store) is InMemoryStore


def test_build_radio_does_not_catalog_the_stats_file(tmp_path):
    (tmp_path / "show-a.mp3").touch()
    (tmp_path / "otradio-stats.json").write_text(
        '{"version": 1, "recordings": {}}', encoding="utf-8"
    )
    config = Config.from_cli(["--library", str(tmp_path), "--dry-run"], env={})
    radio = build_radio(config)
    assert [r.filename for r in radio._catalog.all] == ["show-a.mp3"]


# -- main ----------------------------------------------------------------


def test_main_missing_library_dir_returns_exit_code_1(tmp_path, monkeypatch):
    for var in (
        "OTRADIO_LIBRARY",
        "OTRADIO_VOLUME",
        "OTRADIO_MAX_PLAY_SECONDS",
        "OTRADIO_COMMERCIAL_MARKER",
        "OTRADIO_SPEECH",
    ):
        monkeypatch.delenv(var, raising=False)
    argv = ["--library", str(tmp_path / "missing"), "--dry-run"]
    assert main(argv) == 1


def test_main_keyboard_interrupt_from_run_returns_exit_code_0(tmp_path, monkeypatch):
    for var in (
        "OTRADIO_LIBRARY",
        "OTRADIO_VOLUME",
        "OTRADIO_MAX_PLAY_SECONDS",
        "OTRADIO_COMMERCIAL_MARKER",
        "OTRADIO_SPEECH",
    ):
        monkeypatch.delenv(var, raising=False)

    class InterruptingRadio:
        def run(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(app, "build_radio", lambda config: InterruptingRadio())
    argv = ["--library", str(tmp_path), "--dry-run"]
    assert main(argv) == 0


def test_main_normal_completed_run_returns_exit_code_0(tmp_path, monkeypatch):
    for var in (
        "OTRADIO_LIBRARY",
        "OTRADIO_VOLUME",
        "OTRADIO_MAX_PLAY_SECONDS",
        "OTRADIO_COMMERCIAL_MARKER",
        "OTRADIO_SPEECH",
    ):
        monkeypatch.delenv(var, raising=False)

    class FiniteRadio:
        def run(self):
            return None

    monkeypatch.setattr(app, "build_radio", lambda config: FiniteRadio())
    argv = ["--library", str(tmp_path), "--dry-run"]
    assert main(argv) == 0


def test_main_unexpected_exception_from_run_returns_exit_code_1(tmp_path, monkeypatch):
    for var in (
        "OTRADIO_LIBRARY",
        "OTRADIO_VOLUME",
        "OTRADIO_MAX_PLAY_SECONDS",
        "OTRADIO_COMMERCIAL_MARKER",
        "OTRADIO_SPEECH",
    ):
        monkeypatch.delenv(var, raising=False)

    class BrokenRadio:
        def run(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(app, "build_radio", lambda config: BrokenRadio())
    argv = ["--library", str(tmp_path), "--dry-run"]
    assert main(argv) == 1


def test_main_malformed_flag_raises_system_exit():
    with pytest.raises(SystemExit):
        main(["--volume", "abc"])
