import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from slotrag.benchmarking.config import BenchmarkSuite, StageConfig
from slotrag.benchmarking.datasets import DatasetSpec
from slotrag.benchmarking.runner import (
    BenchmarkBudgetExceeded,
    BenchmarkRunner,
    FrozenPlanPreparationError,
    _BudgetedRetriever,
)
from slotrag.config import AppConfig
from slotrag.models import ExecutionResult, Passage, QuestionRecord, RunMetrics, SlotPlan
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


def test_runner_merges_concurrent_manifest_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "slotrag.benchmarking.runner.provider_clients",
        lambda _config, **_kwargs: (_FakeAgnes(), _FakeService(), _FakeService()),
    )
    suite = BenchmarkSuite(
        benchmark_root=tmp_path / "benchmark",
        datasets=["hotpotqa"],
        stages={"test": StageConfig(split="train", sample_size=1, methods=["hybrid", "graphrag"])},
    )
    output_dir = tmp_path / "run"
    first = BenchmarkRunner(suite, _app_config(), output_dir)
    second = BenchmarkRunner(suite, _app_config(), output_dir)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(first._write_manifest, "test", ["hotpotqa"], ["hybrid"]),
            executor.submit(second._write_manifest, "test", ["hotpotqa"], ["graphrag"]),
        ]
        for future in futures:
            future.result()

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["run_requests"]) == 2
    assert {tuple(request["methods"]) for request in manifest["run_requests"]} == {
        ("hybrid",),
        ("graphrag",),
    }


def test_runner_recomputes_global_progress_from_all_persisted_shards(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "slotrag.benchmarking.runner.provider_clients",
        lambda _config, **_kwargs: (_FakeAgnes(), _FakeService(), _FakeService()),
    )
    suite = BenchmarkSuite(
        benchmark_root=tmp_path / "benchmark",
        datasets=["hotpotqa"],
        stages={"test": StageConfig(split="train", sample_size=1, methods=["hybrid", "graphrag"])},
    )
    output_dir = tmp_path / "run"
    runner = BenchmarkRunner(suite, _app_config(), output_dir)
    records = {
        "hybrid/q1.json": {"result": {"status": "ok"}},
        "graphrag/q2.json": {"result": {"status": "failed"}},
    }
    for relative, record in records.items():
        item_path = output_dir / "items" / "test" / "hotpotqa" / relative
        item_path.parent.mkdir(parents=True, exist_ok=True)
        item_path.write_text(json.dumps(record), encoding="utf-8")
    for relative in ("hybrid/q1/attempt-0001.json", "graphrag/q2/attempt-0001.json", "graphrag/q2/attempt-0002.json"):
        attempt_path = output_dir / "attempts" / "test" / "hotpotqa" / relative
        attempt_path.parent.mkdir(parents=True, exist_ok=True)
        attempt_path.write_text("{}", encoding="utf-8")

    progress = runner._write_stage_progress("test")

    assert progress["completed"] == 2
    assert progress["attempts"] == 3
    assert progress["retried"] == 1
    assert progress["ok"] == 1
    assert progress["failed"] == 1
    assert json.loads((output_dir / "progress.json").read_text(encoding="utf-8")) == progress


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
    assert record["schema_version"] == 25
    assert metrics["index_build_latency_ms"] >= 20
    assert metrics["wall_latency_ms"] < metrics["index_build_latency_ms"]


def test_frozen_plan_stage_rejects_compile_incompatible_methods():
    with pytest.raises(ValueError, match="compiler-compatible"):
        StageConfig(
            split="train",
            sample_size=1,
            methods=["slotrag", "slotrag-no-direct"],
            frozen_plan_source="slotrag",
        )


def test_runner_compiles_one_frozen_plan_and_replays_same_hash(tmp_path, monkeypatch):
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
    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "Answer", "arguments": ["?answer"]}],
        "outputs": ["?answer"],
    })
    compiled = []

    def compile_plan(method_spec, dataset, question, client):
        compiled.append((method_spec.key, dataset, question.id, client))
        return plan, RunMetrics(
            llm_calls=1,
            prompt_tokens=11,
            completion_tokens=3,
            compilation_llm_calls=1,
            compilation_prompt_tokens=11,
            compilation_completion_tokens=3,
            compilation_latency_ms=12.5,
        )

    replayed = []

    def run_replay(method, **kwargs):
        replayed.append((method, kwargs["frozen_plan"]))
        return ExecutionResult(
            answer="Alpha",
            plan=kwargs["frozen_plan"],
            metrics=RunMetrics(frozen_plan_replays=1),
        )

    class Retriever:
        passages = [Passage(id="p1", doc_id="d1", text="Alpha is the answer.")]

        def build_index(self):
            pass

    monkeypatch.setattr("slotrag.benchmarking.runner.compile_slotrag_plan", compile_plan, raising=False)
    monkeypatch.setattr("slotrag.benchmarking.runner.run_method", run_replay)
    suite = BenchmarkSuite(
        benchmark_root=benchmark_root,
        datasets=["hotpotqa"],
        stages={"test": StageConfig(
            split="train",
            sample_size=1,
            methods=["slotrag", "slotrag-typed-extraction"],
            frozen_plan_source="slotrag",
        )},
    )
    runner = BenchmarkRunner(suite, _app_config(), tmp_path / "run")
    monkeypatch.setattr(runner, "_retriever", lambda _question: Retriever())

    assert runner.run("test")["completed"] == 2
    assert len(compiled) == 1
    assert [method for method, _plan in replayed] == ["slotrag", "slotrag-typed-extraction"]
    assert replayed[0][1] == replayed[1][1] == plan

    snapshots = list((tmp_path / "run" / "plans" / "test").rglob("*.json"))
    assert len(snapshots) == 1
    records = [json.loads(path.read_text(encoding="utf-8")) for path in (tmp_path / "run" / "items" / "test").rglob("*.json")]
    assert {record["schema_version"] for record in records} == {25}
    assert len({record["plan_provenance"]["plan_sha256"] for record in records}) == 1
    assert len({record["plan_provenance"]["effective_plan_sha256"] for record in records}) == 1
    assert {record["plan_provenance"]["source_method"] for record in records} == {"slotrag"}
    assert {record["plan_provenance"]["compiler_metrics"]["compilation_llm_calls"] for record in records} == {1}
    assert {record["result"]["metrics"]["llm_calls"] for record in records} == {0}

    assert runner.run("test")["skipped"] == 2
    assert len(compiled) == 1


