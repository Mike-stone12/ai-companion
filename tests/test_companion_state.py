"""The companion's own state: mood that decays over time, absence, and the prompt summary."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from companion.core.state import (
    MAX_CONTEXT_CHARS,
    CompanionState,
    Mood,
    StateStore,
    apply_reply_emotion,
    current_mood,
    idle_emotion,
    record_user_message,
    render_state_context,
)

NOW = datetime(2026, 10, 19, 20, 0, tzinfo=UTC)
HALF_LIFE = timedelta(hours=2)


def state(emotion="neutral", intensity=0.0, minutes_ago=0, last_user=None):
    return CompanionState(
        mood=Mood(emotion, intensity, NOW - timedelta(minutes=minutes_ago)),
        last_user_message=last_user,
    )


def test_mood_halves_after_one_half_life():
    mood = current_mood(state("happy", 0.8, minutes_ago=120), NOW, HALF_LIFE)

    assert mood.emotion == "happy"
    assert mood.intensity == pytest.approx(0.4)


def test_faded_mood_returns_to_calm():
    mood = current_mood(state("angry", 0.6, minutes_ago=600), NOW, HALF_LIFE)

    assert mood.emotion == "neutral"
    assert mood.intensity == 0.0


def test_reply_emotion_sets_a_new_mood():
    updated = apply_reply_emotion(state(), "happy", NOW, HALF_LIFE)

    assert updated.mood.emotion == "happy"
    assert 0.5 <= updated.mood.intensity <= 0.7
    assert updated.mood.updated_at == NOW


def test_repeating_an_emotion_strengthens_it():
    once = apply_reply_emotion(state(), "sad", NOW, HALF_LIFE)
    twice = apply_reply_emotion(once, "sad", NOW, HALF_LIFE)

    assert twice.mood.intensity > once.mood.intensity
    assert twice.mood.intensity <= 1.0


def test_a_strong_mood_is_not_wiped_by_one_different_reply():
    upset = state("angry", 0.9)

    updated = apply_reply_emotion(upset, "happy", NOW, HALF_LIFE)

    # A cheerful line while still upset softens the mood instead of flipping it at once.
    assert updated.mood.emotion == "angry"
    assert updated.mood.intensity < 0.9


def test_neutral_reply_calms_the_mood_down():
    updated = apply_reply_emotion(state("sad", 0.6), "neutral", NOW, HALF_LIFE)

    assert updated.mood.emotion == "sad"
    assert updated.mood.intensity == pytest.approx(0.3)


def test_unknown_emotion_is_treated_as_neutral():
    updated = apply_reply_emotion(state("happy", 0.6), "ecstatic!!", NOW, HALF_LIFE)

    assert updated.mood.emotion == "happy"
    assert updated.mood.intensity == pytest.approx(0.3)


def test_long_absence_turns_a_calm_mood_into_missing_the_user():
    absent = state(last_user=NOW - timedelta(days=2))

    mood = current_mood(absent, NOW, HALF_LIFE)

    assert mood.emotion == "sad"
    assert mood.intensity > 0


def test_a_live_mood_wins_over_missing_the_user():
    absent = state("happy", 0.9, last_user=NOW - timedelta(days=2))

    assert current_mood(absent, NOW, HALF_LIFE).emotion == "happy"


def test_record_user_message_updates_the_timestamp_and_keeps_the_mood():
    before = state("happy", 0.5)

    after = record_user_message(before, NOW, HALF_LIFE)

    assert after.last_user_message == NOW
    assert after.mood == before.mood


def test_coming_back_after_a_long_absence_keeps_the_sulk_for_a_while():
    returned = record_user_message(state(last_user=NOW - timedelta(days=3)), NOW, HALF_LIFE)

    assert current_mood(returned, NOW, HALF_LIFE).emotion == "sad"
    assert current_mood(returned, NOW + timedelta(hours=1), HALF_LIFE).emotion == "sad"
    assert current_mood(returned, NOW + timedelta(hours=8), HALF_LIFE).emotion == "neutral"


def test_idle_emotion_follows_a_noticeable_mood_only():
    assert idle_emotion(state("shy", 0.7), NOW, HALF_LIFE) == "shy"
    assert idle_emotion(state("shy", 0.2), NOW, HALF_LIFE) is None
    assert idle_emotion(state(), NOW, HALF_LIFE) is None


def test_context_describes_mood_and_time_since_last_message():
    text = render_state_context(state("sad", 0.6, last_user=NOW - timedelta(hours=3)), NOW, HALF_LIFE)

    assert "fairly down" in text
    assert "3 hours ago" in text
    assert "first time" not in text
    assert len(text) <= MAX_CONTEXT_CHARS


def test_context_after_a_long_absence_mentions_missing_the_user():
    text = render_state_context(state(last_user=NOW - timedelta(days=3)), NOW, HALF_LIFE)

    assert "3 days ago" in text
    assert "missed" in text


def test_context_for_a_first_conversation():
    text = render_state_context(state(), NOW, HALF_LIFE)

    assert "calm" in text
    assert "first time" in text


def test_context_includes_the_current_activity_when_known():
    with_activity = CompanionState(Mood("neutral", 0.0, NOW), None, activity="watching a drama")

    assert "watching a drama" in render_state_context(with_activity, NOW, HALF_LIFE)


def test_context_is_capped_even_with_a_long_activity():
    long_activity = CompanionState(Mood("happy", 0.9, NOW), NOW, activity="x" * 1000)

    assert len(render_state_context(long_activity, NOW, HALF_LIFE)) <= MAX_CONTEXT_CHARS


def test_store_round_trip(tmp_path):
    store = StateStore(tmp_path / "state.json")
    original = CompanionState(Mood("happy", 0.5, NOW), NOW - timedelta(hours=1), activity="reading")

    store.save(original)

    assert store.load() == original
    saved = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert saved["version"] == 1


def test_missing_store_loads_a_fresh_calm_state(tmp_path):
    loaded = StateStore(tmp_path / "state.json").load(now=NOW)

    assert loaded.mood == Mood("neutral", 0.0, NOW)
    assert loaded.last_user_message is None


@pytest.mark.parametrize("content", [
    "{broken", "[]",
    '{"version": 1, "mood": {"emotion": "happy", "intensity": "lots", "updated_at": "x"}}',
    '{"version": 1, "mood": {"emotion": "happy", "intensity": 0.5, "updated_at": "2026-10-19T20:00:00"}}',
])
def test_corrupt_store_falls_back_to_a_fresh_state(tmp_path, content):
    path = tmp_path / "state.json"
    path.write_text(content, encoding="utf-8")

    assert StateStore(path).load(now=NOW).mood == Mood("neutral", 0.0, NOW)


def test_loaded_values_are_clamped(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "version": 1,
        "mood": {"emotion": "happy", "intensity": 7, "updated_at": NOW.isoformat()},
        "last_user_message": None,
        "activity": "y" * 500,
    }), encoding="utf-8")

    loaded = StateStore(path).load(now=NOW)

    assert loaded.mood.intensity == 1.0
    assert len(loaded.activity) <= 80


def test_chat_context_places_state_after_memory_and_before_the_summary():
    from companion.core.chat.summary import build_chat_messages

    turns = [{"role": "user", "content": "hi"}]
    messages = build_chat_messages("System", turns, memory_context="Memory", summary="Earlier", state_context="State")

    assert [message["content"] for message in messages] == [
        "System", "Memory", "State", "Conversation summary:\nEarlier", "hi",
    ]
    assert build_chat_messages("System", turns, state_context="  ") == [{"role": "system", "content": "System"}, *turns]


def test_summary_lines_for_the_state_viewer():
    from companion.core.state import state_summary_lines

    lines = state_summary_lines(
        CompanionState(Mood("happy", 0.8, NOW), NOW - timedelta(minutes=5), activity="reading"), NOW, HALF_LIFE,
    )

    assert lines == ["Mood: very happy (80%)", "Doing: reading", "Your last message: 5 minutes ago"]
    assert state_summary_lines(state(), NOW, HALF_LIFE)[-1] == "Your last message: none yet"


@pytest.mark.parametrize(("availability", "phrase"), [
    ("asleep", "woke you"),
    ("drowsy", "sleepy"),
    ("busy", "keep replies brief"),
])
def test_context_adds_a_hint_for_how_available_she_is(availability, phrase):
    awake_state = CompanionState(Mood("happy", 0.9, NOW), NOW - timedelta(days=3), "x" * 80, availability)

    text = render_state_context(awake_state, NOW, HALF_LIFE)

    assert phrase in text
    assert len(text) <= MAX_CONTEXT_CHARS


def test_free_availability_adds_no_hint():
    text = render_state_context(CompanionState(Mood("neutral", 0.0, NOW), None, "reading", "free"), NOW, HALF_LIFE)

    assert "Right now you are reading." in text
    assert "brief" not in text
