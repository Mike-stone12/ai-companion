"""Describe the companion's state for the chat context, in a bounded number of characters.

The description turns feelings into behaviour: how strong the dominant feeling is
picks a tier (a hint / clearly shown / wants to be coaxed), the personality's style
and candor pick how it comes out, and guardrails keep it from turning into
manipulation or from ignoring a user who is genuinely upset.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .model import (
    EMOTION_NAMES,
    FADE_FLOOR,
    IDLE_THRESHOLD,
    NEGATIVE,
    CompanionState,
    active_reasons,
    current_feelings,
    day_mood,
    dominant,
    in_care_mode,
)
from .traits import Traits

MAX_CONTEXT_CHARS = 700
MAX_ACTIVITY_CHARS = 80
STRONG = 0.65
HEADER = "Your current state (let it color your reply naturally; never report it like a status):"

LABELS = {
    "joy": "happy",
    "anger": "annoyed",
    "hurt": "hurt",
    "jealousy": "jealous",
    "longing": "like you missed the user",
}
AVAILABILITY_HINTS = {
    "asleep": "You were asleep and this message woke you: reply groggily in a few words, then drift back to sleep.",
    "drowsy": "It is late and you are sleepy: keep it short and let it show.",
    "busy": "You are in the middle of something, so keep replies brief.",
}
MODERATE_STYLE = {
    "direct": "Tell the user plainly what bothers you.",
    "sarcastic": "Let it out with a little sarcasm.",
    "cold": "Be a bit curt and distant.",
    "pouty": "Sulk and complain about it cutely.",
}
MILD = "Only let it slip in a word or a tone; do not say it outright."
STRONG_LINE = "Keep replies short and cool; you want the user to make it up to you, and a real apology works."
TSUNDERE = "Outwardly you deny feeling it, even though you do."
CARE_FIRST = "The user seems genuinely upset right now: set your own feelings aside and comfort them first."
GUARDRAIL = (
    "Never threaten to leave, guilt-trip the user, or ask them to spend time only with you; "
    "let it go once they make it up to you."
)


def describe(name: str, value: float) -> str:
    degree = "slightly" if value < IDLE_THRESHOLD else "fairly" if value < 0.7 else "very"
    return f"{degree} {LABELS[name]}"


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


def _closeness(value: float) -> str:
    if value >= 0.8:
        return "You two are very close; you can joke freely."
    if value >= 0.5:
        return "You two are close."
    return "You are still finding your way back to being close."


def _guidance(name: str, value: float, traits: Traits) -> list[str]:
    if name not in NEGATIVE:
        return []
    lines = [MILD if value < IDLE_THRESHOLD else STRONG_LINE if value >= STRONG else MODERATE_STYLE[traits.style]]
    if traits.candor < 0.4 and name in {"jealousy", "hurt"}:
        lines.append(TSUNDERE)
    return lines


def render_state_context(state: CompanionState, now: datetime, traits: Traits, base: timedelta) -> str:
    values = current_feelings(state, now, traits, base)
    reasons = active_reasons(state, now, traits, base)
    name, value = dominant(state, now, traits, base)
    parts = [HEADER]
    if name is None:
        parts.append("You feel calm.")
    else:
        feeling = f"You feel {describe(name, value)}"
        if reasons.get(name):
            feeling += f" (because {'; '.join(reasons[name][-2:])})"
        second = max((n for n in EMOTION_NAMES if n != name), key=lambda n: values[n])
        if values[second] >= 0.3:
            feeling += f", and {describe(second, values[second])}"
        parts.append(feeling + ".")
    if in_care_mode(state, now):
        parts.append(CARE_FIRST)
    elif name is not None:
        parts.extend(_guidance(name, value, traits))
    if any(values[n] >= FADE_FLOOR for n in NEGATIVE):
        parts.append(GUARDRAIL)
    activity = " ".join(state.activity.split())[:MAX_ACTIVITY_CHARS]
    if activity:
        parts.append(f"Right now you are {activity}.")
    hint = AVAILABILITY_HINTS.get(state.availability)
    if hint:
        parts.append(hint)
    if state.last_user_message is None:
        parts.append("This is the first time you are talking with the user.")
    else:
        parts.append(f"The user last wrote to you {_ago(now - state.last_user_message)}.")
    mood = day_mood(state, now)
    if mood >= 0.3:
        parts.append("Overall it has been a good day for you.")
    elif mood <= -0.3:
        parts.append("Overall today has felt a bit rough.")
    parts.append(_closeness(state.relationship.closeness))
    return " ".join(parts)[:MAX_CONTEXT_CHARS]


def state_summary_lines(state: CompanionState, now: datetime, traits: Traits, base: timedelta) -> list[str]:
    """Plain lines for the Companion state viewer."""
    values = current_feelings(state, now, traits, base)
    reasons = active_reasons(state, now, traits, base)
    lines = []
    for name in EMOTION_NAMES:
        line = f"{LABELS[name].capitalize()}: {round(values[name] * 100)}%"
        if reasons.get(name):
            line += f" — {'; '.join(reasons[name])}"
        lines.append(line)
    if in_care_mode(state, now):
        lines.append("Care first: comforting the user")
    mood = day_mood(state, now)
    lines.append(f"Today: {'good' if mood >= 0.3 else 'rough' if mood <= -0.3 else 'so-so'} ({mood:+.2f})")
    lines.append(
        f"Closeness: {round(state.relationship.closeness * 100)}%, trust: {round(state.relationship.trust * 100)}%"
    )
    if state.activity:
        lines.append(f"Doing: {state.activity}")
    last = _ago(now - state.last_user_message) if state.last_user_message else "none yet"
    lines.append(f"Your last message: {last}")
    if state.changes:
        lines.append("Recent changes:")
        for change in state.changes[-5:]:
            stamp = change.at.astimezone().strftime("%m-%d %H:%M")
            cause = f" ({change.cause})" if change.cause else ""
            lines.append(f"  {stamp} {change.emotion} {change.delta:+.2f}{cause}")
    return lines
