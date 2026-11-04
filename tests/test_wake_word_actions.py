import pytest

from companion.core.config import AppConfig
from companion.core.wake_word_actions import wake_word_enabled


@pytest.mark.parametrize("overrides,expected", [
    ({}, True),
    ({"wake_word": False}, False),
    ({"wake_word_phrases": ()}, False),
    ({"wake_word_phrases": ("",)}, False),
    ({"wake_word_phrases": (" \t\n",)}, False),
    ({"wake_word_model_dir": ""}, False),
    ({"wake_word_model_dir": " \t\n"}, False),
    ({"voice_input": False}, False),
    ({"transcription_model": ""}, False),
    ({"transcription_model": " \t\n"}, False),
])
def test_wake_word_requires_recognition_and_voice_input(overrides, expected):
    config = AppConfig(**{
        "wake_word": True, "wake_word_phrases": ("hey whale",),
        "wake_word_model_dir": "model", "voice_input": True,
        "transcription_model": "transcribe", **overrides,
    })
    assert wake_word_enabled(config) is expected
