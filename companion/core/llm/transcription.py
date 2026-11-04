"""Standard-library audio transcription for OpenAI-compatible endpoints."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from http.client import HTTPException, HTTPResponse


class TranscriptionError(RuntimeError):
    """Audio validation, transport, or provider response failure."""


def build_multipart_body(
    audio: bytes,
    filename: str,
    content_type: str,
    model: str,
    language: str | None = None,
    prompt: str | None = None,
) -> tuple[bytes, str]:
    """Encode form fields and an unchanged binary file with a fresh boundary."""
    if any(char in filename or char in content_type for char in "\r\n"):
        raise ValueError("filename and content_type must not contain newlines")
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in (("model", model), ("language", language), ("prompt", prompt)):
        if value is not None:
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                f'{value}\r\n'.encode()
            )
    quoted_filename = filename.replace("\\", "\\\\").replace('"', '\\"')
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{quoted_filename}"\r\nContent-Type: {content_type}\r\n\r\n'.encode()
    )
    parts.extend((audio, f"\r\n--{boundary}--\r\n".encode("ascii")))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _http_error(status: int, body: bytes, api_key: str) -> TranscriptionError:
    details = body.decode("utf-8", errors="replace")
    try:
        payload = json.loads(details)
    except ValueError:
        pass
    else:
        if isinstance(payload, dict):
            error = payload.get("error", payload)
            message = error.get("message") if isinstance(error, dict) else error
            if isinstance(message, str):
                details = message
    # Redact before truncating so a key straddling the cutoff cannot leak.
    details = details.replace(api_key, "[redacted]")
    details = details.replace(json.dumps(api_key)[1:-1], "[redacted]")
    details = " ".join(details.split())
    if len(details) > 300:
        details = details[:300] + "..."
    return TranscriptionError(f"Transcription request failed: HTTP {status} {details}".rstrip())


def transcribe(
    audio: bytes,
    *,
    base_url: str,
    api_key: str,
    model: str,
    filename: str = "speech.wav",
    content_type: str = "audio/wav",
    language: str | None = None,
    prompt: str | None = None,
    timeout: float = 30.0,
    transport: Callable[..., HTTPResponse] | None = None,
) -> str:
    """POST audio once and return stripped text.

    ``transport`` follows ``urlopen(request, timeout=...)`` and returns a
    context-managed response. The timeout is a finite positive socket timeout
    in seconds, not an overall deadline. No audio or response data is logged.
    """
    if not audio:
        raise TranscriptionError("Audio input must not be empty")
    if not api_key or not api_key.strip():
        raise TranscriptionError("An API key is required for transcription")
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")

    body, form_content_type = build_multipart_body(audio, filename, content_type, model, language, prompt)
    request = urllib.request.Request(
        base_url.rstrip("/") + "/audio/transcriptions",
        data=body,
        headers={"Content-Type": form_content_type, "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    opener = transport if transport is not None else urllib.request.urlopen
    try:
        try:
            with opener(request, timeout=timeout) as response:
                response_body = response.read()
                if not 200 <= response.status < 300:
                    raise _http_error(response.status, response_body, api_key)
        except urllib.error.HTTPError as exc:
            try:
                details = exc.read()
            except (OSError, urllib.error.URLError, HTTPException):
                details = b"Unable to read provider error"
            finally:
                exc.close()
            # Provider exception reasons can contain credentials; suppress chaining.
            raise _http_error(exc.code, details, api_key) from None
    except (urllib.error.URLError, OSError, HTTPException):
        raise TranscriptionError("Transcription request failed: network error or timeout") from None

    try:
        payload = json.loads(response_body.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise TranscriptionError("Transcription response contained malformed JSON") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
        raise TranscriptionError("Transcription response must include a text string")
    return payload["text"].strip()
