import asyncio
import tempfile
from pathlib import Path

import pytest

from companion.adapters import tts_edge


def temp_mp3s():
    return set(Path(tempfile.gettempdir()).glob("tmp*.mp3"))


class FakeCommunicate:
    instances = []
    behaviour = "ok"

    def __init__(self, text, voice, **kwargs):
        self.kwargs = kwargs
        FakeCommunicate.instances.append(self)

    async def save(self, path):
        if self.behaviour == "hang":
            await asyncio.sleep(30)
        if self.behaviour == "error":
            Path(path).write_bytes(b"partial")
            raise ConnectionError("network unreachable")
        Path(path).write_bytes(b"ID3 fake mp3")


@pytest.fixture
def fake_edge_tts(monkeypatch):
    FakeCommunicate.instances = []
    FakeCommunicate.behaviour = "ok"
    monkeypatch.setattr(tts_edge, "edge_tts", type("FakeModule", (), {"Communicate": FakeCommunicate}))
    return FakeCommunicate


def test_successful_synthesis_returns_the_file(fake_edge_tts):
    path = asyncio.run(tts_edge.synthesize_to_file("你好", "zh-CN-XiaoxiaoNeural"))
    assert Path(path).read_bytes() == b"ID3 fake mp3"
    Path(path).unlink()


def test_network_timeouts_are_shortened(fake_edge_tts):
    path = asyncio.run(tts_edge.synthesize_to_file("你好", "zh-CN-XiaoxiaoNeural"))
    Path(path).unlink()
    kwargs = fake_edge_tts.instances[0].kwargs
    assert kwargs["connect_timeout"] == tts_edge.TTS_CONNECT_TIMEOUT_S
    assert kwargs["receive_timeout"] == tts_edge.TTS_RECEIVE_TIMEOUT_S


def test_hanging_synthesis_times_out_and_cleans_up(fake_edge_tts):
    fake_edge_tts.behaviour = "hang"
    before = temp_mp3s()
    with pytest.raises(RuntimeError, match="timed out"):
        asyncio.run(tts_edge.synthesize_to_file("你好", "zh-CN-XiaoxiaoNeural", timeout=0.2))
    assert temp_mp3s() == before


def test_failed_synthesis_removes_the_partial_file(fake_edge_tts):
    fake_edge_tts.behaviour = "error"
    before = temp_mp3s()
    with pytest.raises(ConnectionError):
        asyncio.run(tts_edge.synthesize_to_file("你好", "zh-CN-XiaoxiaoNeural"))
    assert temp_mp3s() == before


def test_missing_edge_tts_is_reported(monkeypatch):
    monkeypatch.setattr(tts_edge, "edge_tts", None)
    with pytest.raises(RuntimeError, match="not installed"):
        asyncio.run(tts_edge.synthesize_to_file("你好", "zh-CN-XiaoxiaoNeural"))


def test_default_chinese_voice_is_the_lively_one_and_english_is_unchanged():
    from companion.core.config import AppConfig

    config = AppConfig()

    assert config.voice_zh == "zh-CN-XiaoyiNeural"
    assert config.voice_en == "en-US-AriaNeural"


def test_prosody_applies_to_chinese_only():
    from companion.core.config import AppConfig

    config = AppConfig(tts_pitch="+12Hz", tts_rate="+7%")

    assert tts_edge.choose_tts_prosody(config, "你好呀") == ("+7%", "+12Hz")
    assert tts_edge.choose_tts_prosody(config, "Hello there") == ("+0%", "+0Hz")


def test_rate_and_pitch_reach_edge_tts(fake_edge_tts):
    path = asyncio.run(tts_edge.synthesize_to_file("你好", "zh-CN-XiaoyiNeural", rate="+6%", pitch="+10Hz"))
    Path(path).unlink()

    assert fake_edge_tts.instances[-1].kwargs["rate"] == "+6%"
    assert fake_edge_tts.instances[-1].kwargs["pitch"] == "+10Hz"


@pytest.mark.parametrize(("name", "value"), [("TTS_PITCH", "10Hz"), ("TTS_PITCH", "+10"), ("TTS_PITCH", "+500Hz"),
                                             ("TTS_RATE", "+5"), ("TTS_RATE", "fast"), ("TTS_RATE", "+150%")])
def test_invalid_prosody_settings_are_rejected(name, value):
    from companion.core.settings_schema import validate

    with pytest.raises(ValueError, match=name):
        validate(name, value)


@pytest.mark.parametrize(("name", "value"), [("TTS_PITCH", " +12Hz "), ("TTS_PITCH", "-5Hz"), ("TTS_RATE", "+10%")])
def test_valid_prosody_settings_are_normalized(name, value):
    from companion.core.settings_schema import validate

    assert validate(name, value) == value.strip()


def test_invalid_prosody_from_the_environment_falls_back_to_neutral():
    from companion.core.config import AppConfig

    config = AppConfig(tts_pitch="loud", tts_rate="+5")

    assert tts_edge.choose_tts_prosody(config, "你好") == ("+0%", "+0Hz")
