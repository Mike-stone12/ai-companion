import logging
from copy import deepcopy

import pytest

from companion.core.memory.recall import select_memories, tokenize
from companion.core.memory.semantic_recall import cosine_similarity, select_semantic_memories


def entry(summary, day):
    return {
        "summary": summary,
        "category": "preference",
        "source": "chat",
        "updated_at": f"2026-10-{day:02d}T12:00:00+00:00",
    }


class FakeEmbedder:
    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = []

    def __call__(self, texts):
        self.calls.append(list(texts))
        return [self.vectors[text] for text in texts]


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ([1.0, 2.0], [1.0, 2.0], 1.0),
        ([1.0, 0.0], [0.0, 1.0], 0.0),
        ([0.0, 0.0], [1.0, 2.0], 0.0),
        ([1.0, 2.0], [0.0, 0.0], 0.0),
        ([1.0, 0.0], [-1.0, 0.0], -1.0),
        ([], [], 0.0),
    ],
)
def test_cosine_similarity(a, b, expected):
    result = cosine_similarity(a, b)
    assert isinstance(result, float)
    assert result == pytest.approx(expected)


@pytest.mark.parametrize("a,b", [([1.0], [1.0, 2.0]), ([], [1.0])])
def test_cosine_dimension_mismatch(a, b):
    with pytest.raises(ValueError):
        cosine_similarity(a, b)


def test_paraphrase_selected_and_embeddings_are_batched():
    query = "preferred beverage"
    memories = [entry("enjoys espresso", 1)] + [entry(f"books {day}", day) for day in range(2, 14)]
    embed = FakeEmbedder({query: [1.0, 0.0], **{item["summary"]: [0.0, 1.0] for item in memories}})
    embed.vectors[memories[0]["summary"]] = [1.0, 0.0]
    assert not tokenize(query) & tokenize(memories[0]["summary"])
    assert memories[0] not in select_memories(memories, query)

    assert select_semantic_memories(memories, query, embed) == [memories[0], *memories[-7:]]
    assert embed.calls == [[query, *[item["summary"] for item in memories]]]


@pytest.mark.parametrize("threshold,indices", [(0.5, [0, 3, 4, 5]), (0.7, [2, 3, 4, 5])])
def test_threshold_excludes_weak_matches_and_unused_slots_fill_by_recency(threshold, indices):
    memories = [entry(f"memory {day}", day) for day in range(1, 7)]
    embed = FakeEmbedder({"query": [1.0, 0.0], **{item["summary"]: [0.0, 1.0] for item in memories}})
    embed.vectors[memories[0]["summary"]] = [3.0, 4.0]  # Similarity 0.6.
    assert select_semantic_memories(memories, "query", embed, limit=4, min_similarity=threshold) == [
        memories[index] for index in indices
    ]


def test_threshold_is_inclusive():
    memories = [entry("old", 1), entry("middle", 2), entry("new", 3)]
    embed = FakeEmbedder({"query": [1.0, 0.0], "old": [1.0, 0.0], "middle": [0.0, 1.0], "new": [0.0, 1.0]})
    assert select_semantic_memories(memories, "query", embed, limit=2, min_similarity=1.0) == [memories[0], memories[2]]


@pytest.mark.parametrize(
    "limit,indices", [(-1, []), (0, []), (1, [4]), (2, [0, 4]), (3, [0, 3, 4]), (4, [0, 1, 3, 4]), (8, [0, 1, 2, 3, 4])]
)
def test_half_budget_limit_no_duplicates_stored_order_and_no_mutation(limit, indices):
    memories = [entry(f"memory {day}", day) for day in range(1, 6)]
    before = deepcopy(memories)
    embed = FakeEmbedder(
        {"query": [1.0, 0.0], **{item["summary"]: [1.0, float(index)] for index, item in enumerate(memories)}}
    )
    selected = select_semantic_memories(memories, "query", embed, limit=limit, min_similarity=0.0)
    assert selected == [memories[index] for index in indices]
    assert len({id(item) for item in selected}) == len(selected)
    assert all(item is memories[index] for item, index in zip(selected, indices, strict=True))
    assert memories == before


@pytest.mark.parametrize("query", ["", " \n\t"])
def test_empty_query_uses_timestamp_recency_without_embedding(query):
    memories = [entry("first", 3), entry("second", 1), entry("third", 4), entry("fourth", 2)]
    embed = FakeEmbedder({})
    assert select_semantic_memories(memories, query, embed, limit=2) == [memories[0], memories[2]]
    assert embed.calls == []


def test_empty_memories_do_not_embed():
    embed = FakeEmbedder({})
    assert select_semantic_memories([], "query", embed) == []
    assert embed.calls == []


@pytest.mark.parametrize("failure", ["raise", "too_few", "too_many", "dimensions", "empty_dimensions"])
def test_embedding_failure_falls_back_to_lexical_without_logging_text(failure, caplog):
    query = "private coffee question"
    memories = [entry("private coffee preference", 1), entry("private books", 2), entry("private cats", 3)]

    def embed(texts):
        if failure == "raise":
            raise RuntimeError(" ".join(texts))
        vectors = [[1.0, 0.0] for _ in texts]
        if failure == "too_few":
            return vectors[:-1]
        if failure == "too_many":
            return vectors + [[1.0, 0.0]]
        vectors[-1] = [] if failure == "empty_dimensions" else [1.0]
        return vectors

    with caplog.at_level(logging.WARNING, logger="companion.core.memory.semantic_recall"):
        selected = select_semantic_memories(memories, query, embed, limit=2)
    assert selected == select_memories(memories, query, limit=2) == [memories[0], memories[2]]
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert query not in caplog.text
    assert all(item["summary"] not in caplog.text for item in memories)
    assert all(record.exc_info is None for record in caplog.records)


def test_similarity_ties_prefer_recent_then_first_input_position():
    memories = [entry("old", 1), entry("first", 2), entry("second", 2), entry("new", 3)]
    embed = FakeEmbedder({"query": [1.0, 0.0], **{item["summary"]: [1.0, 0.0] for item in memories}})
    embed.vectors["new"] = [0.0, 1.0]
    for _ in range(3):
        assert select_semantic_memories(memories, "query", embed, limit=2) == [memories[1], memories[3]]


def test_missing_timestamps_and_recency_ties_use_input_order():
    memories = [{"summary": "first"}, {"summary": "second"}, entry("new", 3)]
    embed = FakeEmbedder({"query": [1.0], "first": [0.0], "second": [0.0], "new": [0.0]})
    assert select_semantic_memories(memories, "query", embed, limit=2) == [memories[0], memories[2]]


def test_semantic_selection_preserves_stored_order_with_unsorted_timestamps():
    memories = [entry("new", 4), entry("old", 1), entry("middle", 3), entry("other", 2)]
    embed = FakeEmbedder({"query": [1.0, 0.0], **{item["summary"]: [0.0, 1.0] for item in memories}})
    embed.vectors["old"] = [1.0, 0.0]
    assert select_semantic_memories(memories, "query", embed, limit=3) == memories[:3]
