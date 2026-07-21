import json
import time

import pytest

from slotrag.benchmarking.config import BenchmarkSuite, StageConfig
from slotrag.benchmarking.datasets import DatasetSpec
from slotrag.benchmarking.runner import BenchmarkBudgetExceeded, BenchmarkRunner, _BudgetedRetriever
from slotrag.config import AppConfig
from slotrag.models import ExecutionResult, Passage
from slotrag.providers import ChatResult, ProviderStats, Usage


class _FakeAgnes:
    def __init__(self):
        self.stats = ProviderStats()

    def complete(self, *_args, **_kwargs):
        self.stats.attempts += 1
        self.stats.successes += 1
        return ChatResult(content="Alpha", usage=Usage(prompt_tokens=2, completion_tokens=1))


class _FakeService:
    def __init__(self):
        self.stats = ProviderStats()


class _FakeRetriever:
    def __init__(self):
        self.calls = 0

    def search(self, query):
        self.calls += 1
        return [query]


def _app_config():
    return AppConfig.model_validate({
        "agnes": {"base_url": "http://agnes/v1", "model": "a", "api_key_env": "A", "timeout_seconds": 1},
        "embedding": {"base_url": "http://embedding/v1", "model": "e", "api_key_env": "E", "timeout_seconds": 1, "dimension": 2},
        "reranker": {"base_url": "http://reranker/v1", "model": "r", "api_key_env": "R", "timeout_seconds": 1},
    })


def test_retrieval_budget_blocks_calls_before_execution():
    retriever = _FakeRetriever()
    guarded = _BudgetedRetriever(retriever, max_calls=1)
    assert guarded.search("one") == ["one"]
    with pytest.raises(BenchmarkBudgetExceeded):
        guarded.search("two")
    assert retriever.calls == 1


def test_runner_persists_atomic_items_and_resumes(tmp_path, monkeypatch):
    benchmark_root = tmp_path / "benchmark"
    benchmark_root.mkdir()
    dataset_path = benchmark_root / "toy.jsonl"
    dataset_path.write_text(json.dumps({
        "id": "q1",
        "question": "What is named Alpha?",
        "answers": ["Alpha"],
        "passages": [{"id": "p1", "doc_id": "d1", "text": "Alpha is the answer."}],
        "type": "bridge",
    }) + "\n", encoding="utf-8")
    spec = DatasetSpec("hotpotqa", "toy.jsonl", "toy.jsonl", "f1", lambda record: record["type"])
    monkeypatch.setitem(__import__("slotrag.benchmarking.runner", fromlist=["DATASETS"]).DATASETS, "hotpotqa", spec)
    fake_agnes = _FakeAgnes()
    monkeypatch.setattr(
        "slotrag.benchmarking.runner.provider_clients",
        lambda _config: (fake_agnes, _FakeService(), _FakeService()),
    )
    suite = BenchmarkSuite(
        benchmark_root=benchmark_root,
        datasets=["hotpotqa"],
        stages={"test": StageConfig(split="train", sample_size=1, methods=["graphrag"])},
    )
    runner = BenchmarkRunner(suite, _app_config(), tmp_path / "run")
    assert runner.run("test") == {"completed": 1, "skipped": 0, "retried": 0, "failed": 0, "empty": 0, "unsupported": 0}
    assert runner.run("test") == {"completed": 0, "skipped": 1, "retried": 0, "failed": 0, "empty": 0, "unsupported": 0}
    assert len(list((tmp_path / "run" / "items" / "test").rglob("*.json"))) == 1
    attempt_paths = list((tmp_path / "run" / "attempts" / "test").rglob("attempt-*.json"))
    assert len(attempt_paths) == 1
    assert json.loads(attempt_paths[0].read_text(encoding="utf-8"))["attempt_index"] == 1
    assert not list((tmp_path / "run").rglob("*.part"))


