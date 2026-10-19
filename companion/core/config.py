from __future__ import annotations

import os
from dataclasses import dataclass

# AppConfig reads the environment when this module is imported; importing companion.paths
# loads the project .env first.
import companion.paths  # noqa: F401


def env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class AppConfig:
    base_url: str = os.getenv("OPENAI_BASE_URL") or os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1")
    api_key: str = os.getenv("OPENAI_API_KEY") or os.getenv("MOONSHOT_API_KEY", "")
    model: str = os.getenv("OPENAI_MODEL") or os.getenv("MOONSHOT_MODEL", "kimi-k2.6")
    voice: str = os.getenv("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
    voice_zh: str = os.getenv("EDGE_TTS_VOICE_ZH", os.getenv("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural"))
    voice_en: str = os.getenv("EDGE_TTS_VOICE_EN", "en-US-AriaNeural")
    system_prompt: str = os.getenv(
        "COMPANION_SYSTEM_PROMPT",
        "You are a friendly Live2D desktop companion. Reply briefly, warmly, and in spoken language.",
    )
    request_timeout: int = int(os.getenv("OPENAI_TIMEOUT", "60"))
    request_retries: int = int(os.getenv("OPENAI_RETRIES", "2"))
    memory_enabled: bool = os.getenv("MEMORY_ENABLED", "1").strip() not in {"0", "false", "False"}
    memory_consolidation: bool = os.getenv("MEMORY_CONSOLIDATION", "1").strip() not in {"0", "false", "False"}
    memory_relevant_recall: bool = os.getenv("MEMORY_RELEVANT_RECALL", "1").strip() not in {"0", "false", "False"}
    conversation_summary: bool = os.getenv("CONVERSATION_SUMMARY", "1").strip() not in {"0", "false", "False"}
    memory_limit: int = int(os.getenv("MEMORY_LIMIT", "24"))
    chat_thinking: bool = env_flag("CHAT_THINKING", default=False)
    chat_tools: bool = env_flag("CHAT_TOOLS", default=False)
