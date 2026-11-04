from unittest.mock import Mock

import pytest

from companion.core.voice_input_actions import can_start_voice_input, deliver_voice_input_result
from companion.core.voice_input_controller import VoiceInputResult


@pytest.mark.parametrize("blocked", ["busy", "worker_active", "closing"])
def test_voice_press_is_ignored_while_unavailable(blocked):
    flags = dict(busy=False, worker_active=False, closing=False)
    assert can_start_voice_input(**flags)
    flags[blocked] = True
    assert not can_start_voice_input(**flags)


def test_transcript_uses_chat_submission():
    submit, notice = Mock(), Mock()
    deliver_voice_input_result(VoiceInputResult("ok", text="hello"), submit, notice)
    submit.assert_called_once_with("hello")
    notice.assert_not_called()


@pytest.mark.parametrize("status", ["too_short", "empty_transcript", "error"])
def test_unsuccessful_recording_shows_notice(status):
    submit, notice = Mock(), Mock()
    deliver_voice_input_result(VoiceInputResult(status, message="provider error"), submit, notice)
    submit.assert_not_called()
    notice.assert_called_once()
    assert notice.call_args.args[0]


@pytest.mark.parametrize("status", ["idle", "recording", "transcribing", "disabled"])
def test_nonterminal_results_do_nothing(status):
    submit, notice = Mock(), Mock()
    deliver_voice_input_result(VoiceInputResult(status), submit, notice)
    submit.assert_not_called()
    notice.assert_not_called()
