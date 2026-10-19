"""Run the window's reply-pacing callbacks with Qt stand-ins (Qt is unavailable in CI)."""

import random
from collections import deque
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_voice_input_qt_adapters import load_class

from companion.core.chat import pacing
from companion.core.persona import CHILDHOOD_FRIEND
from companion.core.schedule import block_at, presence_label
from companion.core.state import IDLE_THRESHOLD, current_mood, fresh_state
from companion.core.text import SentenceSplitter, sanitize_reply_text, sanitize_tts_text

NOW = datetime(2026, 10, 19, 20, 0, tzinfo=UTC)


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

    def fire(self, window):
        self.active = False
        window.show_next_message()


@pytest.fixture
def window():
    cls = load_class(
        "companion/ui/main_window.py", "CompanionWindow",
        QWidget=type("QWidget", (), {}), local_now=Mock(return_value=NOW), timedelta=timedelta, deque=deque,
        MessageSplitter=pacing.MessageSplitter, reply_delay=pacing.reply_delay, typing_delay=pacing.typing_delay,
        SentenceSplitter=SentenceSplitter, sanitize_reply_text=sanitize_reply_text,
        sanitize_tts_text=sanitize_tts_text, block_at=block_at, presence_label=presence_label,
        current_mood=current_mood, IDLE_THRESHOLD=IDLE_THRESHOLD,
    )
    instance = cls.__new__(cls)
    instance.config = SimpleNamespace(reply_pacing=True, daily_schedule=False, mood_half_life_minutes=120)
    instance.persona = CHILDHOOD_FRIEND
    instance.companion_state = None
    instance.pacing_rng = random.Random(1)
    instance.message_splitter = pacing.MessageSplitter()
    instance.pending_messages = deque()
    instance.messages_shown = 0
    instance.message_timer = FakeTimer()
    instance.chat_panel = Mock()
    instance.tts_queue = deque()
    instance.run_next_tts = Mock()
    instance.set_status = Mock()
    instance.speak_reply = True
    instance.stream_done = False
    instance.reply_parts = []
    instance.busy = True
    instance.maybe_finish_reply = Mock()
    return instance


def shown(window):
    return [call.args[0] for call in window.chat_panel.add_reply_message.call_args_list]


def test_first_message_goes_out_as_soon_as_its_line_is_complete(window):
    window.on_reply_delta("你来啦！\n我等")

    assert window.message_timer.intervals == [0]
    window.message_timer.fire(window)
    assert shown(window) == ["你来啦！"]
    # The stream is still running, so "typing…" shows for what comes next.
    window.chat_panel.show_typing.assert_called()


def test_later_messages_wait_for_a_typing_pause_and_are_spoken_in_order(window):
    window.on_reply_delta("你来啦！\n我等你好久了，今天过得怎么样？\n")
    window.message_timer.fire(window)
    window.message_timer.fire(window)

    assert shown(window) == ["你来啦！", "我等你好久了，今天过得怎么样？"]
    assert 600 <= window.message_timer.intervals[1] <= 4000
    assert list(window.tts_queue) == ["你来啦！", "我等你好久了，今天过得怎么样？"]


def test_the_last_line_arrives_when_the_stream_ends(window):
    window.on_reply_delta("第一条\n最后一条")
    window.message_timer.fire(window)
    window.stream_done = True
    window.queue_messages(window.message_splitter.finish())
    window.message_timer.fire(window)

    assert shown(window) == ["第一条", "最后一条"]


def test_busy_routine_delays_the_first_message_and_says_so(window):
    window.config.daily_schedule = True
    window.local_now = None
    window.current_block = Mock(return_value=block_at(CHILDHOOD_FRIEND.schedule, NOW.replace(hour=10)))

    window.on_reply_delta("在上课呢\n")

    assert 4000 <= window.message_timer.intervals[0] <= 15000
    window.set_status.assert_called_with("In class…")
    window.chat_panel.show_typing.assert_called()


def test_annoyed_companion_types_slower(window):
    from dataclasses import replace

    from companion.core.state import Feeling

    state = fresh_state(NOW)
    window.companion_state = replace(state, feelings={**state.feelings, "anger": Feeling(0.6, NOW)})

    assert window.typing_slowness() == 1.4
    window.companion_state = fresh_state(NOW)
    assert window.typing_slowness() == 1.0


def test_pacing_off_keeps_the_streaming_bubble(window):
    window.config.reply_pacing = False
    window.render_reply = Mock()

    window.on_reply_delta("你好\n")

    window.render_reply.assert_called_once()
    assert window.message_timer.intervals == []


def test_speech_waits_for_the_message_when_pacing(window):
    window.on_reply_sentence("你好。")

    assert not window.tts_queue
