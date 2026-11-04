"""Persist the companion state in state.json; unreadable data starts a fresh, calm state.

Version 2 holds the multi-feeling model. Version 1 files (a single mood from the
first state release) are migrated on load: the mood becomes the matching feeling.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from companion.core import settings_file

from .model import (
    CAPS,
    EMOTION_NAMES,
    MAX_CHANGES,
    MAX_REASON_CHARS,
    MAX_REASONS,
    Change,
    CompanionState,
    Feeling,
    Reason,
    Relationship,
    fresh_state,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2
V1_TAGS = {"happy": "joy", "shy": "joy", "sad": "hurt", "angry": "anger"}


def _aware(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be text")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def _optional_time(value: object) -> datetime | None:
    return None if value is None else _aware(value)


def _unit(value: object, high: float = 1.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected a number")
    return min(max(float(value), 0.0), high)


def _text(value: object) -> str:
    return value[:MAX_REASON_CHARS] if isinstance(value, str) else ""


def _parse_v2(data: dict, now: datetime) -> CompanionState:
    raw = data.get("feelings")
    if not isinstance(raw, dict):
        raise ValueError("feelings must be an object")
    feelings = {}
    for name in EMOTION_NAMES:
        item = raw.get(name)
        if not isinstance(item, dict):
            feelings[name] = Feeling(0.0, now)
            continue
        reasons = tuple(
            Reason(_text(reason.get("text")), _aware(reason.get("at")))
            for reason in item.get("reasons", [])[:MAX_REASONS]
            if isinstance(reason, dict) and _text(reason.get("text"))
        )
        feelings[name] = Feeling(_unit(item.get("value"), CAPS.get(name, 1.0)), _aware(item.get("updated_at")), reasons)
    relationship = data.get("relationship") or {}
    if not isinstance(relationship, dict):
        raise ValueError("relationship must be an object")
    changes = tuple(
        Change(_aware(item.get("at")), item["emotion"], float(item.get("delta", 0)), _text(item.get("cause")))
        for item in data.get("changes", [])[-MAX_CHANGES:]
        if isinstance(item, dict) and item.get("emotion") in EMOTION_NAMES
        and isinstance(item.get("delta", 0), (int, float))
    )
    day = data.get("day_mood", 0.0)
    if isinstance(day, bool) or not isinstance(day, (int, float)):
        raise ValueError("day_mood must be a number")
    return CompanionState(
        feelings=feelings,
        last_user_message=_optional_time(data.get("last_user_message")),
        relationship=Relationship(
            _unit(relationship.get("closeness", 0.6)), _unit(relationship.get("trust", 0.6)),
        ),
        changes=changes,
        care_until=_optional_time(data.get("care_until")),
        day_mood=min(max(float(day), -1.0), 1.0),
        day_mood_at=_optional_time(data.get("day_mood_at")),
    )


def _parse_v1(data: dict, now: datetime) -> CompanionState:
    state = fresh_state(now)
    mood = data.get("mood")
    if not isinstance(mood, dict):
        raise ValueError("mood must be an object")
    name = V1_TAGS.get(mood.get("emotion"))
    feelings = dict(state.feelings)
    if name:
        feelings[name] = Feeling(_unit(mood.get("intensity"), CAPS.get(name, 1.0)), _aware(mood.get("updated_at")))
    return CompanionState(feelings=feelings, last_user_message=_optional_time(data.get("last_user_message")))


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self, now: datetime | None = None) -> CompanionState:
        now = now or datetime.now(UTC)
        data = settings_file.load_settings(self.path)
        if data:
            try:
                return _parse_v2(data, now) if data.get("version") == SCHEMA_VERSION else _parse_v1(data, now)
            except (ValueError, TypeError, KeyError) as exc:
                logger.warning("Ignoring unreadable companion state %s: %s", self.path, exc)
        return fresh_state(now)

    def save(self, state: CompanionState) -> None:
        def stamp(value: datetime | None) -> str | None:
            return value.isoformat() if value else None

        settings_file.save_settings(self.path, {
            "version": SCHEMA_VERSION,
            "feelings": {
                name: {
                    "value": round(feeling.value, 4),
                    "updated_at": feeling.updated_at.isoformat(),
                    "reasons": [{"text": reason.text, "at": reason.at.isoformat()} for reason in feeling.reasons],
                }
                for name, feeling in state.feelings.items()
            },
            "last_user_message": stamp(state.last_user_message),
            "relationship": {
                "closeness": round(state.relationship.closeness, 4),
                "trust": round(state.relationship.trust, 4),
            },
            "changes": [
                {"at": change.at.isoformat(), "emotion": change.emotion, "delta": change.delta, "cause": change.cause}
                for change in state.changes
            ],
            "care_until": stamp(state.care_until),
            "day_mood": round(state.day_mood, 4),
            "day_mood_at": stamp(state.day_mood_at),
        })
