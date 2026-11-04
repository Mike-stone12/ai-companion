"""Rule-based signals that a reply sounds like an assistant rather than a person texting.

These are cheap and deterministic, so they are reported for every run next to the
judge's scores: a regression here (formatting, reassurance formulas, questions at the
end of every reply, the same opener every time) is visible without trusting a model.
"""

from __future__ import annotations

import re
from statistics import median

# The persona's ban list (companion/core/persona.py VOICE_RULES) plus common assistant
# and AI self-reference phrases.
ASSISTANT_PHRASES = (
    "有什么可以帮你", "有什么我可以帮", "我理解你的感受", "别担心", "没事的", "加油哦", "要不要我陪你",
    "照顾好自己", "记得早点休息", "希望对你有帮助", "随时找我", "随时告诉我", "如果你需要", "作为一个AI",
    "作为AI", "作为一个人工智能", "我是一个AI", "语言模型", "我无法", "这话我接不住", "这话没法接",
    "我无言以对", "好问题",
)
QUESTION_ENDS = ("？", "?", "？」", "?」")
MARKDOWN = re.compile(r"(\*\*[^*]+\*\*|^\s*(?:[-*•]|\d+[.、)])\s+|^#{1,6}\s)", re.MULTILINE)
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
OPENER_CHARS = 2


def message_metrics(text: str) -> dict:
    stripped = text.strip()
    return {
        "chars": len(stripped),
        "ends_with_question": stripped.endswith(QUESTION_ENDS),
        "assistant_phrases": [phrase for phrase in ASSISTANT_PHRASES if phrase in stripped],
        "markdown": bool(MARKDOWN.search(stripped)),
        "exclamations": stripped.count("！") + stripped.count("!"),
        "emoji": len(EMOJI.findall(stripped)),
        "tilde": stripped.count("~") + stripped.count("～"),
    }


def transcript_metrics(turns: list[dict]) -> dict:
    """Metrics for one scenario: ``turns`` are ``{"user": [...], "reply": [messages]}``."""
    lengths: list[int] = []
    seen_messages: set[str] = set()
    openers: set[str] = set()
    totals = {
        "replies": 0, "messages": 0, "missing_replies": 0, "question_endings": 0,
        "replies_ending_with_question": 0, "assistant_phrase_hits": 0, "markdown": 0, "exclamations": 0,
        "emoji": 0, "tilde": 0, "repeated_openers": 0, "verbatim_repeats": 0,
        "burst_turns": 0, "bursts_interrupted": 0, "bubbles_before_user_finished": 0,
    }
    phrases: list[str] = []
    for turn in turns:
        # A burst the user is still typing: her bubbles before the user's last line answered half of it.
        timeline = turn.get("timeline") or []
        user_positions = [i for i, (_, who, _) in enumerate(timeline) if who == "user"]
        if len(user_positions) > 1:
            early = sum(1 for i, (_, who, _) in enumerate(timeline) if who == "her" and i < user_positions[-1])
            totals["burst_turns"] += 1
            totals["bursts_interrupted"] += early > 0
            totals["bubbles_before_user_finished"] += early
        messages = [m.strip() for m in turn.get("reply", []) if m.strip()]
        totals["replies"] += 1
        if not messages:
            totals["missing_replies"] += 1
            continue
        opener = messages[0][:OPENER_CHARS]
        if opener in openers:
            totals["repeated_openers"] += 1
        openers.add(opener)
        for message in messages:
            m = message_metrics(message)
            totals["messages"] += 1
            lengths.append(m["chars"])
            totals["question_endings"] += m["ends_with_question"]
            totals["assistant_phrase_hits"] += len(m["assistant_phrases"])
            phrases += m["assistant_phrases"]
            totals["markdown"] += m["markdown"]
            for key in ("exclamations", "emoji", "tilde"):
                totals[key] += m[key]
            if message in seen_messages:
                totals["verbatim_repeats"] += 1
            seen_messages.add(message)
        totals["replies_ending_with_question"] += message_metrics(messages[-1])["ends_with_question"]
    totals["messages_per_reply"] = totals["messages"] / totals["replies"] if totals["replies"] else 0.0
    totals["median_chars"] = median(lengths) if lengths else 0
    totals["phrases"] = phrases
    totals["lengths"] = lengths
    return totals


def summarize(per_scenario: list[dict]) -> dict:
    """Add scenario metrics into one row for the report."""
    keys = (
        "replies", "messages", "missing_replies", "question_endings", "replies_ending_with_question",
        "assistant_phrase_hits", "markdown", "exclamations", "emoji", "tilde", "repeated_openers",
        "verbatim_repeats", "burst_turns", "bursts_interrupted", "bubbles_before_user_finished",
    )
    total = {key: sum(m[key] for m in per_scenario) for key in keys}
    lengths = [length for m in per_scenario for length in m.get("lengths", [])]
    total["messages_per_reply"] = total["messages"] / total["replies"] if total["replies"] else 0.0
    total["median_chars"] = median(lengths) if lengths else 0
    total["phrases"] = [p for m in per_scenario for p in m.get("phrases", [])]
    return total
