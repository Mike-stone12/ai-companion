"""Describe the companion's state for the chat context, in a bounded number of characters."""

from __future__ import annotations

from datetime import datetime, timedelta

from .mood import IDLE_THRESHOLD, MISS_AFTER, NEUTRAL, CompanionState, current_mood

MAX_CONTEXT_CHARS = 300
MAX_ACTIVITY_CHARS = 80
HEADER = "Your current state (let it color your reply naturally; never report it like a status):"

ADJECTIVES = {
    "happy": "happy",
    "sad": "down",
    "angry": "annoyed",
    "surprised": "surprised",
    "shy": "shy and flustered",
    "confused": "puzzled",
    "awkward": "awkward",
}


def describe_mood(emotion: str, intensity: float) -> str:
    if emotion == NEUTRAL or intensity <= 0:
        return "calm"
    degree = "slightly" if intensity < IDLE_THRESHOLD else "fairly" if intensity < 0.7 else "very"
    return f"{degree} {ADJECTIVES.get(emotion, emotion)}"


def _ago(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    return f"{hours // 24} days ago"


def state_summary_lines(state: CompanionState, now: datetime, half_life: timedelta) -> list[str]:
    """Plain lines for the state viewer in the UI."""
    mood = current_mood(state, now, half_life)
    lines = [f"Mood: {describe_mood(mood.emotion, mood.intensity)} ({round(mood.intensity * 100)}%)"]
    if state.activity:
        lines.append(f"Doing: {state.activity}")
    last = _ago(now - state.last_user_message) if state.last_user_message else "none yet"
    lines.append(f"Your last message: {last}")
    return lines


def render_state_context(state: CompanionState, now: datetime, half_life: timedelta) -> str:
    mood = current_mood(state, now, half_life)
    parts = [HEADER, f"You feel {describe_mood(mood.emotion, mood.intensity)}."]
    activity = " ".join(state.activity.split())[:MAX_ACTIVITY_CHARS]
    if activity:
        parts.append(f"Right now you are {activity}.")
    if state.last_user_message is None:
        parts.append("This is the first time you are talking with the user.")
    else:
        absence = now - state.last_user_message
        line = f"The user last wrote to you {_ago(absence)}."
        if absence > MISS_AFTER:
            line += " You missed them and feel a little neglected, but you are glad they are back."
        parts.append(line)
    return " ".join(parts)[:MAX_CONTEXT_CHARS]
