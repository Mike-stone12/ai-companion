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


def _parse_wake_word_phrases(raw: str) -> tuple[str, ...]:
    phrases = (phrase.strip() for phrase in raw.replace("，", ",").split(","))
    return tuple(dict.fromkeys(phrase for phrase in phrases if phrase))


@dataclass(slots=True)
class AppConfig:
    base_url: str = _values.get("OPENAI_BASE_URL") or _values.get("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1")
    api_key: str = os.getenv("OPENAI_API_KEY") or os.getenv("MOONSHOT_API_KEY", "")
    model: str = _values.get("OPENAI_MODEL") or _values.get("MOONSHOT_MODEL", "kimi-k2.6")
    voice: str = _values.get("EDGE_TTS_VOICE", "zh-CN-XiaoyiNeural")
    voice_zh: str = _values.get("EDGE_TTS_VOICE_ZH", _values.get("EDGE_TTS_VOICE", "zh-CN-XiaoyiNeural"))
    voice_en: str = _values.get("EDGE_TTS_VOICE_EN", "en-US-AriaNeural")
    # Applied to the Chinese voice only, as Edge TTS offsets ("+10Hz", "+6%").
    tts_pitch: str = _values.get("TTS_PITCH", "+10Hz").strip()
    tts_rate: str = _values.get("TTS_RATE", "+6%").strip()
    # Optional expert override; empty uses the active persona (companion/core/persona.py).
    system_prompt: str = _values.get("COMPANION_SYSTEM_PROMPT", "").strip()
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
    voice_input: bool = env_flag("VOICE_INPUT", default=False, values=_values)
    # Require an explicit model before voice input can be used.
    transcription_model: str = _values.get("TRANSCRIPTION_MODEL", "").strip()
    wake_word: bool = env_flag("WAKE_WORD", default=False, values=_values)
    wake_word_phrases: tuple[str, ...] = _parse_wake_word_phrases(_values.get("WAKE_WORD_PHRASES", ""))
    wake_word_model_dir: str = _values.get("WAKE_WORD_MODEL_DIR", "").strip()
    proactive_chat: bool = env_flag("PROACTIVE_CHAT", default=False, values=_values)
    active_app_monitor: bool = env_flag("ACTIVE_APP_MONITOR", default=False, values=_values)
    live2d_model: str = _values.get("LIVE2D_MODEL", "").strip()
    companion_state: bool = env_flag("COMPANION_STATE", default=True, values=_values)
    daily_schedule: bool = env_flag("DAILY_SCHEDULE", default=True, values=_values)
    emotion_appraisal: bool = env_flag("EMOTION_APPRAISAL", default=True, values=_values)
    mood_half_life_minutes: int = int(_values.get("MOOD_HALF_LIFE_MINUTES", "120"))

    @property
    def voice_input_usable(self) -> bool:
        """Whether push-to-talk is opted into with a configured model."""
        return self.voice_input and bool(self.transcription_model.strip())

    @property
    def wake_word_usable(self) -> bool:
        """Whether wake word is opted into with phrases and a model directory string."""
        return (
            self.wake_word
            and any(phrase.strip() for phrase in self.wake_word_phrases)
            and bool(self.wake_word_model_dir.strip())
        )

    def __post_init__(self) -> None:
        self.embedding_model = self.embedding_model.strip()
        if not self.embedding_model:
            self.memory_semantic_recall = False
