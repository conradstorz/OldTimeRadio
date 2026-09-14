import itertools
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
from otradio.controls import Command, KeyboardControls, NullControls
from otradio.scheduler import AlternatingScheduler, EmptyLibrary
from otradio.speech import NullSpeaker
from otradio.store import REASON_ERA_CHANGE, REASON_SKIP, InMemoryStore, JsonMetadataStore


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


# -- runtime controls ----------------------------------------------------


class ScriptedControls:
    def __init__(self, commands):
        self._commands = list(commands)

    def poll(self):
        return self._commands.pop(0) if self._commands else None


class RecordingSpeaker:
    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(text)


class BusyPlayer:
    """Reports busy for a fixed number of polls, counts stop() calls."""

    def __init__(self, busy_polls):
        self._busy_polls = busy_polls
        self.stopped = 0
        self.closed = False
        self.played = []

    def start(self):
        pass

    def play(self, path):
        self.played.append(path)

    def stop(self):
        self.stopped += 1
        self._busy_polls = 0

    def is_busy(self):
        self._busy_polls -= 1
        return self._busy_polls >= 0

    def close(self):
        self.closed = True


def make_era_radio(controls, era=None):
    catalog = Catalog(
        [
            Recording(
                id="forties.mp3",
                filename="forties.mp3",
                path=Path("forties.mp3"),
                release_date=date(1947, 1, 1),
                genre=Genre.SHOW,
            ),
            Recording(
                id="fifties.mp3",
                filename="fifties.mp3",
                path=Path("fifties.mp3"),
                release_date=date(1952, 1, 1),
                genre=Genre.SHOW,
            ),
            Recording(
                id="commercial-a.mp3",
                filename="commercial-a.mp3",
                path=Path("commercial-a.mp3"),
                release_date=None,
                genre=Genre.COMMERCIAL,
            ),
        ]
    )
    config = Config.from_cli([], env={})
    player = BusyPlayer(busy_polls=5)
    speaker = RecordingSpeaker()
    store = InMemoryStore()
    scheduler = AlternatingScheduler(catalog, rng=random.Random(0), era=era)
    clock = itertools.count(start=0.0, step=1.0)
    radio = Radio(
        config=config,
        catalog=catalog,
        scheduler=scheduler,
        player=player,
        speaker=speaker,
        store=store,
        controls=controls,
        sleep=lambda _seconds: None,
        now=lambda: datetime(1952, 7, 26, 19, 0),
        monotonic=lambda: next(clock),
    )
    return radio, player, speaker, store, scheduler


def test_cycle_era_command_stops_the_show_and_records_an_interruption():
    radio, player, _speaker, store, scheduler = make_era_radio(
        ScriptedControls([Command.CYCLE_ERA])
    )
    radio.run(max_iterations=1)
    assert player.stopped == 1
    played_id = next(
        rid for rid in ("forties.mp3", "fifties.mp3")
        if store.stats_for(rid).num_of_plays == 1
    )
    interruptions = store.stats_for(played_id).interruptions
    assert len(interruptions) == 1
    assert interruptions[0].seconds_played == 1
    assert interruptions[0].reason == REASON_ERA_CHANGE
    assert scheduler.era == 1940  # None -> first decade


def test_cycle_era_command_announces_the_new_era():
    radio, _player, speaker, _store, _scheduler = make_era_radio(
        ScriptedControls([Command.CYCLE_ERA])
    )
    radio.run(max_iterations=1)
    assert "playing the 1940s" in speaker.said


def test_cycling_past_the_last_decade_announces_all_eras():
    radio, _player, speaker, _store, _scheduler = make_era_radio(
        ScriptedControls([Command.CYCLE_ERA]), era=1950
    )
    radio.run(max_iterations=1)
    assert "playing all eras" in speaker.said


def test_null_controls_change_nothing():
    radio, player, speaker, store, scheduler = make_era_radio(NullControls())
    radio.run(max_iterations=1)
    assert player.stopped == 0
    assert scheduler.era is None
    assert speaker.said == [GREETING]


def test_cycle_era_command_burst_coalesces_into_one_stop_and_announcement():
    """A burst of queued CYCLE_ERA commands must not produce one one-tick
    show per command: they are drained and applied as a single jump."""
    radio, player, speaker, store, scheduler = make_era_radio(
        ScriptedControls([Command.CYCLE_ERA, Command.CYCLE_ERA])
    )
    radio.run(max_iterations=1)
    assert player.stopped == 1
    assert scheduler.era == 1950
    assert speaker.said == [GREETING, "playing the 1950s"]


def test_cycle_era_end_to_end_third_pick_is_the_new_eras_show():
    radio, player, _speaker, store, scheduler = make_era_radio(
        ScriptedControls([Command.CYCLE_ERA])
    )
    radio.run(max_iterations=3)
    assert scheduler.era == 1940
    assert [p.name for p in player.played][2] == "forties.mp3"
    assert store.stats_for("forties.mp3").num_of_plays >= 1


# -- build_radio controls/era wiring -------------------------------------


def test_build_radio_wires_keyboard_controls_when_configured(tmp_path):
    config = Config.from_cli(
        ["--library", str(tmp_path), "--dry-run", "--controls", "keyboard"], env={}
    )
    radio = build_radio(config)
    assert isinstance(radio._controls, KeyboardControls)


def test_build_radio_defaults_to_null_controls(tmp_path):
    config = Config.from_cli(["--library", str(tmp_path), "--dry-run"], env={})
    radio = build_radio(config)
    assert isinstance(radio._controls, NullControls)


