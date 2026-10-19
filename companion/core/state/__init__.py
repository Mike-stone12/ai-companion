"""The companion's own state: feelings with reasons, the day's mood, and the relationship.

See model.py for the rules, appraisal.py for the LLM's part, traits.py for the
personality parameters, render.py for the chat context, and store.py for state.json.
"""

from .appraisal import Appraisal, appraise, parse_appraisal, should_appraise
from .model import (
    EMOTION_NAMES,
    EVENT_TYPES,
    IDLE_THRESHOLD,
    AppraisalEvent,
    CompanionState,
    Feeling,
    Mood,
    Reason,
    Relationship,
    active_reasons,
    apply_events,
    apply_reply_tag,
    current_feelings,
    current_mood,
    dominant,
    fresh_state,
    idle_emotion,
    record_user_message,
)
from .render import MAX_CONTEXT_CHARS, render_state_context, state_summary_lines
from .store import StateStore
from .traits import DEFAULT_TRAITS, STYLES, TRAIT_NAMES, Traits

__all__ = [
    "DEFAULT_TRAITS",
    "EMOTION_NAMES",
    "EVENT_TYPES",
    "IDLE_THRESHOLD",
    "MAX_CONTEXT_CHARS",
    "STYLES",
    "TRAIT_NAMES",
    "Appraisal",
    "AppraisalEvent",
    "CompanionState",
    "Feeling",
    "Mood",
    "Reason",
    "Relationship",
    "StateStore",
    "Traits",
    "active_reasons",
    "appraise",
    "apply_events",
    "apply_reply_tag",
    "current_feelings",
    "current_mood",
    "dominant",
    "fresh_state",
    "idle_emotion",
    "parse_appraisal",
    "record_user_message",
    "render_state_context",
    "should_appraise",
    "state_summary_lines",
]
