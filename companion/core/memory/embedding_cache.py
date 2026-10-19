"""Bounded in-memory LRU caching for an injected embedding callable."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable


class CachingEmbedder:
    """Cache exact texts, refreshing recency in input order on successful calls.

    Failed calls leave both cached vectors and their recency unchanged. A batch
    may exceed the cache capacity; all its vectors are still returned.
    """

    def __init__(
        self,
        embed: Callable[[list[str]], list[list[float]]],
        max_size: int = 256,
    ) -> None:
        if type(max_size) is not int or max_size <= 0:
            raise ValueError("max_size must be a positive integer")
        self._embed = embed
        self._max_size = max_size
        self._cache: OrderedDict[str, list[float]] = OrderedDict()

    def __call__(self, texts: list[str]) -> list[list[float]]:
        resolved = {text: self._cache[text] for text in texts if text in self._cache}
        missing = list(dict.fromkeys(text for text in texts if text not in resolved))
        if missing:
            vectors = self._embed(missing)
            if len(vectors) != len(missing):
                raise RuntimeError("Embedding response vector count does not match input count")
            resolved.update(zip(missing, vectors, strict=True))

        result = []
        for text in texts:
            vector = resolved[text]
            result.append(vector)
            self._cache[text] = vector
            self._cache.move_to_end(text)
            if len(self._cache) > self._max_size:
                self._cache.popitem(last=False)
        return result

    def clear(self) -> None:
        """Discard all cached embeddings."""
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)