def test_build_radio_passes_the_configured_era_to_the_scheduler(tmp_path):
    (tmp_path / "show-1947-01-01.mp3").touch()
    config = Config.from_cli(
        ["--library", str(tmp_path), "--dry-run", "--era", "1940"], env={}
    )
    radio = build_radio(config)
    assert radio._scheduler.era == 1940


def test_build_radio_falls_back_to_all_eras_when_the_decade_is_absent(tmp_path):
    (tmp_path / "show-1947-01-01.mp3").touch()
    config = Config.from_cli(
        ["--library", str(tmp_path), "--dry-run", "--era", "1930"], env={}
    )
    radio = build_radio(config)
    assert radio._scheduler.era is None


# -- skip command ----------------------------------------------------------


def test_skip_stops_the_show_silently_and_a_show_plays_next():
    radio, player, speaker, store, _scheduler = make_era_radio(
        ScriptedControls([Command.SKIP])
    )
    radio.run(max_iterations=2)
    assert player.stopped == 1
    assert speaker.said == [GREETING]  # a skip is silent
    skipped = player.played[0].name
    interruptions = store.stats_for(skipped).interruptions
    assert len(interruptions) == 1
    assert interruptions[0].seconds_played == 1
    assert interruptions[0].reason == REASON_SKIP
    # The pick after a skipped show is another show, not the commercial the
    # alternation would have chosen.
    assert player.played[1].name in ("forties.mp3", "fifties.mp3")


def test_unknown_command_is_a_no_op():
    from enum import Enum

    class OtherCommand(Enum):
        MYSTERY = "mystery"

    radio, player, _speaker, store, _scheduler = make_era_radio(
        ScriptedControls([OtherCommand.MYSTERY])
    )
    radio.run(max_iterations=1)
    assert player.stopped == 0
    played_id = player.played[0].name
    assert len(store.stats_for(played_id).interruptions) == 0


def test_skip_during_a_commercial_stops_it_and_records_an_interruption():
    radio, player, _speaker, store, scheduler = make_era_radio(
        ScriptedControls([Command.SKIP])
    )
    commercial = Recording(
        id="commercial-a.mp3",
        filename="commercial-a.mp3",
        path=Path("commercial-a.mp3"),
        release_date=None,
        genre=Genre.COMMERCIAL,
    )
    stopped = radio._handle_command(commercial, started=0.0)
    assert stopped is True
    assert player.stopped == 1
    assert scheduler.next().genre is Genre.SHOW
    interruptions = store.stats_for("commercial-a.mp3").interruptions
    assert len(interruptions) == 1
    assert interruptions[0].reason == REASON_SKIP


def test_reverse_burst_cycle_then_skip_coalesces_into_one_stop():
    radio, player, speaker, store, scheduler = make_era_radio(
        ScriptedControls([Command.CYCLE_ERA, Command.SKIP])
    )
    radio.run(max_iterations=2)
    assert player.stopped == 1
    assert scheduler.era == 1940
    assert "playing the 1940s" in speaker.said
    assert player.played[1].name == "forties.mp3"
    skipped = player.played[0].name
    assert store.stats_for(skipped).interruptions[0].reason == REASON_SKIP


def test_skip_then_normal_rhythm_resumes_with_a_commercial():
    radio, player, _speaker, _store, _scheduler = make_era_radio(
        ScriptedControls([Command.SKIP])
    )
    radio.run(max_iterations=3)
    assert player.played[1].name in ("forties.mp3", "fifties.mp3")
    assert player.played[2].name == "commercial-a.mp3"


def test_skip_logs_a_journal_line(caplog):
    radio, player, _speaker, _store, _scheduler = make_era_radio(
        ScriptedControls([Command.SKIP])
    )
    with caplog.at_level(logging.INFO):
        radio.run(max_iterations=1)
    skipped = player.played[0].name
    assert any(
        record.message == f"Skipping {skipped}" for record in caplog.records
    )


def test_pure_era_change_does_not_log_a_skip_line(caplog):
    radio, _player, _speaker, _store, _scheduler = make_era_radio(
        ScriptedControls([Command.CYCLE_ERA])
    )
    with caplog.at_level(logging.INFO):
        radio.run(max_iterations=1)
    assert not any(
        record.message.startswith("Skipping") for record in caplog.records
    )


def test_drain_loop_never_drops_the_command_after_a_long_burst():
    """A burst of 101 CYCLE_ERA commands followed by a SKIP (102 commands
    total) must still have the SKIP honored: the drain loop must tally every
    fetched command, not just the first 101."""
    radio, player, _speaker, _store, _scheduler = make_era_radio(
        ScriptedControls([Command.CYCLE_ERA] * 101 + [Command.SKIP])
    )
    radio.run(max_iterations=2)
    # A pure era-change burst alone would make the second pick a commercial
    # (the normal alternation); a dropped SKIP would leave it that way. The
    # SKIP forces a show next instead.
    assert player.played[1].name in ("forties.mp3", "fifties.mp3")


def test_mixed_skip_and_cycle_burst_coalesces_into_one_stop():
    radio, player, speaker, store, scheduler = make_era_radio(
        ScriptedControls([Command.SKIP, Command.CYCLE_ERA])
    )
    radio.run(max_iterations=2)
    assert player.stopped == 1
    assert scheduler.era == 1940
    assert "playing the 1940s" in speaker.said
    skipped = player.played[0].name
    interruptions = store.stats_for(skipped).interruptions
    assert len(interruptions) == 1
    assert interruptions[0].reason == REASON_SKIP
    # Era 1940 plus the forced show means the next pick is forties.mp3.
    assert player.played[1].name == "forties.mp3"
