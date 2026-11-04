"""Exercise session persistence and startup wiring without Qt."""

import ast
import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from companion.core.proactive.events import REMINDER
from companion.core.proactive.session import ProactiveSession
from companion.core.proactive.triggers import ReminderTrigger
from companion.core.tools import reminder_store
from companion.core.tools.builtin import build_builtin_registry
from companion.core.tools.reminders import ReminderStore

NOW = datetime(2026, 10, 18, 9, tzinfo=UTC)


def test_store_round_trip_and_save_on_each_add(tmp_path, monkeypatch):
    save = Mock(wraps=reminder_store.save_reminders)
    monkeypatch.setattr(reminder_store, "save_reminders", save)
    store = ReminderStore(data_dir=tmp_path, clock=lambda: NOW)
    save.assert_not_called()
    first = store.add("Water", NOW + timedelta(minutes=1))
    assert reminder_store.load_reminders(tmp_path / "reminders.json") == [first]
    second = store.add("Break", NOW + timedelta(hours=1))
    assert save.call_count == 2
    reopened = ReminderStore(data_dir=tmp_path, clock=lambda: NOW)
    assert reopened.list() == [first, second]
    assert save.call_count == 2


def test_missing_file_does_not_create_data_directory(tmp_path):
    data_dir = tmp_path / "missing"
    store = ReminderStore(data_dir=data_dir, clock=lambda: NOW)
    assert store.list(include_past=True) == store.due() == []
    assert not data_dir.exists()


@pytest.mark.parametrize("contents", [b"{broken", b"\xff", b'{"version":2,"reminders":[]}'])
def test_corrupt_file_unchanged_until_valid_change(tmp_path, caplog, contents):
    path = tmp_path / "reminders.json"
    path.write_bytes(contents)
    with caplog.at_level(logging.WARNING):
        store = ReminderStore(data_dir=tmp_path, clock=lambda: NOW)
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert store.list(include_past=True) == store.due() == []
    with pytest.raises(ValueError):
        store.add("", NOW)
    assert path.read_bytes() == contents
    assert list(tmp_path.iterdir()) == [path]
    reminder = store.add("Valid", NOW)
    assert reminder_store.load_reminders(path) == [reminder]


def test_unreadable_file_warns_and_is_untouched(tmp_path, monkeypatch, caplog):
    path = tmp_path / "reminders.json"
    path.write_bytes(b"original bytes")
    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", Mock(side_effect=PermissionError("denied")))
        with caplog.at_level(logging.WARNING):
            store = ReminderStore(data_dir=tmp_path, clock=lambda: NOW)
        assert store.list(include_past=True) == []
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert path.read_bytes() == b"original bytes"
    assert list(tmp_path.iterdir()) == [path]


def test_save_failure_keeps_session_usable(tmp_path, monkeypatch, caplog):
    store = ReminderStore(data_dir=tmp_path, clock=lambda: NOW)
    first = store.add("Existing", NOW)
    path = tmp_path / "reminders.json"
    original = path.read_bytes()
    save = Mock(side_effect=OSError("disk full"))
    with monkeypatch.context() as patch:
        patch.setattr(reminder_store, "save_reminders", save)
        with caplog.at_level(logging.WARNING):
            second = store.add("New", NOW + timedelta(hours=1))
            trigger = ReminderTrigger(store)
            assert len(trigger.poll(NOW)) == 1
            assert trigger.poll(NOW) == []
        assert store.list(include_past=True) == [first, second]
        assert save.call_count == 2
    assert "disk full" in caplog.text
    assert path.read_bytes() == original
    third = store.add("Later", NOW + timedelta(hours=2))
    assert reminder_store.load_reminders(path) == [second, third]


