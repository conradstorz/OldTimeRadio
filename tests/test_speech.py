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
