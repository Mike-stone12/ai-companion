"""LLM judge for the human-likeness eval: absolute scores and blind A/B comparisons.

The judge is any callable taking chat messages and returning the reply text, so tests
inject a fake and the runner passes ``OpenAICompatibleClient.complete``. Scores come
back as JSON; anything malformed is reported as an error for that scenario rather than
guessed. A/B comparisons run twice with the order swapped, since judges favour
whichever transcript they see first; a split decision counts as a tie.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

Judge = Callable[[list[dict[str, str]]], str]
SCORE_KEYS = ("human", "character", "emotion", "context")

RUBRIC = """You judge how much a companion character's chat replies feel like a real person texting \
someone close (Chinese casual texting between old friends), not like an AI assistant.

The character: {persona}

Score each 1-10 (10 = indistinguishable from a real close friend):
- human: reads like a real person texting: length, rhythm, splitting into short messages, wording, \
not eager, not formulaic, no assistant habits (advice lists, reassurance formulas, offers to help, \
a question at the end of every reply, formatting).
- character: consistent with the character and her own life, preferences, and mood.
- emotion: emotional fit and tact for what the user said: neither flat nor overdone; takes the \
user's side when they are down.
- context: follows the conversation and remembers what was said; no forced callbacks.

What a real person would do in this scene: {focus}

Lines starting with "用户" are the user; lines starting with "她" are the character; each line is one \
chat message. Reply with JSON only:
{{"human": n, "character": n, "emotion": n, "context": n, \
"assistant_moments": ["exact lines that sound like an assistant or a bot"], \
"best_line": "the most human line", "comment": "one or two sentences in Chinese"}}"""

PAIRWISE = """You compare two versions of the same chat between a user and a companion character, \
and decide which character feels more like a real person texting someone close (Chinese casual \
texting between old friends) rather than an AI assistant. Consider wording, length and rhythm, \
emotional tact, consistency, memory of the conversation, and the absence of assistant habits.

The character: {persona}
What a real person would do in this scene: {focus}

Version A:
{a}

Version B:
{b}

Reply with JSON only: {{"winner": "A" | "B" | "tie", "reason": "one sentence in Chinese"}}"""


def render_transcript(turns: list[dict]) -> str:
    lines = []
    for turn in turns:
        lines += [f"用户：{message}" for message in turn.get("user", [])]
        lines += [f"她：{message}" for message in turn.get("reply", [])] or ["她：（没有回复）"]
    return "\n".join(lines)


def parse_json(text: str) -> dict:
    """The first JSON object in the reply (judges sometimes wrap it in a code fence)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON object in the judge's reply")
    value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("the judge's reply is not a JSON object")
    return value


def score(judge: Judge, turns: list[dict], *, persona: str, focus: str) -> dict:
    prompt = RUBRIC.format(persona=persona, focus=focus)
    reply = judge([
        {"role": "system", "content": prompt},
        {"role": "user", "content": render_transcript(turns)},
    ])
    data = parse_json(reply)
    scores = {}
    for key in SCORE_KEYS:
        value = data.get(key)
        if not isinstance(value, int | float) or not 1 <= value <= 10:
            raise ValueError(f"score {key!r} missing or out of range: {value!r}")
        scores[key] = float(value)
    moments = data.get("assistant_moments") or []
    return {
        **scores,
        "overall": sum(scores.values()) / len(scores),
        "assistant_moments": [str(m) for m in moments if str(m).strip()][:5],
        "best_line": str(data.get("best_line", "")),
        "comment": str(data.get("comment", "")),
    }


def _winner(judge: Judge, first: list[dict], second: list[dict], persona: str, focus: str) -> tuple[str, str]:
    prompt = PAIRWISE.format(
        persona=persona, focus=focus, a=render_transcript(first), b=render_transcript(second),
    )
    data = parse_json(judge([{"role": "user", "content": prompt}]))
    winner = str(data.get("winner", "")).strip().upper()
    if winner not in {"A", "B", "TIE"}:
        raise ValueError(f"unknown winner {winner!r}")
    return winner, str(data.get("reason", ""))


def compare(judge: Judge, before: list[dict], after: list[dict], *, persona: str, focus: str) -> dict:
    """Which run is more human for one scenario: "after", "before", or "tie" (both orders)."""
    first, reason_1 = _winner(judge, before, after, persona, focus)
    second, reason_2 = _winner(judge, after, before, persona, focus)
    votes = [
        {"A": "before", "B": "after", "TIE": "tie"}[first],
        {"A": "after", "B": "before", "TIE": "tie"}[second],
    ]
    if votes[0] == votes[1]:
        result = votes[0]
    elif "tie" in votes:
        result = next(vote for vote in votes if vote != "tie")
    else:
        result = "tie"
    return {"result": result, "votes": votes, "reasons": [reason_1, reason_2]}