def test_no_data_directory_never_reads_or_writes_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with monkeypatch.context() as patch:
        for name in ("exists", "read_text", "write_text", "mkdir"):
            patch.setattr(Path, name, Mock(side_effect=AssertionError("Disk accessed")))
        load = Mock(side_effect=AssertionError("Persistence accessed"))
        save = Mock(side_effect=AssertionError("Persistence accessed"))
        patch.setattr(reminder_store, "load_reminders", load)
        patch.setattr(reminder_store, "save_reminders", save)
        store = ReminderStore(clock=lambda: NOW)
        reminder = store.add("Water", NOW)
        assert store.due() == [reminder]
        assert len(ReminderTrigger(store).poll(NOW)) == 1
        assert store.list(include_past=True) == [reminder]
        load.assert_not_called()
        save.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_overdue_reminder_reaches_engine_once_across_restarts(tmp_path):
    store = ReminderStore(data_dir=tmp_path, clock=lambda: NOW)
    reminder = store.add("Water", NOW + timedelta(minutes=1))
    later = NOW + timedelta(hours=1)
    reopened = ReminderStore(data_dir=tmp_path, clock=lambda: later)
    assert reopened.due() == [reminder]
    session = ProactiveSession(reopened, later)
    result = session.tick(later, busy=False, input_has_text=False)
    assert result.event.kind == REMINDER
    assert result.event.payload == {"text": reminder.text, "due_at": reminder.due_at}
    assert session.tick(later, busy=False, input_has_text=False) is None
    # Polling remains non-consuming within the session; snapshots omit proposed IDs.
    assert reopened.due() == [reminder]
    restarted = ReminderStore(data_dir=tmp_path, clock=lambda: later)
    assert restarted.due() == []


def test_rejected_proposals_keep_existing_no_retry_semantics(tmp_path):
    store = ReminderStore(data_dir=tmp_path, clock=lambda: NOW)
    store.add("Water", NOW)
    session = ProactiveSession(store, NOW)
    assert session.tick(NOW, busy=True, input_has_text=False) is None
    assert session.tick(NOW, busy=False, input_has_text=False) is None
    assert ReminderStore(data_dir=tmp_path, clock=lambda: NOW).due() == []


@pytest.mark.parametrize("chat_tools", [False, True])
@pytest.mark.parametrize("proactive_chat", [False, True])
def test_window_startup_only_loads_reminders_when_tools_enabled(
    tmp_path, monkeypatch, chat_tools, proactive_chat,
):
    # Execute the real initializer through registry creation, without importing Qt.
    path = Path(__file__).resolve().parents[1] / "companion/ui/main_window.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "CompanionWindow")
    init = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
    end = next(i for i, node in enumerate(init.body) if isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Attribute) and target.attr == "tool_registry" for target in node.targets
    ))
    init.body = init.body[:end + 1]
    cls.body = [init]
    cls.bases = [ast.Name(id="FakeWidget", ctx=ast.Load())]
    namespace = {
        "FakeWidget": object, "AppConfig": SimpleNamespace, "OpenAICompatibleClient": Mock(),
        "ReminderStore": ReminderStore, "build_builtin_registry": build_builtin_registry,
        "DATA_DIR": tmp_path,
    }
    store = ReminderStore(data_dir=tmp_path, clock=lambda: NOW)
    reminder = store.add("Next year", NOW + timedelta(days=365))
    contents = (tmp_path / "reminders.json").read_bytes()
    load = Mock(wraps=reminder_store.load_reminders)
    save = Mock(wraps=reminder_store.save_reminders)
    monkeypatch.setattr(reminder_store, "load_reminders", load)
    monkeypatch.setattr(reminder_store, "save_reminders", save)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(path), "exec"), namespace)
    window = namespace["CompanionWindow"](SimpleNamespace(chat_tools=chat_tools, proactive_chat=proactive_chat))
    if chat_tools:
        load.assert_called_once_with(tmp_path / "reminders.json")
        result = window.tool_registry.execute("list_reminders", {})
        assert result.ok
        assert json.loads(result.content) == [asdict(reminder)]
    else:
        load.assert_not_called()
        assert window.tool_registry is None
    save.assert_not_called()
    assert (tmp_path / "reminders.json").read_bytes() == contents
