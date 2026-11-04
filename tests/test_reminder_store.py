import json
import logging
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

import pytest

from companion.core import settings_file
from companion.core.tools.reminder_store import (
    deserialize_reminders,
    load_reminders,
    save_reminders,
    serialize_reminders,
)
from companion.core.tools.reminders import Reminder

REMINDER = Reminder(
    id="reminder-123",
    text="Drink water — 喝水",
    due_at="2020-10-18T15:00:00.123456+05:30",
    created_at="2020-10-18T08:00:00-07:00",
)


def test_round_trip_preserves_identity_text_and_aware_timestamps(tmp_path):
    path = tmp_path / "reminders.json"
    save_reminders(path, [REMINDER])

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": 1, "reminders": [asdict(REMINDER)],
    }
    assert load_reminders(path) == [REMINDER]
    assert deserialize_reminders(serialize_reminders([REMINDER])) == [REMINDER]
    for field in ("due_at", "created_at"):
        assert datetime.fromisoformat(getattr(load_reminders(path)[0], field)).utcoffset() is not None


def test_missing_file_is_empty_and_is_not_created(tmp_path, caplog):
    path = tmp_path / "missing" / "reminders.json"
    with caplog.at_level(logging.WARNING):
        assert load_reminders(path) == []
    assert not path.parent.exists()
    assert caplog.records


@pytest.mark.parametrize("contents", [b"{broken", b"\xff", b"[" * 2000 + b"]" * 2000])
def test_corrupt_json_is_empty_warns_and_is_untouched(tmp_path, caplog, contents):
    path = tmp_path / "reminders.json"
    path.write_bytes(contents)
    with caplog.at_level(logging.WARNING):
        assert load_reminders(path) == []
    assert caplog.records
    assert path.read_bytes() == contents
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("data", [
    None, [], "invalid", 42, {}, {"version": 1}, {"reminders": []},
    {"version": 2, "reminders": []}, {"version": True, "reminders": []},
    {"version": "1", "reminders": []}, {"version": 1, "reminders": {}},
])
def test_wrong_shape_or_version_is_empty_warns_and_is_untouched(tmp_path, caplog, data):
    path = tmp_path / "reminders.json"
    contents = json.dumps(data).encode("utf-8")
    path.write_bytes(contents)
    with caplog.at_level(logging.WARNING):
        assert load_reminders(path) == []
    assert caplog.records
    assert path.read_bytes() == contents


@pytest.mark.parametrize("bad_entry", [
    None, [], "invalid", 42, {},
    {**asdict(REMINDER), "id": ""}, {**asdict(REMINDER), "id": 1},
    {**asdict(REMINDER), "text": " "}, {**asdict(REMINDER), "text": 1},
    {**asdict(REMINDER), "text": "x" * 201},
    {**asdict(REMINDER), "due_at": "invalid"},
    {**asdict(REMINDER), "due_at": "2020-10-18T15:00:00"},
    {**asdict(REMINDER), "due_at": None},
    {**asdict(REMINDER), "created_at": "2020-10-18T08:00:00"},
    {**asdict(REMINDER), "created_at": []},
])
def test_malformed_entries_are_skipped_and_valid_entries_kept(tmp_path, caplog, bad_entry):
    path = tmp_path / "reminders.json"
    contents = json.dumps({"version": 1, "reminders": [bad_entry, asdict(REMINDER), bad_entry]})
    path.write_text(contents, encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert load_reminders(path) == [REMINDER]
    assert len(caplog.records) == 2
    assert path.read_text(encoding="utf-8") == contents


def test_empty_reminders_round_trip_without_warnings(tmp_path, caplog):
    path = tmp_path / "reminders.json"
    save_reminders(str(path), [])
    assert load_reminders(str(path)) == []
    assert not caplog.records


def test_completed_ids_are_excluded_but_overdue_pending_reminders_are_kept(tmp_path):
    path = tmp_path / "reminders.json"
    fired = replace(REMINDER, id="fired")
    delivered = replace(REMINDER, id="delivered")
    future = replace(REMINDER, id="future", due_at="2099-10-18T15:00:00+05:30")
    reminders = [fired, REMINDER, delivered, future]
    expected = {"version": 1, "reminders": [asdict(REMINDER), asdict(future)]}

    assert serialize_reminders(reminders, completed_ids={fired.id, delivered.id}) == expected
    save_reminders(path, iter(reminders), completed_ids=iter([fired.id, delivered.id]))
    assert json.loads(path.read_text(encoding="utf-8")) == expected
    assert load_reminders(path) == [REMINDER, future]
    assert reminders == [fired, REMINDER, delivered, future]


def test_save_uses_atomic_helper_and_creates_parents(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "data" / "reminders.json"
    original_save = settings_file.save_settings
    original_replace = settings_file.os.replace
    saved = []
    replaced = []

    def record_save(target, data):
        saved.append(target)
        original_save(target, data)

    def record_replace(source, target):
        assert Path(source).parent == path.parent
        assert json.loads(Path(source).read_text(encoding="utf-8"))["reminders"] == [asdict(REMINDER)]
        assert not path.exists() or path.read_bytes() == b"old contents"
        replaced.append(target)
        original_replace(source, target)

    monkeypatch.setattr(settings_file, "save_settings", record_save)
    monkeypatch.setattr(settings_file.os, "replace", record_replace)
    save_reminders(path, [REMINDER])
    path.write_bytes(b"old contents")
    save_reminders(path, [REMINDER])
    assert saved == replaced == [path, path]
    assert load_reminders(path) == [REMINDER]
    assert list(path.parent.iterdir()) == [path]


def test_failed_atomic_replace_preserves_existing_file(tmp_path, monkeypatch):
    path = tmp_path / "reminders.json"
    save_reminders(path, [REMINDER])
    contents = path.read_bytes()

    def fail_replace(source, target):
        raise OSError("replacement failed")

    monkeypatch.setattr(settings_file.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replacement failed"):
        save_reminders(path, [])
    assert path.read_bytes() == contents
