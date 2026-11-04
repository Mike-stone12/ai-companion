import runpy
from copy import deepcopy

import pytest

from companion.core import config
from companion.core.memory import recall
from companion.core.memory.store import MemoryStore


@pytest.fixture
def memories():
    # Deliberately not in timestamp order: the two recall modes order differently.
    return [
        {"summary": "tea", "updated_at": "2026-10-03"},
        {"summary": "coffee", "updated_at": "2026-10-01"},
        {"summary": "cats", "updated_at": "2026-10-04"},
        {"summary": "books", "updated_at": "2026-10-02"},
    ]


@pytest.mark.parametrize("limit", [0, 2, 8, -1])
def test_disabled_recall_preserves_old_recency_selection_and_order(memories, limit):
    before = deepcopy(memories)
    expected = sorted(memories, key=lambda item: item.get("updated_at", ""), reverse=True)[:limit]

    assert recall.select_context_memories(memories, "coffee", limit, False) == expected
    assert memories == before


def test_enabled_recall_includes_older_lexically_relevant_memory(memories):
    assert recall.select_context_memories(memories, "coffee", 2, True) == [memories[1], memories[2]]


@pytest.mark.parametrize("query", ["unmatched", "", "!!!"])
def test_enabled_recall_uses_documented_fallback_in_input_order(memories, query):
    selected = recall.select_context_memories(memories, query, 2, True)

    assert selected == recall.select_memories(memories, query, limit=2)
    assert selected == [memories[0], memories[2]]


@pytest.mark.parametrize("enabled, summaries", [(False, ["cats", "tea"]), (True, ["coffee", "cats"])])
def test_store_renders_selected_memories(tmp_path, memories, enabled, summaries):
    store = MemoryStore(tmp_path / "memory.json")
    store.items = memories

    context = store.render_context(max_items=2, query="coffee", relevant_recall=enabled)

    assert context.splitlines()[1:] == [f"- [memory] {summary}" for summary in summaries]


@pytest.mark.parametrize("value, expected", [(None, True), ("0", False), ("1", True), (" false ", False)])
def test_memory_relevant_recall_setting(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("MEMORY_RELEVANT_RECALL", raising=False)
    else:
        monkeypatch.setenv("MEMORY_RELEVANT_RECALL", value)
    config_class = runpy.run_path(config.__file__)["AppConfig"]
    assert config_class().memory_relevant_recall is expected
