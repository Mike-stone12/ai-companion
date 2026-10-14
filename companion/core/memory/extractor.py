from __future__ import annotations

import json
import logging
import re

from companion.core.llm.client import (
    THINKING_DISABLED,
    OpenAICompatibleClient,
    supports_thinking_toggle,
)
from companion.core.memory.gate import heuristic_memory_candidates
from companion.core.memory.store import clip_memory_text

logger = logging.getLogger(__name__)


# Extraction runs in the background, so it can wait out per-minute rate limits.
MEMORY_RETRY_DELAYS = (10, 25)


MEMORY_EXTRACTION_PROMPT = (
    "你是桌面陪伴助手的记忆提取器。"
    "只提取适合长期记忆的重要信息，例如用户身份、重要人物特征、稳定偏好、待办计划、关键事件。"
    "忽略寒暄、即时情绪和泛泛回答。"
    '输出必须是 JSON 对象：{"memories": [{"summary": string, "category": string}]}。'
    'summary 要压缩、具体、中文、20字以内。最多输出 3 条。没有重要信息就输出 {"memories": []}。'
)


MEMORY_EXTRACTION_TEMPERATURE = 0.2


def strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    return cleaned


def extraction_request_options(base_url: str) -> dict:
    options: dict = {"response_format": {"type": "json_object"}}
    # Disabling reasoning makes extraction several times faster and cheaper (Kimi ~5s -> ~1s,
    # DeepSeek ~1.5s -> ~0.8s).
    if supports_thinking_toggle(base_url):
        options.update(THINKING_DISABLED)
    # Moonshot fixes the temperature per mode (0.6 with thinking off), so only set it elsewhere.
    if "moonshot" not in base_url:
        options["temperature"] = MEMORY_EXTRACTION_TEMPERATURE
    return options


def parse_memory_reply(content: str) -> list[dict[str, str]] | None:
    try:
        parsed = json.loads(strip_json_fence(content))
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        parsed = parsed.get("memories")
    if not isinstance(parsed, list):
        return None

    memories: list[dict[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        summary = clip_memory_text(str(item.get("summary", "")).strip(), 28)
        if summary:
            memories.append(
                {"summary": summary, "category": str(item.get("category") or "memory"), "source": "llm"}
            )
    return memories[:3]


def extract_memories_with_llm(
    client: OpenAICompatibleClient, user_text: str, assistant_text: str
) -> list[dict[str, str]]:
    if not client.config.api_key:
        return heuristic_memory_candidates(user_text)

    messages = [
        {"role": "system", "content": MEMORY_EXTRACTION_PROMPT},
        {
            "role": "user",
            "content": json.dumps({"user_message": user_text, "assistant_reply": assistant_text}, ensure_ascii=False),
        },
    ]
    try:
        content = client.complete(
            messages,
            extra=extraction_request_options(client.config.base_url),
            retry_delays=MEMORY_RETRY_DELAYS,
        )
    except RuntimeError as exc:
        logger.warning("LLM extraction failed, falling back to heuristics: %s", exc)
        return heuristic_memory_candidates(user_text)

    memories = parse_memory_reply(content)
    if memories is None:
        logger.warning("Could not parse extraction reply, falling back to heuristics")
        logger.debug("Unparseable extraction reply: %s", content)
        return heuristic_memory_candidates(user_text)
    return memories
