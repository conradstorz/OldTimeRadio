import subprocess
import sys
from pathlib import Path

import otradio


def test_package_exports_the_public_surface():
    assert hasattr(otradio, "Config")
    assert hasattr(otradio, "Radio")
    assert hasattr(otradio, "build_radio")
    assert hasattr(otradio, "main")


def test_module_entry_point_shows_help():
    result = subprocess.run(
        [sys.executable, "-m", "otradio", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--library" in result.stdout


def test_missing_library_exits_nonzero_with_a_clear_message(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "otradio", "--library", str(tmp_path / "nope"), "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "not found" in (result.stdout + result.stderr).lower()


def test_legacy_script_is_a_shim_with_no_logic():
    source = Path(__file__).resolve().parents[1] / "play_radio.py"
    text = source.read_text(encoding="utf-8")
    assert "from otradio.app import main" in text
    assert "pygame" not in text
    assert "Recording_dict" not in text
    assert len(text.splitlines()) < 20


def test_legacy_script_runs_and_shows_help():
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "play_radio.py", "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--library" in result.stdout
