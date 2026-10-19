"""The companion's own state: a mood that carries over between replies and fades with time."""

from .mood import (
    IDLE_THRESHOLD,
    CompanionState,
    Mood,
    apply_reply_emotion,
    current_mood,
    idle_emotion,
    record_user_message,
)
from .render import MAX_CONTEXT_CHARS, render_state_context, state_summary_lines
from .store import StateStore

__all__ = [
    "IDLE_THRESHOLD",
    "MAX_CONTEXT_CHARS",
    "CompanionState",
    "Mood",
    "StateStore",
    "apply_reply_emotion",
    "current_mood",
    "idle_emotion",
    "record_user_message",
    "render_state_context",
    "state_summary_lines",
]
