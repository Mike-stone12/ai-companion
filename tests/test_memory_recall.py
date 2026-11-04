from copy import deepcopy

import pytest

from companion.core.memory.recall import score_relevance, select_memories, tokenize
from companion.core.memory.store import MemoryStore


def entry(summary, day):
    return {
        "summary": summary,
        "category": "preference",
        "source": "chat",
        "updated_at": f"2026-10-{day:02d}T12:00:00+00:00",
    }


@pytest.mark.parametrize(
    "text,expected",
    [
        ("我喜欢咖啡，茶！", {"我喜", "喜欢", "欢咖", "咖啡", "茶"}),
        ("COFFEE, coffee! I a tea; café ÉCOLE 123.", {"coffee", "tea", "café", "école"}),
        ("喜欢Coffee和茶 tea!", {"喜欢", "coffee", "和茶", "tea"}),
        ("咖，啡 茶", {"咖", "啡", "茶"}),
        ("", set()),
        (" \n!?123", set()),
    ],
)
def test_tokenize(text, expected):
    assert tokenize(text) == expected


@pytest.mark.parametrize(
    "query,summary,expected",
    [
        ("coffee", "coffee tea", 0.5),
        ("COFFEE coffee", "coffee coffee", 1.0),
        ("咖啡还是茶", "咖啡", 1.0),
        ("coffee", "cats", 0.0),
        ("", "coffee", 0.0),
        ("coffee", "", 0.0),
        ("!?", "coffee", 0.0),
    ],
)
def test_score_relevance(query, summary, expected):
    score = score_relevance(query, summary)
    assert isinstance(score, float)
    assert score == expected


def test_old_relevant_memory_is_selected_over_newer_unrelated_memories():
    memories = [entry("喜欢咖啡", 1)] + [entry(f"住在北京 {day}", day) for day in range(2, 14)]

    selected = select_memories(memories, "我喜欢什么饮料？咖啡还是茶")

    assert selected == [memories[0], *memories[-7:]]


@pytest.mark.parametrize("query", ["", " \n\t", "unmatched", "!!!"])
def test_fallback_matches_existing_recent_context(query, tmp_path):
    store = MemoryStore(tmp_path / "unused.json")
    store.items = [entry(f"memory {day}", day) for day in range(12, 0, -1)]

    selected = select_memories(store.items, query)

    assert selected == sorted(store.items, key=lambda item: item["updated_at"], reverse=True)[:8]
    assert [f"- [{item['category']}] {item['summary']}" for item in selected] == (
        store.render_context().splitlines()[1:]
    )


@pytest.mark.parametrize("query", ["coffee", "", "unmatched"])
def test_output_follows_input_order_even_when_timestamps_do_not(query):
    memories = [entry("tea", 3), entry("coffee", 1), entry("cats", 4), entry("books", 2)]
    selected = select_memories(memories, query, limit=3)
    expected = [memories[0], memories[1], memories[2]] if query == "coffee" else [memories[0], memories[2], memories[3]]
    assert selected == expected


@pytest.mark.parametrize("limit", [0, 1, 2, 8, 20])
def test_limit_no_duplicates_and_input_is_not_mutated(limit):
    memories = [entry(f"coffee {day}", day) for day in range(1, 13)]
    before = deepcopy(memories)
    original_ids = [id(item) for item in memories]

    selected = select_memories(memories, "coffee", limit=limit)

    assert len(selected) == min(limit, len(memories))
    assert len({id(item) for item in selected}) == len(selected)
    assert memories == before
    assert [id(item) for item in memories] == original_ids
    assert all(any(item is original for original in memories) for item in selected)
    assert selected is not memories


def test_relevance_score_takes_priority_over_recency():
    memories = [entry("coffee", 1), entry("coffee tea", 2), entry("books", 3)]
    assert select_memories(memories, "coffee", limit=2) == [memories[0], memories[2]]


def test_score_ties_prefer_newer_then_first_input_position():
    memories = [entry("coffee old", 1), entry("coffee first", 2), entry("coffee second", 2)]
    for _ in range(3):
        assert select_memories(memories, "coffee", limit=1, relevant_slots=1) == [memories[1]]


def test_recency_ties_prefer_first_input_position():
    memories = [entry("coffee", 1), entry("tea", 1), entry("books", 1)]
    assert select_memories(memories, "", limit=2) == memories[:2]


@pytest.mark.parametrize("relevant_slots,indices", [(None, [0, 3, 4]), (0, [2, 3, 4]), (2, [0, 1, 4]), (9, [0, 1, 2])])
def test_relevant_slot_budget(relevant_slots, indices):
    memories = [
        entry("coffee", 1),
        entry("coffee tea", 2),
        entry("coffee tea milk", 3),
        entry("books", 4),
        entry("cats", 5),
    ]
    assert select_memories(memories, "coffee", limit=3, relevant_slots=relevant_slots) == [
        memories[index] for index in indices
    ]


def test_unused_relevant_slots_are_filled_by_recency():
    memories = [entry("coffee", 1), entry("tea", 2), entry("books", 3), entry("cats", 4)]
    assert select_memories(memories, "coffee", limit=3, relevant_slots=3) == [memories[0], memories[2], memories[3]]


def test_empty_memories_and_negative_budgets():
    assert select_memories([], "coffee") == []
    memories = [entry("coffee", 1), entry("tea", 2)]
    assert select_memories(memories, "coffee", limit=-1) == []
    assert select_memories(memories, "coffee", limit=1, relevant_slots=-1) == [memories[1]]
