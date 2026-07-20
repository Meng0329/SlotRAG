import httpx
import pytest

from slotrag.config import AgnesConfig, EmbeddingConfig, RerankerConfig
from slotrag.errors import SchemaError
from slotrag.providers import AgnesClient, EmbeddingClient, RerankerClient


def _transport(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_agnes_parses_tool_call(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret")
    def handler(request):
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(200, json={"id": "x", "choices": [{"message": {"content": None, "tool_calls": [{"id": "call", "function": {"name": "emit", "arguments": '{"rows": []}'}}]}, "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 2, "completion_tokens": 3}})
    client = AgnesClient(AgnesConfig(base_url="http://test/v1", model="m", api_key_env="TEST_KEY", timeout_seconds=1), _transport(handler))
    result = client.complete([{"role": "user", "content": "x"}], tools=[{"type": "function"}])
    assert result.tool_calls[0].name == "emit"
    assert result.usage.total_tokens == 5


def test_embedding_reorders_and_validates_dimension(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret")
    def handler(request):
        return httpx.Response(200, json={"data": [{"index": 1, "embedding": [2.0, 3.0]}, {"index": 0, "embedding": [0.0, 1.0]}]})
    client = EmbeddingClient(EmbeddingConfig(base_url="http://test/v1", model="m", api_key_env="TEST_KEY", timeout_seconds=1, dimension=2), _transport(handler))
    assert client.embed(["a", "b"]) == [[0.0, 1.0], [2.0, 3.0]]


def test_embedding_rejects_wrong_dimension(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret")
    def handler(request):
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})
    client = EmbeddingClient(EmbeddingConfig(base_url="http://test/v1", model="m", api_key_env="TEST_KEY", timeout_seconds=1, dimension=2), _transport(handler))
    with pytest.raises(SchemaError):
        client.embed("a")


def test_reranker_accepts_top_level_array(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret")
    def handler(request):
        return httpx.Response(200, json=[{"index": 1, "score": .8}, {"index": 0, "score": .2}])
    client = RerankerClient(RerankerConfig(base_url="http://test/v1", model="m", api_key_env="TEST_KEY", timeout_seconds=1), _transport(handler))
    values = client.rerank("q", ["a", "b"], top_n=2)
    assert values[0].index == 1
    assert values[0].document == "b"


def test_provider_retries_transient_status_and_records_attempts(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret")
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})

    config = EmbeddingConfig(
        base_url="http://test/v1",
        model="m",
        api_key_env="TEST_KEY",
        timeout_seconds=1,
        dimension=2,
        max_retries=1,
        retry_backoff_seconds=0,
    )
    client = EmbeddingClient(config, _transport(handler))
    assert client.embed("a") == [[1.0, 0.0]]
    assert client.stats.attempts == 2
    assert client.stats.retries == 1
    assert client.stats.successes == 1
