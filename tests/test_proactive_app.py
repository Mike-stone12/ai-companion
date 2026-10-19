"""Run real window callbacks with fakes; Qt and audio are unavailable in CI."""

import ast
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from companion.core.chat.history import ConversationHistory
from companion.core.proactive.session import ProactiveSession, proactive_request
from companion.core.text import sanitize_reply_text, sanitize_tts_text
from companion.core.tools.reminders import ReminderStore

NOW = datetime(2026, 10, 18, 9, tzinfo=UTC)


@pytest.fixture
def window(tmp_path):
    path = Path(__file__).resolve().parents[1] / "companion/ui/main_window.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "CompanionWindow")
    methods = {
        "setup_proactive", "on_proactive_tick", "send_message", "reset_reply_state", "start_chat_worker",
        "on_reply_delta", "on_reply_sentence", "on_reply_finished", "render_reply", "history_text", "record_reply",
        "maybe_finish_reply", "finish_interaction", "closeEvent", "submit_message",
    }
    cls.bases = [ast.Name(id="FakeWidget", ctx=ast.Load())]
    cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in methods]
    namespace = {
        "FakeWidget": type("FakeWidget", (), {"closeEvent": Mock()}),
        "ProactiveSession": ProactiveSession, "proactive_request": proactive_request,
        "ReminderStore": ReminderStore, "local_now": Mock(return_value=NOW),
        "QTimer": Mock(), "QThread": Mock(), "ChatStreamWorker": Mock(), "Callable": Callable,
        "sanitize_reply_text": sanitize_reply_text, "sanitize_tts_text": sanitize_tts_text,
        "tts_edge": SimpleNamespace(is_available=lambda: True), "logger": Mock(),
        "foreground_app_name": Mock(return_value="Editor"),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(path), "exec"), namespace)
    instance = namespace["CompanionWindow"]()
    instance.config = SimpleNamespace(proactive_chat=True, active_app_monitor=False)
    instance.history = ConversationHistory(tmp_path / "history.json")
    instance.messages = [{"role": "system", "content": "Companion"}]
    for name in (
        "chat_input", "send_button", "chat_panel", "set_status", "client", "tool_registry",
        "on_reply_emotion", "on_reply_error", "run_next_tts", "start_memory_worker", "start_summary_worker",
        "audio_watchdog", "set_talking", "save_window_state", "idle_timer", "bridge", "discard_pending_clips",
    ):
        setattr(instance, name, Mock())
    instance.chat_input.text.return_value = ""
    instance.conversation_window = Mock(side_effect=lambda *a, **kw: lambda: list(instance.messages))
    instance.busy = False
    instance.stream_done = True
    instance.renderer_ready = True
    instance.tts_thread = None
    instance.summary_thread = None
    instance.voice_session = None
    instance.transcription_thread = None
    instance.tts_queue = deque()
    instance.pending_clips = {}
    instance.pending_user_text = "stale previous user text"
    return instance


def test_disabled_setting_creates_no_timer_engine_or_requests(window):
    window.config.proactive_chat = False
    window.setup_proactive(None)
    window.on_proactive_tick()
    assert window.proactive is None
    assert window.proactive_timer is None
    window.setup_proactive.__globals__["QTimer"].assert_not_called()
    window.setup_proactive.__globals__["local_now"].assert_not_called()
    window.conversation_window.assert_not_called()


def test_enabled_timer_starts_every_thirty_seconds_and_stops_on_close(window):
    window.setup_proactive(ReminderStore())
    timer = window.proactive_timer
    timer.setInterval.assert_called_once_with(30_000)
    timer.timeout.connect.assert_called_once_with(window.on_proactive_tick)
    timer.start.assert_called_once_with()
    window.closeEvent(Mock())
    timer.stop.assert_called_once_with()
    window.on_proactive_tick()
    window.conversation_window.assert_not_called()


@pytest.mark.parametrize("proactive_chat, monitor", [(False, False), (False, True), (True, False)])
def test_disabled_monitor_never_queries_adapter(window, proactive_chat, monitor):
    window.config.proactive_chat = proactive_chat
    window.config.active_app_monitor = monitor
    window.setup_proactive(ReminderStore())
    window.on_proactive_tick()
    window.on_proactive_tick.__globals__["foreground_app_name"].assert_not_called()
    assert window.proactive is None or window.proactive.active_app is None


