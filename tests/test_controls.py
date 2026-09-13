import io
import threading
import time

from otradio.controls import Command, KeyboardControls, NullControls


def test_null_controls_never_has_a_command():
    controls = NullControls()
    assert controls.poll() is None
    assert controls.poll() is None


def test_keyboard_controls_starts_no_thread_before_first_poll():
    controls = KeyboardControls(stream=io.StringIO(""))
    assert controls._reader is None


def drain(controls, tries=50):
    """Poll until a command appears or the injected stream is exhausted."""
    for _ in range(tries):
        command = controls.poll()
        if command is not None:
            return command
        time.sleep(0.01)
    return None


def test_keyboard_controls_maps_e_to_cycle_era():
    controls = KeyboardControls(stream=io.StringIO("e\n"))
    assert drain(controls) is Command.CYCLE_ERA


def test_keyboard_controls_is_case_insensitive_and_strips():
    controls = KeyboardControls(stream=io.StringIO("  E  \n"))
    assert drain(controls) is Command.CYCLE_ERA


def test_keyboard_controls_ignores_unknown_lines():
    controls = KeyboardControls(stream=io.StringIO("x\nquit\n"))
    assert drain(controls, tries=20) is None


def test_keyboard_controls_poll_maps_queued_lines_without_a_live_thread():
    controls = KeyboardControls(stream=io.StringIO(""))
    controls._reader = threading.current_thread()  # pretend already started
    controls._queue.put("e\n")
    controls._queue.put("noise\n")
    controls._queue.put("E\n")
    assert controls.poll() is Command.CYCLE_ERA
    assert controls.poll() is None
    assert controls.poll() is Command.CYCLE_ERA
    assert controls.poll() is None
