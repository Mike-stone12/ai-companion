"""Exercise window summary callbacks with fake Qt objects, without importing GUI dependencies."""

import ast
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from companion.core.chat.history import ConversationHistory, ConversationSummary
from companion.core.chat.summary import build_chat_messages, plan_summary_update
from companion.core.memory.store import MemoryStore


@pytest.fixture
def window(tmp_path):
    # Compile just the real callback methods: importing main_window requires Qt WebEngine.
    path = Path(__file__).resolve().parents[1] / "companion/ui/main_window.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "CompanionWindow")
    methods = {
        "conversation_window", "state_context", "start_summary_worker", "on_summary_ready",
        "on_summary_thread_finished", "history_text", "record_reply", "closeEvent",
    }
    cls.bases = [ast.Name(id="FakeWidget", ctx=ast.Load())]
    cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in methods]
    namespace = {
        "FakeWidget": type("FakeWidget", (), {"closeEvent": Mock()}),
        "ConversationSummary": ConversationSummary,
        "CONVERSATION_WINDOW": 11,
        "build_chat_messages": build_chat_messages,
        "Callable": Callable,
        "plan_summary_update": plan_summary_update,
        "QThread": Mock(side_effect=lambda *_: Mock()),
        "SummaryWorker": Mock(side_effect=lambda *_: Mock()),
        "logger": Mock(),
    }
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    exec(compile(module, str(path), "exec"), namespace)
    instance = namespace["CompanionWindow"]()
    instance.config = SimpleNamespace(conversation_summary=True, memory_relevant_recall=True, api_key="fake-key")
    instance.client = Mock()
    instance.history = ConversationHistory(tmp_path / "history.json", max_entries=24)
    instance.history.entries = [
        {"role": role, "content": f"{role} {pair}"}
        for pair in range(12)
        for role in ("user", "assistant")
    ]
    instance.messages = [{"role": "system", "content": "System"}, *instance.history.messages()]
    instance.memory_store = SimpleNamespace(render_context=lambda **kwargs: "Memory")
    instance.memory_embedder = None
    instance.summary_thread = None
    instance.summary_worker = None
    instance.summary_snapshot = None
    instance.reply_emotion = None
    instance.save_window_state = Mock()
    instance.idle_timer = Mock()
    instance.proactive_timer = None
    instance.audio_watchdog = Mock()
    instance.bridge = Mock()
    instance.tts_queue = []
    instance.discard_pending_clips = Mock()
    instance.voice_session = None
    instance.transcription_thread = None
    instance.wake_thread = instance.wake_capture_timer = None
    instance.pause_wake_word = Mock()
    return instance


@pytest.mark.parametrize("enabled", [False, True])
def test_chat_context_passes_current_message_and_recall_flag(window, tmp_path, enabled):
    window.config.memory_relevant_recall = enabled
    window.memory_store = MemoryStore(tmp_path / "memory.json")
    window.memory_store.items = [
        {"summary": "coffee", "updated_at": "2026-10-01"},
        *[{"summary": f"books {day}", "updated_at": f"2026-10-{day:02d}"} for day in range(2, 11)],
    ]

    context = window.conversation_window("coffee")

    memory_context = context[1]["content"]
    assert ("- [memory] coffee" in memory_context) is enabled
    assert len(memory_context.splitlines()[1:]) == 8


@pytest.mark.parametrize("failure", ["SummaryWorker", "QThread", "plan_summary_update"])
def test_summary_start_failure_does_not_interrupt_recording_reply(window, monkeypatch, failure):
    namespace = window.record_reply.__globals__
    with monkeypatch.context() as patch:
        patch.setitem(namespace, failure, Mock(side_effect=RuntimeError("Private provider text")))
        window.record_reply("Still recorded")

    assert window.messages[-1] == {"role": "assistant", "content": "Still recorded"}
    assert ConversationHistory(window.history.path).messages()[-1] == window.messages[-1]
    assert window.summary_thread is None
    assert window.summary_worker is None
    assert window.summary_snapshot is None
    namespace["logger"].info.assert_called_once_with("Conversation summary worker could not start")
    window.start_summary_worker()
    assert window.summary_thread is not None