def test_runner_preserves_failed_attempt_before_successful_retry(tmp_path, monkeypatch):
    benchmark_root = tmp_path / "benchmark"
    benchmark_root.mkdir()
    (benchmark_root / "toy.jsonl").write_text(json.dumps({
        "id": "q1",
        "question": "What is named Alpha?",
        "answers": ["Alpha"],
        "passages": [{"id": "p1", "doc_id": "d1", "text": "Alpha is the answer."}],
        "type": "bridge",
    }) + "\n", encoding="utf-8")
    spec = DatasetSpec("hotpotqa", "toy.jsonl", "toy.jsonl", "f1", lambda record: record["type"])
    monkeypatch.setitem(__import__("slotrag.benchmarking.runner", fromlist=["DATASETS"]).DATASETS, "hotpotqa", spec)
    monkeypatch.setattr(
        "slotrag.benchmarking.runner.provider_clients",
        lambda _config: (_FakeAgnes(), _FakeService(), _FakeService()),
    )
    outcomes = [
        ExecutionResult(status="failed", error="RuntimeError: transient"),
        ExecutionResult(status="ok", answer="Alpha"),
    ]
    monkeypatch.setattr("slotrag.benchmarking.runner.run_method", lambda *_args, **_kwargs: outcomes.pop(0))
    suite = BenchmarkSuite(
        benchmark_root=benchmark_root,
        datasets=["hotpotqa"],
        stages={"test": StageConfig(split="train", sample_size=1, methods=["graphrag"])},
    )
    runner = BenchmarkRunner(suite, _app_config(), tmp_path / "run")

    first = runner.run("test")
    second = runner.run("test")

    assert first["failed"] == 1
    assert second["retried"] == 1
    attempt_paths = sorted((tmp_path / "run" / "attempts" / "test").rglob("attempt-*.json"))
    assert [path.name for path in attempt_paths] == ["attempt-0001.json", "attempt-0002.json"]
    attempts = [json.loads(path.read_text(encoding="utf-8")) for path in attempt_paths]
    assert [(item["attempt_index"], item["result"]["status"], item["failure_category"]) for item in attempts] == [
        (1, "failed", "other"),
        (2, "ok", "ok"),
    ]
    final_path = next((tmp_path / "run" / "items" / "test").rglob("*.json"))
    final = json.loads(final_path.read_text(encoding="utf-8"))
    assert final["attempt_index"] == 2
    assert final["result"]["status"] == "ok"


def test_runner_excludes_shared_index_build_from_online_wall_latency(tmp_path, monkeypatch):
    benchmark_root = tmp_path / "benchmark"
    benchmark_root.mkdir()
    (benchmark_root / "toy.jsonl").write_text(json.dumps({
        "id": "q1",
        "question": "Alpha?",
        "answers": ["Alpha"],
        "passages": [{"id": "p1", "doc_id": "d1", "text": "Alpha."}],
        "type": "bridge",
    }) + "\n", encoding="utf-8")
    spec = DatasetSpec("hotpotqa", "toy.jsonl", "toy.jsonl", "f1", lambda record: record["type"])
    monkeypatch.setitem(__import__("slotrag.benchmarking.runner", fromlist=["DATASETS"]).DATASETS, "hotpotqa", spec)
    monkeypatch.setattr(
        "slotrag.benchmarking.runner.provider_clients",
        lambda _config: (_FakeAgnes(), _FakeService(), _FakeService()),
    )

    class Retriever:
        passages = [Passage(id="p1", doc_id="d1", text="Alpha.")]

        def build_index(self):
            time.sleep(0.02)

        def search(self, _query):
            return []

    suite = BenchmarkSuite(
        benchmark_root=benchmark_root,
        datasets=["hotpotqa"],
        stages={"test": StageConfig(split="train", sample_size=1, methods=["hybrid"])},
    )
    runner = BenchmarkRunner(suite, _app_config(), tmp_path / "run")
    monkeypatch.setattr(runner, "_retriever", lambda _question: Retriever())
    monkeypatch.setattr("slotrag.benchmarking.runner.run_method", lambda *_args, **_kwargs: ExecutionResult(answer="Alpha"))

    runner.run("test")

    final_path = next((tmp_path / "run" / "items" / "test").rglob("*.json"))
    record = json.loads(final_path.read_text(encoding="utf-8"))
    metrics = record["result"]["metrics"]
    assert record["schema_version"] == 8
    assert metrics["index_build_latency_ms"] >= 20
    assert metrics["wall_latency_ms"] < metrics["index_build_latency_ms"]
