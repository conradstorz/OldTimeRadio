import json
import os
from datetime import datetime
from pathlib import Path

from otradio.store import (
    REASON_ERA_CHANGE,
    REASON_SKIP,
    InMemoryStore,
    Interruption,
    JsonMetadataStore,
    PlayStats,
)


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
    store.record_interruption("gunsmoke.mp3", when, seconds_played=42, reason=REASON_SKIP)
    interruptions = store.stats_for("gunsmoke.mp3").interruptions
    assert len(interruptions) == 1
    assert interruptions[0].at == when
    assert interruptions[0].seconds_played == 42
    assert interruptions[0].reason == REASON_SKIP


def test_record_interruption_stores_era_change_reason():
    store = InMemoryStore()
    when = datetime(1952, 7, 26)
    store.record_interruption(
        "gunsmoke.mp3", when, seconds_played=42, reason=REASON_ERA_CHANGE
    )
    interruptions = store.stats_for("gunsmoke.mp3").interruptions
    assert interruptions[0].reason == REASON_ERA_CHANGE


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


def test_stats_for_mutating_returned_scalar_does_not_corrupt_store():
    store = InMemoryStore()
    store.record_played("gunsmoke.mp3", datetime(1952, 7, 26))
    stats = store.stats_for("gunsmoke.mp3")
    stats.num_of_plays = 999
    assert store.stats_for("gunsmoke.mp3").num_of_plays == 1


def test_stats_for_mutating_returned_unavailable_at_does_not_corrupt_store():
    store = InMemoryStore()
    when = datetime(1952, 7, 26)
    store.record_unavailable("broken.mp3", when)
    stats = store.stats_for("broken.mp3")
    stats.unavailable_at.append(datetime(1999, 1, 1))
    assert store.stats_for("broken.mp3").unavailable_at == [when]


def test_stats_for_mutating_returned_interruptions_does_not_corrupt_store():
    store = InMemoryStore()
    when = datetime(1952, 7, 26)
    store.record_interruption("gunsmoke.mp3", when, seconds_played=42, reason=REASON_SKIP)
    stats = store.stats_for("gunsmoke.mp3")
    stats.interruptions.append(Interruption(at=when, seconds_played=1, reason=REASON_SKIP))
    assert len(store.stats_for("gunsmoke.mp3").interruptions) == 1


def test_stats_for_returns_a_new_object_each_call():
    store = InMemoryStore()
    store.record_played("gunsmoke.mp3", datetime(1952, 7, 26))
    assert store.stats_for("gunsmoke.mp3") is not store.stats_for("gunsmoke.mp3")


# -- JsonMetadataStore ---------------------------------------------------


def make_json_store(tmp_path):
    return JsonMetadataStore(tmp_path / "otradio-stats.json")


def test_json_store_on_a_missing_file_starts_empty_and_creates_nothing(tmp_path):
    store = make_json_store(tmp_path)
    assert store.stats_for("gunsmoke.mp3") == PlayStats()
    assert not (tmp_path / "otradio-stats.json").exists()


def test_json_store_round_trips_history_across_instances(tmp_path):
    store = make_json_store(tmp_path)
    store.record_played("gunsmoke.mp3", datetime(1952, 7, 26, 19, 0))
    store.record_unavailable("broken.mp3", datetime(1952, 7, 27, 9, 30))
    store.record_interruption(
        "gunsmoke.mp3",
        datetime(1952, 7, 28, 20, 15),
        seconds_played=340,
        reason=REASON_SKIP,
    )

    reloaded = make_json_store(tmp_path)
    stats = reloaded.stats_for("gunsmoke.mp3")
    assert stats.num_of_plays == 1
    assert stats.last_played == datetime(1952, 7, 26, 19, 0)
    assert stats.available is True
    assert stats.interruptions == [
        Interruption(
            at=datetime(1952, 7, 28, 20, 15),
            seconds_played=340,
            reason=REASON_SKIP,
        )
    ]
    broken = reloaded.stats_for("broken.mp3")
    assert broken.available is False
    assert broken.unavailable_at == [datetime(1952, 7, 27, 9, 30)]


