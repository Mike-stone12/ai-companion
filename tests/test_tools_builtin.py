import json
from datetime import UTC, datetime, timedelta

import pytest

from companion.core.tools.builtin import build_builtin_registry
from companion.core.tools.reminders import ReminderStore

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


@pytest.fixture
def tools(tmp_path):
    store = ReminderStore(tmp_path / "reminders.json", clock=lambda: NOW)
    return store, build_builtin_registry(store, clock=lambda: NOW)


def test_schemas(tools):
    _, registry = tools
    schemas = {item["function"]["name"]: item["function"] for item in registry.schemas()}
    assert set(schemas) == {"get_time", "set_reminder", "list_reminders"}
    for name, required in [("get_time", []), ("set_reminder", ["text", "when"]), ("list_reminders", [])]:
        params = schemas[name]["parameters"]
        assert params["required"] == required
        assert set(params["properties"]) == set(required)
        assert all(prop["type"] == "string" for prop in params["properties"].values())


def test_execute_time(tools):
    _, registry = tools
    result = registry.execute("get_time", {})
    assert result.ok
    local = NOW.astimezone()
    assert local.date().isoformat() in result.content
    assert local.strftime("%H:%M:%S") in result.content
    assert local.strftime("%A") in result.content


@pytest.mark.parametrize("when", ["2026-10-19T12:00:00", "2026-10-19T12:00:00+05:30", "2026-10-19T12:00:00Z"])
def test_execute_reminders(tools, when):
    store, registry = tools
    assert json.loads(registry.execute("list_reminders", {}).content) == []
    result = registry.execute("set_reminder", json.dumps({"text": "Tea", "when": when}))
    assert result.ok
    reminder, = store.list()
    expected = datetime.fromisoformat(when)
    if expected.tzinfo is None:
        expected = expected.astimezone()
    assert datetime.fromisoformat(reminder.due_at) == expected
    assert reminder.id in result.content
    assert reminder.due_at in result.content
    store.add("Already due", NOW)
    listed = registry.execute("list_reminders", {})
    assert listed.ok
    assert [item["id"] for item in json.loads(listed.content)] == [reminder.id]


@pytest.mark.parametrize("text, when", [
    ("Tea", "not-a-date"), ("Tea", (NOW - timedelta(seconds=1)).isoformat()),
    (" ", "2026-10-19T12:00:00Z"), ("x" * 201, "2026-10-19T12:00:00Z"),
])
def test_invalid_reminder_is_wrapped(tools, text, when):
    store, registry = tools
    result = registry.execute("set_reminder", {"text": text, "when": when})
    assert not result.ok
    assert result.content == "Tool execution failed (ValueError)"
    assert store.list(include_past=True) == []


def test_factories_are_independent(tools, tmp_path):
    _, registry = tools
    other = build_builtin_registry(ReminderStore(tmp_path / "other.json", clock=lambda: NOW))
    assert registry.execute("set_reminder", {"text": "Tea", "when": "2026-10-19T12:00:00Z"}).ok
    assert json.loads(other.execute("list_reminders", {}).content) == []
