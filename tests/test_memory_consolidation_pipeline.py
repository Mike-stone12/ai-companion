from copy import deepcopy
from functools import partial
from types import SimpleNamespace

import pytest

from companion.core.memory.consolidate_pipeline import consolidate_candidates
from companion.core.memory.consolidator import ConsolidationDecision, decide

NOW = "2026-10-18T12:00:00+00:00"


def entry(summary, updated_at="2026-10-01T12:00:00+00:00"):
    return {"summary": summary, "category": "preference", "source": "chat", "updated_at": updated_at}


class FakeRequest:
    def __init__(self, *replies):
        self.replies = iter(replies)
        self.calls = []

    def __call__(self, candidate, existing_memories):
        self.calls.append((candidate, list(existing_memories)))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_add_then_update_sees_changes_in_same_batch():
    request = FakeRequest(
        ConsolidationDecision("ADD", None, "Likes tea"),
        ConsolidationDecision("UPDATE", 0, "Likes green tea"),
        ConsolidationDecision("NOOP", None, None),
    )
    result = consolidate_candidates(
        [], [entry("Tea"), entry("Green tea"), entry("More tea")], request, now=lambda: NOW
    )
    assert request.calls == [
        ("Tea", []),
        ("Green tea", ["Likes tea"]),
        ("More tea", ["Likes green tea"]),
    ]
    assert result.entries == [entry("Likes green tea", NOW)]
    assert result.counts == {"ADD": 1, "UPDATE": 1, "NOOP": 1, "DELETE": 0}
    assert result.fallback_count == 0


@pytest.mark.parametrize("action,target", [("NOOP", None), ("DELETE", 0)])
def test_noop_and_delete_preserve_entries_and_are_reported(action, target):
    def unexpected_clock():
        pytest.fail("No change should require a timestamp")

    existing = [entry("Likes tea")]
    request = FakeRequest(ConsolidationDecision(action, target, None))
    result = consolidate_candidates(existing, [entry("No longer likes tea")], request, now=unexpected_clock)
    assert result.entries == existing
    assert result.counts[action] == 1
    assert sum(result.counts.values()) == 1
    assert result.fallback_count == 0


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("failed"),
        TimeoutError("timeout"),
        None,
        "not JSON",
        '{"action":"UPDATE","target":99,"summary":"Invalid"}',
    ],
)
def test_failure_falls_back_to_exact_dedupe_and_continues(failure):
    existing = [entry("Likes tea")]
    request = FakeRequest(failure, failure, failure, ConsolidationDecision("UPDATE", 1, "Loves tea"))
    result = consolidate_candidates(
        existing,
        [entry("Likes tea"), entry("Enjoys tea"), entry("Enjoys tea"), entry("Tea update")],
        request,
        now=lambda: NOW,
    )
    assert result.entries == [existing[0], entry("Loves tea", NOW)]
    assert request.calls[-1] == ("Tea update", ["Likes tea", "Enjoys tea"])
    assert result.counts == {"ADD": 1, "UPDATE": 1, "NOOP": 2, "DELETE": 0}
    assert result.fallback_count == 3


def test_valid_raw_answer_uses_existing_parser():
    request = FakeRequest('```json\n{"action":"ADD","summary":"Likes tea"}\n```')
    result = consolidate_candidates([], [entry("Tea")], request, now=lambda: NOW)
    assert result.entries == [entry("Likes tea", NOW)]
    assert result.counts["ADD"] == 1
    assert result.fallback_count == 0


def test_empty_batch_returns_independent_copy_without_request():
    existing = [entry("Likes tea")]
    request = FakeRequest()
    result = consolidate_candidates(existing, [], request, now=lambda: NOW)
    assert result.entries == existing
    assert result.entries is not existing
    assert result.entries[0] is not existing[0]
    assert request.calls == []
    assert result.counts == {"ADD": 0, "UPDATE": 0, "NOOP": 0, "DELETE": 0}
    assert result.fallback_count == 0


def test_inputs_are_not_mutated_or_aliased():
    existing = [entry("Likes tea"), entry("Likes cats")]
    candidates = [entry("Green tea"), entry("Coffee")]
    before = deepcopy((existing, candidates))
    request = FakeRequest(
        ConsolidationDecision("UPDATE", 0, "Likes green tea"),
        ConsolidationDecision("ADD", None, "Likes coffee"),
    )
    result = consolidate_candidates(existing, candidates, request, now=lambda: NOW)
    assert (existing, candidates) == before
    for item in result.entries:
        item["summary"] = "Changed by caller"
    assert (existing, candidates) == before


def test_retention_is_left_to_store_and_existing_duplicates_are_preserved():
    existing = [entry("Duplicate") for _ in range(30)]
    request = FakeRequest(ConsolidationDecision("ADD", None, "New"))
    result = consolidate_candidates(existing, [entry("New")], request, now=lambda: NOW)
    assert result.entries == [*existing, entry("New", NOW)]


def test_existing_decide_can_be_bound_as_request_callable():
    class FakeClient:
        config = SimpleNamespace(base_url="https://example.invalid/v1")

        def complete(self, messages, **kwargs):
            return '{"action":"UPDATE","target":0,"summary":"Likes green tea"}'

    request = partial(decide, client=FakeClient())
    result = consolidate_candidates([entry("Likes tea")], [entry("Green tea")], request, now=lambda: NOW)
    assert result.entries == [entry("Likes green tea", NOW)]
    assert result.counts["UPDATE"] == 1
