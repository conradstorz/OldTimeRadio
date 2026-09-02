from datetime import datetime

from otradio.store import InMemoryStore, PlayStats


def test_unknown_recording_starts_with_blank_stats():
    store = InMemoryStore()
    stats = store.stats_for("gunsmoke.mp3")
    assert stats == PlayStats()
    assert stats.num_of_plays == 0
    assert stats.last_played is None
    assert stats.available is None


def test_record_played_increments_count_and_marks_available():
    store = InMemoryStore()
    when = datetime(1952, 7, 26, 19, 0)
    store.record_played("gunsmoke.mp3", when)
    stats = store.stats_for("gunsmoke.mp3")
    assert stats.num_of_plays == 1
    assert stats.last_played == when
    assert stats.available is True


def test_record_played_accumulates():
    store = InMemoryStore()
    store.record_played("gunsmoke.mp3", datetime(1952, 7, 26))
    store.record_played("gunsmoke.mp3", datetime(1952, 7, 27))
    stats = store.stats_for("gunsmoke.mp3")
    assert stats.num_of_plays == 2
    assert stats.last_played == datetime(1952, 7, 27)


def test_record_unavailable_appends_timestamp_and_marks_unavailable():
    store = InMemoryStore()
    when = datetime(1952, 7, 26)
    store.record_unavailable("broken.mp3", when)
    stats = store.stats_for("broken.mp3")
    assert stats.unavailable_at == [when]
    assert stats.available is False
    assert stats.num_of_plays == 0


def test_record_interruption_appends_event():
    store = InMemoryStore()
    when = datetime(1952, 7, 26)
    store.record_interruption("gunsmoke.mp3", when, seconds_played=42)
    interruptions = store.stats_for("gunsmoke.mp3").interruptions
    assert len(interruptions) == 1
    assert interruptions[0].at == when
    assert interruptions[0].seconds_played == 42


def test_stats_are_kept_per_recording():
    store = InMemoryStore()
    store.record_played("a.mp3", datetime(1952, 7, 26))
    assert store.stats_for("a.mp3").num_of_plays == 1
    assert store.stats_for("b.mp3").num_of_plays == 0


def test_stats_for_does_not_create_entry_for_unknown_recording():
    store = InMemoryStore()
    store.stats_for("never-played.mp3")
    store.stats_for("never-played.mp3")
    assert "never-played.mp3" not in store._stats


def test_save_is_a_no_op_that_does_not_raise():
    """Persistence is deliberately unimplemented; save() exists for the protocol."""
    store = InMemoryStore()
    store.record_played("a.mp3", datetime(1952, 7, 26))
    store.save()
    assert store.stats_for("a.mp3").num_of_plays == 1
