from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from companion.core.settings_values import load_setting_values

# Keep import-time defaults; paths loads .env before these values are merged.
_values = load_setting_values()


def env_flag(name: str, default: bool, values: Mapping[str, str] | None = None) -> bool:
    raw = (os.environ if values is None else values).get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class AppConfig:
    base_url: str = _values.get("OPENAI_BASE_URL") or _values.get("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1")
    api_key: str = os.getenv("OPENAI_API_KEY") or os.getenv("MOONSHOT_API_KEY", "")
    model: str = _values.get("OPENAI_MODEL") or _values.get("MOONSHOT_MODEL", "kimi-k2.6")
    voice: str = _values.get("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
    voice_zh: str = _values.get("EDGE_TTS_VOICE_ZH", _values.get("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural"))
    voice_en: str = _values.get("EDGE_TTS_VOICE_EN", "en-US-AriaNeural")
    system_prompt: str = _values.get(
        "COMPANION_SYSTEM_PROMPT",
        "You are a friendly Live2D desktop companion. Reply briefly, warmly, and in spoken language.",
    )
    request_timeout: int = int(_values.get("OPENAI_TIMEOUT", "60"))
    request_retries: int = int(_values.get("OPENAI_RETRIES", "2"))
    memory_enabled: bool = _values.get("MEMORY_ENABLED", "1").strip() not in {"0", "false", "False"}
    memory_consolidation: bool = _values.get("MEMORY_CONSOLIDATION", "1").strip() not in {"0", "false", "False"}
    memory_relevant_recall: bool = _values.get("MEMORY_RELEVANT_RECALL", "1").strip() not in {"0", "false", "False"}
    memory_semantic_recall: bool = env_flag("MEMORY_SEMANTIC_RECALL", default=False, values=_values)
    embedding_model: str = _values.get("EMBEDDING_MODEL", "").strip()
    conversation_summary: bool = _values.get("CONVERSATION_SUMMARY", "1").strip() not in {"0", "false", "False"}
    memory_limit: int = int(_values.get("MEMORY_LIMIT", "24"))
    chat_thinking: bool = env_flag("CHAT_THINKING", default=False, values=_values)
    chat_tools: bool = env_flag("CHAT_TOOLS", default=False, values=_values)
    proactive_chat: bool = env_flag("PROACTIVE_CHAT", default=False, values=_values)
    live2d_model: str = _values.get("LIVE2D_MODEL", "").strip()

    def __post_init__(self) -> None:
        self.embedding_model = self.embedding_model.strip()
        if not self.embedding_model:
            self.memory_semantic_recall = False
