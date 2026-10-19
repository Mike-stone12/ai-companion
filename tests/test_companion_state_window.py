"""Run the window's companion-state callbacks with Qt stand-ins (Qt is unavailable in CI)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_voice_input_qt_adapters import Signal, load_class

from companion.core import state as companion_state
from companion.core.state import CompanionState, Mood, StateStore

NOW = datetime(2026, 10, 19, 20, 0, tzinfo=UTC)


@pytest.fixture
def window(tmp_path):
    clock = Mock(return_value=NOW)
    cls = load_class(
        "companion/ui/main_window.py", "CompanionWindow",
        QWidget=type("QWidget", (), {}), local_now=clock, timedelta=timedelta,
        apply_reply_emotion=companion_state.apply_reply_emotion,
        record_user_message=companion_state.record_user_message,
        idle_emotion=companion_state.idle_emotion,
        render_state_context=companion_state.render_state_context,
        state_summary_lines=companion_state.state_summary_lines,
    )
    instance = cls.__new__(cls)
    instance.clock = clock
    instance.config = SimpleNamespace(companion_state=True, mood_half_life_minutes=120)
    instance.state_store = StateStore(tmp_path / "state.json")
    instance.companion_state = CompanionState(Mood("neutral", 0.0, NOW))
    instance.idle_face = None
    instance.renderer_ready = True
    instance.bridge = SimpleNamespace(setIdleEmotion=Signal())
    return instance


def test_state_context_is_empty_when_the_feature_is_off(window):
    window.companion_state = None

    assert window.state_context() == ""


def test_state_context_describes_the_current_mood(window):
    window.companion_state = CompanionState(Mood("happy", 0.8, NOW))

    assert "very happy" in window.state_context()


def test_reply_emotion_updates_and_saves_the_mood_and_idle_face(window):
    window.reply_emotion = "shy"

    window.record_reply_mood()

    assert window.companion_state.mood.emotion == "shy"
    assert window.state_store.load().mood.emotion == "shy"
    assert window.bridge.setIdleEmotion.values == [("shy",)]


def test_missing_reply_emotion_counts_as_neutral(window):
    window.companion_state = CompanionState(Mood("sad", 0.6, NOW))
    window.reply_emotion = None

    window.record_reply_mood()

    assert window.companion_state.mood.intensity == pytest.approx(0.3)


def test_user_message_time_is_recorded(window):
    window.record_user_activity()

    assert window.companion_state.last_user_message == NOW
    assert window.state_store.load().last_user_message == NOW


def test_idle_face_is_sent_only_when_it_changes_and_clears_as_the_mood_fades(window):
    window.companion_state = CompanionState(Mood("happy", 0.8, NOW))
    window.refresh_idle_emotion()
    window.refresh_idle_emotion()
    window.clock.return_value = NOW + timedelta(hours=4)
    window.refresh_idle_emotion()

    assert window.bridge.setIdleEmotion.values == [("happy",), ("",)]


def test_idle_face_waits_for_the_renderer(window):
    window.renderer_ready = False
    window.companion_state = CompanionState(Mood("happy", 0.8, NOW))

    window.refresh_idle_emotion()

    assert window.bridge.setIdleEmotion.values == []


def test_feature_off_never_touches_the_store(window, tmp_path):
    window.companion_state = None
    window.reply_emotion = "happy"

    window.record_reply_mood()
    window.record_user_activity()
    window.refresh_idle_emotion()

    assert not (tmp_path / "state.json").exists()
    assert window.bridge.setIdleEmotion.values == []


def test_save_failure_keeps_the_state_in_memory(window):
    window.state_store = Mock(save=Mock(side_effect=OSError("disk full")))
    window.reply_emotion = "happy"

    window.record_reply_mood()

    assert window.companion_state.mood.emotion == "happy"


def test_state_viewer_text(window):
    window.companion_state = CompanionState(Mood("happy", 0.8, NOW), NOW - timedelta(minutes=5))

    assert window.state_viewer_text() == "Mood: very happy (80%)\nYour last message: 5 minutes ago"
    window.companion_state = None
    assert "turned off" in window.state_viewer_text()
