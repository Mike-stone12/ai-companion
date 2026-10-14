from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from companion.core.config import AppConfig
from companion.core.text import sanitize_reply_text


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
        if retry_delays is None:
            retry_delays = tuple(min(4, attempt) for attempt in range(1, self.config.request_retries + 1))

        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"
        payload: dict = {"model": self.config.model, "messages": messages, **(extra or {})}
        if temperature is not None:
            payload["temperature"] = temperature
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }

        attempt_count = len(retry_delays) + 1
        data = None
        for attempt in range(1, attempt_count + 1):
            request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
            print(f"[llm] Requesting {endpoint} model={self.config.model} attempt={attempt}/{attempt_count}")
            try:
                with urllib.request.urlopen(request, timeout=self.config.request_timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                break
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
                        print(f"[llm] {reason}, retrying in {delay_seconds}s.")
                        time.sleep(delay_seconds)
                        continue
                    if rate_limited:
                        raise RuntimeError("请求过于频繁（API 账号限流），请稍后再试。") from exc
                    raise RuntimeError("模型当前繁忙，请稍后重试。") from exc
                raise RuntimeError(f"LLM request failed: HTTP {exc.code} {details}") from exc
            except urllib.error.URLError as exc:
                raise RuntimeError(f"LLM request failed: {exc.reason}") from exc

        if data is None:
            raise RuntimeError("LLM response was empty after retries.")

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
