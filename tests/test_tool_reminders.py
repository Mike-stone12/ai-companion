import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import pytest

from companion.core.tools.reminders import ReminderStore

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


def test_order_persistence_and_due(tmp_path):
    path = tmp_path / "nested" / "reminders.json"
    store = ReminderStore(path, clock=lambda: NOW)
    assert store.list() == store.due() == []
    later = store.add("  Later  ", "2026-10-18T15:00:00+01:00")
    earlier = store.add("Earlier", NOW + timedelta(hours=1))
    assert later.text == "Later"
    assert later.created_at == NOW.isoformat()
    assert 0 < len(later.id) <= 16
    assert later.id != earlier.id
    assert store.list() == [earlier, later]
    assert store.due() == []
    assert store.due(NOW + timedelta(hours=1)) == [earlier]
    assert json.loads(path.read_text(encoding="utf-8")) == [asdict(later), asdict(earlier)]
    reopened = ReminderStore(path, clock=lambda: NOW + timedelta(hours=2))
    assert reopened.list() == []
    assert reopened.list(include_past=True) == [earlier, later]
    assert reopened.due() == [earlier, later]


@pytest.mark.parametrize("text", ["", " \t\n", "x" * 201])
def test_invalid_text(tmp_path, text):
    store = ReminderStore(tmp_path / "reminders.json", clock=lambda: NOW)
    with pytest.raises(ValueError):
        store.add(text, NOW + timedelta(hours=1))
    assert store.list(include_past=True) == []


@pytest.mark.parametrize("due_at", [
    NOW - timedelta(seconds=1), "2026-10-18T13:00:00+02:00",
    "invalid", "2026-10-19T12:00:00", datetime(2026, 10, 19),
])
def test_invalid_due_time(tmp_path, due_at):
    store = ReminderStore(tmp_path / "reminders.json", clock=lambda: NOW)
    with pytest.raises(ValueError):
        store.add("Test", due_at)
    assert store.list(include_past=True) == []


@pytest.mark.parametrize("contents", [b"{broken", b"{}", b"null", b"42", b"[{}]", b"\xff"])
def test_corrupt_file_is_empty_and_can_be_replaced(tmp_path, contents):
    path = tmp_path / "reminders.json"
    path.write_bytes(contents)
    store = ReminderStore(path, clock=lambda: NOW)
    assert store.list() == store.due() == []
    reminder = store.add("Valid", NOW + timedelta(hours=1))
    assert ReminderStore(path, clock=lambda: NOW).list() == [reminder]


def test_text_limit_and_due_boundary(tmp_path):
    store = ReminderStore(tmp_path / "reminders.json", clock=lambda: NOW)
    reminder = store.add("x" * 200, NOW)
    assert store.due() == [reminder]
    assert store.list() == []
