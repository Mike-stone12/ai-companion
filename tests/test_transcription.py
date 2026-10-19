import io
import json
import traceback
import urllib.error
from email import policy
from email.parser import BytesParser
from http.client import IncompleteRead

import pytest

from companion.core.llm.transcription import TranscriptionError, build_multipart_body, transcribe

API_KEY = "secret-transcription-key"
AUDIO = b"RIFF\x00\xff\x80\r\nrecorded audio\x00"


class FakeResponse(io.BytesIO):
    def __init__(self, body=b'{"text": "  Hello world!\\n"}', status=200):
        super().__init__(body)
        self.status = status


class FakeTransport:
    def __init__(self, result=None):
        self.result = result if result is not None else FakeResponse()
        self.calls = []

    def __call__(self, request, timeout):
        self.calls.append((request, timeout))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def run_transcription(transport, **kwargs):
    options = dict(base_url="https://example.test/v1", api_key=API_KEY, model="whisper-1")
    options.update(kwargs)
    return transcribe(options.pop("audio", AUDIO), transport=transport, **options)


def parse_multipart(body, content_type):
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
    )
    assert message.is_multipart()
    assert not message.defects
    boundary = message.get_boundary().encode()
    assert body.startswith(b"--" + boundary + b"\r\n")
    assert body.endswith(b"\r\n--" + boundary + b"--\r\n")
    return {part.get_param("name", header="content-disposition"): part for part in message.iter_parts()}


@pytest.mark.parametrize("suffix", ["", "/", "///"])
@pytest.mark.parametrize("timeout", [30.0, 7.5])
def test_request_and_success(suffix, timeout):
    transport = FakeTransport()
    kwargs = {} if timeout == 30.0 else {"timeout": timeout}
    assert run_transcription(transport, base_url="https://example.test/v1" + suffix, **kwargs) == "Hello world!"
    assert len(transport.calls) == 1
    request, actual_timeout = transport.calls[0]
    assert request.full_url == "https://example.test/v1/audio/transcriptions"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == f"Bearer {API_KEY}"
    assert actual_timeout == timeout
    parts = parse_multipart(request.data, request.get_header("Content-type"))
    assert set(parts) == {"model", "file"}
    assert parts["model"].get_payload(decode=True) == b"whisper-1"
    assert parts["file"].get_filename() == "speech.wav"
    assert parts["file"].get_content_type() == "audio/wav"
    assert parts["file"].get_payload(decode=True) == AUDIO
    assert transport.result.closed


@pytest.mark.parametrize("language,prompt", [(None, None), ("en", "Names: Zoë"), ("", "")])
def test_optional_fields_and_custom_file(language, prompt):
    transport = FakeTransport()
    run_transcription(transport, filename="voice.webm", content_type="audio/webm", language=language, prompt=prompt)
    request, _ = transport.calls[0]
    parts = parse_multipart(request.data, request.get_header("Content-type"))
    for name, value in (("language", language), ("prompt", prompt)):
        if value is None:
            assert name not in parts
        else:
            assert parts[name].get_payload(decode=True) == value.encode("utf-8")
    assert parts["file"].get_filename() == "voice.webm"
    assert parts["file"].get_content_type() == "audio/webm"
    assert parts["file"].get_payload(decode=True) == AUDIO


def test_builder_uses_unique_boundaries_and_escapes_filename():
    filename = 'my "speech".wav'
    body, content_type = build_multipart_body(AUDIO, filename, "audio/wav", "whisper-1")
    _, other_content_type = build_multipart_body(AUDIO, filename, "audio/wav", "whisper-1")
    assert content_type != other_content_type
    assert parse_multipart(body, content_type)["file"].get_filename() == filename


@pytest.mark.parametrize("kwargs", [{"filename": "bad\r\nname"}, {"content_type": "audio/wav\ninvalid"}])
def test_invalid_part_headers(kwargs):
    transport = FakeTransport()
    with pytest.raises(ValueError, match="newlines"):
        run_transcription(transport, **kwargs)
    assert not transport.calls


