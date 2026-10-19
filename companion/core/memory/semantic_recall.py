"""Embedding-based recall with an injected embedder and lexical fallback."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from math import hypot

from companion.core.memory.recall import select_memories

logger = logging.getLogger(__name__)


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Return cosine similarity, or zero for empty or zero-norm vectors.

    Different dimensions raise ValueError, including when one vector is empty.
    """
    if len(a) != len(b):
        raise ValueError("Vectors must have matching dimensions")
    norm_a, norm_b = hypot(*a), hypot(*b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return sum((x / norm_a) * (y / norm_b) for x, y in zip(a, b, strict=True))


def select_semantic_memories(
    memories: list[dict[str, str]],
    query: str,
    embed: Callable[[list[str]], list[list[float]]],
    limit: int = 8,
    min_similarity: float = 0.3,
) -> list[dict[str, str]]:
    """Select semantic matches and recent entries, preserving stored order.

    The embedder receives the query followed by summaries in one batch and must
    return one equal-dimension vector per text, in the same order. Up to
    limit // 2 slots go to scores at or above min_similarity. Remaining slots
    use descending updated_at strings, just like lexical recall. Similarity
    ties prefer recency, then the earlier input position for equal timestamps.

    Empty queries use recency alone. Embedding errors use lexical recall and
    log a warning without text or exception details. Results reference the
    original dictionaries without editing them; each input position occurs once.
    """
    if limit <= 0 or not memories:
        return []
    if not query.strip():
        return select_memories(memories, query, limit=limit, relevant_slots=0)

    try:
        vectors = embed([query, *[item["summary"] for item in memories]])
        if len(vectors) != len(memories) + 1:
            raise ValueError("Embedder returned an unexpected vector count")
        scores = [cosine_similarity(vectors[0], vector) for vector in vectors[1:]]
    except Exception:
        # Embedder exceptions may contain private input text: omit their details.
        logger.warning("Semantic recall failed; falling back to lexical recall")
        return select_memories(memories, query, limit=limit)

    recent = sorted(range(len(memories)), key=lambda index: memories[index].get("updated_at", ""), reverse=True)
    # Stable sorting retains timestamp order, then input order for exact ties.
    relevant = sorted(
        (index for index in recent if scores[index] >= min_similarity),
        key=lambda index: scores[index],
        reverse=True,
    )
    chosen = set(relevant[: limit // 2])
    for index in recent:
        if len(chosen) >= limit:
            break
        chosen.add(index)
    return [item for index, item in enumerate(memories) if index in chosen]
