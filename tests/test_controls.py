import io
import logging
import threading

from otradio.controls import Command, KeyboardControls, NullControls


def test_null_controls_never_has_a_command():
    controls = NullControls()
    assert controls.poll() is None
    assert controls.poll() is None


def test_keyboard_controls_starts_no_thread_before_first_poll():
    controls = KeyboardControls(stream=io.StringIO(""))
    assert controls._reader is None


def drain(controls, timeout=5.0):
    """Poll until a command appears or the finite injected stream is exhausted."""
    command = controls.poll()  # first poll starts the reader thread
    if command is not None:
        return command
    controls._reader.join(timeout)  # stream is finite; the thread exits fast
    while True:
        command = controls.poll()
        if command is not None:
            return command
        if controls._queue.empty():
            return None


def test_keyboard_controls_maps_e_to_cycle_era():
    controls = KeyboardControls(stream=io.StringIO("e\n"))
    assert drain(controls) is Command.CYCLE_ERA


def test_keyboard_controls_is_case_insensitive_and_strips():
    controls = KeyboardControls(stream=io.StringIO("  E  \n"))
    assert drain(controls) is Command.CYCLE_ERA


def test_keyboard_controls_ignores_unknown_lines():
    controls = KeyboardControls(stream=io.StringIO("x\nquit\n"))
    assert drain(controls) is None


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


def test_keyboard_controls_queue_is_bounded_against_a_stuck_key():
    """A stuck key spamming lines must not grow the queue without bound."""
    controls = KeyboardControls(stream=io.StringIO("e\n" * 200))
    first = controls.poll()  # starts the reader thread
    controls._reader.join(5)
    assert controls._reader.is_alive() is False
    count = 1 if first is not None else 0
    while True:
        command = controls.poll()
        if command is None:
            break
        count += 1
    assert count <= 64


def test_keyboard_controls_reader_thread_death_is_logged_not_raised(
    monkeypatch, caplog
):
    monkeypatch.setattr("otradio.controls.sys.stdin", None)
    controls = KeyboardControls(stream=None)
    with caplog.at_level(logging.WARNING):
        assert controls.poll() is None
        controls._reader.join(5)
    assert controls._reader.is_alive() is False
    assert controls.poll() is None
    assert "Keyboard controls stopped reading input" in caplog.text
