import json

from slotrag.tracing import provider_trace, record_provider_event


def test_provider_trace_records_sanitized_event_without_secret(tmp_path):
    trace_path = tmp_path / "trace.jsonl"
    with provider_trace(trace_path, include_payloads=True):
        record_provider_event(
            service="agnes",
            url="http://provider/v1/chat/completions",
            request={"model": "qwen", "api_key": "should-not-leak", "messages": [{"role": "user", "content": "Q"}]},
            response={"id": "req-1", "choices": [{"message": {"content": "A"}}]},
            status_code=200,
            latency_ms=12.5,
        )

    event = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
    assert event["service"] == "agnes"
    assert event["request"]["api_key"] == "<redacted>"
    assert "should-not-leak" not in trace_path.read_text(encoding="utf-8")
    assert event["response"]["id"] == "req-1"


def test_provider_trace_is_noop_when_not_enabled(tmp_path):
    trace_path = tmp_path / "trace.jsonl"
    with provider_trace(None, include_payloads=True):
        record_provider_event(service="embedding", url="http://provider/v1/embeddings", request={}, response={})
    assert not trace_path.exists()

