"""Pure lexical recall for the dictionaries used by MemoryStore."""

from __future__ import annotations

from itertools import groupby
from unicodedata import name


def _script(character: str) -> str | None:
    if character.isalpha() and name(character, "").startswith("LATIN "):
        return "latin"
    # Han (including extensions), hiragana, katakana, and Hangul.
    if any(
        start <= ord(character) <= end
        for start, end in (
            (0x3400, 0x4DBF),
            (0x4E00, 0x9FFF),
            (0xF900, 0xFAFF),
            (0x20000, 0x2FA1F),
            (0x30000, 0x323AF),
            (0x3041, 0x3096),
            (0x30A1, 0x30FA),
            (0x1100, 0x11FF),
            (0x3131, 0x318E),
            (0xAC00, 0xD7A3),
        )
    ):
        return "cjk"
    return None


def tokenize(text: str) -> set[str]:
    """Return lowercase Latin words (2+ letters) and CJK run bigrams.

    Isolated CJK characters are unigrams. Punctuation, digits, whitespace,
    and script changes separate runs; they do not produce features.
    """
    features: set[str] = set()
    for script, characters in groupby(text, key=_script):
        run = "".join(characters)
        if script == "latin" and len(run) >= 2:
            features.add(run.lower())
        elif script == "cjk":
            if len(run) == 1:
                features.add(run)
            else:
                features.update(run[index : index + 2] for index in range(len(run) - 1))
    return features


def _overlap(query_features: set[str], memory_features: set[str]) -> float:
    if not query_features or not memory_features:
        return 0.0
    return len(query_features & memory_features) / len(memory_features)


def score_relevance(query: str, summary: str) -> float:
    """Score in [0, 1]: shared features divided by summary feature count.

    Repeated features count once. Inputs with no features score zero.
    """
    return _overlap(tokenize(query), tokenize(summary))


def select_memories(
    memories: list[dict[str, str]],
    query: str,
    limit: int = 8,
    relevant_slots: int | None = None,
) -> list[dict[str, str]]:
    """Select relevant entries, then fill by recency, preserving input order.

    Relevance gets half the slots by default. Its budget is clamped to
    [0, limit]; a nonpositive limit returns an empty list. Score ties prefer
    newer updated_at strings, matching MemoryStore's timestamp comparison.
    Exact ties prefer the earlier input position, as in its stable sort.

    Empty queries and zero overlap select the same entries as recency-only
    recall, returned in input order. Each input position is selected once;
    the returned list references the original dictionaries without editing them.
    """
    if limit <= 0:
        return []
    budget = min(limit, max(0, limit // 2 if relevant_slots is None else relevant_slots))
    recent = sorted(range(len(memories)), key=lambda index: memories[index].get("updated_at", ""), reverse=True)
    query_features = tokenize(query)
    scores = [_overlap(query_features, tokenize(item["summary"])) for item in memories]
    # Stable sorting preserves recency order (and input order for exact ties).
    relevant = sorted((index for index in recent if scores[index] > 0), key=lambda index: scores[index], reverse=True)
    chosen = set(relevant[:budget])
    for index in recent:
        if len(chosen) >= limit:
            break
        chosen.add(index)
    return [item for index, item in enumerate(memories) if index in chosen]


def select_context_memories(
    memories: list[dict[str, str]],
    query: str,
    limit: int = 8,
    relevant_recall: bool = True,
) -> list[dict[str, str]]:
    """Use lexical recall, or preserve the legacy newest-first selection when disabled."""
    if relevant_recall:
        return select_memories(memories, query, limit=limit)
    return sorted(memories, key=lambda item: item.get("updated_at", ""), reverse=True)[:limit]
