"""Metadata and validated persistence for settings a future panel may edit."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from companion.core import settings_file
from companion.core.model_profile import DEFAULT_MODEL
from companion.core.settings_values import SECRET_MARKERS
from companion.core.url_security import is_plaintext_remote_url

SettingValue = bool | int | float | str


@dataclass(frozen=True, slots=True)
class Setting:
    name: str
    kind: Literal["bool", "int", "float", "choice", "str"]
    default: SettingValue
    label: str
    choices: tuple[str, ...] = ()
    minimum: int | float | None = None
    maximum: int | float | None = None


# These are built-in defaults, never values from an environment-configured
# AppConfig instance. Tests compare them with the existing consumers' defaults.
# An empty LIVE2D_MODEL selects DEFAULT_MODEL in model_profile.
EDITABLE_SETTINGS = (
    Setting("OPENAI_BASE_URL", "str", "https://api.moonshot.ai/v1", "Chat API base URL (OpenAI-compatible)"),
    Setting("OPENAI_MODEL", "str", "kimi-k2.6", "Chat model"),
    Setting("VISION_MODEL", "str", "", "Picture model (empty: automatic on DeepSeek, otherwise off)"),
    Setting("VISION_BASE_URL", "str", "", "Picture API base URL (empty: same as chat)"),
    Setting("CHAT_THINKING", "bool", False, "Chat reasoning"),
    Setting("CHAT_TOOLS", "bool", False, "Chat tools"),
    Setting("VOICE_INPUT", "bool", False, "Push-to-talk voice input (requires transcription model)"),
    Setting("TRANSCRIPTION_MODEL", "str", "", "Transcription model"),
    Setting("WAKE_WORD", "bool", False, "Wake word (requires wake phrases and model directory)"),
    Setting("WAKE_WORD_PHRASES", "str", "", "Wake phrases (comma-separated)"),
    Setting("WAKE_WORD_MODEL_DIR", "str", "", "Wake-word Vosk model directory"),
    Setting(
        "COMPANION_STATE", "bool", True, "Companion feelings that carry over between replies (also colour the voice)",
    ),
    Setting("EMOTION_APPRAISAL", "bool", True, "Judge emotional turns with one extra LLM request"),
    Setting("REPLY_PACING", "bool", True, "Reply in a few short messages with typing pauses"),
    Setting("COMPANION_DIARY", "bool", True, "Companion keeps a diary and remembers what it said about itself"),
    Setting("MOOD_HALF_LIFE_MINUTES", "int", 120, "Mood half-life (minutes)", minimum=5),
    Setting("DAILY_SCHEDULE", "bool", True, "Daily routine (sleeps, studies, has evenings off)"),
    Setting("PROACTIVE_CHAT", "bool", False, "Proactive chat"),
    Setting("ACTIVE_APP_MONITOR", "bool", False, "Active app monitor (requires proactive chat)"),
    Setting("LOG_LEVEL", "choice", "INFO", "Log level", choices=("DEBUG", "INFO", "WARNING", "ERROR")),
    Setting("EDGE_TTS_VOICE_ZH", "str", "zh-CN-XiaoyiNeural", "Chinese voice"),
    Setting("TTS_PITCH", "str", "+10Hz", "Chinese voice pitch offset (e.g. +10Hz)"),
    Setting("TTS_RATE", "str", "+6%", "Chinese voice speed offset (e.g. +6%)"),
    Setting("TTS_PROVIDER", "choice", "EDGE", "Voice provider (OPENAI = custom /audio/speech voice)",
            choices=("EDGE", "OPENAI")),
    Setting("TTS_BASE_URL", "str", "", "Custom voice API base URL (empty: same as chat)"),
    Setting("TTS_MODEL", "str", "", "Custom voice model"),
    Setting("TTS_VOICE", "str", "", "Custom voice name or ID (AI-generated or licensed voices only)"),
    Setting("EDGE_TTS_VOICE_EN", "str", "en-US-AriaNeural", "English voice"),
    Setting("MEMORY_ENABLED", "bool", True, "Memory extraction"),
    Setting("MEMORY_CONSOLIDATION", "bool", True, "Memory consolidation"),
    Setting("MEMORY_RELEVANT_RECALL", "bool", True, "Relevant memory recall"),
    Setting("MEMORY_SEMANTIC_RECALL", "bool", False, "Semantic memory recall"),
    Setting("EMBEDDING_MODEL", "str", "", "Embedding model"),
    Setting("CONVERSATION_SUMMARY", "bool", True, "Conversation summary"),
    Setting("MEMORY_LIMIT", "int", 24, "Memory limit", minimum=1),
    Setting("LIVE2D_MODEL", "str", DEFAULT_MODEL, "Live2D model"),
)
_SETTINGS_BY_NAME = {setting.name: setting for setting in EDITABLE_SETTINGS}
PROSODY_PATTERNS = {"TTS_PITCH": re.compile(r"[+-]\d{1,3}Hz"), "TTS_RATE": re.compile(r"[+-]\d{1,2}%")}
PROSODY_LIMITS = {"TTS_PITCH": 100, "TTS_RATE": 99}


def valid_prosody(name: str, value: str) -> bool:
    """Edge TTS offsets: pitch within ±100 Hz, rate within ±99 %."""
    if not PROSODY_PATTERNS[name].fullmatch(value):
        return False
    return abs(int(value.rstrip("Hz%"))) <= PROSODY_LIMITS[name]


def validate(name: str, value: SettingValue) -> SettingValue:
    """Return a JSON scalar or raise ValueError without echoing its value.

    Booleans and integers require their exact Python types (no text coercion,
    and bool is not an integer here). Float settings accept finite ints/floats.
    Log levels are stripped and uppercased. Model names, model directories and wake
    phrases are stripped like the existing loader; voice strings are preserved as supplied.
    """
    if not isinstance(name, str) or any(marker in name.upper() for marker in SECRET_MARKERS):
        raise ValueError("Setting name is not editable")
    setting = _SETTINGS_BY_NAME.get(name)
    if setting is None:
        raise ValueError(f"Setting is not editable: {name}")

    if setting.kind == "bool":
        if type(value) is not bool:
            raise ValueError(f"{name} requires a boolean")
    elif setting.kind in {"int", "float"}:
        accepted_types = (int,) if setting.kind == "int" else (int, float)
        if type(value) not in accepted_types:
            raise ValueError(f"{name} requires an {setting.kind}")
        if setting.kind == "float":
            try:
                value = float(value)
            except OverflowError as exc:
                raise ValueError(f"{name} requires a finite number") from exc
            if not math.isfinite(value):
                raise ValueError(f"{name} requires a finite number")
        if setting.minimum is not None and value < setting.minimum:
            raise ValueError(f"{name} is below its minimum")
        if setting.maximum is not None and value > setting.maximum:
            raise ValueError(f"{name} is above its maximum")
    else:
        if not isinstance(value, str):
            raise ValueError(f"{name} requires a string")
        if setting.kind == "choice":
            value = value.strip().upper()
            if value not in setting.choices:
                raise ValueError(f"{name} requires an allowed choice")
        elif name in {
            "EMBEDDING_MODEL", "LIVE2D_MODEL", "TRANSCRIPTION_MODEL", "WAKE_WORD_PHRASES", "WAKE_WORD_MODEL_DIR",
        }:
            value = value.strip()
        elif name in {"TTS_PITCH", "TTS_RATE"}:
            value = value.strip()
            if not valid_prosody(name, value):
                example = "+10Hz" if name == "TTS_PITCH" else "+6%"
                raise ValueError(f"{name} requires a signed offset such as {example}")
        elif name in {"TTS_MODEL", "TTS_VOICE"}:
            value = value.strip()
        elif name == "TTS_BASE_URL" and not value.strip():
            value = ""
        elif name == "OPENAI_MODEL":
            value = value.strip()
            if not value:
                raise ValueError(f"{name} requires a model name")
        elif name == "VISION_MODEL":
            value = value.strip()
        elif name == "VISION_BASE_URL" and not value.strip():
            value = ""
        elif name in {"OPENAI_BASE_URL", "VISION_BASE_URL", "TTS_BASE_URL"}:
            value = value.strip().rstrip("/")
            try:
                parts = urlsplit(value)
                plaintext_remote = is_plaintext_remote_url(value)
            except ValueError as exc:
                raise ValueError(f"{name} requires an http(s) URL") from exc
            if parts.scheme not in {"http", "https"} or not parts.netloc or any(char.isspace() for char in value):
                raise ValueError(f"{name} requires an http(s) URL")
            if plaintext_remote:
                raise ValueError(
                    f"{name} must use https unless the host is loopback (localhost, 127.0.0.0/8, ::1)"
                )
    return value


def parse_value(name: str, raw: SettingValue) -> SettingValue:
    """Parse editor text (JSON for typed settings), then validate via the schema.

    Typed widget values are also accepted. Invalid text is passed to validate
    so errors describe the required type without echoing the input.
    """
    setting = _SETTINGS_BY_NAME.get(name) if isinstance(name, str) else None
    if setting is not None and setting.kind in {"bool", "int", "float"} and isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            pass
    return validate(name, raw)


def save_settings(config_path: Path, updates: dict[str, SettingValue]) -> None:
    """Validate the whole batch, merge it into config.json, and write atomically.

    Other sections and unedited settings are preserved. A non-object settings
    section is rejected rather than replaced. Empty updates are a no-op. Values
    take effect on the next configuration load, with existing env precedence.
    """
    if not isinstance(updates, dict):
        raise ValueError("Settings updates must be an object")
    normalized = {name: validate(name, value) for name, value in updates.items()}
    if not normalized:
        return
    config = settings_file.load_settings(config_path)
    current = config.get("settings", {})
    if not isinstance(current, dict):
        raise ValueError("Existing settings must be an object")
    config["settings"] = {**current, **normalized}
    settings_file.save_settings(config_path, config)
