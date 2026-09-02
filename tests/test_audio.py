from pathlib import Path

import pytest

from otradio.audio import NullPlayer, PlaybackError, PygamePlayer


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


class _StubMusic:
    """Stands in for pygame.mixer.music."""

    def __init__(self) -> None:
        self.loaded: list[str] = []
        self.played = 0
        self.stopped = 0
        self.busy = False
        self.load_error: Exception | None = None

    def load(self, path: str) -> None:
        if self.load_error is not None:
            raise self.load_error
        self.loaded.append(path)

    def play(self) -> None:
        self.played += 1
        self.busy = True

    def get_busy(self) -> bool:
        return self.busy

    def stop(self) -> None:
        self.stopped += 1
        self.busy = False


class _StubMixer:
    """Stands in for pygame.mixer."""

    def __init__(self) -> None:
        self.music = _StubMusic()
        self.quit_called = False

    def quit(self) -> None:
        self.quit_called = True


class StubPygame:
    """A fake pygame module, just capable enough to drive PygamePlayer
    without importing pygame or touching audio hardware."""

    class error(Exception):
        """Stands in for pygame.error."""

    def __init__(self) -> None:
        self.mixer = _StubMixer()
        self.quit_called = False

    def quit(self) -> None:
        self.quit_called = True


def make_started_player(volume: float = 1.0) -> tuple[PygamePlayer, StubPygame]:
    """A PygamePlayer wired to a stub pygame, as if start() had run --
    without ever calling the real start() (which would import pygame and
    initialise audio hardware)."""
    player = PygamePlayer(volume=volume)
    stub = StubPygame()
    player._pygame = stub
    return player, stub


def test_pygame_player_play_delegates_load_then_play():
    player, stub = make_started_player()
    player.play(Path("/library/gunsmoke.mp3"))
    assert stub.mixer.music.loaded == [str(Path("/library/gunsmoke.mp3"))]
    assert stub.mixer.music.played == 1


def test_pygame_player_pygame_error_from_load_becomes_playback_error():
    player, stub = make_started_player()
    stub.mixer.music.load_error = stub.error("could not decode")
    with pytest.raises(PlaybackError):
        player.play(Path("/library/broken.mp3"))


def test_pygame_player_os_error_from_load_becomes_playback_error():
    player, stub = make_started_player()
    stub.mixer.music.load_error = OSError("no such file")
    with pytest.raises(PlaybackError):
        player.play(Path("/library/broken.mp3"))


def test_pygame_player_is_busy_reflects_get_busy():
    player, stub = make_started_player()
    assert player.is_busy() is False
    stub.mixer.music.busy = True
    assert player.is_busy() is True
    stub.mixer.music.busy = False
    assert player.is_busy() is False


def test_pygame_player_stop_delegates():
    player, stub = make_started_player()
    player.play(Path("/library/gunsmoke.mp3"))
    player.stop()
    assert stub.mixer.music.stopped == 1
    assert stub.mixer.music.busy is False


def test_pygame_player_close_releases_and_is_idempotent():
    player, stub = make_started_player()
    player.play(Path("/library/gunsmoke.mp3"))
    player.close()
    assert stub.mixer.music.stopped == 1
    assert stub.mixer.quit_called is True
    assert stub.quit_called is True
    assert player._pygame is None
    # A second close() must not raise, e.g. on shutdown after a failure.
    player.close()


def test_pygame_player_play_before_start_raises_playback_error():
    player = PygamePlayer()
    with pytest.raises(PlaybackError):
        player.play(Path("/library/gunsmoke.mp3"))


def test_importing_the_module_does_not_require_pygame():
    """pygame must be imported inside PygamePlayer.start(), not at module level."""
    import ast

    import otradio.audio as audio_module

    module_path = audio_module.__file__
    source = Path(module_path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=module_path)

    def is_pygame_import(node: ast.AST) -> bool:
        if isinstance(node, ast.Import):
            return any(
                alias.name == "pygame" or alias.name.startswith("pygame.")
                for alias in node.names
            )
        if isinstance(node, ast.ImportFrom):
            return node.module is not None and (
                node.module == "pygame" or node.module.startswith("pygame.")
            )
        return False

    def find_pygame_imports(statements: list[ast.stmt]) -> list[ast.stmt]:
        """Recurse into compound statements (try/if/with/for/...) but never
        into a FunctionDef/AsyncFunctionDef/ClassDef body. A function body
        only runs when called; a class body does run at import time (as
        the class statement executes), but pygame is never imported at
        class scope in this module, so neither needs to be checked here."""
        found: list[ast.stmt] = []
        for node in statements:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if is_pygame_import(node):
                found.append(node)
                continue
            for field in ("body", "orelse", "finalbody"):
                child = getattr(node, field, None)
                if child:
                    found.extend(find_pygame_imports(child))
            for handler in getattr(node, "handlers", []):
                found.extend(find_pygame_imports(handler.body))
        return found

    offending = find_pygame_imports(tree.body)
    assert offending == [], (
        "Found pygame import(s) that execute at module import time (outside "
        "any function or class body) in "
        f"{module_path}, on line(s) {[node.lineno for node in offending]}. "
        "pygame must only be imported inside PygamePlayer.start() so the rest "
        "of the package - and the whole test suite - can run on machines "
        "without audio hardware. Move the import inside a method instead of "
        "module/try/if/with/for scope."
    )
