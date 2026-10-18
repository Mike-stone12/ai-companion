import logging
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from companion.core.chat.summary import build_summary_messages, request_summary
from companion.core.memory.extractor import MEMORY_RETRY_DELAYS


class FakeClient:
    def __init__(self, reply='```text\n"Likes music."\n```', base_url="https://api.deepseek.com/v1", error=None):
        self.config = SimpleNamespace(base_url=base_url)
        self.reply = reply
        self.error = error
        self.calls = []

    def complete(self, messages, *, extra, retry_delays):
        self.calls.append((messages, extra, retry_delays))
        if self.error is not None:
            raise self.error
        return self.reply


@pytest.fixture
def turns():
    return [
        {"role": "user", "content": "Private conversation: I like music."},
        {"role": "assistant", "content": "[happy] What do you play?"},
    ]


def test_request_returns_parsed_summary(turns):
    assert request_summary(FakeClient(), turns) == "Likes music."


@pytest.mark.parametrize("previous", [None, "", " \n ", "The user plays piano."])
def test_request_uses_summary_prompt_and_previous_summary(turns, previous):
    client = FakeClient(reply="Plays piano. Likes music.")

    assert request_summary(client, turns, previous_summary=previous, max_chars=12) == "Plays piano."

    assert len(client.calls) == 1
    assert client.calls[0][0] == build_summary_messages(previous, turns, max_chars=12)


@pytest.mark.parametrize(
    "base_url, expected_options",
    [
        ("https://api.deepseek.com/v1", {"thinking": {"type": "disabled"}, "temperature": 0.2}),
        ("https://api.moonshot.ai/v1", {"thinking": {"type": "disabled"}}),
        ("https://api.openai.com/v1", {"temperature": 0.2}),
    ],
)
def test_request_uses_provider_options_and_consolidation_retries(turns, base_url, expected_options):
    client = FakeClient(base_url=base_url)

    request_summary(client, turns)

    _, options, retry_delays = client.calls[0]
    assert options == expected_options
    assert retry_delays == MEMORY_RETRY_DELAYS


@pytest.mark.parametrize("reply", ["", " \n\t ", '```text\n"  "\n```', None, {"private": "model answer"}])
def test_invalid_answer_returns_none_and_logs_safe_warning(turns, reply, caplog):
    with caplog.at_level(logging.INFO):
        assert request_summary(FakeClient(reply=reply), turns) is None

    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert "Private conversation" not in caplog.text
    assert "model answer" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize("error_type", [RuntimeError, TimeoutError, URLError])
def test_client_failure_returns_none_and_logs_safe_warning(turns, error_type, caplog):
    client = FakeClient(error=error_type("Private conversation and provider response"))

    with caplog.at_level(logging.INFO):
        assert request_summary(client, turns) is None

    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert "Private conversation" not in caplog.text
    assert "provider response" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
