"""Run the window's diary and self-memory callbacks with Qt stand-ins (Qt is unavailable in CI)."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_voice_input_qt_adapters import Signal, load_class

import companion.core.state
from companion.core import diary
from companion.core.memory import self_memory
from companion.core.persona import CHILDHOOD_FRIEND
from companion.core.schedule import format_schedule
from companion.core.state import fresh_state
from companion.core.state.model import Change

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 19, 21, 0, tzinfo=TZ)
YESTERDAY = NOW - timedelta(days=1)


@pytest.fixture
def window(tmp_path):
    thread = Mock(started=Signal(), finished=Signal())
    worker = Mock(finished=Signal())
    cls = load_class(
        "companion/ui/main_window.py", "CompanionWindow",
        QWidget=type("QWidget", (), {}), local_now=Mock(return_value=NOW), OWN_CONTEXT_CHARS=600,
        DiaryEntry=diary.DiaryEntry, build_diary_messages=diary.build_diary_messages,
        day_to_write=diary.day_to_write, render_diary_context=diary.render_diary_context, turns_on=diary.turns_on,
        render_self_context=self_memory.render_self_context, should_extract_self=self_memory.should_extract_self,
        format_schedule=format_schedule, QThread=Mock(return_value=thread),
        DiaryWorker=Mock(return_value=worker), SelfMemoryWorker=Mock(return_value=worker),
    )
    instance = cls.__new__(cls)
    instance.thread, instance.worker = thread, worker
    instance.config = SimpleNamespace(api_key="k", daily_schedule=True)
    instance.persona = CHILDHOOD_FRIEND
    instance.client = Mock()
    instance.diary_store = diary.DiaryStore(tmp_path / "diary.json")
    instance.diary_entries = []
    instance.self_memory_store = SimpleNamespace(items=[], load=Mock())
    instance.diary_thread = instance.diary_worker = instance.diary_day = None
    instance.self_memory_thread = instance.self_memory_worker = None
    instance.history = SimpleNamespace(entries=[
        {"role": "user", "content": "今天新来的女同学好漂亮", "at": YESTERDAY.isoformat()},
        {"role": "assistant", "content": "[angry] 哼，关我什么事", "at": YESTERDAY.isoformat()},
        {"role": "user", "content": "早", "at": NOW.isoformat()},
    ])
    state = fresh_state(NOW)
    instance.companion_state = companion.core.state.CompanionState(
        feelings=state.feelings, changes=(Change(YESTERDAY, "jealousy", 0.4, "新来的女同学"),),
    )
    return instance


def test_yesterday_gets_a_diary_request_in_character(window):
    day, messages = window.diary_request()
    payload = json.loads(messages[1]["content"])

    assert day == YESTERDAY.date()
    assert messages[0]["content"].startswith(CHILDHOOD_FRIEND.system_prompt())
    assert payload["conversation"] == ["User: 今天新来的女同学好漂亮", "You: 哼，关我什么事"]
    assert payload["how_your_feelings_changed"] == ["jealousy +0.40 (新来的女同学)"]
    assert "08:30-12:00 [busy] in class" in payload["your_routine"]


def test_writing_and_saving_the_entry(window):
    window.maybe_write_diary()
    window.thread.start.assert_called_once()

    window.on_diary_ready("今天他夸别的女生，我有点不开心，不过晚上追剧追得很开心。")

    assert [entry.day for entry in window.diary_entries] == [YESTERDAY.date()]
    assert window.diary_store.load()[0].text.startswith("今天他夸别的女生")
    assert window.diary_request() is None


def test_no_key_or_feature_off_writes_nothing(window):
    window.config.api_key = ""
    window.maybe_write_diary()
    window.config.api_key = "k"
    window.diary_store = None
    window.maybe_write_diary()

    window.thread.start.assert_not_called()


def test_empty_diary_reply_is_not_saved(window):
    window.diary_day = YESTERDAY.date()
    window.on_diary_ready("")

    assert window.diary_store.load() == []


def test_own_context_combines_diary_and_self_memories(window):
    window.diary_entries = [diary.DiaryEntry(YESTERDAY.date(), "和他聊了新同学的事。", NOW)]
    window.self_memory_store.items = [
        {"summary": "我最喜欢草莓", "category": "preference", "updated_at": NOW.isoformat()},
    ]

    text = window.own_context("你最喜欢什么水果")

    assert "Your recent diary" in text and "和他聊了新同学的事。" in text
    assert "我最喜欢草莓" in text
    assert len(text) <= 600


def test_own_context_is_empty_when_off(window):
    window.diary_store = None

    assert window.own_context("x") == ""


def test_self_statements_start_one_extraction(window):
    window.start_self_memory_worker("你喜欢什么", "我最喜欢草莓啦")
    window.start_self_memory_worker("还有呢", "我也喜欢猫")

    window.thread.start.assert_called_once()


def test_ordinary_replies_are_not_extracted(window):
    window.start_self_memory_worker("你好", "你好呀，今天辛苦啦")

    window.thread.start.assert_not_called()


def test_new_self_memories_reload_the_store(window):
    window.on_self_memory_ready([{"summary": "我最喜欢草莓"}])

    window.self_memory_store.load.assert_called_once()
