from copy import deepcopy

import pytest

from companion.core.chat.summary import build_chat_messages, plan_summary_update


@pytest.fixture
def turns():
    return [
        {"role": role, "content": f"{role} {pair}"}
        for pair in range(6)
        for role in ("user", "assistant")
    ]


@pytest.mark.parametrize("length", [0, 2, 4])
def test_history_within_window_needs_no_summary(turns, length):
    assert plan_summary_update(turns[:length], window=4, summarized_count=0, batch=2) is None


def test_exact_batch_threshold(turns):
    assert plan_summary_update(turns, window=8, summarized_count=0, batch=4) == (turns[:4], 4)


def test_below_batch_threshold(turns):
    assert plan_summary_update(turns, window=10, summarized_count=0, batch=4) is None


def test_skips_covered_turns_and_folds_all_eligible_turns(turns):
    assert plan_summary_update(turns, window=2, summarized_count=4, batch=4) == (turns[4:10], 10)


def test_threshold_counts_only_unsummarized_turns(turns):
    assert plan_summary_update(turns, window=4, summarized_count=6, batch=4) is None


def test_successive_updates_never_repeat_covered_turns(turns):
    first_turns, count = plan_summary_update(turns[:8], window=4, summarized_count=0, batch=4)
    assert plan_summary_update(turns[:8], window=4, summarized_count=count, batch=4) is None
    next_turns, next_count = plan_summary_update(turns, window=4, summarized_count=count, batch=4)
    assert first_turns == turns[:4]
    assert next_turns == turns[4:8]
    assert next_count == 8


@pytest.mark.parametrize("count", [12, 200, 250])
def test_count_at_or_beyond_history_length_does_not_repeat_turns(turns, count):
    assert plan_summary_update(turns, window=2, summarized_count=count, batch=2) is None


def test_empty_truncated_history():
    assert plan_summary_update([], window=2, summarized_count=200, batch=2) is None


def test_odd_window_keeps_pair_together(turns):
    assert plan_summary_update(turns, window=3, summarized_count=2, batch=3) == (turns[2:8], 8)


def test_pair_boundary_can_delay_batch_threshold(turns):
    assert plan_summary_update(turns, window=3, summarized_count=6, batch=3) is None


def test_zero_window_folds_all_remaining_turns(turns):
    assert plan_summary_update(turns, window=0, summarized_count=2, batch=3) == (turns[2:], 12)


def test_pending_user_stays_in_recent_window(turns):
    turns.append({"role": "user", "content": "One more question"})
    assert plan_summary_update(turns, window=1, summarized_count=8, batch=4) == (turns[8:12], 12)


@pytest.mark.parametrize("window, count, batch", [(-1, 0, 2), (2, -1, 2), (2, 0, 0), (2, 0, -1)])
def test_invalid_planning_arguments_are_rejected(turns, window, count, batch):
    with pytest.raises(ValueError):
        plan_summary_update(turns, window=window, summarized_count=count, batch=batch)


@pytest.mark.parametrize("memory", [None, "", "Known user preferences."])
@pytest.mark.parametrize("summary", [None, "", " \n\t ", "Earlier conversation."])
def test_chat_message_order_and_optional_context(turns, memory, summary):
    expected = [{"role": "system", "content": "Be helpful."}]
    if memory:
        expected.append({"role": "system", "content": memory})
    if summary and summary.strip():
        expected.append({"role": "system", "content": "Conversation summary:\nEarlier conversation."})
    expected.extend(turns)

    assert build_chat_messages("Be helpful.", turns, memory_context=memory, summary=summary) == expected


@pytest.mark.parametrize("memory", [None, "", "Known user preferences."])
def test_omitting_summary_matches_existing_app_message_assembly(turns, memory):
    # The app's conversation_window supplies up to 11 recent messages after its system prompt.
    recent = turns[-11:]
    expected = [{"role": "system", "content": "Be helpful."}, *recent]
    if memory:
        expected.insert(1, {"role": "system", "content": memory})
    assert build_chat_messages("Be helpful.", recent, memory_context=memory) == expected


def test_chat_messages_with_no_turns():
    assert build_chat_messages("Be helpful.", []) == [{"role": "system", "content": "Be helpful."}]


def test_helpers_are_deterministic_and_leave_inputs_unchanged(turns):
    original = deepcopy(turns)
    plan = plan_summary_update(turns, window=2, summarized_count=2, batch=4)
    messages = build_chat_messages("System", turns, memory_context="Memory", summary="Summary")
    assert plan_summary_update(turns, window=2, summarized_count=2, batch=4) == plan
    assert build_chat_messages("System", turns, memory_context="Memory", summary="Summary") == messages
    assert turns == original