def test_frozen_plan_attempts_are_immutable_and_stale_inputs_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "slotrag.benchmarking.runner.provider_clients",
        lambda _config: (_FakeAgnes(), _FakeService(), _FakeService()),
    )
    suite = BenchmarkSuite(
        benchmark_root=tmp_path / "benchmark",
        datasets=["hotpotqa"],
        stages={"test": StageConfig(
            split="train",
            sample_size=1,
            methods=["slotrag", "slotrag-typed-extraction"],
            frozen_plan_source="slotrag",
        )},
    )
    runner = BenchmarkRunner(suite, _app_config(), tmp_path / "run")
    question = QuestionRecord(
        id="q1",
        question="What is named Alpha?",
        passages=[Passage(id="p1", doc_id="d1", text="Alpha is the answer.")],
    )
    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "Answer", "arguments": ["?answer"]}],
        "outputs": ["?answer"],
    })
    outcomes = [RuntimeError("transient compiler failure"), (plan, RunMetrics(compilation_llm_calls=1))]
    compile_calls = []

    def compile_plan(*_args):
        compile_calls.append(1)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr("slotrag.benchmarking.runner.compile_slotrag_plan", compile_plan)

    with pytest.raises(FrozenPlanPreparationError) as failed:
        runner._load_or_create_frozen_plan("test", "hotpotqa", question, "slotrag")
    assert failed.value.provenance["status"] == "failed"

    replayed, provenance = runner._load_or_create_frozen_plan("test", "hotpotqa", question, "slotrag")
    assert replayed == plan
    assert provenance["status"] == "ok"
    attempts = sorted((tmp_path / "run" / "plan_attempts" / "test").rglob("attempt-*.json"))
    assert [json.loads(path.read_text(encoding="utf-8"))["status"] for path in attempts] == ["failed", "ok"]
    assert len(list((tmp_path / "run" / "plans" / "test").rglob("*.json"))) == 1

    loaded, _ = runner._load_or_create_frozen_plan("test", "hotpotqa", question, "slotrag")
    assert loaded == plan
    assert len(compile_calls) == 2

    changed = question.model_copy(update={"question": "What is named Beta?"})
    with pytest.raises(ValueError, match="input hash"):
        runner._load_or_create_frozen_plan("test", "hotpotqa", changed, "slotrag")
    assert len(compile_calls) == 2


def test_frozen_plan_stage_can_import_verified_snapshots_without_compiling(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "slotrag.benchmarking.runner.provider_clients",
        lambda _config: (_FakeAgnes(), _FakeService(), _FakeService()),
    )
    source_suite = BenchmarkSuite(
        benchmark_root=tmp_path / "benchmark",
        datasets=["hotpotqa"],
        stages={"source": StageConfig(
            split="train",
            sample_size=1,
            methods=["slotrag"],
            frozen_plan_source="slotrag",
        )},
    )
    source_runner = BenchmarkRunner(source_suite, _app_config(), tmp_path / "source-run")
    question = QuestionRecord(
        id="q1",
        question="What is named Alpha?",
        passages=[Passage(id="p1", doc_id="d1", text="Alpha is the answer.")],
    )
    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "Answer", "arguments": ["?answer"]}],
        "outputs": ["?answer"],
    })
    monkeypatch.setattr(
        "slotrag.benchmarking.runner.compile_slotrag_plan",
        lambda *_args: (plan, RunMetrics(compilation_llm_calls=1)),
    )
    source_runner._load_or_create_frozen_plan("source", "hotpotqa", question, "slotrag")

    import_dir = tmp_path / "source-run" / "plans" / "source"
    imported_suite = BenchmarkSuite(
        benchmark_root=tmp_path / "benchmark",
        datasets=["hotpotqa"],
        stages={"imported": StageConfig(
            split="train",
            sample_size=1,
            methods=["slotrag", "slotrag-anchor-folding"],
            frozen_plan_source="slotrag",
            frozen_plan_import_dir=import_dir,
        )},
    )
    imported_runner = BenchmarkRunner(imported_suite, _app_config(), tmp_path / "imported-run")
    monkeypatch.setattr(
        "slotrag.benchmarking.runner.compile_slotrag_plan",
        lambda *_args: (_ for _ in ()).throw(AssertionError("verified import must not compile")),
    )

    imported_plan, provenance = imported_runner._load_or_create_frozen_plan(
        "imported",
        "hotpotqa",
        question,
        "slotrag",
    )

    assert imported_plan == plan
    assert provenance["preparation_mode"] == "imported"
    assert provenance["imported_from"].endswith("plans/source/hotpotqa/q1-c75de8c1b7c3.json")
    assert len(list((tmp_path / "imported-run" / "plans" / "imported").rglob("*.json"))) == 1
    assert len(list((tmp_path / "imported-run" / "plan_attempts" / "imported").rglob("attempt-*.json"))) == 1
