"""Offline semantic recall and deferred chat wiring; no GUI dependencies."""

import ast
import logging
from collections import Counter
from collections.abc import Callable
from copy import copy, deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from companion.core.chat.emotion import EmotionTagParser
from companion.core.chat.summary import build_chat_messages
from companion.core.config import AppConfig
from companion.core.memory import semantic_recall
from companion.core.memory.embedding_cache import CachingEmbedder
from companion.core.memory.recall import select_context_memories
from companion.core.memory.store import MemoryStore
from companion.core.text import SentenceSplitter


@pytest.fixture
def memories():
    return [
        {"summary": "tea", "updated_at": "2026-10-03"},
        {"summary": "enjoys espresso", "updated_at": "2026-10-01"},
        {"summary": "cats", "updated_at": "2026-10-04"},
        {"summary": "books", "updated_at": "2026-10-02"},
    ]


class CountingEmbedder:
    def __init__(self):
        self.counts = Counter()

    def __call__(self, texts):
        self.counts.update(texts)
        return [[1.0, 0.0] if text in {"preferred beverage", "enjoys espresso"} else [0.0, 1.0]
                for text in texts]


@pytest.mark.parametrize("relevant", [False, True])
@pytest.mark.parametrize("query", ["tea", "unmatched", ""])
@pytest.mark.parametrize("limit", [-1, 0, 2, 8])
def test_without_embedder_preserves_existing_selection(memories, relevant, query, limit):
    before = deepcopy(memories)
    assert semantic_recall.select_request_memories(memories, query, limit, relevant_recall=relevant) == (
        select_context_memories(memories, query, limit, relevant)
    )
    assert memories == before


def test_semantic_recall_finds_paraphrase_lexical_recall_misses(memories):
    query = "preferred beverage"
    assert memories[1] not in select_context_memories(memories, query, 2)
    selected = semantic_recall.select_request_memories(memories, query, 2, embed=CountingEmbedder())
    assert selected == [memories[1], memories[2]]


@pytest.mark.parametrize("relevant", [False, True])
@pytest.mark.parametrize("failure", ["exception", "dimensions", "ranking"])
def test_failures_restore_configured_fallback_without_private_logs(memories, relevant, failure, caplog, monkeypatch):
    query = "private tea question"

    def fail(texts):
        if failure == "dimensions":
            return [[1.0], *[[1.0, 0.0] for _ in texts[1:]]]
        raise RuntimeError(query + str(memories))

    if failure == "ranking":
        monkeypatch.setattr(semantic_recall, "select_semantic_memories", lambda *a, **kw: fail([]))
    with caplog.at_level(logging.WARNING):
        result = semantic_recall.select_request_memories(memories, query, 2, embed=fail, relevant_recall=relevant)
    assert result == select_context_memories(memories, query, 2, relevant)
    assert len(caplog.records) == 1
    assert query not in caplog.text
    assert all(item["summary"] not in caplog.text for item in memories)
    assert caplog.records[0].exc_info is None


def test_session_cache_embeds_stored_texts_once(memories):
    fake = CountingEmbedder()
    embed = CachingEmbedder(fake)
    for query in ("preferred beverage", "another question"):
        semantic_recall.select_request_memories(memories, query, 2, embed=embed)
    assert all(fake.counts[item["summary"]] == 1 for item in memories)
    assert fake.counts["preferred beverage"] == fake.counts["another question"] == 1


@pytest.mark.parametrize("enabled,model", [(False, "model"), (False, ""), (True, ""), (True, "  ")])
def test_disabled_feature_never_constructs_client(monkeypatch, enabled, model):
    client = Mock(side_effect=AssertionError("Must not construct embeddings client"))
    monkeypatch.setattr(semantic_recall, "OpenAICompatibleEmbeddings", client)
    config = AppConfig(memory_semantic_recall=enabled, embedding_model=model)
    assert semantic_recall.create_session_embedder(config) is None
    client.assert_not_called()


def test_session_factory_reuses_key_url_and_bounded_client_timeout(monkeypatch):
    fake = CountingEmbedder()
    factory = Mock(return_value=fake)
    monkeypatch.setattr(semantic_recall, "OpenAICompatibleEmbeddings", factory)
    config = AppConfig(memory_semantic_recall=True, embedding_model="embed-model",
                       base_url="https://chat.invalid/v1", api_key="shared-key", memory_limit=300)
    embed = semantic_recall.create_session_embedder(config)
    assert isinstance(embed, CachingEmbedder)
    factory.assert_called_once_with(config.base_url, "shared-key", "embed-model")
    # Capacity must accommodate all retained memories plus a changing query.
    memories = [{"summary": f"memory {i}"} for i in range(300)]
    for query in ("first", "second"):
        semantic_recall.select_request_memories(memories, query, embed=embed)
    assert all(fake.counts[item["summary"]] == 1 for item in memories)


def load_class(relative_path, name, namespace, methods=None):
    path = Path(__file__).resolve().parents[1] / relative_path
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
    if methods is not None:
        cls.bases = []
        cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in methods]
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), cls],
                        type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("semantic", [False, True])
def test_context_is_snapshotted_and_embeddings_run_only_in_worker(tmp_path, memories, semantic):
    window_class = load_class("companion/ui/main_window.py", "CompanionWindow", {
        "build_chat_messages": build_chat_messages, "CONVERSATION_WINDOW": 11, "copy": copy,
        "Callable": Callable,
    }, {"conversation_window", "state_context", "own_context"})
    worker_class = load_class("companion/app/workers.py", "ChatStreamWorker", {
        "QObject": object, "pyqtSignal": lambda *_: Mock(), "pyqtSlot": lambda: lambda fn: fn,
        "EmotionTagParser": EmotionTagParser, "SentenceSplitter": SentenceSplitter,
    })
    window = window_class()
    window.config = AppConfig(memory_relevant_recall=True, conversation_summary=False)
    window.history = SimpleNamespace(summary=None)
    window.messages = [{"role": "system", "content": "System"}, {"role": "user", "content": "preferred beverage"}]
    window.memory_store = MemoryStore(tmp_path / "memory.json")
    window.memory_store.items = memories + [{"summary": f"recent {i}", "updated_at": f"2026-10-{i}"}
                                          for i in range(10, 20)]
    fake = CountingEmbedder()
    window.memory_embedder = CachingEmbedder(fake) if semantic else None
    expected_legacy = window.memory_store.render_context(query="preferred beverage")
    prepare = window.conversation_window("preferred beverage", defer=True)
    next_prepare = window.conversation_window("another question", defer=True)
    assert callable(prepare)
    assert not fake.counts
    # The worker must use the request's snapshot even if UI state changes later.
    window.memory_store.items.clear()
    window.messages[-1]["content"] = "changed"
    client = Mock(config=AppConfig(api_key="fake", chat_tools=False))
    client.stream_chat.side_effect = lambda _: iter(["Reply."])
    worker = worker_class(client, prepare)
    assert not fake.counts
    worker.run()
    worker.error.emit.assert_not_called()
    payload = client.stream_chat.call_args.args[0]
    assert payload[-1]["content"] == "preferred beverage"
    if semantic:
        assert "enjoys espresso" in payload[1]["content"]
        assert fake.counts["enjoys espresso"] == 1
    else:
        assert payload[1]["content"] == expected_legacy
        assert not fake.counts
    next_worker = worker_class(client, next_prepare)
    next_worker.run()
    next_worker.error.emit.assert_not_called()
    if semantic:
        assert fake.counts["another question"] == 1
        assert all(fake.counts[item["summary"]] == 1 for item in memories)
