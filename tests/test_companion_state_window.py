"""Run the window's companion-state callbacks with Qt stand-ins (Qt is unavailable in CI)."""

import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_voice_input_qt_adapters import Signal, load_class

from companion.core import state as companion_state
from companion.core.persona import CHILDHOOD_FRIEND
from companion.core.schedule import block_at, presence_label
from companion.core.state import Appraisal, AppraisalEvent, Feeling, StateStore, current_feelings, fresh_state

NOW = datetime(2026, 10, 19, 20, 0, tzinfo=UTC)
BASE = timedelta(hours=2)


def feelings(window):
    return current_feelings(window.companion_state, window.clock(), CHILDHOOD_FRIEND.traits, BASE)


def with_feeling(name, value):
    state = fresh_state(NOW)
    return replace(state, feelings={**state.feelings, name: Feeling(value, NOW)})


@pytest.fixture
def window(tmp_path):
    clock = Mock(return_value=NOW)
    thread = Mock(started=Signal(), finished=Signal())
    worker = Mock(finished=Signal())
    cls = load_class(
        "companion/ui/main_window.py", "CompanionWindow",
        QWidget=type("QWidget", (), {}), local_now=clock, timedelta=timedelta, replace=replace,
        apply_events=companion_state.apply_events, apply_reply_tag=companion_state.apply_reply_tag,
        record_user_message=companion_state.record_user_message, idle_emotion=companion_state.idle_emotion,
        render_state_context=companion_state.render_state_context, active_reasons=companion_state.active_reasons,
        state_summary_lines=companion_state.state_summary_lines, should_appraise=companion_state.should_appraise,
        enter_care_mode=companion_state.enter_care_mode, looks_distressed=companion_state.looks_distressed,
        block_at=block_at, presence_label=presence_label,
        QThread=Mock(return_value=thread), AppraisalWorker=Mock(return_value=worker),
    )
    instance = cls.__new__(cls)
    instance.clock = clock
    instance.thread, instance.worker, instance.worker_class = thread, worker, cls
    instance.config = SimpleNamespace(
        companion_state=True, mood_half_life_minutes=120, daily_schedule=False, emotion_appraisal=True, api_key="k",
    )
    instance.persona = CHILDHOOD_FRIEND
    instance.presence_label = Mock()
    instance.state_store = StateStore(tmp_path / "state.json")
    instance.companion_state = fresh_state(NOW)
    instance.idle_face = None
    instance.renderer_ready = True
    instance.closing = False
    instance.client = Mock()
    instance.emotion_rng = random.Random(3)
    instance.appraisal_thread = instance.appraisal_worker = None
    instance.bridge = SimpleNamespace(setIdleEmotion=Signal())
    return instance


def test_state_context_is_empty_when_the_feature_is_off(window):
    window.companion_state = None

    assert window.state_context() == ""


def test_state_context_describes_the_dominant_feeling(window):
    window.companion_state = with_feeling("joy", 0.8)

    assert "very happy" in window.state_context()


def test_reply_tag_nudges_feelings_and_saves(window):
    window.reply_emotion = "happy"

    window.record_reply_mood()

    assert feelings(window)["joy"] == pytest.approx(0.08)
    assert window.state_store.load(now=NOW).feelings["joy"].value == pytest.approx(0.08)


def test_user_message_time_is_recorded(window):
    window.record_user_activity()

    assert window.companion_state.last_user_message == NOW
    assert window.state_store.load(now=NOW).last_user_message == NOW


def test_idle_face_follows_the_dominant_feeling_and_clears_as_it_fades(window):
    window.companion_state = with_feeling("jealousy", 0.7)
    window.refresh_idle_emotion()
    window.refresh_idle_emotion()
    window.clock.return_value = NOW + timedelta(hours=8)
    window.refresh_idle_emotion()

    assert window.bridge.setIdleEmotion.values == [("angry",), ("",)]


def test_idle_face_waits_for_the_renderer(window):
    window.renderer_ready = False
    window.companion_state = with_feeling("joy", 0.8)

    window.refresh_idle_emotion()

    assert window.bridge.setIdleEmotion.values == []


def test_emotional_turn_starts_one_appraisal(window):
    window.start_appraisal_worker("今天新来的女同学好漂亮", "是吗")
    window.start_appraisal_worker("对不起", "哼")

    assert window.appraisal_thread is window.thread
    window.thread.start.assert_called_once()


