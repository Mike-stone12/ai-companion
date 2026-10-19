"""Scripted emotion scenarios: run conversations through the model under several personalities.

``python -m companion.core.state.scenarios [path]`` replays each scenario in
``evals/emotion_scenarios.json`` for every trait preset, with a fixed random seed,
and checks the expectations (feeling bounds, dominant feeling, care mode, prompt
text, idle face, reasons). Fully offline: the appraisal events are scripted, so this
tests the deterministic half of the design (the rules), not the LLM's judgement.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .model import (
    AppraisalEvent,
    CompanionState,
    active_reasons,
    apply_events,
    current_feelings,
    day_mood,
    dominant,
    fresh_state,
    idle_emotion,
    in_care_mode,
    record_user_message,
)
from .render import render_state_context
from .traits import Traits

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "evals" / "emotion_scenarios.json"
START = datetime(2026, 10, 19, 20, 0, tzinfo=UTC)
STEP_GAP = timedelta(minutes=2)
BASE = timedelta(hours=2)
SEED = 20261019


@dataclass
class Outcome:
    scenario: str
    preset: str
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    trajectory: list[dict[str, float]] = field(default_factory=list)


def _apply_step(state: CompanionState, step: dict, now: datetime, traits: Traits, rng: random.Random):
    if "wait_hours" in step:
        return state, now + timedelta(hours=step["wait_hours"])
    if "last_message_hours_ago" in step:
        return replace(state, last_user_message=now - timedelta(hours=step["last_message_hours_ago"])), now
    if step.get("user_returns"):
        return record_user_message(state, now, traits, BASE), now
    events = [AppraisalEvent(e["type"], e.get("intensity", 0.5), e.get("reason", ""), tuple(e.get("targets", [])))
              for e in step.get("events", [])]
    if step.get("user") is not None:
        state = record_user_message(state, now, traits, BASE)
    return apply_events(state, events, now, traits, BASE, user_distress=step.get("distress", 0.0), rng=rng), now


def _check(expect: dict, state: CompanionState, now: datetime, traits: Traits) -> tuple[bool, str]:
    values = current_feelings(state, now, traits, BASE)
    name, _ = dominant(state, now, traits, BASE)
    if "feeling" in expect:
        value = values[expect["feeling"]]
        ok = expect.get("min", 0.0) <= value <= expect.get("max", 1.0)
        bounds = f"[{expect.get('min', 0.0):.2f}, {expect.get('max', 1.0):.2f}]"
        return ok, f"{expect['feeling']} = {value:.2f} in {bounds}"
    if "dominant" in expect:
        return name == expect["dominant"], f"dominant = {name} (want {expect['dominant']})"
    if "dominant_not" in expect:
        return name != expect["dominant_not"], f"dominant = {name} (not {expect['dominant_not']})"
    if "care_mode" in expect:
        return in_care_mode(state, now) == expect["care_mode"], f"care mode = {in_care_mode(state, now)}"
    if "day_mood_min" in expect:
        mood = day_mood(state, now)
        return mood >= expect["day_mood_min"], f"day mood = {mood:+.2f} >= {expect['day_mood_min']}"
    if "idle_face" in expect:
        face = idle_emotion(state, now, traits, BASE)
        return face == expect["idle_face"], f"idle face = {face} (want {expect['idle_face']})"
    if "reason_contains" in expect:
        reasons = [text for texts in active_reasons(state, now, traits, BASE).values() for text in texts]
        return any(expect["reason_contains"] in text for text in reasons), f"reasons {reasons}"
    prompt = render_state_context(state, now, traits, BASE)
    if "prompt_contains" in expect:
        return expect["prompt_contains"] in prompt, f"prompt contains {expect['prompt_contains']!r}"
    if "prompt_lacks" in expect:
        return expect["prompt_lacks"] not in prompt, f"prompt lacks {expect['prompt_lacks']!r}"
    raise ValueError(f"Unknown expectation: {expect}")


def run_scenario(scenario: dict, preset: str, traits: Traits) -> Outcome:
    outcome = Outcome(scenario["name"], preset)
    rng = random.Random(SEED)
    state, now = fresh_state(START), START
    states = []
    for step in scenario["steps"]:
        state, now = _apply_step(state, step, now, traits, rng)
        states.append((state, now))
        outcome.trajectory.append({k: round(v, 2) for k, v in current_feelings(state, now, traits, BASE).items() if v})
        now += STEP_GAP
    for expect in scenario.get("expect", []):
        if "presets" in expect and preset not in expect["presets"]:
            continue
        step_state, step_now = states[expect["step"] - 1]
        ok, description = _check(expect, step_state, step_now, traits)
        (outcome.passed if ok else outcome.failed).append(f"step {expect['step']}: {description}")
    return outcome


def run_all(data: dict) -> list[Outcome]:
    presets = {name: Traits.from_dict(values) for name, values in data["presets"].items()}
    return [run_scenario(scenario, name, traits) for scenario in data["scenarios"] for name, traits in presets.items()]


def format_outcomes(outcomes: list[Outcome]) -> str:
    lines = []
    for outcome in outcomes:
        status = "PASS" if not outcome.failed else "FAIL"
        lines.append(f"{status}  {outcome.scenario} [{outcome.preset}]  trajectory: {outcome.trajectory}")
        lines.extend(f"      FAILED {item}" for item in outcome.failed)
    checks = sum(len(o.passed) + len(o.failed) for o in outcomes)
    failed = sum(len(o.failed) for o in outcomes)
    lines.append(f"{len(outcomes)} scenario runs, {checks - failed}/{checks} checks passed")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args(argv)
    outcomes = run_all(json.loads(args.path.read_text(encoding="utf-8")))
    print(format_outcomes(outcomes))
    return 0 if all(not outcome.failed for outcome in outcomes) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
