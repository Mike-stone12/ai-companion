"""The companion's emotions: what happened (appraised events) -> how much it changes (rules).

An LLM judges *what happened* in a turn (see appraisal.py); the deterministic rules
here decide *how much* each emotion moves, scaled by personality traits and the
long-term relationship. Three time scales:

- feelings (joy, anger, hurt, jealousy, longing): minutes to hours, each with reasons;
- the day's mood: a slow average of the turns' emotional valence (8 h half-life);
- the relationship (closeness, trust): changes by a percent or so per turn.

Guardrails: anger is capped, one turn moves an emotion by at most MAX_STEP, and a
genuinely upset user switches the companion into care-first mode for a while.
All functions are pure and take the time (and any randomness) as arguments.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from .traits import Traits

EMOTION_NAMES = ("joy", "anger", "hurt", "jealousy", "longing")
NEGATIVE = frozenset({"anger", "hurt", "jealousy"})
# Avatar expressions (emotion tags in companion.json) used for each emotion.
EXPRESSIONS = {"joy": "happy", "anger": "angry", "hurt": "sad", "jealousy": "angry", "longing": "sad"}
CAPS = {"anger": 0.8}

# Below FADE_FLOOR a feeling is not noticeable (not described, no idle face); below
# PRUNE it is dropped. Between the two, small nudges can still add up.
FADE_FLOOR = 0.15
PRUNE = 0.02
IDLE_THRESHOLD = 0.35
MAX_STEP = 0.4
JITTER = 0.1
MAX_REASONS = 3
MAX_REASON_CHARS = 60
REASON_TTL = timedelta(days=3)
MAX_CHANGES = 8
DAY_MOOD_HALF_LIFE = timedelta(hours=8)
CARE_WINDOW = timedelta(minutes=30)
# Longing grows with silence: from nothing at 12 h to its maximum at 72 h.
LONGING_START = timedelta(hours=12)
LONGING_FULL = timedelta(hours=72)
LONGING_MAX = 0.8
# Coming back after this long leaves a little hurt ("you disappeared") along with the joy.
RETURN_SULK_AFTER = timedelta(hours=24)

EVENT_TYPES = (
    "praise", "affection", "rival", "perfunctory", "criticism", "tease", "apology", "care", "good_news",
)
# Base change per emotion for an event of intensity 1, before trait scaling and jitter.
EVENT_EFFECTS: dict[str, dict[str, float]] = {
    "praise": {"joy": 0.35, "hurt": -0.1},
    "affection": {"joy": 0.3, "longing": -0.3, "anger": -0.1},
    "rival": {"jealousy": 0.45, "anger": 0.1},
    "perfunctory": {"hurt": 0.25, "anger": 0.1},
    "criticism": {"hurt": 0.35, "anger": 0.25},
    "tease": {"joy": 0.1, "anger": 0.08},
    "care": {"hurt": -0.2, "longing": -0.2, "joy": 0.2, "anger": -0.1},
    "good_news": {"joy": 0.3},
}
# An apology that names the actual grievance helps far more than a generic "sorry".
TARGETED_APOLOGY = 0.45
GENERIC_APOLOGY = 0.12
RELATIONSHIP_EFFECTS = {
    "praise": (0.01, 0.0), "affection": (0.012, 0.005), "care": (0.012, 0.01), "apology": (0.005, 0.01),
    "good_news": (0.006, 0.004), "criticism": (-0.015, -0.01), "perfunctory": (-0.008, 0.0), "rival": (0.0, -0.005),
}
# The companion's own reply tag nudges its feelings a little, so words and state agree.
REPLY_TAG_NUDGES = {"happy": ("joy", 0.08), "shy": ("joy", 0.05), "sad": ("hurt", 0.05), "angry": ("anger", 0.05)}


@dataclass(frozen=True, slots=True)
class Reason:
    text: str
    at: datetime


@dataclass(frozen=True, slots=True)
class Feeling:
    value: float
    updated_at: datetime
    reasons: tuple[Reason, ...] = ()


@dataclass(frozen=True, slots=True)
class Relationship:
    closeness: float = 0.6
    trust: float = 0.6


@dataclass(frozen=True, slots=True)
class Change:
    at: datetime
    emotion: str
    delta: float
    cause: str


@dataclass(frozen=True, slots=True)
class AppraisalEvent:
    type: str
    intensity: float = 0.5
    reason: str = ""
    # For an apology: which emotions' grievances it addresses.
    targets: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Mood:
    """The dominant feeling as an avatar expression, for the idle face and simple callers."""

    emotion: str
    intensity: float


@dataclass(frozen=True)
class CompanionState:
    feelings: Mapping[str, Feeling] = field(default_factory=dict)
    last_user_message: datetime | None = None
    # From the daily schedule; not persisted.
    activity: str = ""
    availability: str = ""
    relationship: Relationship = Relationship()
    changes: tuple[Change, ...] = ()
    care_until: datetime | None = None
    day_mood: float = 0.0
    day_mood_at: datetime | None = None


def fresh_state(now: datetime) -> CompanionState:
    return CompanionState(feelings={name: Feeling(0.0, now) for name in EMOTION_NAMES})


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(max(value, low), high)


def half_life(name: str, traits: Traits, relationship: Relationship, base: timedelta) -> timedelta:
    """Negative feelings fade faster for a quick-to-recover companion who is close to the user."""
    if name in NEGATIVE:
        return base * (1.5 - traits.recovery) * (1.25 - 0.5 * relationship.closeness)
    return base


def _longing_from_absence(state: CompanionState, now: datetime) -> float:
    if state.last_user_message is None:
        return 0.0
    absence = now - state.last_user_message
    if absence <= LONGING_START:
        return 0.0
    progress = min((absence - LONGING_START) / (LONGING_FULL - LONGING_START), 1.0)
    return LONGING_MAX * progress * (0.6 + 0.4 * state.relationship.closeness)


def _settled(state: CompanionState, now: datetime, traits: Traits, base: timedelta) -> dict[str, Feeling]:
    """Each feeling decayed to ``now``, with stale reasons dropped."""
    settled = {}
    for name in EMOTION_NAMES:
        feeling = state.feelings.get(name) or Feeling(0.0, now)
        elapsed = max((now - feeling.updated_at).total_seconds(), 0.0)
        seconds = max(half_life(name, traits, state.relationship, base).total_seconds(), 1.0)
        value = feeling.value * 0.5 ** (elapsed / seconds)
        if name == "longing":
            value = max(value, _longing_from_absence(state, now))
        value = value if value >= PRUNE else 0.0
        reasons = tuple(reason for reason in feeling.reasons if now - reason.at < REASON_TTL) if value else ()
        settled[name] = Feeling(value, now, reasons)
    return settled


def current_feelings(state: CompanionState, now: datetime, traits: Traits, base: timedelta) -> dict[str, float]:
    return {name: feeling.value for name, feeling in _settled(state, now, traits, base).items()}


def active_reasons(state: CompanionState, now: datetime, traits: Traits, base: timedelta) -> dict[str, list[str]]:
    return {
        name: [reason.text for reason in feeling.reasons]
        for name, feeling in _settled(state, now, traits, base).items()
        if feeling.reasons and feeling.value >= FADE_FLOOR
    }


def dominant(state: CompanionState, now: datetime, traits: Traits, base: timedelta) -> tuple[str | None, float]:
    values = current_feelings(state, now, traits, base)
    name = max(EMOTION_NAMES, key=lambda emotion: values[emotion])
    return (name, values[name]) if values[name] >= FADE_FLOOR else (None, 0.0)


def current_mood(state: CompanionState, now: datetime, traits: Traits, base: timedelta) -> Mood:
    name, value = dominant(state, now, traits, base)
    return Mood(EXPRESSIONS[name], value) if name else Mood("neutral", 0.0)


def idle_emotion(state: CompanionState, now: datetime, traits: Traits, base: timedelta) -> str | None:
    mood = current_mood(state, now, traits, base)
    return mood.emotion if mood.intensity >= IDLE_THRESHOLD else None


def in_care_mode(state: CompanionState, now: datetime) -> bool:
    return state.care_until is not None and now < state.care_until


def day_mood(state: CompanionState, now: datetime) -> float:
    if state.day_mood_at is None:
        return 0.0
    elapsed = max((now - state.day_mood_at).total_seconds(), 0.0)
    return state.day_mood * 0.5 ** (elapsed / DAY_MOOD_HALF_LIFE.total_seconds())


def _scale(name: str, delta: float, traits: Traits, relationship: Relationship) -> float:
    """Personality turns a base change into this companion's change."""
    if delta < 0:
        return delta * (0.5 + traits.recovery) * (0.8 + 0.4 * relationship.closeness)
    if name == "anger":
        return delta * (0.5 + traits.irritability)
    if name == "jealousy":
        # Closeness makes the companion more secure, raising the bar for jealousy.
        return delta * (0.3 + 1.4 * traits.jealousy) * (1.2 - 0.4 * relationship.closeness)
    if name == "hurt":
        return delta * (0.5 + traits.sensitivity)
    return delta


