from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from companion.core.memory.edit import DuplicateMemoryError, edit_memory, memory_rows
from companion.core.memory.store import clip_memory_text

NOW = "2026-10-18T12:00:00+00:00"


def entry(summary, updated_at="2026-10-01T12:00:00+00:00"):
    return {"summary": summary, "category": "preference", "source": "chat", "updated_at": updated_at}


def unexpected_clock():
    pytest.fail("An unchanged or rejected edit must not read the clock")


def test_rows_are_newest_first_with_original_indices_and_stable_ties():
    entries = [entry("Old"), entry("New", NOW), entry("Also new", NOW)]
    before = deepcopy(entries)
    rows = memory_rows(entries)
    assert [row.index for row in rows] == [1, 2, 0]
    assert [row.summary for row in rows] == ["New", "Also new", "Old"]
    assert rows[0].timestamp == "2026-10-18 12:00:00+00:00"
    assert rows[0].category == "preference"
    assert rows[0].source == "chat"
    assert entries == before
    with pytest.raises(FrozenInstanceError):
        rows[0].summary = "Changed"


def test_empty_rows():
    assert memory_rows([]) == []


@pytest.mark.parametrize("timestamp", ["", "not a date", "2026-02-30T12:00:00+00:00", None, 123, {}, []])
def test_rows_tolerate_malformed_timestamps(timestamp):
    entries = [entry("Malformed", timestamp), entry("Valid", NOW)]
    before = deepcopy(entries)
    rows = memory_rows(entries)
    assert next(row for row in rows if row.index == 0).timestamp == ""
    assert len(rows) == 2
    assert entries == before


def test_rows_tolerate_missing_timestamp_and_metadata():
    rows = memory_rows([{"summary": "Undated"}, entry("Dated", NOW)])
    assert [row.index for row in rows] == [1, 0]
    assert rows[1].timestamp == ""
    assert rows[1].category == "memory"
    assert rows[1].source == ""


@pytest.mark.parametrize("summary", ["  Likes\n\tcoffee  ", "A long memory with repeated words " * 5])
def test_edit_normalizes_updates_timestamp_and_preserves_all_other_fields(summary):
    entries = [entry("Unchanged"), {**entry("Old"), "custom": "keep this"}]
    before = deepcopy(entries)
    result = edit_memory(entries, 1, summary, now=lambda: NOW)
    assert result == [entries[0], {**entries[1], "summary": clip_memory_text(summary), "updated_at": NOW}]
    assert entries == before
    assert result is not entries
    for original, copied in zip(entries, result, strict=True):
        assert copied is not original
        copied["source"] = "Changed by caller"
    assert entries == before


def test_edit_default_timestamp_uses_store_utc_format():
    before = datetime.now(UTC).replace(microsecond=0)
    result = edit_memory([entry("Old")], 0, "New")
    timestamp = datetime.fromisoformat(result[0]["updated_at"])
    assert before <= timestamp <= datetime.now(UTC)
    assert timestamp.microsecond == 0
    assert result[0]["updated_at"].endswith("+00:00")


@pytest.mark.parametrize("index", [-1, 1, 999, None, True, "0", 0.0])
def test_invalid_index_raises_value_error_without_mutation(index):
    entries = [entry("Existing")]
    before = deepcopy(entries)
    with pytest.raises(ValueError):
        edit_memory(entries, index, "New", now=unexpected_clock)
    assert entries == before


def test_edit_empty_list_raises_value_error():
    with pytest.raises(ValueError):
        edit_memory([], 0, "New", now=unexpected_clock)


@pytest.mark.parametrize("summary", ["", " ", "\n\t  "])
def test_empty_summary_raises_value_error_without_mutation(summary):
    entries = [entry("Existing")]
    before = deepcopy(entries)
    with pytest.raises(ValueError):
        edit_memory(entries, 0, summary, now=unexpected_clock)
    assert entries == before


@pytest.mark.parametrize("summary", ["Likes tea", "  Likes\ntea  ", "Long memory " * 10])
def test_duplicate_summary_is_rejected_after_normalization_without_mutation(summary):
    entries = [entry("Edit me"), entry(clip_memory_text(summary))]
    before = deepcopy(entries)
    assert issubclass(DuplicateMemoryError, ValueError)
    with pytest.raises(DuplicateMemoryError):
        edit_memory(entries, 0, summary, now=unexpected_clock)
    assert entries == before


def test_duplicate_matching_is_exact():
    entries = [entry("Edit me"), entry("Likes tea")]
    result = edit_memory(entries, 0, "likes tea", now=lambda: NOW)
    assert result == [entry("likes tea", NOW), entries[1]]


@pytest.mark.parametrize("summary", ["Likes tea", "  Likes\ntea  "])
def test_noop_preserves_timestamp_and_returns_independent_copies(summary):
    entries = [entry("Likes tea"), entry("Another")]
    before = deepcopy(entries)
    result = edit_memory(entries, 0, summary, now=unexpected_clock)
    assert result == before
    assert result is not entries
    for copied in result:
        copied["summary"] = "Changed by caller"
    assert entries == before
