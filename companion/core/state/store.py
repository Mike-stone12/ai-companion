"""Persist the companion state in state.json; unreadable data starts a fresh, calm state."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from companion.core import settings_file
from companion.core.chat.emotion import EMOTIONS

from .mood import NEUTRAL, CompanionState, Mood
from .render import MAX_ACTIVITY_CHARS

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


def _aware(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be text")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def _parse(data: dict) -> CompanionState:
    raw_mood = data.get("mood")
    if not isinstance(raw_mood, dict):
        raise ValueError("mood must be an object")
    intensity = raw_mood.get("intensity")
    if isinstance(intensity, bool) or not isinstance(intensity, (int, float)):
        raise ValueError("intensity must be a number")
    emotion = raw_mood.get("emotion")
    mood = Mood(
        emotion if emotion in EMOTIONS else NEUTRAL,
        min(max(float(intensity), 0.0), 1.0),
        _aware(raw_mood.get("updated_at")),
    )
    last = data.get("last_user_message")
    activity = data.get("activity")
    return CompanionState(
        mood=mood,
        last_user_message=_aware(last) if last is not None else None,
        activity=activity[:MAX_ACTIVITY_CHARS] if isinstance(activity, str) else "",
    )


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self, now: datetime | None = None) -> CompanionState:
        now = now or datetime.now(UTC)
        data = settings_file.load_settings(self.path)
        if data:
            try:
                return _parse(data)
            except ValueError as exc:
                logger.warning("Ignoring unreadable companion state %s: %s", self.path, exc)
        return CompanionState(Mood(NEUTRAL, 0.0, now))

    def save(self, state: CompanionState) -> None:
        settings_file.save_settings(self.path, {
            "version": SCHEMA_VERSION,
            "mood": {
                "emotion": state.mood.emotion,
                "intensity": round(state.mood.intensity, 4),
                "updated_at": state.mood.updated_at.isoformat(),
            },
            "last_user_message": state.last_user_message.isoformat() if state.last_user_message else None,
            "activity": state.activity,
        })
