"""The trait-driven emotion model: events -> feelings, decay, guardrails, and persistence."""

import json
import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from companion.core.state import (
    AppraisalEvent,
    CompanionState,
    Feeling,
    Reason,
    Relationship,
    StateStore,
    Traits,
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
from companion.core.state.model import CARE_WINDOW, MAX_CHANGES, MAX_STEP, half_life

NOW = datetime(2026, 10, 19, 20, 0, tzinfo=UTC)
BASE = timedelta(hours=2)
TRAITS = Traits()


def rng():
    return random.Random(7)


def event(kind, intensity=1.0, reason="", targets=()):
    return AppraisalEvent(kind, intensity, reason, tuple(targets))


def apply(state, *events, traits=TRAITS, distress=0.0, now=NOW):
    return apply_events(state, events, now, traits, BASE, user_distress=distress, rng=rng())


def values(state, now=NOW, traits=TRAITS):
    return current_feelings(state, now, traits, BASE)


def with_feeling(name, value, *, at=NOW, reasons=(), **kwargs):
    state = fresh_state(at)
    feelings = dict(state.feelings)
    feelings[name] = Feeling(value, at, tuple(reasons))
    return replace(state, feelings=feelings, **kwargs)


# Same event, different personality.

def test_a_jealous_companion_gets_far_more_jealous_than_a_secure_one():
    jealous = apply(fresh_state(NOW), event("rival", reason="he said the new girl is pretty"),
                    traits=Traits(jealousy=0.9))
    secure = apply(fresh_state(NOW), event("rival"), traits=Traits(jealousy=0.1))

    assert values(jealous)["jealousy"] > 2 * values(secure)["jealousy"]
    assert active_reasons(jealous, NOW, TRAITS, BASE)["jealousy"] == ["he said the new girl is pretty"]


def test_irritable_companions_anger_more_and_sensitive_ones_are_hurt_more():
    calm = apply(fresh_state(NOW), event("criticism"), traits=Traits(irritability=0.0, sensitivity=0.0))
    touchy = apply(fresh_state(NOW), event("criticism"), traits=Traits(irritability=1.0, sensitivity=1.0))

    assert values(touchy)["anger"] > values(calm)["anger"]
    assert values(touchy)["hurt"] > values(calm)["hurt"]


def test_quick_recovery_means_negative_feelings_fade_faster():
    slow = half_life("anger", Traits(recovery=0.1), Relationship(), BASE)
    quick = half_life("anger", Traits(recovery=0.9), Relationship(), BASE)

    assert quick < slow
    assert half_life("joy", Traits(recovery=0.9), Relationship(), BASE) == BASE


def test_closeness_raises_the_bar_for_jealousy_and_speeds_recovery():
    distant = apply(fresh_state(NOW), event("rival"))
    close = apply(replace(fresh_state(NOW), relationship=Relationship(1.0, 1.0)), event("rival"))

    assert values(close)["jealousy"] < values(distant)["jealousy"]
    assert half_life("hurt", TRAITS, Relationship(1.0), BASE) < half_life("hurt", TRAITS, Relationship(0.1), BASE)


# Bounds and decay.

def test_feelings_decay_and_vanish():
    state = with_feeling("anger", 0.6)
    hl = half_life("anger", TRAITS, state.relationship, BASE)

    assert values(state, NOW + hl)["anger"] == pytest.approx(0.3)
    assert values(state, NOW + 5 * hl)["anger"] == 0.0
    assert active_reasons(state, NOW + 5 * hl, TRAITS, BASE) == {}


def test_anger_is_capped_and_one_turn_moves_a_feeling_by_at_most_max_step():
    furious = with_feeling("anger", 0.75)
    hit = apply(furious, event("criticism"), event("criticism"), event("criticism"), traits=Traits(irritability=1))

    assert values(hit)["anger"] <= 0.8
    elated = apply(fresh_state(NOW), event("praise"), event("affection"), event("good_news"))
    assert values(elated)["joy"] <= MAX_STEP + 1e-9


def test_one_nice_line_does_not_turn_rage_into_joy():
    state = apply(with_feeling("anger", 0.8), event("praise"))

    name, _ = dominant(state, NOW, TRAITS, BASE)
    assert name == "anger"


def test_jitter_is_small_and_reproducible_with_a_seed():
    first = apply_events(fresh_state(NOW), [event("praise")], NOW, TRAITS, BASE, rng=random.Random(1))
    again = apply_events(fresh_state(NOW), [event("praise")], NOW, TRAITS, BASE, rng=random.Random(1))
    other = apply_events(fresh_state(NOW), [event("praise")], NOW, TRAITS, BASE, rng=random.Random(2))

    assert values(first) == values(again)
    assert values(first)["joy"] == pytest.approx(values(other)["joy"], rel=0.25)
    assert 0.35 * 0.9 <= values(first)["joy"] <= 0.35 * 1.1


def test_unknown_event_types_are_ignored():
    assert values(apply(fresh_state(NOW), event("bribe"))) == values(fresh_state(NOW))


# Making up.

def test_an_apology_for_the_actual_grievance_works_much_better_than_a_generic_sorry():
    jealous = with_feeling("jealousy", 0.6, reasons=[Reason("he praised another girl", NOW)])

    targeted = apply(jealous, event("apology", targets=["jealousy"]))
    generic = apply(jealous, event("apology"))

    assert values(targeted)["jealousy"] < values(generic)["jealousy"]
    assert active_reasons(targeted, NOW, TRAITS, BASE).get("jealousy") is None
    assert active_reasons(generic, NOW, TRAITS, BASE)["jealousy"] == ["he praised another girl"]


def test_care_and_affection_soothe_hurt_and_longing():
    hurt = with_feeling("hurt", 0.5)

    soothed = apply(hurt, event("care"))

    assert values(soothed)["hurt"] < 0.5
    assert values(soothed)["joy"] > 0


# Guardrail: care first.

def test_genuine_user_distress_switches_to_care_first_and_halves_grudges():
    sulking = with_feeling("anger", 0.6)

    state = apply(sulking, distress=0.8)

    assert state.care_until == NOW + CARE_WINDOW
    assert values(state)["anger"] == pytest.approx(0.3)


def test_mild_distress_does_not_switch_modes():
    assert apply(fresh_state(NOW), distress=0.3).care_until is None


# Time away.

def test_longing_grows_with_silence():
    state = replace(fresh_state(NOW), last_user_message=NOW)

    assert values(state, NOW + timedelta(hours=6))["longing"] == 0.0
    assert values(state, NOW + timedelta(days=2))["longing"] > 0.3
    assert values(state, NOW + timedelta(days=10))["longing"] <= 0.8


def test_coming_back_after_days_brings_joy_a_little_hurt_and_eases_longing():
    away = replace(fresh_state(NOW), last_user_message=NOW - timedelta(days=3))
    longing_before = values(away)["longing"]

    back = record_user_message(away, NOW, TRAITS, BASE)

    assert values(back)["joy"] > 0
    assert values(back)["hurt"] > 0
    assert active_reasons(back, NOW, TRAITS, BASE)["hurt"] == ["the user disappeared for 3 days"]
    assert values(back)["longing"] < longing_before
    assert back.last_user_message == NOW


def test_a_message_within_the_day_only_updates_the_timestamp():
    recent = replace(with_feeling("joy", 0.5), last_user_message=NOW - timedelta(hours=1))

    after = record_user_message(recent, NOW, TRAITS, BASE)

    assert values(after)["joy"] == pytest.approx(0.5)
    assert values(after)["hurt"] == 0.0


# Relationship and history.

def test_relationship_moves_slowly():
    state = fresh_state(NOW)
    for _ in range(10):
        state = apply(state, event("affection"))

    assert 0.65 < state.relationship.closeness < 0.8
    assert apply(fresh_state(NOW), event("criticism")).relationship.closeness < 0.6


def test_changes_are_logged_with_causes_and_bounded():
    state = fresh_state(NOW)
    for minute in range(MAX_CHANGES + 4):
        state = apply(state, event("praise", reason=f"compliment {minute}"), now=NOW + timedelta(days=minute))

    assert len(state.changes) == MAX_CHANGES
    assert state.changes[-1].emotion == "joy"
    assert state.changes[-1].cause.startswith("compliment")


def test_reasons_are_capped():
    state = fresh_state(NOW)
    for index in range(5):
        state = apply(state, event("rival", 0.3, reason=f"girl {index}"))

    assert len(active_reasons(state, NOW, TRAITS, BASE)["jealousy"]) == 3


def test_day_mood_follows_the_turns_valence():
    good = apply(fresh_state(NOW), event("praise"), event("good_news"))
    bad = apply(fresh_state(NOW), event("criticism"))

    assert good.day_mood > 0
    assert bad.day_mood < 0


# Face and reply tags.

def test_dominant_feeling_drives_the_idle_face():
    assert idle_emotion(with_feeling("jealousy", 0.6), NOW, TRAITS, BASE) == "angry"
    assert idle_emotion(with_feeling("joy", 0.6), NOW, TRAITS, BASE) == "happy"
    assert idle_emotion(with_feeling("hurt", 0.2), NOW, TRAITS, BASE) is None
    assert current_mood(fresh_state(NOW), NOW, TRAITS, BASE).emotion == "neutral"


def test_reply_tags_nudge_feelings_a_little():
    nudged = apply_reply_tag(fresh_state(NOW), "happy", NOW, TRAITS, BASE)

    assert values(apply_reply_tag(nudged, "happy", NOW, TRAITS, BASE))["joy"] == pytest.approx(0.16)
    assert values(apply_reply_tag(fresh_state(NOW), "neutral", NOW, TRAITS, BASE)) == values(fresh_state(NOW))


# Persistence.

def test_store_round_trip(tmp_path):
    state = apply(fresh_state(NOW), event("rival", reason="new classmate"), distress=0.6)
    state = replace(state, last_user_message=NOW)
    store = StateStore(tmp_path / "state.json")

    store.save(state)
    loaded = store.load(now=NOW)

    assert values(loaded) == pytest.approx(values(state), abs=1e-3)
    assert active_reasons(loaded, NOW, TRAITS, BASE) == active_reasons(state, NOW, TRAITS, BASE)
    assert loaded.relationship.closeness == pytest.approx(state.relationship.closeness, abs=1e-3)
    assert loaded.care_until == state.care_until
    assert len(loaded.changes) == len(state.changes)
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["version"] == 2


def test_version_1_files_are_migrated(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "version": 1,
        "mood": {"emotion": "sad", "intensity": 0.6, "updated_at": NOW.isoformat()},
        "last_user_message": (NOW - timedelta(hours=1)).isoformat(),
        "activity": "",
    }), encoding="utf-8")

    loaded = StateStore(path).load(now=NOW)

    assert values(loaded)["hurt"] == pytest.approx(0.6)
    assert loaded.last_user_message == NOW - timedelta(hours=1)


