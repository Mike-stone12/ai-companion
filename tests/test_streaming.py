import io
import json
import urllib.error

import pytest

from companion.core.config import AppConfig
from companion.core.llm import client as llm_client
from companion.core.llm.client import OpenAICompatibleClient
from companion.core.llm.sse import iter_content_deltas, iter_sse_data
from companion.core.text import SentenceSplitter

# --- SSE parsing ---


def sse_lines(*events, done=True):
    lines = []
    for event in events:
        lines.append(f"data: {json.dumps(event, ensure_ascii=False)}\n".encode())
        lines.append(b"\n")
    if done:
        lines += [b"data: [DONE]\n", b"\n"]
    return lines


def delta(text):
    return {"choices": [{"delta": {"content": text}}]}


def test_sse_data_joins_multiline_events_and_skips_comments():
    lines = [b": keep-alive\n", b"data: one\n", b"data: two\n", b"\n", b"event: ping\n", b"data: three\n", b"\n"]
    assert list(iter_sse_data(lines)) == ["one\ntwo", "three"]


def test_content_deltas_in_order_until_done():
    lines = sse_lines(delta("你好"), delta("呀！"), {"choices": [{"delta": {}}]}, delta("再见"))
    lines += sse_lines(delta("ignored after DONE"), done=False)
    assert list(iter_content_deltas(lines)) == ["你好", "呀！", "再见"]


def test_reasoning_deltas_are_ignored():
    lines = sse_lines({"choices": [{"delta": {"reasoning_content": "thinking..."}}]}, delta("答案"))
    assert list(iter_content_deltas(lines)) == ["答案"]


def test_error_event_raises():
    lines = sse_lines({"error": {"message": "overloaded"}}, done=False)
    with pytest.raises(RuntimeError, match="overloaded"):
        list(iter_content_deltas(lines))


def test_crlf_and_unparseable_events_are_tolerated():
    lines = [b"data: {not json}\r\n", b"\r\n", f"data: {json.dumps(delta('ok'))}\r\n".encode(), b"\r\n"]
    assert list(iter_content_deltas(lines)) == ["ok"]


# --- sentence splitting ---


def split_streamed(text, **kwargs):
    splitter = SentenceSplitter(**kwargs)
    sentences = []
    for char in text:
        sentences += splitter.feed(char)
    return sentences + splitter.flush()


def test_splits_on_chinese_terminators():
    assert split_streamed("你好呀！今天过得怎么样？我很好。") == ["你好呀！", "今天过得怎么样？", "我很好。"]


def test_short_fragments_merge_into_next_sentence():
    assert split_streamed("嗯。好的，我们走吧。") == ["嗯。好的，我们走吧。"]


def test_closing_quotes_and_repeated_marks_stay_with_sentence():
    assert split_streamed("他说：“快走吧！！”然后就走了。") == ["他说：“快走吧！！”", "然后就走了。"]


def test_english_sentences_and_decimals():
    assert split_streamed("Hello there. Pi is 3.14 today. Bye!") == ["Hello there.", "Pi is 3.14 today.", "Bye!"]


def test_newlines_end_sentences():
    assert split_streamed("第一行内容\n第二行内容") == ["第一行内容", "第二行内容"]


def test_first_clause_is_cut_early_to_start_speech_sooner():
    text = "嗨～我今天过得挺好的呀，你呢？最近有没有什么开心的事情，想和我分享一下吗？"
    # Only the first piece is cut at a comma; "你呢？" is shorter than min_chars and merges forward.
    assert split_streamed(text) == [
        "嗨～我今天过得挺好的呀，",
        "你呢？最近有没有什么开心的事情，想和我分享一下吗？",
    ]


def test_long_clause_splits_at_last_comma():
    text = "我们可以先去公园散步，然后再去吃点好吃的东西，最后找个安静的地方坐一会儿聊聊天吧"
    sentences = split_streamed(text, soft_limit=30, first_soft_limit=30)
    assert len(sentences) == 2
    assert sentences[0].endswith("，")
    assert "".join(sentences) == text


def test_flush_returns_unterminated_tail():
    splitter = SentenceSplitter()
    assert splitter.feed("最后一句没有标点") == []
    assert splitter.flush() == ["最后一句没有标点"]
    assert splitter.flush() == []


def test_whitespace_only_is_not_a_sentence():
    assert split_streamed("你好！   \n\n  ") == ["你好！"]


# --- streaming client ---


class FakeStream(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def make_client(base_url="https://api.deepseek.com/v1"):
    config = AppConfig()
    config.api_key = "key"
    config.base_url = base_url
    config.chat_thinking = False
    return OpenAICompatibleClient(config)


def test_stream_chat_yields_deltas_and_sends_stream_flag(monkeypatch):
    sent = {}

    def fake_urlopen(request, timeout):
        sent.update(json.loads(request.data))
        return FakeStream(b"".join(sse_lines(delta("你好"), delta("呀"))))

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", fake_urlopen)
    deltas = list(make_client().stream_chat([{"role": "user", "content": "hi"}]))
    assert deltas == ["你好", "呀"]
    assert sent["stream"] is True
    assert sent["thinking"] == {"type": "disabled"}
    assert "temperature" not in sent


def test_stream_chat_retries_rate_limit_before_streaming(monkeypatch):
    responses = [
        urllib.error.HTTPError("u", 429, "busy", {}, io.BytesIO(b'{"error":{"type":"rate_limit_reached_error"}}')),
        FakeStream(b"".join(sse_lines(delta("ok")))),
    ]
    sleeps = []

    def fake_urlopen(request, timeout):
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(llm_client.time, "sleep", sleeps.append)
    assert list(make_client().stream_chat([{"role": "user", "content": "hi"}])) == ["ok"]
    assert sleeps == [1]