@pytest.mark.parametrize("kwargs,match", [
    ({"audio": b""}, "Audio"), ({"api_key": ""}, "API key"),
    ({"api_key": None}, "API key"), ({"api_key": "  "}, "API key"),
])
def test_invalid_input_before_request(kwargs, match):
    transport = FakeTransport()
    with pytest.raises(TranscriptionError, match=match):
        run_transcription(transport, **kwargs)
    assert transport.calls == []


@pytest.mark.parametrize("status", [400, 401, 429, 500])
@pytest.mark.parametrize("raises_http_error", [False, True])
def test_http_errors_are_truncated_and_redacted(status, raises_http_error, caplog):
    message = f"Provider rejected {API_KEY}: " + "x" * 1000
    body = json.dumps({"error": {"message": message}}).encode()
    result = (
        urllib.error.HTTPError("https://example.test", status, API_KEY, {}, io.BytesIO(body))
        if raises_http_error else FakeResponse(body, status)
    )
    with pytest.raises(TranscriptionError, match=f"HTTP {status}") as caught:
        run_transcription(FakeTransport(result))
    assert "Provider rejected [redacted]" in str(caught.value)
    assert str(caught.value).endswith("...")
    assert len(str(caught.value)) < 400
    assert API_KEY not in "".join(traceback.format_exception(caught.value))
    assert API_KEY not in caplog.text
    assert (result.fp if raises_http_error else result).closed


def test_plain_text_http_error_redacts_key_before_cutoff():
    body = ("x" * 290 + API_KEY + " remainder").encode()
    with pytest.raises(TranscriptionError) as caught:
        run_transcription(FakeTransport(FakeResponse(body, 502)))
    assert "secret-" not in str(caught.value)
    assert "HTTP 502" in str(caught.value)


@pytest.mark.parametrize("error", [
    urllib.error.URLError(API_KEY), TimeoutError(API_KEY), OSError(API_KEY), IncompleteRead(API_KEY.encode()),
])
def test_network_errors(error, caplog):
    with pytest.raises(TranscriptionError, match="network error or timeout") as caught:
        run_transcription(FakeTransport(error))
    assert API_KEY not in "".join(traceback.format_exception(caught.value))
    assert API_KEY not in caplog.text


class BrokenResponse(FakeResponse):
    def read(self, *args):
        raise TimeoutError(API_KEY)


def test_read_timeout_closes_response():
    response = BrokenResponse()
    with pytest.raises(TranscriptionError, match="timeout"):
        run_transcription(FakeTransport(response))
    assert response.closed


def test_http_error_with_unreadable_body_keeps_status():
    response = BrokenResponse()
    error = urllib.error.HTTPError("https://example.test", 503, API_KEY, {}, response)
    with pytest.raises(TranscriptionError, match="HTTP 503") as caught:
        run_transcription(FakeTransport(error))
    assert API_KEY not in "".join(traceback.format_exception(caught.value))
    assert response.closed


@pytest.mark.parametrize("body", [b"not JSON", b"{", b"\xff", API_KEY.encode()])
def test_invalid_json(body):
    with pytest.raises(TranscriptionError, match="JSON") as caught:
        run_transcription(FakeTransport(FakeResponse(body)))
    assert API_KEY not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("payload", [{}, [], None, {"text": None}, {"text": 123}, {"text": [API_KEY]}])
def test_missing_or_invalid_text(payload):
    with pytest.raises(TranscriptionError, match="text") as caught:
        run_transcription(FakeTransport(FakeResponse(json.dumps(payload).encode())))
    assert API_KEY not in str(caught.value)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), None, "30"])
def test_timeout_must_be_finite_and_positive(timeout):
    transport = FakeTransport()
    with pytest.raises(ValueError, match="timeout"):
        run_transcription(transport, timeout=timeout)
    assert not transport.calls
