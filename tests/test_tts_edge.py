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
