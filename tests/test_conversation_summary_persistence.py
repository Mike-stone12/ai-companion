import json
import logging

import pytest

from companion.core.chat.history import MAX_HISTORY_ENTRIES, ConversationHistory, ConversationSummary
from companion.core.chat.summary import plan_summary_update


def test_summary_round_trip_preserves_turns_and_legacy_loader_shape(tmp_path):
    path = tmp_path / "history.json"
    history = ConversationHistory(path)
    history.append("user", "I play piano.")
    history.append("assistant", "[happy] What do you practice?")
    history.summary = ConversationSummary("Plays piano. 喜欢音乐。", summarized_count=2)
    history.save()

    restored = ConversationHistory(path)
    assert restored.entries == history.entries
    assert restored.messages() == history.messages()
    assert restored.summary == history.summary
    # The original loader accepts a list and skips dictionaries without a role.
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert [item for item in data if item.get("role") in ("user", "assistant")] == history.entries


def test_legacy_history_has_no_summary_and_load_does_not_rewrite_it(tmp_path):
    path = tmp_path / "history.json"
    original = '[{"role": "user", "content": "hi"}]'
    path.write_text(original, encoding="utf-8")

    history = ConversationHistory(path)
    assert history.messages() == [{"role": "user", "content": "hi"}]
    assert history.summary is None
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    "summary",
    [
        None, "private summary", [], {},
        {"text": "private summary"},
        {"summarized_count": 1},
        {"text": 42, "summarized_count": 1},
        {"text": "private summary", "summarized_count": "1"},
        {"text": "private summary", "summarized_count": True},
        {"text": "private summary", "summarized_count": 1.0},
        {"text": "private summary", "summarized_count": -1},
        {"text": "private summary", "summarized_count": 2},
    ],
)
def test_malformed_summary_is_ignored_with_warning(tmp_path, caplog, summary):
    path = tmp_path / "history.json"
    path.write_text(json.dumps([{"role": "user", "content": "hi"}, {"summary": summary}]), encoding="utf-8")
    original = path.read_bytes()

    with caplog.at_level(logging.WARNING):
        history = ConversationHistory(path)

    assert history.messages() == [{"role": "user", "content": "hi"}]
    assert history.summary is None
    assert any(record.levelno == logging.WARNING and "summary" in record.message for record in caplog.records)
    assert "private summary" not in caplog.text
    assert path.read_bytes() == original


@pytest.mark.parametrize("operation", ["append", "save", "load"])
@pytest.mark.parametrize("covered, expected", [(0, 0), (1, 0), (10, 8), (200, 198)])
def test_trimming_adjusts_summary_cursor(tmp_path, operation, covered, expected):
    path = tmp_path / "history.json"
    history = ConversationHistory(path)
    history.entries = [{"role": "user", "content": str(i), "at": ""} for i in range(MAX_HISTORY_ENTRIES)]
    history.summary = ConversationSummary("Earlier conversation.", summarized_count=covered)
    extra = [{"role": "user", "content": str(i), "at": ""} for i in (200, 201)]
    if operation == "append":
        for entry in extra:
            history.append(entry["role"], entry["content"])
    elif operation == "save":
        history.entries.extend(extra)
        history.save()
    else:
        path.write_text(json.dumps([
            *history.entries, *extra,
            {"summary": {"text": history.summary.text, "summarized_count": covered}},
        ]), encoding="utf-8")
        history.load()
        history.save()

    restored = ConversationHistory(path)
    assert len(restored.entries) == MAX_HISTORY_ENTRIES
    assert restored.entries[0]["content"] == "2"
    assert restored.summary == ConversationSummary("Earlier conversation.", summarized_count=expected)
    turns = restored.messages()
    assert plan_summary_update(turns, window=0, summarized_count=restored.summary.summarized_count, batch=1) == (
        turns[expected:], len(turns),
    )


def test_save_without_summary_uses_original_list_format(tmp_path):
    path = tmp_path / "history.json"
    history = ConversationHistory(path)
    history.append("user", "hi")
    assert json.loads(path.read_text(encoding="utf-8")) == history.entries
    assert ConversationHistory(path).summary is None


def test_clear_removes_summary_too(tmp_path):
    path = tmp_path / "history.json"
    history = ConversationHistory(path)
    history.append("user", "hi")
    history.summary = ConversationSummary("Greeting.", summarized_count=1)
    history.save()
    history.clear()
    assert history.summary is None
    assert ConversationHistory(path).summary is None
    assert json.loads(path.read_text(encoding="utf-8")) == []


def test_reload_resets_previous_summary(tmp_path):
    path = tmp_path / "history.json"
    history = ConversationHistory(path)
    history.summary = ConversationSummary("Past conversation.", summarized_count=0)
    history.load()
    assert history.summary is None


def test_failed_atomic_save_preserves_history_and_summary(tmp_path, monkeypatch):
    path = tmp_path / "history.json"
    history = ConversationHistory(path)
    history.append("user", "hi")
    history.summary = ConversationSummary("Greeting.", summarized_count=1)
    history.save()
    original = path.read_bytes()

    def fail_replace(source, destination):
        raise OSError("Simulated write failure")

    monkeypatch.setattr("companion.core.chat.history.os.replace", fail_replace)
    history.summary = ConversationSummary("Changed summary.", summarized_count=1)
    with pytest.raises(OSError, match="Simulated write failure"):
        history.save()
    assert path.read_bytes() == original
    assert sorted(item.name for item in tmp_path.iterdir()) == ["history.json"]
