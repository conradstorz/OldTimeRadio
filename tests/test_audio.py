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
