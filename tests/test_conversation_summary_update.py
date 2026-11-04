from copy import deepcopy
from unittest.mock import Mock

import pytest

from companion.core.chat.history import ConversationHistory, ConversationSummary
from companion.core.chat.summary import build_chat_messages, update_conversation_summary


@pytest.fixture
def turns():
    return [
        {"role": role, "content": f"{role} {pair}"}
        for pair in range(10)
        for role in ("user", "assistant")
    ]


@pytest.mark.parametrize("summary", [None, ConversationSummary("Earlier facts.", 2)])
def test_no_fold_returns_original_without_request(turns, summary):
    request = Mock()
    assert update_conversation_summary(turns[:4], summary, request, window=4) is summary
    request.assert_not_called()


@pytest.mark.parametrize("summary", [None, ConversationSummary("Earlier facts.", 2)])
def test_success_updates_text_and_cursor_using_only_eligible_turns(turns, summary):
    original = deepcopy(turns)
    request = Mock(return_value="Updated facts.")
    result = update_conversation_summary(turns, summary, request, window=3)
    assert result == ConversationSummary("Updated facts.", 16)
    covered = summary.summarized_count if summary else 0
    request.assert_called_once_with(turns[covered:16], summary.text if summary else None)
    assert turns == original
    request.reset_mock()
    assert update_conversation_summary(turns, result, request, window=3) is result
    request.assert_not_called()


@pytest.mark.parametrize("summary", [None, ConversationSummary("Earlier facts.", 2)])
@pytest.mark.parametrize("reply", [None, "", " \n "])
def test_invalid_result_preserves_summary_and_cursor(turns, summary, reply):
    assert update_conversation_summary(turns, summary, Mock(return_value=reply), window=4) is summary


@pytest.mark.parametrize("summary", [None, ConversationSummary("Earlier facts.", 2)])
def test_request_exception_preserves_state_and_does_not_log_private_text(turns, summary, caplog):
    request = Mock(side_effect=TimeoutError("Private provider response"))
    assert update_conversation_summary(turns, summary, request, window=4) is summary
    request.assert_called_once()
    assert "Private provider response" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_update_persists_and_is_injected_after_restart(tmp_path, turns):
    history = ConversationHistory(tmp_path / "history.json")
    history.entries = deepcopy(turns)
    history.summary = update_conversation_summary(
        history.messages(), history.summary, Mock(return_value="Likes music."), window=4,
    )
    history.save()
    restored = ConversationHistory(history.path)
    assert restored.summary == ConversationSummary("Likes music.", 16)
    payload = build_chat_messages("System", restored.messages()[-4:], summary=restored.summary.text)
    assert payload[1] == {"role": "system", "content": "Conversation summary:\nLikes music."}
    assert payload[2:] == turns[-4:]