def test_json_store_flushes_each_record_without_save(tmp_path):
    """The appliance is powered off at the wall: save() usually never runs."""
    store = make_json_store(tmp_path)
    store.record_played("gunsmoke.mp3", datetime(1952, 7, 26))
    # No save(). A fresh instance must already see the play.
    assert make_json_store(tmp_path).stats_for("gunsmoke.mp3").num_of_plays == 1


def test_json_store_leaves_no_tmp_file_behind(tmp_path):
    store = make_json_store(tmp_path)
    store.record_played("gunsmoke.mp3", datetime(1952, 7, 26))
    store.save()
    leftovers = [p.name for p in tmp_path.iterdir()]
    assert leftovers == ["otradio-stats.json"]


def test_json_store_writes_the_documented_format(tmp_path):
    store = make_json_store(tmp_path)
    store.record_played("gunsmoke.mp3", datetime(1952, 7, 26, 19, 0))
    data = json.loads((tmp_path / "otradio-stats.json").read_text(encoding="utf-8"))
    assert data["version"] == 2
    entry = data["recordings"]["gunsmoke.mp3"]
    assert entry == {
        "num_of_plays": 1,
        "last_played": "1952-07-26T19:00:00",
        "available": True,
        "unavailable_at": [],
        "interruptions": [],
    }


def test_json_store_writes_the_documented_interruption_format(tmp_path):
    store = make_json_store(tmp_path)
    store.record_interruption(
        "gunsmoke.mp3",
        datetime(1952, 7, 28, 20, 15),
        seconds_played=340,
        reason=REASON_SKIP,
    )
    data = json.loads((tmp_path / "otradio-stats.json").read_text(encoding="utf-8"))
    entry = data["recordings"]["gunsmoke.mp3"]
    assert entry["interruptions"] == [
        {"at": "1952-07-28T20:15:00", "seconds_played": 340, "reason": "skip"}
    ]


def test_json_store_save_is_a_flush_and_does_not_raise(tmp_path):
    store = make_json_store(tmp_path)
    store.record_played("a.mp3", datetime(1952, 7, 26))
    store.save()
    assert make_json_store(tmp_path).stats_for("a.mp3").num_of_plays == 1


def test_json_store_inherits_snapshot_isolation(tmp_path):
    store = make_json_store(tmp_path)
    store.record_played("gunsmoke.mp3", datetime(1952, 7, 26))
    snapshot = store.stats_for("gunsmoke.mp3")
    snapshot.num_of_plays = 999
    assert store.stats_for("gunsmoke.mp3").num_of_plays == 1


def test_json_store_quarantines_unparseable_json(tmp_path):
    stats_path = tmp_path / "otradio-stats.json"
    stats_path.write_text("{not json", encoding="utf-8")

    store = make_json_store(tmp_path)

    assert store.stats_for("gunsmoke.mp3") == PlayStats()
    assert not stats_path.exists()
    bad = tmp_path / "otradio-stats.json.bad"
    assert bad.read_text(encoding="utf-8") == "{not json"


def test_json_store_quarantines_wrong_shape(tmp_path):
    stats_path = tmp_path / "otradio-stats.json"
    stats_path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    make_json_store(tmp_path)
    assert not stats_path.exists()
    assert (tmp_path / "otradio-stats.json.bad").exists()


def test_json_store_quarantines_unknown_version(tmp_path):
    stats_path = tmp_path / "otradio-stats.json"
    stats_path.write_text(
        json.dumps({"version": 999, "recordings": {}}), encoding="utf-8"
    )
    make_json_store(tmp_path)
    assert not stats_path.exists()
    assert (tmp_path / "otradio-stats.json.bad").exists()