def _event_deltas(
    event: AppraisalEvent, settled: Mapping[str, Feeling], traits: Traits, relationship: Relationship,
) -> dict[str, float]:
    intensity = _clamp(event.intensity)
    if event.type == "apology":
        targets = [name for name in event.targets if name in NEGATIVE and settled[name].value > 0]
        relief = (0.5 + traits.recovery) * intensity
        if targets:
            deltas = {name: -0.1 * relief for name in NEGATIVE}
            deltas.update({name: -TARGETED_APOLOGY * relief for name in targets})
            return deltas
        return {name: -GENERIC_APOLOGY * relief for name in NEGATIVE}
    effects = EVENT_EFFECTS.get(event.type, {})
    return {name: _scale(name, base * intensity, traits, relationship) for name, base in effects.items()}


def _clip_reason(text: str) -> str:
    cleaned = "".join(char for char in text if char.isprintable())
    return " ".join(cleaned.split())[:MAX_REASON_CHARS].strip()


def _log(changes: tuple[Change, ...], new: Iterable[Change]) -> tuple[Change, ...]:
    return (*changes, *new)[-MAX_CHANGES:]


def apply_events(
    state: CompanionState,
    events: Iterable[AppraisalEvent],
    now: datetime,
    traits: Traits,
    base: timedelta,
    *,
    user_distress: float = 0.0,
    rng: random.Random | None = None,
) -> CompanionState:
    """Fold one turn's appraised events into the state."""
    rng = rng or random.Random()
    settled = _settled(state, now, traits, base)
    totals = dict.fromkeys(EMOTION_NAMES, 0.0)
    causes: dict[str, str] = {}
    closeness, trust = state.relationship.closeness, state.relationship.trust
    targeted: set[str] = set()
    for event in events:
        if event.type not in EVENT_TYPES:
            continue
        if event.type == "apology":
            targeted.update(event.targets)
        for name, delta in _event_deltas(event, settled, traits, state.relationship).items():
            totals[name] += delta * rng.uniform(1 - JITTER, 1 + JITTER)
            if delta > 0 and event.reason:
                causes[name] = _clip_reason(event.reason)
            causes.setdefault(name, _clip_reason(event.reason) or event.type.replace("_", " "))
        close_delta, trust_delta = RELATIONSHIP_EFFECTS.get(event.type, (0.0, 0.0))
        intensity = _clamp(event.intensity)
        closeness += close_delta * intensity
        trust += trust_delta * intensity

    feelings: dict[str, Feeling] = {}
    logged = []
    valence = 0.0
    for name in EMOTION_NAMES:
        feeling = settled[name]
        step = _clamp(totals[name], -MAX_STEP, MAX_STEP)
        value = _clamp(feeling.value + step, 0.0, CAPS.get(name, 1.0))
        reasons = feeling.reasons
        if name in targeted:
            reasons = ()
        if step > 0.05 and name in causes:
            reasons = (*[reason for reason in reasons if reason.text != causes[name]], Reason(causes[name], now))
            reasons = reasons[-MAX_REASONS:]
        if value < PRUNE:
            value, reasons = 0.0, ()
        feelings[name] = Feeling(value, now, reasons)
        actual = value - feeling.value
        if abs(actual) >= 0.05:
            logged.append(Change(now, name, round(actual, 2), causes.get(name, "")))
        valence += actual if name == "joy" else -actual if name in NEGATIVE else 0.0

    updated = replace(
        state,
        feelings=feelings,
        relationship=Relationship(_clamp(closeness, 0.1, 1.0), _clamp(trust, 0.1, 1.0)),
        changes=_log(state.changes, logged),
        day_mood=_clamp(day_mood(state, now) + 0.5 * valence, -1.0, 1.0),
        day_mood_at=now,
    )
    return enter_care_mode(updated, now) if user_distress >= 0.5 else updated