def test_monitor_samples_before_each_engine_tick_even_when_busy(window):
    window.config.active_app_monitor = True
    window.setup_proactive(ReminderStore())
    window.busy = True
    namespace = window.on_proactive_tick.__globals__
    calls = Mock()
    calls.attach_mock(namespace["foreground_app_name"], "query")
    window.proactive.active_app.record_sample = calls.sample
    window.proactive.engine.tick = calls.tick
    calls.tick.return_value = None
    for seconds in (30, 60):
        now = NOW + timedelta(seconds=seconds)
        namespace["local_now"].return_value = now
        window.on_proactive_tick()
        assert [call[0] for call in calls.mock_calls] == ["query", "sample", "tick"]
        calls.sample.assert_called_once_with("Editor", now)
        assert calls.tick.call_args.args[0] == now
        calls.reset_mock()


@pytest.mark.parametrize("raises", [False, True])
def test_monitor_unavailable_sample_skips_update_and_still_ticks(window, raises):
    window.config.active_app_monitor = True
    window.setup_proactive(ReminderStore())
    namespace = window.on_proactive_tick.__globals__
    query = namespace["foreground_app_name"]
    query.return_value = None
    if raises:
        query.side_effect = RuntimeError("Unavailable")
    window.proactive.active_app.record_sample = Mock()
    window.proactive.engine.tick = Mock(return_value=None)
    window.on_proactive_tick()
    query.assert_called_once_with()
    window.proactive.active_app.record_sample.assert_not_called()
    window.proactive.engine.tick.assert_called_once()
    assert namespace["logger"].debug.called
    namespace["logger"].info.assert_not_called()
    namespace["logger"].warning.assert_not_called()
    namespace["logger"].error.assert_not_called()


@pytest.mark.parametrize("state", ["busy", "streaming", "tts", "queued_speech", "playing", "typing"])
def test_no_turn_during_activity(window, state):
    window.setup_proactive(ReminderStore())
    if state == "busy":
        window.busy = True
    elif state == "streaming":
        window.stream_done = False
    elif state == "tts":
        window.tts_thread = Mock()
    elif state == "queued_speech":
        window.tts_queue.append("Hello")
    elif state == "playing":
        window.pending_clips["url"] = "clip"
    else:
        window.chat_input.text.return_value = "Draft"
    window.on_proactive_tick()
    window.conversation_window.assert_not_called()
    window.start_chat_worker.__globals__["ChatStreamWorker"].assert_not_called()


def test_proactive_reply_uses_normal_stream_speech_and_history_without_user_instruction(window):
    window.setup_proactive(ReminderStore())
    window.on_proactive_tick()
    worker_factory = window.start_chat_worker.__globals__["ChatStreamWorker"]
    payload = worker_factory.call_args.args[1]
    assert "morning" in payload()[-1]["content"]
    assert window.busy and not window.stream_done
    assert window.speak_reply
    window.chat_panel.add_user.assert_not_called()
    assert window.history.messages() == []
    assert len(window.messages) == 1
    worker = window.chat_worker
    worker.delta.connect.assert_called_once_with(window.on_reply_delta)
    worker.sentence.connect.assert_called_once_with(window.on_reply_sentence)
    worker.finished.connect.assert_any_call(window.on_reply_finished)
    window.on_reply_delta("Good morning.")
    window.chat_panel.update_reply.assert_called_with("Good morning.")
    window.on_reply_sentence("Good morning.")
    assert list(window.tts_queue) == ["Good morning."]
    window.run_next_tts.assert_called_once_with()
    window.on_reply_finished("Good morning.")
    window.start_memory_worker.assert_not_called()
    assert ConversationHistory(window.history.path).messages() == [
        {"role": "assistant", "content": "Good morning."},
    ]
    assert window.busy  # Speech still queued even though the stream is complete.
    window.tts_queue.clear()
    window.maybe_finish_reply()
    assert not window.busy


@pytest.mark.parametrize("enabled", [False, True])
def test_user_send_preserves_normal_turn_and_updates_activity_only_when_enabled(window, enabled):
    window.config.proactive_chat = enabled
    window.setup_proactive(ReminderStore())
    later = NOW + timedelta(minutes=3)
    window.send_message.__globals__["local_now"].return_value = later
    window.chat_input.text.return_value = "Hello"
    window.send_message()
    if enabled:
        assert window.proactive.last_user_activity == later
    window.chat_panel.add_user.assert_called_once_with("Hello")
    assert window.history.messages() == [{"role": "user", "content": "Hello"}]
    window.on_reply_finished("Hi!")
    window.start_memory_worker.assert_called_once_with("Hello", "Hi!")
