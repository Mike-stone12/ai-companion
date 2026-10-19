"""Session tools and the real worker methods, exercised without importing Qt or TTS."""

import ast
import io
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, call

import pytest

from companion.core.chat.emotion import EmotionTagParser
from companion.core.config import AppConfig
from companion.core.llm.client import OpenAICompatibleClient
from companion.core.text import SentenceSplitter
from companion.core.tools import reminders
from companion.core.tools.builtin import build_builtin_registry
from companion.core.tools.loop import run_tool_rounds
from companion.core.tools.registry import ToolRegistry
from companion.core.tools.reminders import ReminderStore

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


def chunk(**delta):
    return {"choices": [{"delta": delta}]}


def tool_call(name, arguments="{}"):
    return chunk(tool_calls=[{"index": 0, "id": "one", "function": {"name": name, "arguments": arguments}}])


def test_in_memory_reminders_survive_turns_without_disk_io(monkeypatch):
    def no_disk(*args):
        pytest.fail("Session reminders must not access disk")

    monkeypatch.setattr(reminders, "load_json", no_disk)
    monkeypatch.setattr(reminders, "save_settings", no_disk)
    store = ReminderStore(clock=lambda: NOW)
    registry = build_builtin_registry(store, clock=lambda: NOW)
    visible = []

    def set_stream(messages, tools):
        assert tools == registry.schemas()
        if messages[-1]["role"] == "tool":
            assert "Tea" in messages[-1]["content"]
            return [chunk(content="Saved.")]
        return [tool_call("set_reminder", '{"text":"Tea","when":"2026-10-19T12:00:00Z"}')]

    def list_stream(messages, tools):
        if messages[-1]["role"] == "tool":
            assert [row["text"] for row in json.loads(messages[-1]["content"])] == ["Tea"]
            return [chunk(content="You have a reminder.")]
        return [tool_call("list_reminders")]

    for stream in (set_stream, list_stream):
        result = run_tool_rounds([{"role": "user", "content": "Request"}], registry, stream, visible.append)
        assert result.rounds == 2
    assert visible == ["Saved.", "You have a reminder."]
    assert ReminderStore(clock=lambda: NOW).list() == []
    with pytest.raises(ValueError):
        store.add("", NOW)
    assert len(store.list()) == 1


@pytest.fixture
def worker_class():
    # Follow the summary app tests: compile the real worker with fake signals,
    # avoiding imports of PyQt6 and the TTS adapter entirely.
    path = Path(__file__).resolve().parents[1] / "companion/app/workers.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ChatStreamWorker")
    namespace = {
        "QObject": object, "pyqtSignal": lambda *_: Mock(), "pyqtSlot": lambda: lambda fn: fn,
        "OpenAICompatibleClient": OpenAICompatibleClient, "ToolRegistry": ToolRegistry,
        "EmotionTagParser": EmotionTagParser, "SentenceSplitter": SentenceSplitter,
        "run_tool_rounds": run_tool_rounds, "DEMO_REPLY": "Demo reply.",
        "Callable": Callable,
    }
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["ChatStreamWorker"]


def test_disabled_worker_preserves_request_bytes_and_text(worker_class, monkeypatch):
    client = OpenAICompatibleClient(AppConfig(api_key="key", chat_tools=False, chat_thinking=False,
                                            base_url="https://api.deepseek.com/v1"))
    sent = []

    def urlopen(request, timeout):
        sent.append(request.data)
        return io.BytesIO(f'data: {json.dumps(chunk(content="[happy] Hello there."))}\n\n'.encode())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    messages = [{"role": "user", "content": "Hello"}]
    worker = worker_class(client, messages, registry=ToolRegistry())
    worker.run()
    assert sent == [json.dumps({"model": client.config.model, "messages": messages, "stream": True,
                               "thinking": {"type": "disabled"}}).encode()]
    worker.finished.emit.assert_called_once_with("Hello there.")
    worker.emotion.emit.assert_called_once_with("happy")
    worker.sentence.emit.assert_called_once_with("Hello there.")
    worker.error.emit.assert_not_called()


def test_enabled_worker_streams_only_text_through_existing_pipeline(worker_class):
    registry = ToolRegistry()
    registry.register(lambda: "private tool result", name="check")
    client = Mock(config=AppConfig(api_key="key", chat_tools=True))
    worker = worker_class(client, [], registry=registry)

    def stream(messages, tools):
        assert tools == registry.schemas()
        if not messages:
            yield chunk(content="[hap")
            yield tool_call("check")
            assert worker.delta.emit.call_count == 0
        else:
            assert messages[-1]["content"] == "private tool result"
            yield chunk(content="py] Hello there.")
            worker.delta.emit.assert_called_once_with("Hello there.")
            yield chunk(content=" All done.")

    client.stream_chat_chunks.side_effect = stream
    worker.run()
    client.stream_chat.assert_not_called()
    worker.emotion.emit.assert_called_once_with("happy")
    worker.delta.emit.assert_has_calls([call("Hello there."), call(" All done.")])
    worker.sentence.emit.assert_has_calls([call("Hello there."), call("All done.")])
    worker.finished.emit.assert_called_once_with("Hello there. All done.")
    worker.error.emit.assert_not_called()


def test_enabled_worker_bounds_rounds(worker_class):
    registry = ToolRegistry()
    executed = []

    @registry.tool
    def check():
        executed.append(True)
        return "hidden"

    client = Mock(config=AppConfig(api_key="key", chat_tools=True))
    client.stream_chat_chunks.side_effect = lambda *_: iter([tool_call("check")])
    worker = worker_class(client, [], registry=registry)
    worker.run()
    assert client.stream_chat_chunks.call_count == 3
    assert len(executed) == 2
    worker.delta.emit.assert_not_called()
    worker.sentence.emit.assert_not_called()
    worker.finished.emit.assert_called_once_with("")


@pytest.mark.parametrize("partial", [False, True])
def test_enabled_worker_preserves_stream_interruption(worker_class, partial):
    client = Mock(config=AppConfig(api_key="key", chat_tools=True))

    def stream(*args):
        if partial:
            yield chunk(content="[happy] Partial reply.")
        raise RuntimeError("Stream deadline")

    client.stream_chat_chunks.side_effect = stream
    worker = worker_class(client, [], registry=ToolRegistry())
    worker.run()
    assert worker.delta.emit.call_count == int(partial)
    worker.error.emit.assert_called_once_with("Stream deadline")
    worker.finished.emit.assert_not_called()


def test_enabled_demo_does_not_request_tools(worker_class):
    client = Mock(config=AppConfig(api_key="", chat_tools=True))
    worker = worker_class(client, [], registry=ToolRegistry())
    worker.run()
    client.stream_chat_chunks.assert_not_called()
    client.stream_chat.assert_not_called()
    worker.finished.emit.assert_called_once_with("Demo reply.")
