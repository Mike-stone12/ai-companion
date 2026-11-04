import io
import json
import logging
import urllib.error

import pytest

from companion.core.llm.embeddings import OpenAICompatibleEmbeddings
from companion.core.memory.recall import select_memories
from companion.core.memory.semantic_recall import select_semantic_memories


class FakeResponse(io.BytesIO):
    def __init__(self, body, status=200):
        super().__init__(body)
        self.status = status


class FakeTransport:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def __call__(self, request, timeout):
        self.calls.append((request, timeout))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def response(*vectors):
    return FakeResponse(json.dumps({"data": [
        {"index": index, "embedding": vector} for index, vector in reversed(list(enumerate(vectors)))
    ]}).encode("utf-8"))


def make_client(transport, **kwargs):
    return OpenAICompatibleEmbeddings(
        base_url="https://example.test/v1/", api_key="test-key", model="embedding-model",
        transport=transport, **kwargs,
    )


def test_request_and_reordering(caplog):
    transport = FakeTransport(response([1, 0], [0, 1]))
    texts = ["private coffee preference", "private book preference"]
    with caplog.at_level(logging.INFO):
        vectors = make_client(transport, timeout=7.5)(texts)
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert all(isinstance(value, float) for vector in vectors for value in vector)
    assert len(transport.calls) == 1
    request, timeout = transport.calls[0]
    assert request.full_url == "https://example.test/v1/embeddings"
    assert request.get_method() == "POST"
    assert dict(request.header_items()) == {
        "Content-type": "application/json", "Authorization": "Bearer test-key",
    }
    assert json.loads(request.data) == {"model": "embedding-model", "input": texts}
    assert timeout == 7.5
    assert all(text not in caplog.text for text in texts)


def test_empty_input_does_not_call_transport():
    transport = FakeTransport()
    assert make_client(transport)([]) == []
    assert transport.calls == []


def test_batching_preserves_input_order_with_batch_local_indices():
    transport = FakeTransport(response([1], [2]), response([3], [4]), response([5]))
    assert make_client(transport, batch_size=2)(["a", "b", "c", "d", "e"]) == [
        [1.0], [2.0], [3.0], [4.0], [5.0],
    ]
    assert [json.loads(request.data)["input"] for request, _ in transport.calls] == [
        ["a", "b"], ["c", "d"], ["e"],
    ]
    assert all(0 < timeout < float("inf") for _, timeout in transport.calls)


@pytest.mark.parametrize("status", [199, 300, 401, 429, 500])
def test_non_success_status(status):
    reply = FakeResponse(b"not JSON", status=status)
    with pytest.raises(RuntimeError, match=f"HTTP {status}"):
        make_client(FakeTransport(reply))(["text"])
    assert reply.closed


def test_urllib_http_error():
    error = urllib.error.HTTPError("https://example.test", 403, "Forbidden", {}, io.BytesIO(b"private text"))
    with pytest.raises(RuntimeError, match="HTTP 403"):
        make_client(FakeTransport(error))(["text"])
    assert error.fp.closed


@pytest.mark.parametrize("error", [urllib.error.URLError("offline"), TimeoutError("timed out")])
def test_transport_errors(error):
    with pytest.raises(RuntimeError, match="Embedding request failed"):
        make_client(FakeTransport(error))(["text"])


@pytest.mark.parametrize("body", [b"not JSON", b"{", b"\xff"])
def test_malformed_json(body):
    reply = FakeResponse(body)
    with pytest.raises(RuntimeError, match="JSON"):
        make_client(FakeTransport(reply))(["text"])
    assert reply.closed


@pytest.mark.parametrize("body", [{}, {"data": None}, {"data": {}}, [], None])
def test_missing_or_invalid_data(body):
    with pytest.raises(RuntimeError, match="data"):
        make_client(FakeTransport(FakeResponse(json.dumps(body).encode())))(["text"])


@pytest.mark.parametrize("vectors", [[], [[1.0], [2.0]]])
def test_count_mismatch(vectors):
    with pytest.raises(RuntimeError, match="count"):
        make_client(FakeTransport(response(*vectors)))(["text"])


@pytest.mark.parametrize("indices", [[0, 0], [-1, 1], [0, 2], [0, "1"], [0, True], [0, 1.0]])
def test_invalid_indices(indices):
    body = {"data": [{"index": index, "embedding": [1.0]} for index in indices]}
    with pytest.raises(RuntimeError, match="index"):
        make_client(FakeTransport(FakeResponse(json.dumps(body).encode())))(["a", "b"])


@pytest.mark.parametrize("item", [None, {}, {"embedding": [1.0]}, {"index": 0},
                                  {"index": 0, "embedding": "base64"},
                                  {"index": 0, "embedding": ["bad"]},
                                  {"index": 0, "embedding": [True]},
                                  {"index": 0, "embedding": [float("nan")]},
                                  {"index": 0, "embedding": [float("inf")]}])
def test_malformed_embedding_item(item):
    body = json.dumps({"data": [item]}).encode()
    with pytest.raises(RuntimeError, match="Embedding response"):
        make_client(FakeTransport(FakeResponse(body)))(["text"])


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), None])
def test_timeout_must_be_finite_and_positive(timeout):
    with pytest.raises(ValueError, match="timeout"):
        make_client(FakeTransport(), timeout=timeout)


@pytest.mark.parametrize("batch_size", [0, -1, 1.5, True])
def test_batch_size_must_be_a_positive_integer(batch_size):
    with pytest.raises(ValueError, match="batch_size"):
        make_client(FakeTransport(), batch_size=batch_size)


def test_client_works_as_semantic_recall_embedder():
    memories = [
        {"summary": "enjoys espresso", "updated_at": "2026-10-01"},
        {"summary": "reads novels", "updated_at": "2026-10-02"},
        {"summary": "likes hiking", "updated_at": "2026-10-03"},
    ]
    query = "preferred beverage"
    transport = FakeTransport(response([1, 0], [1, 0]), response([0, 1], [0, 1]))
    client = make_client(transport, batch_size=2)
    assert memories[0] not in select_memories(memories, query, limit=2)
    assert select_semantic_memories(memories, query, client, limit=2) == [memories[0], memories[2]]
    assert [text for request, _ in transport.calls for text in json.loads(request.data)["input"]] == [
        query, *[item["summary"] for item in memories],
    ]


def test_request_failure_allows_lexical_recall_fallback(caplog):
    memories = [
        {"summary": "private coffee preference", "updated_at": "2026-10-01"},
        {"summary": "books", "updated_at": "2026-10-02"},
        {"summary": "hiking", "updated_at": "2026-10-03"},
    ]
    client = make_client(FakeTransport(FakeResponse(b"private coffee preference", status=500)))
    with caplog.at_level(logging.WARNING):
        assert select_semantic_memories(memories, "coffee", client, limit=2) == [memories[0], memories[2]]
    assert "falling back to lexical recall" in caplog.text
    assert "coffee" not in caplog.text
