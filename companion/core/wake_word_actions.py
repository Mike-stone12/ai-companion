"""Desktop wake-word enablement without GUI or recognizer dependencies."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from companion.core.config import AppConfig


def wake_word_enabled(config: AppConfig) -> bool:
    """Detection needs both local recognition settings and usable voice input."""
    return config.wake_word_usable and config.voice_input_usable
