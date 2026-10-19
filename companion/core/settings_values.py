from __future__ import annotations

import logging
import os
from collections.abc import Mapping

from companion import paths
from companion.core.settings_file import load_settings

logger = logging.getLogger(__name__)

# Only application settings are accepted; environment variables used by Python,
# Qt, or other libraries must not be supplied through config.json.
SETTING_NAMES = frozenset({
    "OPENAI_BASE_URL", "MOONSHOT_BASE_URL", "OPENAI_MODEL", "MOONSHOT_MODEL",
    "EDGE_TTS_VOICE", "EDGE_TTS_VOICE_ZH", "EDGE_TTS_VOICE_EN",
    "COMPANION_SYSTEM_PROMPT", "OPENAI_TIMEOUT", "OPENAI_RETRIES",
    "MEMORY_ENABLED", "MEMORY_CONSOLIDATION", "MEMORY_RELEVANT_RECALL",
    "MEMORY_SEMANTIC_RECALL", "EMBEDDING_MODEL", "CONVERSATION_SUMMARY",
    "MEMORY_LIMIT", "CHAT_THINKING", "CHAT_TOOLS", "PROACTIVE_CHAT",
    "LOG_LEVEL", "LIVE2D_MODEL", "LIVE2D_VENDOR_DIR",
})
SECRET_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD")


def merge_settings(raw_settings: object, environment: Mapping[str, str]) -> dict[str, str]:
    """Return JSON scalars overlaid by the environment, without changing either input.

    Missing values stay absent so each consumer retains its existing defaults and
    parsing rules. Diagnostics name rejected keys but never include their values.
    """
    values: dict[str, str] = {}
    if isinstance(raw_settings, Mapping):
        for name, value in raw_settings.items():
            if any(marker in name.upper() for marker in SECRET_MARKERS):
                logger.warning("Ignoring secret setting in config.json: %s", name)
            elif name == "COMPANION_DATA_DIR":
                logger.warning("Ignoring data directory setting in config.json: %s", name)
            elif name not in SETTING_NAMES:
                logger.debug("Ignoring unknown setting in config.json: %s", name)
            elif isinstance(value, bool):
                values[name] = "1" if value else "0"
            elif isinstance(value, (str, int, float)):
                values[name] = str(value)
            else:
                logger.debug("Ignoring non-scalar setting in config.json: %s", name)
    values.update(environment)
    return values


def load_setting_values() -> dict[str, str]:
    """Read the optional settings section after paths has loaded the project .env."""
    return merge_settings(load_settings(paths.CONFIG_PATH).get("settings"), os.environ)
