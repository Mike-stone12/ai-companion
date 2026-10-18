import importlib
from copy import deepcopy

import pytest

from companion.core import config
from companion.core.memory import consolidate_pipeline
from companion.core.memory import store as store_module
from companion.core.memory.consolidator import ConsolidationDecision
from companion.core.memory.store import MemoryStore

NOW = "2026-10-18T12:00:00+00:00"


def entry(summary, updated_at="2026-10-01T12:00:00+00:00"):
    return {"summary": summary, "category": "preference", "source": "chat", "updated_at": updated_at}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "utc_now_iso", lambda: NOW)
    memory_store = MemoryStore(tmp_path / "memory.json")
    memory_store.items = [entry("Likes tea"), entry("Lives in Beijing"), entry("Likes cats")]
    memory_store.save()
    return memory_store


def consolidate(store, candidates, request):
    return consolidate_pipeline.consolidate_store(store, candidates, request)


def test_add_is_saved_and_loads_current_memories(store):
    before = deepcopy(store.items)
    store.items = []  # The helper must load the persisted state.

    def request(candidate, existing):
        assert existing == [item["summary"] for item in before]
        return '{"action":"ADD","summary":"Likes coffee"}'

    result = consolidate(store, [entry("Coffee")], request)
    assert store.items == [*before, entry("Likes coffee", NOW)]
    assert MemoryStore(store.path).items == store.items
    assert (result.added, result.updated, result.unchanged) == (1, 0, 0)


def test_update_replaces_in_place_and_preserves_other_memories(store):
    before = deepcopy(store.items)
    result = consolidate(
        store, [entry("Moved")], lambda *_: ConsolidationDecision("UPDATE", 1, "Lives in Shanghai")
    )
    assert store.items == [before[0], entry("Lives in Shanghai", NOW), before[2]]
    assert MemoryStore(store.path).items == store.items
    assert (result.added, result.updated, result.unchanged) == (0, 1, 0)


@pytest.mark.parametrize("action,target", [("NOOP", None), ("DELETE", 1)])
def test_noop_and_delete_leave_store_unchanged(store, action, target):
    before = deepcopy(store.items)
    result = consolidate(store, [entry("Candidate")], lambda *_: ConsolidationDecision(action, target, None))
    assert store.items == before
    assert MemoryStore(store.path).items == before
    assert (result.added, result.updated, result.unchanged) == (0, 0, 1)


@pytest.mark.parametrize("failure", ["llm", "pipeline", "invalid_reply"])
def test_failure_falls_back_to_store_dedupe_including_metadata(store, monkeypatch, failure):
    candidates = [{"summary": " Likes\ntea ", "category": "new", "source": "llm"}, entry("Likes coffee")]
    expected = MemoryStore(store.path.parent / "expected.json")
    expected.items = deepcopy(store.items)
    expected.upsert_many(candidates)

    def request(*_):
        if failure == "invalid_reply":
            return "invalid JSON"
        raise RuntimeError("private memory text")

    if failure == "pipeline":
        monkeypatch.setattr(consolidate_pipeline, "consolidate_candidates", request)
    result = consolidate(store, candidates, request)
    assert store.items == expected.items
    assert MemoryStore(store.path).items == expected.items
    assert (result.added, result.updated, result.unchanged) == (1, 0, 1)
    assert result.fallback_count == 2


def test_partial_pipeline_failure_discards_unpersisted_updates(store):
    replies = iter([ConsolidationDecision("UPDATE", 0, "Merged"), None])
    result = consolidate(store, [entry("Candidate one"), entry("Candidate two")], lambda *_: next(replies))
    assert "Merged" not in [item["summary"] for item in store.items]
    assert {item["summary"] for item in store.items} == {
        "Likes tea", "Lives in Beijing", "Likes cats", "Candidate one", "Candidate two"
    }
    assert result.added == 2


@pytest.mark.parametrize("external_entries", [[entry("Externally edited"), entry("Likes coffee")], []])
@pytest.mark.parametrize("request_fails", [False, True])
def test_concurrent_write_falls_back_on_fresh_store(store, external_entries, request_fails):
    candidates = [entry("Likes coffee"), entry("Likes hiking")]

    def request(*_):
        other_store = MemoryStore(store.path)
        other_store.items = deepcopy(external_entries)
        other_store.save()
        if request_fails:
            raise RuntimeError("private memory text")
        return ConsolidationDecision("ADD", None, "Consolidated candidate")

    result = consolidate(store, candidates, request)
    persisted = MemoryStore(store.path).items
    expected_summaries = {item["summary"] for item in external_entries + candidates}
    assert {item["summary"] for item in persisted} == expected_summaries
    assert len(persisted) == len(expected_summaries)
    assert persisted == store.items
    if external_entries:
        assert external_entries[0] in persisted
    added = len(expected_summaries) - len(external_entries)
    assert (result.added, result.updated, result.unchanged) == (added, 0, len(candidates) - added)
    assert result.fallback_count == len(candidates)


def test_retention_keeps_newest_entries_at_store_limit(store):
    store.limit = 3
    store.items[1]["updated_at"] = "2026-10-02T12:00:00+00:00"
    store.items[2]["updated_at"] = "2026-10-03T12:00:00+00:00"
    store.save()
    consolidate(store, [entry("Coffee")], lambda *_: ConsolidationDecision("ADD", None, "Likes coffee"))
    assert [item["summary"] for item in store.items] == ["Likes coffee", "Likes cats", "Lives in Beijing"]
    assert MemoryStore(store.path, limit=3).items == store.items


def test_existing_duplicates_are_not_cleaned_up(store):
    store.items.append(entry("Likes tea"))
    store.save()
    before = deepcopy(store.items)
    consolidate(store, [entry("Candidate")], lambda *_: ConsolidationDecision("NOOP", None, None))
    assert MemoryStore(store.path).items == before


@pytest.mark.parametrize("value,expected", [(None, True), ("0", False), ("1", True)])
def test_memory_consolidation_config(monkeypatch, value, expected):
    with monkeypatch.context() as env:
        if value is None:
            env.delenv("MEMORY_CONSOLIDATION", raising=False)
        else:
            env.setenv("MEMORY_CONSOLIDATION", value)
        try:
            assert importlib.reload(config).AppConfig().memory_consolidation is expected
        finally:
            env.undo()
            importlib.reload(config)