def test_json_store_quarantines_version_1_files(tmp_path):
    """Version 2 added the interruption reason; nothing was deployed under
    version 1, so an old-shaped file quarantines by design rather than
    migrating."""
    stats_path = tmp_path / "otradio-stats.json"
    stats_path.write_text(
        json.dumps(
            {
                "version": 1,
                "recordings": {
                    "a.mp3": {
                        "num_of_plays": 1,
                        "last_played": None,
                        "available": None,
                        "unavailable_at": [],
                        "interruptions": [],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    store = make_json_store(tmp_path)
    assert store.stats_for("a.mp3") == PlayStats()
    assert not stats_path.exists()
    assert (tmp_path / "otradio-stats.json.bad").exists()


def test_json_store_quarantines_malformed_entry(tmp_path):
    stats_path = tmp_path / "otradio-stats.json"
    stats_path.write_text(
        json.dumps({"version": 2, "recordings": {"a.mp3": {"num_of_plays": 1}}}),
        encoding="utf-8",
    )
    store = make_json_store(tmp_path)
    assert store.stats_for("a.mp3") == PlayStats()
    assert (tmp_path / "otradio-stats.json.bad").exists()


def test_json_store_quarantines_invalid_interruption_reason(tmp_path):
    stats_path = tmp_path / "otradio-stats.json"
    stats_path.write_text(
        json.dumps(
            {
                "version": 2,
                "recordings": {
                    "a.mp3": {
                        "num_of_plays": 0,
                        "last_played": None,
                        "available": None,
                        "unavailable_at": [],
                        "interruptions": [
                            {
                                "at": "1952-07-26T00:00:00",
                                "seconds_played": 5,
                                "reason": "bogus",
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    store = make_json_store(tmp_path)
    assert store.stats_for("a.mp3") == PlayStats()
    assert not stats_path.exists()
    assert (tmp_path / "otradio-stats.json.bad").exists()


def test_json_store_quarantines_invalid_utf8(tmp_path):
    stats_path = tmp_path / "otradio-stats.json"
    stats_path.write_bytes(b"\xff\xfe\x00 not utf-8")
    store = make_json_store(tmp_path)
    assert store.stats_for("gunsmoke.mp3") == PlayStats()
    assert not stats_path.exists()
    assert (tmp_path / "otradio-stats.json.bad").read_bytes() == b"\xff\xfe\x00 not utf-8"


def test_json_store_quarantine_overwrites_a_previous_bad_file(tmp_path):
    (tmp_path / "otradio-stats.json.bad").write_text("older garbage", encoding="utf-8")
    stats_path = tmp_path / "otradio-stats.json"
    stats_path.write_text("newer garbage", encoding="utf-8")
    make_json_store(tmp_path)
    bad = tmp_path / "otradio-stats.json.bad"
    assert bad.read_text(encoding="utf-8") == "newer garbage"


def test_json_store_recovers_after_quarantine(tmp_path):
    stats_path = tmp_path / "otradio-stats.json"
    stats_path.write_text("garbage", encoding="utf-8")
    store = make_json_store(tmp_path)

    store.record_played("gunsmoke.mp3", datetime(1952, 7, 26))

    reloaded = make_json_store(tmp_path)
    assert reloaded.stats_for("gunsmoke.mp3").num_of_plays == 1
    assert (tmp_path / "otradio-stats.json.bad").exists()


def test_json_store_survives_an_unwritable_path(tmp_path):
    """A read-only SD card must never stop the radio playing (F1)."""
    store = JsonMetadataStore(tmp_path / "does-not-exist" / "otradio-stats.json")
    store.record_played("gunsmoke.mp3", datetime(1952, 7, 26))
    assert store.stats_for("gunsmoke.mp3").num_of_plays == 1
    store.save()


def test_json_store_goes_readonly_when_file_unreadable_and_unquarantinable(
    tmp_path, monkeypatch
):
    stats_path = tmp_path / "otradio-stats.json"
    stats_path.write_text("precious history", encoding="utf-8")
    monkeypatch.setattr(
        Path, "read_bytes", lambda self, **kw: (_ for _ in ()).throw(PermissionError())
    )
    monkeypatch.setattr(os, "replace", lambda src, dst: (_ for _ in ()).throw(PermissionError()))
    store = JsonMetadataStore(stats_path)
    monkeypatch.undo()

    store.record_played("gunsmoke.mp3", datetime(1952, 7, 26))
    store.save()

    assert stats_path.read_text(encoding="utf-8") == "precious history"


def test_json_store_quarantines_wrong_typed_num_of_plays(tmp_path):
    stats_path = tmp_path / "otradio-stats.json"
    stats_path.write_text(
        json.dumps(
            {
                "version": 2,
                "recordings": {
                    "a.mp3": {
                        "num_of_plays": "lots",
                        "last_played": None,
                        "available": None,
                        "unavailable_at": [],
                        "interruptions": [],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    store = make_json_store(tmp_path)
    assert store.stats_for("a.mp3") == PlayStats()
    assert not stats_path.exists()
    assert (tmp_path / "otradio-stats.json.bad").exists()
