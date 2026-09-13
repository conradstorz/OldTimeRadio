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


def test_max_play_seconds_flag_overrides_environment_variable():
    config = Config.from_cli(
        ["--max-play-seconds", "900"],
        env={"OTRADIO_MAX_PLAY_SECONDS": "300"},
    )
    assert config.max_play_seconds == 900


def test_commercial_marker_flag_overrides_environment_variable():
    config = Config.from_cli(
        ["--commercial-marker", "sponsor"],
        env={"OTRADIO_COMMERCIAL_MARKER": "advert"},
    )
    assert config.commercial_marker == "sponsor"


def test_no_speech_flag_overrides_environment_variable():
    config = Config.from_cli(
        ["--no-speech"],
        env={"OTRADIO_SPEECH": "1"},
    )
    assert config.speech_enabled is False


def test_malformed_volume_env_exits_with_usage_error(capsys):
    with pytest.raises(SystemExit) as exc_info:
        Config.from_cli([], env={"OTRADIO_VOLUME": "abc"})
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "OTRADIO_VOLUME: invalid float value: 'abc'" in captured.err


def test_malformed_max_play_seconds_env_exits_with_usage_error(capsys):
    with pytest.raises(SystemExit) as exc_info:
        Config.from_cli([], env={"OTRADIO_MAX_PLAY_SECONDS": "abc"})
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "OTRADIO_MAX_PLAY_SECONDS: invalid int value: 'abc'" in captured.err


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


def test_era_defaults_to_all():
    config = Config.from_cli([], env={})
    assert config.era is None


def test_era_flag_parses_a_decade():
    config = Config.from_cli(["--era", "1940"], env={})
    assert config.era == 1940


def test_era_flag_normalizes_a_mid_decade_year():
    config = Config.from_cli(["--era", "1947"], env={})
    assert config.era == 1940


def test_era_flag_accepts_all():
    config = Config.from_cli(["--era", "all"], env={})
    assert config.era is None


def test_era_env_var_is_used_and_flag_wins():
    assert Config.from_cli([], env={"OTRADIO_ERA": "1950"}).era == 1950
    config = Config.from_cli(["--era", "all"], env={"OTRADIO_ERA": "1950"})
    assert config.era is None


def test_malformed_era_flag_exits_with_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        Config.from_cli(["--era", "forties"], env={})
    assert excinfo.value.code == 2


def test_malformed_era_env_var_exits_with_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        Config.from_cli([], env={"OTRADIO_ERA": "forties"})
    assert excinfo.value.code == 2


def test_controls_defaults_to_none():
    config = Config.from_cli([], env={})
    assert config.controls == "none"


def test_controls_flag_and_env_with_flag_precedence():
    assert Config.from_cli(["--controls", "keyboard"], env={}).controls == "keyboard"
    assert Config.from_cli([], env={"OTRADIO_CONTROLS": "keyboard"}).controls == "keyboard"
    config = Config.from_cli(
        ["--controls", "none"], env={"OTRADIO_CONTROLS": "keyboard"}
    )
    assert config.controls == "none"


def test_invalid_controls_value_exits_with_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        Config.from_cli(["--controls", "gpio"], env={})
    assert excinfo.value.code == 2
    with pytest.raises(SystemExit) as excinfo:
        Config.from_cli([], env={"OTRADIO_CONTROLS": "gpio"})
    assert excinfo.value.code == 2