@pytest.mark.parametrize("state", ["running", "finished", "absent"])
def test_close_waits_for_running_summary_and_ignores_late_result(window, state):
    window.start_summary_worker()
    thread = window.summary_thread
    thread.isRunning.return_value = state == "running"
    if state == "absent":
        window.summary_thread = None
    window.history.save = Mock()
    event = Mock()

    window.closeEvent(event)
    window.on_summary_ready(ConversationSummary("Late result", 12))

    if state == "running":
        thread.quit.assert_called_once_with()
        thread.wait.assert_called_once_with(2000)
        assert thread.method_calls.index(("quit", (), {})) < thread.method_calls.index(("wait", (2000,), {}))
    else:
        thread.quit.assert_not_called()
        thread.wait.assert_not_called()
    assert window.summary_snapshot is None
    assert window.history.summary is None
    window.history.save.assert_not_called()
    window.record_reply.__globals__["FakeWidget"].closeEvent.assert_called_once_with(event)


def test_running_summary_skips_new_requests_until_thread_finishes(window):
    window.start_summary_worker()
    thread, worker = window.summary_thread, window.summary_worker
    assert thread is not None
    thread.start.assert_called_once()
    worker.moveToThread.assert_called_once_with(thread)
    thread.started.connect.assert_called_once_with(worker.run)
    window.start_summary_worker()
    assert window.summary_thread is thread
    assert window.summary_worker is worker
    window.on_summary_thread_finished()
    assert window.summary_thread is None
    assert window.summary_worker is None
    assert window.summary_snapshot is None
    window.start_summary_worker()
    assert window.summary_thread is not thread


@pytest.mark.parametrize("reason", ["disabled", "demo", "within_window", "already_folded"])
def test_summary_does_not_start_when_unneeded(window, reason):
    if reason == "disabled":
        window.config.conversation_summary = False
    elif reason == "demo":
        window.config.api_key = ""
    elif reason == "within_window":
        window.history.entries = window.history.entries[-4:]
    else:
        window.history.summary = ConversationSummary("Existing", 12)
    window.start_summary_worker()
    assert window.summary_thread is None


def test_result_rebases_cursor_after_new_turns_trim_history(window):
    window.start_summary_worker()
    for role in ("user", "assistant"):
        window.messages.append({"role": role, "content": "New turn"})
        window.history.append(role, "New turn")
    window.on_summary_ready(ConversationSummary("Updated", 12))
    restored = ConversationHistory(window.history.path)
    assert restored.summary == ConversationSummary("Updated", 10)
    assert restored.messages() == window.history.messages()


def test_result_does_not_advance_cursor_for_appended_untrimmed_turns(window):
    window.history.max_entries = 200
    window.start_summary_worker()
    window.messages.append({"role": "user", "content": "Pending"})
    window.history.append("user", "Pending")
    window.on_summary_ready(ConversationSummary("Updated", 12))
    assert window.history.summary == ConversationSummary("Updated", 12)


def test_failed_update_keeps_trimmed_cursor_and_does_not_save(window):
    previous = ConversationSummary("Existing", 2)
    window.history.summary = previous
    window.start_summary_worker()
    window.messages.append({"role": "user", "content": "Pending"})
    window.history.append("user", "Pending")
    window.history.save = Mock()
    window.on_summary_ready(previous)
    assert window.history.summary == ConversationSummary("Existing", 1)
    window.history.save.assert_not_called()


def test_save_failure_keeps_old_summary_and_chat_context(window):
    window.history.summary = ConversationSummary("Existing", 2)
    window.start_summary_worker()
    window.history.save = Mock(side_effect=OSError("Private path"))
    window.on_summary_ready(ConversationSummary("Updated", 12))
    assert window.history.summary == ConversationSummary("Existing", 2)
    assert window.conversation_window()[2]["content"] == "Conversation summary:\nExisting"


def test_persisted_summary_is_injected_and_disabled_setting_omits_it(window):
    window.history.summary = ConversationSummary("Existing", 2)
    window.history.save()
    window.history = ConversationHistory(window.history.path)
    context = window.conversation_window()
    assert context[:3] == [
        {"role": "system", "content": "System"},
        {"role": "system", "content": "Memory"},
        {"role": "system", "content": "Conversation summary:\nExisting"},
    ]
    assert context[3:] == window.messages[-11:]
    window.config.conversation_summary = False
    assert window.conversation_window() == context[:2] + context[3:]
