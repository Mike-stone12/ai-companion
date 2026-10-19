import pytest

from companion.core.memory.embedding_cache import CachingEmbedder
from companion.core.memory.semantic_recall import select_semantic_memories


class FakeEmbedder:
    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = []
        self.error = None
        self.response = None

    def __call__(self, texts):
        self.calls.append(list(texts))
        if self.error is not None:
            raise self.error
        if self.response is not None:
            return self.response
        return [self.vectors[text] for text in texts]


def test_first_call_embeds_everything_and_repeat_uses_cache():
    inner = FakeEmbedder({"a": [1.0], "b": [2.0]})
    embed = CachingEmbedder(inner)
    assert embed(["a", "b"]) == [[1.0], [2.0]]
    assert inner.calls == [["a", "b"]]
    assert embed(["b", "a"]) == [[2.0], [1.0]]
    assert inner.calls == [["a", "b"]]
    assert len(embed) == 2


def test_partial_overlap_embeds_only_new_texts_in_first_seen_order():
    inner = FakeEmbedder({"a": [1.0], "b": [2.0], "c": [3.0], "d": [4.0]})
    embed = CachingEmbedder(inner)
    embed(["a", "b"])
    assert embed(["b", "d", "a", "c", "d"]) == [[2.0], [4.0], [1.0], [3.0], [4.0]]
    assert inner.calls == [["a", "b"], ["d", "c"]]


def test_duplicate_inputs_are_embedded_once_and_returned_at_every_position():
    inner = FakeEmbedder({"a": [1.0], "b": [2.0]})
    embed = CachingEmbedder(inner)
    assert embed(["b", "a", "b", "a"]) == [[2.0], [1.0], [2.0], [1.0]]
    assert inner.calls == [["b", "a"]]
    assert len(embed) == 2


def test_cache_keys_use_exact_text():
    inner = FakeEmbedder({"a": [1.0], "A": [2.0], " a ": [3.0], "": [4.0]})
    embed = CachingEmbedder(inner)
    assert embed(["a", "A", " a ", ""]) == [[1.0], [2.0], [3.0], [4.0]]
    assert inner.calls == [["a", "A", " a ", ""]]


def test_empty_input_does_not_embed():
    inner = FakeEmbedder({})
    embed = CachingEmbedder(inner)
    assert embed([]) == []
    assert inner.calls == []
    assert len(embed) == 0


def test_lru_eviction_and_hits_refresh_recency():
    inner = FakeEmbedder({"a": [1.0], "b": [2.0], "c": [3.0]})
    embed = CachingEmbedder(inner, max_size=2)
    embed(["a", "b"])
    embed(["a"])
    embed(["c"])
    assert len(embed) == 2
    assert embed(["a", "c"]) == [[1.0], [3.0]]
    assert inner.calls == [["a", "b"], ["c"]]
    assert embed(["b"]) == [[2.0]]
    assert inner.calls == [["a", "b"], ["c"], ["b"]]
    assert len(embed) == 2


def test_oversized_batch_returns_all_vectors_and_uses_last_access_for_recency():
    inner = FakeEmbedder({"a": [1.0], "b": [2.0], "c": [3.0]})
    embed = CachingEmbedder(inner, max_size=2)
    embed(["a"])
    assert embed(["a", "b", "c", "a"]) == [[1.0], [2.0], [3.0], [1.0]]
    assert len(embed) == 2
    assert embed(["c", "a"]) == [[3.0], [1.0]]
    assert inner.calls == [["a"], ["b", "c"]]
    embed(["b"])
    assert inner.calls == [["a"], ["b", "c"], ["b"]]


@pytest.mark.parametrize("failure", ["exception", "too_few", "too_many"])
def test_failure_leaves_cache_contents_and_recency_unchanged(failure):
    inner = FakeEmbedder({"a": [1.0], "b": [2.0], "c": [3.0], "d": [4.0], "e": [5.0]})
    embed = CachingEmbedder(inner, max_size=2)
    embed(["a", "b"])
    error = OSError("embedding unavailable")
    if failure == "exception":
        inner.error = error
    else:
        inner.response = [[3.0]] if failure == "too_few" else [[3.0], [5.0], [6.0]]

    with pytest.raises(OSError if failure == "exception" else RuntimeError) as caught:
        embed(["a", "c", "e"])
    if failure == "exception":
        assert caught.value is error
    else:
        assert "count" in str(caught.value)
    assert len(embed) == 2

    inner.error = None
    inner.response = None
    embed(["d"])
    # The failed hit on a must not refresh it: b survives the insertion of d.
    assert embed(["b", "d"]) == [[2.0], [4.0]]
    assert inner.calls == [["a", "b"], ["c", "e"], ["d"]]
    assert embed(["a", "c", "e"]) == [[1.0], [3.0], [5.0]]
    assert inner.calls[-1] == ["a", "c", "e"]
    assert len(embed) == 2


def test_clear_empties_cache_and_next_call_embeds_again():
    inner = FakeEmbedder({"a": [1.0], "b": [2.0]})
    embed = CachingEmbedder(inner)
    embed(["a", "b"])
    embed.clear()
    assert len(embed) == 0
    assert embed(["a", "b"]) == [[1.0], [2.0]]
    assert inner.calls == [["a", "b"], ["a", "b"]]


@pytest.mark.parametrize("max_size", [0, -1, 1.5, True, False, None, "2"])
def test_max_size_must_be_a_positive_integer(max_size):
    with pytest.raises(ValueError, match="max_size"):
        CachingEmbedder(FakeEmbedder({}), max_size=max_size)


def test_repeated_semantic_ranking_does_not_embed_again():
    memories = [
        {"summary": "enjoys espresso", "updated_at": "2026-10-01"},
        {"summary": "reads novels", "updated_at": "2026-10-02"},
        {"summary": "likes hiking", "updated_at": "2026-10-03"},
    ]
    query = "preferred beverage"
    inner = FakeEmbedder({
        query: [1.0, 0.0], "enjoys espresso": [1.0, 0.0],
        "reads novels": [0.0, 1.0], "likes hiking": [0.0, 1.0],
    })
    embed = CachingEmbedder(inner)
    for _ in range(2):
        assert select_semantic_memories(memories, query, embed, limit=2) == [memories[0], memories[2]]
        assert inner.calls == [[query, *[item["summary"] for item in memories]]]