@pytest.mark.parametrize("content", [
    "{broken", "[]",
    '{"version": 2, "feelings": "x"}',
    '{"version": 2, "feelings": {"joy": {"value": "lots", "updated_at": "2026-10-19T20:00:00+00:00"}}}',
    '{"version": 2, "feelings": {"joy": {"value": 0.5, "updated_at": "2026-10-19T20:00:00"}}}',
    '{"version": 1, "mood": {"emotion": "happy", "intensity": 0.5, "updated_at": "2026-10-19T20:00:00"}}',
])
def test_corrupt_files_start_fresh(tmp_path, content):
    path = tmp_path / "state.json"
    path.write_text(content, encoding="utf-8")

    assert values(StateStore(path).load(now=NOW)) == values(fresh_state(NOW))


def test_loaded_values_are_clamped(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"version": 2, "feelings": {
        "anger": {"value": 5, "updated_at": NOW.isoformat(), "reasons": [{"text": "x" * 500, "at": NOW.isoformat()}]},
    }}), encoding="utf-8")

    loaded = StateStore(path).load(now=NOW)

    assert values(loaded)["anger"] == 0.8
    assert len(active_reasons(loaded, NOW, TRAITS, BASE)["anger"][0]) <= 60


def test_state_is_a_plain_value():
    assert CompanionState() == CompanionState()