@pytest.mark.parametrize("change", [
    {"emotion_appraisal": False}, {"api_key": ""},
])
def test_appraisal_needs_the_setting_and_a_key(window, change):
    for key, value in change.items():
        setattr(window.config, key, value)

    window.start_appraisal_worker("你好可爱", "嘿嘿")

    assert window.appraisal_thread is None


def test_small_talk_is_not_appraised(window):
    window.start_appraisal_worker("今天天气不错", "是呀")

    assert window.appraisal_thread is None


def test_appraisal_result_moves_feelings_with_the_persona_traits(window):
    appraisal = Appraisal((AppraisalEvent("rival", 1.0, "he said the new girl is pretty"),))

    window.on_appraisal_ready(appraisal)

    assert feelings(window)["jealousy"] > 0.3
    assert "he said the new girl is pretty" in window.state_viewer_text()
    assert window.bridge.setIdleEmotion.values == [("angry",)]


def test_distress_in_the_appraisal_turns_on_care_first(window):
    window.companion_state = with_feeling("anger", 0.6)

    window.on_appraisal_ready(Appraisal((), user_distress=0.9))

    assert "comfort them first" in window.state_context()


def test_failed_or_late_appraisals_change_nothing(window):
    before = window.companion_state
    window.on_appraisal_ready(None)
    window.closing = True
    window.on_appraisal_ready(Appraisal((AppraisalEvent("praise", 1.0),)))

    assert window.companion_state is before


def test_feature_off_never_touches_the_store(window, tmp_path):
    window.companion_state = None
    window.reply_emotion = "happy"

    window.record_reply_mood()
    window.record_user_activity()
    window.refresh_idle_emotion()
    window.start_appraisal_worker("你好可爱", "嘿嘿")
    window.on_appraisal_ready(Appraisal((AppraisalEvent("praise", 1.0),)))

    assert not (tmp_path / "state.json").exists()
    assert window.bridge.setIdleEmotion.values == []
    assert window.appraisal_thread is None


def test_save_failure_keeps_the_state_in_memory(window):
    window.state_store = Mock(save=Mock(side_effect=OSError("disk full")))
    window.reply_emotion = "happy"

    window.record_reply_mood()

    assert feelings(window)["joy"] > 0


def test_state_viewer_text(window):
    window.companion_state = replace(with_feeling("joy", 0.8), last_user_message=NOW - timedelta(minutes=5))

    text = window.state_viewer_text()

    assert "Happy: 80%" in text
    assert "Your last message: 5 minutes ago" in text
    window.companion_state = None
    assert "turned off" in window.state_viewer_text()


def test_routine_adds_the_current_activity_and_availability(window):
    window.config.daily_schedule = True
    window.clock.return_value = NOW.replace(hour=3)

    text = window.state_context()

    assert "Right now you are sleeping." in text
    assert "woke you" in text
    assert "Doing: sleeping" in window.state_viewer_text()


def test_routine_off_adds_no_activity(window):
    window.clock.return_value = NOW.replace(hour=3)

    assert "Right now" not in window.state_context()


def test_presence_label_follows_the_routine(window):
    window.config.daily_schedule = True
    window.clock.return_value = NOW.replace(hour=20)
    window.refresh_presence()
    window.presence_label.setText.assert_called_with("● Watching a drama or playing games")

    window.config.daily_schedule = False
    window.refresh_presence()
    window.presence_label.setVisible.assert_called_with(False)


def test_is_awake_uses_the_persona_routine(window):
    assert not window.is_awake(NOW.replace(hour=3))
    assert window.is_awake(NOW.replace(hour=10))


def test_the_reply_to_a_distress_message_is_already_caring(window):
    from companion.core.state.render import CARE_FIRST, STRONG_LINE

    window.companion_state = with_feeling("jealousy", 0.75)
    assert STRONG_LINE in window.state_context()

    window.precheck_distress("我今天被老板骂了，好难过")
    context = window.state_context()

    assert CARE_FIRST in context
    assert STRONG_LINE not in context
    assert feelings(window)["jealousy"] == pytest.approx(0.375)


def test_ordinary_messages_do_not_trigger_care_first(window):
    window.companion_state = with_feeling("anger", 0.75)

    window.precheck_distress("今天天气不错")

    assert "comfort them first" not in window.state_context()
