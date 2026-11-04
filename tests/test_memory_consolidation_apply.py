from copy import deepcopy

import pytest

from companion.core.memory.apply import apply_consolidation
from companion.core.memory.consolidator import ConsolidationDecision
from companion.core.memory.store import clip_memory_text

NOW = "2026-10-18T12:00:00+00:00"


def entry(summary, updated_at="2026-10-01T12:00:00+00:00"):
    return {"summary": summary, "category": "preference", "source": "chat", "updated_at": updated_at}


def test_add_appends_normalized_entry_with_injected_timestamp():
    entries = [entry("Likes tea")]
    candidate = {"summary": "  Likes\ncoffee  "}
    result = apply_consolidation(
        entries, candidate, ConsolidationDecision("ADD", None, "  Likes\ncoffee  "), now=lambda: NOW
    )
    assert result.entries == [
        entries[0],
        {
            "summary": "Likes coffee",
            "category": "memory",
            "source": "",
            "updated_at": NOW,
        },
    ]
    assert result.action_applied == "ADD"
    assert not result.fallback_to_add
    assert not result.deferred_delete


def test_add_uses_decision_summary_and_candidate_metadata():
    summary = "A long consolidated memory " * 5
    result = apply_consolidation(
        [], entry("Raw candidate"), ConsolidationDecision("ADD", None, summary), now=lambda: NOW
    )
    assert result.entries == [entry(clip_memory_text(summary), NOW)]


def test_add_exact_duplicate_is_noop_after_normalization():
    entries = [entry("Likes tea")]
    result = apply_consolidation(
        entries, entry("Likes tea"), ConsolidationDecision("ADD", None, " Likes\ntea "), now=lambda: NOW
    )
    assert result.entries == entries
    assert result.action_applied == "NOOP"


def test_add_respects_limit_by_updated_timestamp():
    entries = [entry("Recent", "2026-10-17T12:00:00+00:00"), entry("Old")]
    result = apply_consolidation(
        entries, entry("New"), ConsolidationDecision("ADD", None, "New"), now=lambda: NOW, limit=2
    )
    assert result.entries == [entry("New", NOW), entries[0]]


def test_update_replaces_target_preserving_position_and_metadata():
    entries = [entry("Likes tea"), entry("Lives in Beijing"), entry("Likes cats")]
    result = apply_consolidation(
        entries, {"summary": "Moved"}, ConsolidationDecision("UPDATE", 1, " Lives\nin Shanghai "), now=lambda: NOW
    )
    assert result.entries == [entries[0], entry("Lives in Shanghai", NOW), entries[2]]
    assert result.action_applied == "UPDATE"
    assert not result.fallback_to_add


@pytest.mark.parametrize("target", [None, -1, 1, 999, True, "0"])
def test_invalid_update_target_falls_back_to_adding_original_candidate(target):
    entries = [entry("Existing")]
    result = apply_consolidation(
        entries, entry("Candidate"), ConsolidationDecision("UPDATE", target, "Merged"), now=lambda: NOW
    )
    assert result.entries == [entries[0], entry("Candidate", NOW)]
    assert result.action_applied == "ADD"
    assert result.fallback_to_add


def test_fallback_add_still_deduplicates():
    entries = [entry("Candidate")]
    result = apply_consolidation(
        entries, entry("Candidate"), ConsolidationDecision("UPDATE", None, "Merged"), now=lambda: NOW
    )
    assert result.entries == entries
    assert result.action_applied == "NOOP"
    assert result.fallback_to_add


@pytest.mark.parametrize("action,target", [("NOOP", None), ("DELETE", 0), ("DELETE", 999)])
def test_noop_and_delete_leave_entries_unchanged_without_reading_clock(action, target):
    def unexpected_clock():
        pytest.fail("An unchanged result must not read the clock")

    entries = [entry("Existing")]
    result = apply_consolidation(
        entries, entry("Candidate"), ConsolidationDecision(action, target, None), now=unexpected_clock, limit=0
    )
    assert result.entries == entries
    assert result.action_applied == "NOOP"
    assert result.deferred_delete == (action == "DELETE")
    assert result.deferred_delete_target == target


@pytest.mark.parametrize(
    "decision",
    [
        ConsolidationDecision("ADD", None, "New"),
        ConsolidationDecision("ADD", None, "Existing"),
        ConsolidationDecision("UPDATE", 0, "New"),
        ConsolidationDecision("UPDATE", None, "New"),
        ConsolidationDecision("NOOP", None, None),
        ConsolidationDecision("DELETE", 0, None),
    ],
)
def test_inputs_and_entry_dictionaries_are_never_mutated(decision):
    entries = [entry("Existing")]
    candidate = entry("Candidate")
    before = deepcopy((entries, candidate, decision))
    result = apply_consolidation(entries, candidate, decision, now=lambda: NOW)
    assert (entries, candidate, decision) == before
    assert result.entries is not entries
    for item in result.entries:
        item["summary"] = "Changed by caller"
    assert (entries, candidate, decision) == before


def test_zero_limit_retains_no_entries_on_add():
    result = apply_consolidation([], entry("New"), ConsolidationDecision("ADD", None, "New"), now=lambda: NOW, limit=0)
    assert result.entries == []


def test_empty_summary_is_not_added():
    result = apply_consolidation([], {"summary": " "}, ConsolidationDecision("ADD", None, " "), now=lambda: NOW)
    assert result.entries == []
    assert result.action_applied == "NOOP"
