"""OpenAI-compatible embeddings using the chat client's standard-library transport."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from collections.abc import Callable
from http.client import HTTPResponse


class OpenAICompatibleEmbeddings:
    """Callable embedder for ``select_semantic_memories``.

    ``transport`` has the ``urlopen(request, timeout=...)`` interface and returns
    a context-managed HTTP response. Each batch makes one attempt, with a finite
    socket timeout in seconds; failures raise RuntimeError so recall can fall back
    to lexical matching. Input texts and response bodies are never logged.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 30.0,
        *,
        transport: Callable[..., HTTPResponse] | None = None,
        batch_size: int = 64,
    ) -> None:
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        if type(batch_size) is not int or batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.batch_size = batch_size
        self._transport = transport if transport is not None else urllib.request.urlopen

    def __call__(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self._embed_batch(texts[start:start + self.batch_size]))
        return vectors

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        request = urllib.request.Request(
            self.base_url + "/embeddings",
            data=json.dumps({"model": self.model, "input": texts}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with self._transport(request, timeout=self.timeout) as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError(f"Embedding request failed: HTTP {response.status}")
                body = response.read()
        except urllib.error.HTTPError as exc:
            exc.close()
            raise RuntimeError(f"Embedding request failed: HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise RuntimeError("Embedding request failed: network error or timeout") from exc

        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise RuntimeError("Embedding response contained malformed JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise RuntimeError("Embedding response must include a data list")
        data = payload["data"]
        if len(data) != len(texts):
            raise RuntimeError("Embedding response vector count does not match input count")

        vectors: dict[int, list[float]] = {}
        for item in data:
            if not isinstance(item, dict):
                raise RuntimeError("Embedding response data items must be objects")
            index = item.get("index")
            if type(index) is not int or not 0 <= index < len(texts) or index in vectors:
                raise RuntimeError("Embedding response has a missing, invalid or duplicate index")
            embedding = item.get("embedding")
            if not isinstance(embedding, list) or any(type(value) not in (int, float) for value in embedding):
                raise RuntimeError("Embedding response must contain numeric embedding lists")
            try:
                vector = [float(value) for value in embedding]
            except OverflowError as exc:
                raise RuntimeError("Embedding response vector values must be finite") from exc
            if not all(math.isfinite(value) for value in vector):
                raise RuntimeError("Embedding response vector values must be finite")
            vectors[index] = vector
        return [vectors[index] for index in range(len(texts))]
