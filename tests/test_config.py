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