def enter_care_mode(state: CompanionState, now: datetime) -> CompanionState:
    """Care first: set small grudges aside for a while because the user is genuinely upset.

    Called from the appraisal and, before the reply is generated, from a zero-cost
    keyword pre-check, so the reply to the upsetting message itself is caring. Grudges
    are halved only once per window, however often it is called.
    """
    if in_care_mode(state, now):
        return replace(state, care_until=now + CARE_WINDOW)
    feelings = dict(state.feelings)
    for name in ("anger", "jealousy"):
        feeling = feelings.get(name)
        if feeling is not None:
            # Halving the stored value halves the decayed one too: decay is multiplicative.
            feelings[name] = Feeling(feeling.value * 0.5, feeling.updated_at, feeling.reasons)
    return replace(state, feelings=feelings, care_until=now + CARE_WINDOW)


def apply_reply_tag(
    state: CompanionState, tag: str | None, now: datetime, traits: Traits, base: timedelta,
) -> CompanionState:
    """A small nudge from the emotion tag the companion chose for its own reply."""
    settled = _settled(state, now, traits, base)
    nudge = REPLY_TAG_NUDGES.get(tag or "")
    if nudge is not None:
        name, delta = nudge
        feeling = settled[name]
        settled[name] = Feeling(_clamp(feeling.value + delta, 0.0, CAPS.get(name, 1.0)), now, feeling.reasons)
    return replace(state, feelings=settled)


def record_user_message(state: CompanionState, now: datetime, traits: Traits, base: timedelta) -> CompanionState:
    """The user wrote: longing is partly satisfied; a long absence leaves joy and a little hurt."""
    settled = _settled(state, now, traits, base)
    changes = []
    absence = now - state.last_user_message if state.last_user_message else None
    if absence is not None and absence > RETURN_SULK_AFTER:
        days = max(int(absence / timedelta(days=1)), 1)
        reason = Reason(f"the user disappeared for {days} day{'s' if days != 1 else ''}", now)
        hurt = settled["hurt"]
        added = 0.15 * (0.5 + traits.sensitivity)
        settled["hurt"] = Feeling(_clamp(hurt.value + added), now, (*hurt.reasons, reason)[-MAX_REASONS:])
        joy = settled["joy"]
        settled["joy"] = Feeling(_clamp(joy.value + 0.2), now, joy.reasons)
        changes += [Change(now, "hurt", round(added, 2), reason.text), Change(now, "joy", 0.2, "the user came back")]
    longing = settled["longing"]
    settled["longing"] = Feeling(longing.value * 0.5, now, ())
    return replace(state, feelings=settled, last_user_message=now, changes=_log(state.changes, changes))
