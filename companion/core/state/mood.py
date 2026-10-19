"""Mood arithmetic: reply emotions feed a mood that decays toward calm.

All functions are pure and take the time as an argument, so they are deterministic
in tests. Times must be timezone-aware.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from companion.core.chat.emotion import EMOTIONS

NEUTRAL = "neutral"
# A reply's emotion sets the mood to this strength, or pulls a matching mood toward 1.
REPLY_WEIGHT = 0.6
# A different emotion only replaces a mood weaker than REPLY_WEIGHT; a stronger one softens.
SOFTEN_FACTOR = 0.7
# Below this the mood counts as calm; at or above IDLE_THRESHOLD the idle face shows it.
FADE_FLOOR = 0.15
IDLE_THRESHOLD = 0.35
# After this long without a message from the user, a calm companion starts to miss them.
MISS_AFTER = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class Mood:
    emotion: str
    intensity: float
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CompanionState:
    mood: Mood
    last_user_message: datetime | None = None
    # What the companion is doing right now and how available it is (free, busy, drowsy,
    # asleep), both taken from the daily schedule; not persisted.
    activity: str = ""
    availability: str = ""


def _calm(now: datetime) -> Mood:
    return Mood(NEUTRAL, 0.0, now)


def _decayed(mood: Mood, now: datetime, half_life: timedelta) -> Mood:
    if mood.emotion == NEUTRAL or mood.intensity <= 0:
        return _calm(now)
    elapsed = max((now - mood.updated_at).total_seconds(), 0.0)
    seconds = max(half_life.total_seconds(), 1.0)
    intensity = mood.intensity * 0.5 ** (elapsed / seconds)
    return Mood(mood.emotion, intensity, now) if intensity >= FADE_FLOOR else _calm(now)


def current_mood(state: CompanionState, now: datetime, half_life: timedelta) -> Mood:
    """The mood right now, including missing the user after a long silence."""
    mood = _decayed(state.mood, now, half_life)
    if mood.intensity < IDLE_THRESHOLD and state.last_user_message is not None:
        absence = now - state.last_user_message
        if absence > MISS_AFTER:
            days = absence / timedelta(days=1)
            return Mood("sad", min(0.6, IDLE_THRESHOLD + 0.1 * days), now)
    return mood


def apply_reply_emotion(state: CompanionState, emotion: str, now: datetime, half_life: timedelta) -> CompanionState:
    """Fold the emotion tag of the companion's latest reply into its mood."""
    emotion = emotion if emotion in EMOTIONS else NEUTRAL
    mood = _decayed(state.mood, now, half_life)
    if emotion == NEUTRAL:
        intensity = mood.intensity * 0.5
        updated = Mood(mood.emotion, intensity, now) if intensity >= FADE_FLOOR else _calm(now)
    elif emotion == mood.emotion:
        updated = Mood(emotion, min(1.0, mood.intensity + REPLY_WEIGHT * (1 - mood.intensity)), now)
    elif mood.intensity > REPLY_WEIGHT:
        updated = Mood(mood.emotion, mood.intensity * SOFTEN_FACTOR, now)
    else:
        updated = Mood(emotion, REPLY_WEIGHT, now)
    return replace(state, mood=updated)


def record_user_message(state: CompanionState, now: datetime, half_life: timedelta) -> CompanionState:
    """Note the user's message, keeping the mood they come back to (e.g. having missed them)."""
    return replace(state, mood=current_mood(state, now, half_life), last_user_message=now)


def idle_emotion(state: CompanionState, now: datetime, half_life: timedelta) -> str | None:
    """The expression to hold while idle, or None for the default face."""
    mood = current_mood(state, now, half_life)
    return mood.emotion if mood.emotion != NEUTRAL and mood.intensity >= IDLE_THRESHOLD else None
