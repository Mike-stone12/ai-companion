"""Run the window's message-merging path with Qt stand-ins (Qt is unavailable in CI)."""

from collections import deque
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_voice_input_qt_adapters import Signal, load_class

from companion.core.chat.history import ConversationHistory
from companion.core.chat.merge import QUIET_CLOSED, QUIET_OPEN, MessageMerger, merged_text
from companion.core.chat.quote import MARKER, clip_quote, quote_display, quote_turn_text

NOW = datetime(2026, 11, 4, 20, 0, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now


class FakeTimer:
    def __init__(self):
        self.active = False
        self.intervals = []

    def isActive(self):
        return self.active

    def start(self, ms):
        self.active = True
        self.intervals.append(ms)

    def stop(self):
        self.active = False


class FakeWorker:
    def __init__(self, payload):
        self.payload = payload
        for name in ("emotion", "delta", "sentence", "finished", "error"):
            setattr(self, name, Signal())


@pytest.fixture
def window(tmp_path):
    clock = Clock()
    cls = load_class(
        "companion/ui/main_window.py", "CompanionWindow",
        QWidget=type("QWidget", (), {}), time=clock, local_now=Mock(return_value=NOW),
        MessageMerger=MessageMerger, merged_text=merged_text, sanitize_reply_text=lambda text: text.strip(),
        MARKER=MARKER, clip_quote=clip_quote, quote_display=quote_display, quote_turn_text=quote_turn_text,
        tts_edge=SimpleNamespace(is_available=lambda: False), deque=deque,
    )
    instance = cls.__new__(cls)
    instance.clock = clock
    instance.config = SimpleNamespace(message_merge=True, reply_pacing=False)
    instance.history = ConversationHistory(tmp_path / "history.json")
    instance.messages = [{"role": "system", "content": "Companion"}]
    instance.merger = MessageMerger()
    instance.merge_timer = FakeTimer()
    instance.turn_user_texts = []
    instance.reply_supersedable = False
    instance.activity_pending = False
    instance.busy = False
    instance.stream_done = True
    instance.renderer_ready = False
    instance.proactive = None
    instance.pending_image = None
    instance.pending_quote = None
    instance.reply_parts, instance.reply_notes, instance.tts_queue = [], [], deque()
    instance.pending_user_text = ""
    for name in (
        "chat_input", "send_button", "chat_panel", "set_status", "pause_wake_word", "resume_wake_word",
        "set_talking", "precheck_distress", "record_user_activity", "record_reply", "record_reply_mood",
        "start_memory_worker", "maybe_finish_reply", "render_reply", "quote_bar", "quote_label",
    ):
        setattr(instance, name, Mock())
    instance.conversation_window = Mock(side_effect=lambda text, defer: [dict(m) for m in instance.messages])
    instance.workers = []

    def start_chat_worker(payload):
        worker = FakeWorker(payload)
        instance.chat_worker = worker
        worker.emotion.connect(instance.on_reply_emotion)
        worker.delta.connect(instance.on_reply_delta)
        worker.sentence.connect(instance.on_reply_sentence)
        worker.finished.connect(instance.on_reply_finished)
        worker.error.connect(instance.on_reply_error)
        instance.workers.append(worker)

    instance.start_chat_worker = start_chat_worker
    return instance


def send(window, text):
    window.chat_input.text.return_value = text
    window.send_message()


def fire(window):
    window.merge_timer.active = False
    window.flush_merged()


def user_turns(window):
    return [m["content"] for m in window.messages if m["role"] == "user"]


def test_a_message_shows_at_once_but_waits_for_the_rest_of_the_burst(window):
    send(window, "我跟你说，")

    window.chat_panel.add_user.assert_called_once_with("我跟你说，")
    window.chat_input.clear.assert_called_once()
    window.chat_input.setEnabled.assert_not_called()
    assert window.workers == []
    assert window.merge_timer.intervals == [int(QUIET_OPEN * 1000)]
    assert window.merge_waiting()


def test_a_burst_becomes_one_request_with_one_user_turn_per_message(window):
    send(window, "在吗")
    window.clock.now += 1
    send(window, "今天被老板骂了。")
    assert window.merge_timer.intervals[-1] == int(QUIET_CLOSED * 1000)

    fire(window)

    assert len(window.workers) == 1
    assert user_turns(window) == ["在吗", "今天被老板骂了。"]
    assert [entry["content"] for entry in window.history.messages()] == ["在吗", "今天被老板骂了。"]
    assert window.pending_user_text == "在吗\n今天被老板骂了。"
    window.precheck_distress.assert_called_once_with("在吗\n今天被老板骂了。")
    assert window.busy
    assert not window.merge_waiting()


def test_activity_is_recorded_once_the_reply_starts(window):
    send(window, "好的。")
    fire(window)
    window.record_user_activity.assert_not_called()

    window.workers[0].delta.emit("嗯嗯")

    window.record_user_activity.assert_called_once_with()
    assert not window.reply_supersedable


def test_a_message_before_any_reply_text_restarts_the_request_with_everything(window):
    send(window, "今天好累")
    fire(window)
    first = window.workers[0]

    window.clock.now += 1
    send(window, "加班到十点。")
    assert not window.busy
    assert len(window.workers) == 1
    fire(window)

    assert len(window.workers) == 2
    assert user_turns(window) == ["今天好累", "加班到十点。"]
    assert window.pending_user_text == "今天好累\n加班到十点。"
    # The dropped request can no longer reach the window.
    first.delta.emit("旧的回复")
    first.finished.emit("旧的回复")
    assert window.reply_parts == []
    window.record_reply.assert_not_called()
    window.workers[1].delta.emit("辛苦啦")
    window.record_user_activity.assert_called_once_with()


def test_a_message_while_she_is_replying_waits_for_the_next_turn(window):
    send(window, "你在干嘛？")
    fire(window)
    window.workers[0].delta.emit("在追剧")

    send(window, "什么剧？")
    assert window.busy
    assert len(window.workers) == 1
    assert window.merge_timer.intervals == [int(QUIET_CLOSED * 1000)]

    window.workers[0].finished.emit("在追剧")
    window.finish_interaction()
    assert window.merge_timer.active
    fire(window)

    assert len(window.workers) == 2
    assert user_turns(window) == ["你在干嘛？", "什么剧？"]
    assert window.pending_user_text == "什么剧？"


def test_a_failed_request_still_records_the_activity_and_clears_the_turn(window):
    send(window, "你好。")
    fire(window)
    window.workers[0].error.emit("timeout")

    window.record_user_activity.assert_called_once_with()
    assert window.turn_user_texts == []


def test_blank_input_is_ignored(window):
    send(window, "")
    window.chat_panel.add_user.assert_not_called()
    assert not window.merge_waiting()


def test_merging_off_sends_each_message_straight_away(window):
    window.config.message_merge = False
    window.submit_message = Mock()

    send(window, "在吗")

    window.submit_message.assert_called_once_with("在吗", None)
    assert not window.merge_waiting()


def test_a_quote_reply_shows_a_marker_and_gives_the_model_the_quoted_line(window):
    window.set_quote("我最喜欢草莓", False)
    window.quote_bar.show.assert_called_once_with()
    window.quote_label.setText.assert_called_once_with("↪ 我最喜欢草莓")

    send(window, "那你上次说芒果")
    fire(window)

    window.chat_panel.add_user.assert_called_once_with("↪ 我最喜欢草莓\n那你上次说芒果")
    assert user_turns(window) == ["[引用你说的：「我最喜欢草莓」]\n那你上次说芒果"]
    assert window.pending_quote is None
    window.quote_bar.hide.assert_called()


def test_the_quote_is_kept_until_there_is_text_to_send(window):
    window.set_quote("晚安", False)
    send(window, "   ")
    assert window.pending_quote == ("晚安", False)
    window.clear_quote()
    send(window, "好")
    fire(window)
    assert user_turns(window) == ["好"]


def test_quoting_with_merging_off_goes_through_submit(window):
    window.config.message_merge = False
    window.submit_message = Mock()
    window.set_quote("我下周五考六级", True)

    send(window, "记住了吗")

    window.submit_message.assert_called_once_with(
        "[引用我自己说的：「我下周五考六级」]\n记住了吗", "↪ 我下周五考六级\n记住了吗",
    )
