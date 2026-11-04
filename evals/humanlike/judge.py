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

RUBRIC = """You are a strict judge of whether a companion character's chat replies feel like a real \
person texting someone close (Chinese casual texting between old friends), or like an AI.

The character: {persona}

First list every flaw you can find, quoting the line: assistant habits (advice, reassurance formulas, \
offers to help, explaining herself or her limits, a question at the end of most replies, interviewing \
the user), unnatural rhythm (answering half a sentence before the user finished, instant long replies), \
repetition, forced or wrong callbacks, things the user did not say, tone that is off for the moment, \
lines that are too polished or "written". Then score each 1-10:
- human: could this be a real friend's chat log?
- character: consistent with the character, her own life, preferences, and mood.
- emotion: emotional fit and tact for what the user said.
- context: follows the conversation, remembers what was said, answers what the user actually said.

Calibration: typical chatbot output deserves 4-6; good roleplay with a few tells 7; 8 only with no \
clear tell; 9-10 only if you would bet it is a real person. Start from 6 and move per flaw or strength.

What a real person would do in this scene: {focus}

Each line is one chat bubble. "用户" is the user, "她" is the character; [n s] is seconds since the \
user's first message in that exchange (a line sent while she was replying shows up between her lines). \
"{turn_break}" separates exchanges: before it the user had finished and was waiting, so her replies \
there can only answer what came before it; never count them as interrupting a later exchange. \
Reply with JSON only:
{{"flaws": ["quoted line: what is wrong"], "human": n, "character": n, "emotion": n, "context": n, \
"assistant_moments": ["exact lines that sound like an assistant or a bot"], \
"best_line": "the most human line", "comment": "one or two sentences in Chinese"}}"""

PAIRWISE = """You compare two versions of the same chat between a user and a companion character, \
and decide which character feels more like a real person texting someone close (Chinese casual \
texting between old friends) rather than an AI assistant. Consider wording, length and rhythm, \
emotional tact, consistency, memory of the conversation, timing ([n s] = seconds since the user's \
first message in that exchange; "{turn_break}" separates exchanges, and before it the user had \
finished and was waiting), and the absence of assistant habits. Both versions may be good; \
pick the one with fewer tells, and say tie only if you truly cannot tell them apart.

The character: {persona}
What a real person would do in this scene: {focus}

Version A:
{a}

Version B:
{b}

Reply with JSON only: {{"winner": "A" | "B" | "tie", "reason": "one sentence in Chinese"}}"""


# Between exchanges: the user had stopped and waited, so later lines were not yet written when
# she answered (without it, judges read a reply to part one of a story as an interruption).
TURN_BREAK = "—— 用户停下等她回复；下面是之后的新一段 ——"


def render_transcript(turns: list[dict]) -> str:
    """One line per bubble, with timing when the run recorded it."""
    lines = []
    for index, turn in enumerate(turns):
        if index:
            lines.append(TURN_BREAK)
        timeline = turn.get("timeline")
        if timeline:
            lines += [f"[{t:g}s] {'用户' if who == 'user' else '她'}：{text}" for t, who, text in timeline]
            if not any(who == "her" for _, who, _ in timeline):
                lines.append("她：（没有回复）")
            continue
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
    prompt = RUBRIC.format(persona=persona, focus=focus, turn_break=TURN_BREAK)
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
        "flaws": [str(f) for f in (data.get("flaws") or []) if str(f).strip()][:8],
        "assistant_moments": [str(m) for m in moments if str(m).strip()][:5],
        "best_line": str(data.get("best_line", "")),
        "comment": str(data.get("comment", "")),
    }


def _winner(judge: Judge, first: list[dict], second: list[dict], persona: str, focus: str) -> tuple[str, str]:
    prompt = PAIRWISE.format(
        persona=persona, focus=focus, turn_break=TURN_BREAK, a=render_transcript(first), b=render_transcript(second),
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
