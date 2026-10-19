from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Iterator

from companion.core.config import AppConfig
from companion.core.llm.sse import iter_chat_chunks, iter_content_deltas
from companion.core.text import sanitize_reply_text

logger = logging.getLogger(__name__)


# Bound the wait for streamed content: DeepSeek, when overloaded, answers 200 and then sends only
# keep-alive comments every ~12 s, which never trips the socket timeout.
STREAM_FIRST_CONTENT_TIMEOUT_S = 30
STREAM_IDLE_TIMEOUT_S = 30
THINKING_TOGGLE_PROVIDERS = ("moonshot", "deepseek")
THINKING_DISABLED = {"thinking": {"type": "disabled"}}


def supports_thinking_toggle(base_url: str) -> bool:
    # Providers without the toggle reject the unknown "thinking" field.
    return any(provider in base_url for provider in THINKING_TOGGLE_PROVIDERS)


def chat_request_options(config: AppConfig) -> dict:
    # Reasoning roughly doubles reply latency and makes replies too long to speak; a companion
    # rarely needs it. Temperature is left to the provider: Moonshot only accepts 1 with
    # thinking on and 0.6 with it off.
    if not config.chat_thinking and supports_thinking_toggle(config.base_url):
        return dict(THINKING_DISABLED)
    return {}


class OpenAICompatibleClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def chat(self, messages: list[dict[str, str]]) -> str:
        if not self.config.api_key:
            return (
                "Demo mode is active. Set OPENAI_API_KEY, OPENAI_BASE_URL, and OPENAI_MODEL "
                "to enable live responses."
            )
        return sanitize_reply_text(self.complete(messages, extra=chat_request_options(self.config)))

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        extra: dict | None = None,
        retry_delays: tuple[float, ...] | None = None,
    ) -> str:
        payload: dict = {"model": self.config.model, "messages": messages, **(extra or {})}
        if temperature is not None:
            payload["temperature"] = temperature
        with self._open(payload, retry_delays) as response:
            data = json.loads(response.read().decode("utf-8"))

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("LLM response did not include any choices.")

        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            text_parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
            ]
            content = "\n".join(part for part in text_parts if part).strip()

        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("LLM response content was empty.")

        return content.strip()

    def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        tool_choice: str | dict | None = None,
    ) -> Iterator[str | dict]:
        """Yield raw text without tools, or OpenAI chunk dicts with non-empty tools.

        Chunk dicts retain content, tool-call fragments, and finish reasons.
        Use ``stream_chat_chunks`` for a consistent dict interface across tool rounds.
        """
        if tools:
            yield from self.stream_chat_chunks(messages, tools, tool_choice=tool_choice)
            return
        with self._open_chat_stream(messages) as response:
            yield from iter_content_deltas(
                response,
                first_content_timeout=STREAM_FIRST_CONTENT_TIMEOUT_S,
                idle_timeout=STREAM_IDLE_TIMEOUT_S,
            )

    def stream_chat_chunks(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        tool_choice: str | dict | None = None,
    ) -> Iterator[dict]:
        """Yield OpenAI chunks; pass this bound method to ``run_tool_rounds``.

        The output stays dict-shaped even with no tools. Tool choice is only
        sent when tools is non-empty; text and tool arguments are not sanitized.
        """
        with self._open_chat_stream(messages, tools, tool_choice) as response:
            yield from iter_chat_chunks(
                response,
                first_content_timeout=STREAM_FIRST_CONTENT_TIMEOUT_S,
                idle_timeout=STREAM_IDLE_TIMEOUT_S,
            )

    def _open_chat_stream(self, messages: list[dict], tools=None, tool_choice=None):
        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": True,
            **chat_request_options(self.config),
        }
        if tools:
            payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
        return self._open(payload, None)

    def _open(self, payload: dict, retry_delays: tuple[float, ...] | None):
        if retry_delays is None:
            retry_delays = tuple(min(4, attempt) for attempt in range(1, self.config.request_retries + 1))

        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }

        attempt_count = len(retry_delays) + 1
        for attempt in range(1, attempt_count + 1):
            request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
            logger.info("Requesting %s model=%s attempt=%d/%d", endpoint, self.config.model, attempt, attempt_count)
            try:
                return urllib.request.urlopen(request, timeout=self.config.request_timeout)
            except urllib.error.HTTPError as exc:
                details = exc.read().decode("utf-8", errors="ignore")
                if exc.code == 401 or "invalid_authentication_error" in details:
                    raise RuntimeError(
                        f"API 鉴权失败：OPENAI_API_KEY 无效、已过期，或不属于 {self.config.base_url}。"
                    ) from exc
                if exc.code == 404 and "model" in details.lower():
                    raise RuntimeError(
                        f"模型不可用：{self.config.base_url} 上没有 {self.config.model}。"
                    ) from exc
                rate_limited = exc.code == 429 and "overloaded" not in details
                if exc.code == 429 or "engine_overloaded_error" in details:
                    if attempt < attempt_count:
                        delay_seconds = retry_delays[attempt - 1]
                        reason = "Rate limited" if rate_limited else "Model busy"
                        logger.warning("%s, retrying in %ss", reason, delay_seconds)
                        time.sleep(delay_seconds)
                        continue
                    if rate_limited:
                        raise RuntimeError("请求过于频繁（API 账号限流），请稍后再试。") from exc
                    raise RuntimeError("模型当前繁忙，请稍后重试。") from exc
                raise RuntimeError(f"LLM request failed: HTTP {exc.code} {details}") from exc
            except urllib.error.URLError as exc:
                raise RuntimeError(f"LLM request failed: {exc.reason}") from exc
        raise RuntimeError("LLM request failed after retries.")
