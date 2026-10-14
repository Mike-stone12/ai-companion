from __future__ import annotations

import re

from companion.core.memory.store import clip_memory_text


# Gate for calling the LLM extractor. Very common chit-chat openers (我想/我要/今天) are left
# out on purpose: each extraction costs a request, and the API may be tightly rate limited.
MEMORY_TRIGGER_RE = re.compile(
    r"(我叫|你可以叫我|我是|我住在|我在|我喜欢|我不喜欢|我讨厌|我打算|我准备|明天|最近|下周|周末|生日|工作|上班|上学|考试|面试|搬家|旅行|男朋友|女朋友|对象|老公|老婆|妈妈|爸爸|姐姐|哥哥|弟弟|妹妹|室友|同事|朋友)"
)


MEMORY_GATE_MIN_LENGTH = 6


# Fallback used only when the LLM extractor cannot be reached, so it favours precision.
HEURISTIC_MEMORY_PATTERNS = (
    (r"(?:我叫|你可以叫我)([^，。！!？?\s]{1,12})", "identity", "用户名字：{value}"),
    (r"我是(?!说|不是|在|真|的)([^，。！!？?]{1,20})", "identity", "用户身份：{value}"),
    (r"我喜欢([^，。！!？?]{1,24})", "preference", "用户喜欢：{value}"),
    (r"我不喜欢([^，。！!？?]{1,24})", "preference", "用户不喜欢：{value}"),
    (r"我讨厌([^，。！!？?]{1,24})", "preference", "用户讨厌：{value}"),
    (r"我住在([^，。！!？?]{1,24})", "profile", "用户住在：{value}"),
)


def heuristic_memory_candidates(user_text: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for pattern, category, template in HEURISTIC_MEMORY_PATTERNS:
        match = re.search(pattern, user_text)
        if not match:
            continue
        value = clip_memory_text(match.group(1).strip(" ，。！!？?"), 28)
        if not value:
            continue
        candidates.append({"summary": template.format(value=value), "category": category, "source": "heuristic"})
    return candidates[:3]


def should_extract_memory(user_text: str) -> bool:
    stripped = user_text.strip()
    if heuristic_memory_candidates(stripped):
        return True
    return len(stripped) >= MEMORY_GATE_MIN_LENGTH and bool(MEMORY_TRIGGER_RE.search(stripped))
