"""Exercise window summary callbacks with fake Qt objects, without importing GUI dependencies."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from companion.core.chat.history import ConversationHistory, ConversationSummary
from companion.core.chat.summary import build_chat_messages, plan_summary_update


@pytest.fixture
def window(tmp_path):
    # Compile just the real callback methods: importing main_window requires Qt WebEngine.
    path = Path(__file__).resolve().parents[1] / "companion/ui/main_window.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "CompanionWindow")
    methods = {
        "conversation_window", "start_summary_worker", "on_summary_ready", "on_summary_thread_finished",
    }
    cls.bases = []
    cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in methods]
    namespace = {
        "ConversationSummary": ConversationSummary,
        "CONVERSATION_WINDOW": 11,
        "build_chat_messages": build_chat_messages,
        "plan_summary_update": plan_summary_update,
        "QThread": Mock(side_effect=lambda *_: Mock()),
        "SummaryWorker": Mock(side_effect=lambda *_: Mock()),
        "logger": Mock(),
    }
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), "exec"), namespace)
    instance = namespace["CompanionWindow"]()
    instance.config = SimpleNamespace(conversation_summary=True, api_key="fake-key")
    instance.client = Mock()
    instance.history = ConversationHistory(tmp_path / "history.json", max_entries=24)
    instance.history.entries = [
        {"role": role, "content": f"{role} {pair}"}
        for pair in range(12)
        for role in ("user", "assistant")
    ]
    instance.messages = [{"role": "system", "content": "System"}, *instance.history.messages()]
    instance.memory_store = SimpleNamespace(render_context=lambda: "Memory")
    instance.summary_thread = None
    instance.summary_worker = None
    instance.summary_snapshot = None
    return instance


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
