"""Custom voices: choosing the provider, the /audio/speech request, and falling back to Edge."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import Mock

import pytest
from test_voice_input_qt_adapters import load_class

from companion.adapters import tts_openai
from companion.core.tts_provider import CustomVoice, custom_voice, rate_to_speed

KEY = "sk-voice-secret"


CHAT = "https://api.deepseek.com/v1"
DASHSCOPE = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_edge_is_the_default_and_incomplete_settings_fall_back_to_it():
    assert custom_voice("edge", "", "m", "v", CHAT, KEY, "") == (None, "")
    assert custom_voice("openai", "", "", "v", CHAT, KEY, "") == (None, "")
    assert custom_voice("openai", "", "m", " ", CHAT, KEY, "") == (None, "")


def test_same_host_as_chat_reuses_the_chat_key():
    voice, reason = custom_voice("OPENAI", "", " tts-1 ", " girl-01 ", CHAT + "/", KEY, "")

    assert voice == CustomVoice("openai", CHAT, "tts-1", "girl-01", KEY)
    assert reason == ""


def test_another_provider_never_gets_the_chat_key():
    voice, reason = custom_voice("openai", DASHSCOPE, "m", "v", CHAT, KEY, "")

    assert voice is None
    assert "no key of its own" in reason


def test_another_provider_with_its_own_key():
    voice, _ = custom_voice("openai", DASHSCOPE, "m", "v", CHAT, KEY, "sk-own")

    assert voice.api_key == "sk-own"


def test_a_local_server_gets_no_key_unless_one_is_set():
    voice, _ = custom_voice("openai", "http://127.0.0.1:9880/v1", "m", "v", CHAT, KEY, "")
    assert voice.api_key == ""
    voice, _ = custom_voice("openai", "http://127.0.0.1:9880/v1", "m", "v", CHAT, KEY, "sk-local")
    assert voice.api_key == "sk-local"


def test_no_authorization_header_without_a_key():
    request = tts_openai.speech_request(CustomVoice("openai", "http://127.0.0.1:1/v1", "m", "v", ""), "hi", 1.0)

    assert request.get_header("Authorization") is None
    with_key = tts_openai.speech_request(CustomVoice("openai", "https://x.example/v1", "m", "v", KEY), "hi", 1.0)
    assert with_key.get_header("Authorization") == f"Bearer {KEY}"


@pytest.mark.parametrize(("rate", "speed"), [("+6%", 1.06), ("-10%", 0.9), ("+0%", 1.0), ("fast", 1.0), ("-99%", 0.5)])
def test_rate_becomes_speed(rate, speed):
    assert rate_to_speed(rate) == pytest.approx(speed)


class Handler(BaseHTTPRequestHandler):
    status = 200
    requests: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Handler.requests.append((self.path, self.headers["Authorization"], body))
        self.send_response(Handler.status)
        self.end_headers()
        self.wfile.write(b"ID3fake-mp3" if Handler.status == 200 else f"bad key {KEY}".encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    Handler.requests, Handler.status = [], 200
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}/v1"
    httpd.shutdown()


def test_speech_request_and_audio_file(server):
    voice = CustomVoice("openai", server, "tts-1", "girl-01", KEY)

    path = tts_openai.synthesize_to_file(voice, "你好呀", speed=1.06)

    assert Path(path).read_bytes() == b"ID3fake-mp3"
    Path(path).unlink()
    route, auth, body = Handler.requests[0]
    assert route == "/v1/audio/speech"
    assert auth == f"Bearer {KEY}"
    assert body == {"model": "tts-1", "input": "你好呀", "voice": "girl-01", "response_format": "mp3", "speed": 1.06}


def test_http_errors_never_echo_the_key(server):
    Handler.status = 401

    with pytest.raises(RuntimeError) as excinfo:
        tts_openai.synthesize_to_file(CustomVoice("openai", server, "m", "v", KEY), "hi")

    assert "HTTP 401" in str(excinfo.value)
    assert KEY not in str(excinfo.value)


def test_unreachable_service_is_reported_by_type():
    with pytest.raises(RuntimeError, match="unreachable"):
        tts_openai.synthesize_to_file(CustomVoice("openai", "http://127.0.0.1:9/v1", "m", "v", KEY), "hi", timeout=1)


def worker_class(**dependencies):
    return load_class("companion/app/workers.py", "TTSWorker", rate_to_speed=rate_to_speed, **dependencies)


def test_worker_uses_the_custom_voice(monkeypatch):
    openai = Mock(synthesize_to_file=Mock(return_value="/tmp/custom.mp3"))
    edge = Mock()
    worker = worker_class(tts_openai=openai, tts_edge=edge, asyncio=Mock())(
        "你好", "zh-CN-XiaoyiNeural", "+6%", "+10Hz", CustomVoice("openai", "u", "m", "v", KEY),
    )
    done = []
    worker.finished.connect(done.append)

    worker.run()

    assert done == ["/tmp/custom.mp3"]
    openai.synthesize_to_file.assert_called_once()
    edge.synthesize_to_file.assert_not_called()


def test_worker_falls_back_to_edge_and_says_why():
    openai = Mock(synthesize_to_file=Mock(side_effect=RuntimeError("Voice service returned HTTP 503")))
    asyncio = Mock(run=Mock(return_value="/tmp/edge.mp3"))
    worker = worker_class(tts_openai=openai, tts_edge=Mock(), asyncio=asyncio)(
        "你好", "zh-CN-XiaoyiNeural", custom=CustomVoice("openai", "u", "m", "v", KEY),
    )
    done, fell = [], []
    worker.finished.connect(done.append)
    worker.fellBack.connect(fell.append)

    worker.run()

    assert done == ["/tmp/edge.mp3"]
    assert fell == ["Voice service returned HTTP 503"]
