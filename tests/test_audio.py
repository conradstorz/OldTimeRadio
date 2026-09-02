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
        into a FunctionDef/AsyncFunctionDef/ClassDef body — code inside those
        only runs when called/instantiated, not at import time."""
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
