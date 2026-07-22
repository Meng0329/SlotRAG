from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import resource
import signal
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import AppConfig
from ..data import normalize_jsonl
from ..models import ExecutionResult, QuestionRecord, RunMetrics, SlotPlan
from ..providers import AgnesClient, EmbeddingClient, RerankerClient, provider_clients
from ..retrieval import EmbeddingCache, HybridRetriever
from .config import BenchmarkSuite
from .datasets import DATASETS, load_sample
from .methods import METHODS, compile_slotrag_plan, run_method, slotrag_compile_options
from .metrics import score_record


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _safe_id(value: str) -> str:
    prefix = "".join(char if char.isalnum() or char in "-_" else "_" for char in value)[:80]
    digest = hashlib.sha256(value.encode()).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _plan_sha256(plan: SlotPlan) -> str:
    return _canonical_sha256(plan.model_dump(mode="json"))


def _failure_category(status: str, error: str | None, answer: str | None) -> str:
    if status == "ok":
        return "ok" if answer and answer.strip() else "empty_answer"
    if status == "empty":
        return "empty"
    if status == "unsupported_operation":
        return "unsupported_operation"
    if status == "budget_exceeded":
        return "budget_exceeded"
    message = (error or "").casefold()
    if "429" in message or "rate limit" in message:
        return "provider_http_429"
    if any(token in message for token in ("500", "502", "503", "504", "server error")):
        return "provider_http_5xx"
    if any(token in message for token in ("connecterror", "connection", "dns", "timed out", "timeout")):
        return "provider_connect"
    if any(token in message for token in ("configuration", "validationerror", "schemaerror", "missing environment")):
        return "configuration"
    return "other"


def _git_revision(path: Path) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _source_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    roots = [root / "src", root / "configs", root / "tests"]
    files = [root / "pyproject.toml", root / "README.md", root / "benchmark" / "download_datasets.py"]
    for directory in roots:
        if directory.exists():
            files.extend(path for path in directory.rglob("*") if path.is_file() and "__pycache__" not in path.parts)
    for path in sorted(set(files)):
        if not path.exists():
            continue
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_dirty(root: Path) -> bool:
    try:
        return bool(subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        return True


def _gpu_inventory() -> list[str]:
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return [line.strip() for line in output.splitlines() if line.strip()]
    except (OSError, subprocess.CalledProcessError):
        return []


def _package_versions() -> dict[str, str]:
    names = ["slotrag", "httpx", "numpy", "pydantic", "PyYAML", "rank-bm25", "typer"]
    versions: dict[str, str] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "unavailable"
    return versions


def _stats_delta(before: tuple[int, int, int, float, tuple[str, ...]], after: tuple[int, int, int, float, tuple[str, ...]]) -> dict[str, Any]:
    return {
        "attempts": after[0] - before[0],
        "successes": after[1] - before[1],
        "retries": after[2] - before[2],
        "latency_ms": after[3] - before[3],
        "request_ids": list(after[4][len(before[4]):]),
    }


class BenchmarkBudgetExceeded(RuntimeError):
    pass


class FrozenPlanPreparationError(RuntimeError):
    def __init__(self, message: str, provenance: dict[str, Any]) -> None:
        super().__init__(message)
        self.provenance = provenance


class _BudgetedAgnes:
    def __init__(self, client: AgnesClient, max_calls: int) -> None:
        self.client = client
        self.max_calls = max_calls
        self.calls = 0

    def complete(self, *args: Any, **kwargs: Any) -> Any:
        if self.calls >= self.max_calls:
            raise BenchmarkBudgetExceeded(f"LLM call budget exceeded ({self.max_calls})")
        self.calls += 1
        return self.client.complete(*args, **kwargs)

    def require_tool(self, *args: Any, **kwargs: Any) -> Any:
        return self.client.require_tool(*args, **kwargs)


class _BudgetedRetriever:
    def __init__(self, retriever: HybridRetriever, max_calls: int) -> None:
        self.retriever = retriever
        self.max_calls = max_calls
        self.calls = 0

    def search(self, *args: Any, **kwargs: Any) -> Any:
        if self.calls >= self.max_calls:
            raise BenchmarkBudgetExceeded(f"retrieval call budget exceeded ({self.max_calls})")
        self.calls += 1
        return self.retriever.search(*args, **kwargs)


@contextmanager
def _question_deadline(seconds: float) -> Any:
    if not hasattr(signal, "setitimer"):
        yield
        return
    previous_handler = signal.getsignal(signal.SIGALRM)

    def expire(_signum: int, _frame: Any) -> None:
        raise BenchmarkBudgetExceeded(f"question timeout exceeded ({seconds:g}s)")

    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


class BenchmarkRunner:
    """Facade for reproducible sampling, execution, and per-item persistence."""

    def __init__(self, suite: BenchmarkSuite, app_config: AppConfig, output_dir: Path) -> None:
        self.suite = suite
        self.app_config = app_config
        self.output_dir = output_dir
        self.agnes, self.embedding, self.reranker = provider_clients(app_config)
        self.embedding_cache = EmbeddingCache(output_dir / "cache" / "embeddings.json")

    def _sample_path(self, stage: str, dataset: str) -> Path:
        return self.output_dir / "samples" / stage / f"{dataset}.jsonl"

    def _plan_snapshot_path(self, stage: str, dataset: str, question_id: str) -> Path:
        return self.output_dir / "plans" / stage / dataset / f"{_safe_id(question_id)}.json"

    def _plan_attempt_dir(self, stage: str, dataset: str, question_id: str) -> Path:
        return self.output_dir / "plan_attempts" / stage / dataset / _safe_id(question_id)

    def _load_or_create_sample(self, stage_name: str, dataset: str) -> list[QuestionRecord]:
        stage = self.suite.stage(stage_name)
        sample_path = self._sample_path(stage_name, dataset)
        if sample_path.exists():
            from ..data import load_questions

            return load_questions(sample_path)
        questions = load_sample(
            DATASETS[dataset],
            self.suite.benchmark_root,
            split=stage.split,
            size=stage.sample_size,
            seed=self.suite.seed,
        )
        normalize_jsonl(questions, sample_path)
        return questions

    def prepare(self, stage_name: str) -> dict[str, int]:
        return {dataset: len(self._load_or_create_sample(stage_name, dataset)) for dataset in self.suite.datasets}

    def sample(self, stage_name: str, dataset: str) -> list[QuestionRecord]:
        if dataset not in self.suite.datasets:
            raise ValueError(f"dataset is not configured: {dataset}")
        return self._load_or_create_sample(stage_name, dataset)

    def _retriever(self, question: QuestionRecord) -> HybridRetriever:
        from ..data import chunk_passages

        passages = chunk_passages(
            question.passages,
            chunk_tokens=self.app_config.retrieval.chunk_tokens,
            overlap=self.app_config.retrieval.chunk_overlap,
        )
        return HybridRetriever(
            passages,
            self.embedding,
            self.reranker,
            bm25_k=self.app_config.retrieval.bm25_k,
            dense_k=self.app_config.retrieval.dense_k,
            final_k=self.app_config.retrieval.final_k,
            rrf_k=self.app_config.retrieval.rrf_k,
            bm25_weight=self.app_config.retrieval.bm25_weight,
            dense_weight=self.app_config.retrieval.dense_weight,
            rerank_enabled=self.app_config.reranker.enabled,
            cache=self.embedding_cache,
        )

    def _provider_snapshot(self) -> dict[str, tuple[int, int, int, float, tuple[str, ...]]]:
        return {
            "agnes": self.agnes.stats.snapshot(),
            "embedding": self.embedding.stats.snapshot(),
            "reranker": self.reranker.stats.snapshot(),
        }

    @staticmethod
    def _plan_provenance(record: dict[str, Any], snapshot_path: str | None) -> dict[str, Any]:
        provenance = {key: value for key, value in record.items() if key != "plan"}
        provenance["snapshot_path"] = snapshot_path
        return provenance

    def _frozen_plan_input(
        self,
        stage_name: str,
        dataset: str,
        question: QuestionRecord,
        source_method: str,
    ) -> dict[str, Any]:
        return {
            "stage": stage_name,
            "dataset": dataset,
            "question_id": question.id,
            "question": question.question,
            "source_method": source_method,
            "compiler_options": slotrag_compile_options(METHODS[source_method], dataset, question),
        }

    def _load_or_create_frozen_plan(
        self,
        stage_name: str,
        dataset: str,
        question: QuestionRecord,
        source_method: str,
    ) -> tuple[SlotPlan, dict[str, Any]]:
        snapshot_path = self._plan_snapshot_path(stage_name, dataset, question.id)
        relative_snapshot_path = snapshot_path.relative_to(self.output_dir).as_posix()
        compile_input = self._frozen_plan_input(stage_name, dataset, question, source_method)
        input_sha256 = _canonical_sha256(compile_input)
        if snapshot_path.exists():
            try:
                snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
                if snapshot.get("status") != "ok":
                    raise ValueError("snapshot status is not ok")
                if snapshot.get("input_sha256") != input_sha256:
                    raise ValueError("snapshot input hash does not match the current stage question and compiler options")
                plan = SlotPlan.model_validate(snapshot["plan"])
                if snapshot.get("plan_sha256") != _plan_sha256(plan):
                    raise ValueError("snapshot plan hash does not match its plan payload")
            except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
                raise ValueError(f"invalid frozen plan snapshot {snapshot_path}: {exc}") from exc
            return plan, self._plan_provenance(snapshot, relative_snapshot_path)

        attempt_dir = self._plan_attempt_dir(stage_name, dataset, question.id)
        attempt_paths = sorted(attempt_dir.glob("attempt-*.json")) if attempt_dir.exists() else []
        attempt_indices = [
            int(path.stem.rsplit("-", 1)[-1])
            for path in attempt_paths
            if path.stem.rsplit("-", 1)[-1].isdigit()
        ]
        attempt_index = max(attempt_indices, default=0) + 1
        before = self._provider_snapshot()
        started = time.perf_counter()
        plan: SlotPlan | None = None
        compiler_metrics: RunMetrics | None = None
        error: Exception | None = None
        try:
            with _question_deadline(self.suite.budget.question_timeout_seconds):
                plan, compiler_metrics = compile_slotrag_plan(
                    METHODS[source_method],
                    dataset,
                    question,
                    _BudgetedAgnes(self.agnes, self.suite.budget.max_llm_calls),
                )
        except Exception as exc:
            error = exc
        after = self._provider_snapshot()
        delta = {name: _stats_delta(before[name], after[name]) for name in before}
        provider_delta = {
            "attempts": sum(value["attempts"] for value in delta.values()),
            **delta,
        }
        base_record: dict[str, Any] = {
            "schema_version": 1,
            "stage": stage_name,
            "dataset": dataset,
            "question_id": question.id,
            "source_method": source_method,
            "input_sha256": input_sha256,
            "compiler_options": compile_input["compiler_options"],
            "attempt_index": attempt_index,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "wall_latency_ms": (time.perf_counter() - started) * 1000,
            "provider_delta": provider_delta,
        }
        attempt_path = attempt_dir / f"attempt-{attempt_index:04d}.json"
        if error is not None or plan is None or compiler_metrics is None:
            message = f"{error.__class__.__name__}: {error}" if error is not None else "RuntimeError: compiler returned no plan"
            failed_record = {
                **base_record,
                "status": "failed",
                "error": message,
                "failure_category": _failure_category("failed", message, None),
            }
            _atomic_json(attempt_path, failed_record)
            raise FrozenPlanPreparationError(
                message,
                self._plan_provenance(failed_record, None),
            )
        snapshot = {
            **base_record,
            "status": "ok",
            "error": None,
            "failure_category": "ok",
            "plan_sha256": _plan_sha256(plan),
            "plan": plan.model_dump(mode="json"),
            "compiler_metrics": compiler_metrics.model_dump(mode="json"),
        }
        _atomic_json(attempt_path, snapshot)
        _atomic_json(snapshot_path, snapshot)
        return plan, self._plan_provenance(snapshot, relative_snapshot_path)

    def _instrument(
        self,
        result: ExecutionResult,
        before: dict[str, tuple[int, int, int, float, tuple[str, ...]]],
        cache_before: tuple[int, int],
        wall_ms: float,
        peak_rss_mb: float,
        index_build_ms: float,
        index_bytes: int,
        index_delta: dict[str, Any],
        index_cache_delta: tuple[int, int],
    ) -> tuple[ExecutionResult, dict[str, Any]]:
        after = self._provider_snapshot()
        cache_after = self.embedding_cache.snapshot()
        delta = {name: _stats_delta(before[name], after[name]) for name in before}
        provider_latency = sum(value["latency_ms"] for value in delta.values())
        attempts = sum(value["attempts"] for value in delta.values())
        retries = sum(value["retries"] for value in delta.values())
        request_ids = [request_id for value in delta.values() for request_id in value["request_ids"]]
        instrumented = result.metrics.model_copy(update={
            "llm_calls": delta["agnes"]["attempts"],
            "embedding_calls": delta["embedding"]["attempts"],
            "reranker_calls": delta["reranker"]["attempts"],
            "retry_count": retries,
            "provider_latency_ms": provider_latency,
            "latency_ms": provider_latency,
            "wall_latency_ms": wall_ms,
            "peak_rss_mb": max(result.metrics.peak_rss_mb, peak_rss_mb),
            "cache_hits": cache_after[0] - cache_before[0],
            "cache_misses": cache_after[1] - cache_before[1],
            "index_build_latency_ms": result.metrics.index_build_latency_ms + index_build_ms,
            "index_provider_latency_ms": sum(value["latency_ms"] for value in index_delta.values()),
            "index_embedding_calls": index_delta["embedding"]["attempts"],
            "index_cache_hits": index_cache_delta[0],
            "index_cache_misses": index_cache_delta[1],
            "index_bytes": max(result.metrics.index_bytes, index_bytes),
            "provider_request_ids": list(dict.fromkeys(result.metrics.provider_request_ids + request_ids)),
        })
        return result.model_copy(update={"metrics": instrumented}), {"attempts": attempts, **delta}

    def _method_seeds(self, method: str) -> list[int]:
        return self.suite.random_seeds if method == "slotrag-random" else [self.suite.seed]

    def run(
        self,
        stage_name: str,
        *,
        datasets: list[str] | None = None,
        methods: list[str] | None = None,
    ) -> dict[str, int]:
        stage = self.suite.stage(stage_name)
        selected_datasets = datasets or self.suite.datasets
        selected_methods = methods or stage.methods
        unknown_datasets = sorted(set(selected_datasets) - set(self.suite.datasets))
        unknown_methods = sorted(set(selected_methods) - set(stage.methods))
        if unknown_datasets:
            raise ValueError(f"datasets are not configured for this suite: {', '.join(unknown_datasets)}")
        if unknown_methods:
            raise ValueError(f"methods are not configured for stage {stage_name}: {', '.join(unknown_methods)}")
        counts = {"completed": 0, "skipped": 0, "retried": 0, "failed": 0, "empty": 0, "unsupported": 0}
        self._write_manifest(stage_name, selected_datasets, selected_methods)
        for dataset in selected_datasets:
            questions = self._load_or_create_sample(stage_name, dataset)
            for method in selected_methods:
                for seed in self._method_seeds(method):
                    method_label = method if len(self._method_seeds(method)) == 1 else f"{method}@{seed}"
                    for question in questions:
                        item_path = self.output_dir / "items" / stage_name / dataset / method_label / f"{_safe_id(question.id)}.json"
                        attempt_dir = self.output_dir / "attempts" / stage_name / dataset / method_label / _safe_id(question.id)
                        attempt_paths = sorted(attempt_dir.glob("attempt-*.json")) if attempt_dir.exists() else []
                        previous: dict[str, Any] | None = None
                        if item_path.exists():
                            try:
                                previous = json.loads(item_path.read_text(encoding="utf-8"))
                                previous_status = previous.get("result", {}).get("status")
                            except (OSError, json.JSONDecodeError):
                                previous_status = None
                            if previous is not None and not attempt_paths:
                                legacy = dict(previous)
                                legacy_result = legacy.get("result", {})
                                legacy["schema_version"] = 2
                                legacy["attempt_index"] = 1
                                legacy.setdefault("failure_category", _failure_category(
                                    str(legacy_result.get("status", "failed")),
                                    legacy_result.get("error"),
                                    legacy_result.get("answer"),
                                ))
                                legacy.setdefault("budget", self.suite.budget.model_dump(mode="json"))
                                _atomic_json(attempt_dir / "attempt-0001.json", legacy)
                                attempt_paths = [attempt_dir / "attempt-0001.json"]
                            if previous_status == "ok":
                                counts["skipped"] += 1
                                continue
                            counts["retried"] += 1
                        attempt_indices = [
                            int(path.stem.rsplit("-", 1)[-1])
                            for path in attempt_paths
                            if path.stem.rsplit("-", 1)[-1].isdigit()
                        ]
                        attempt_index = max(attempt_indices, default=0) + 1
                        frozen_plan: SlotPlan | None = None
                        plan_provenance: dict[str, Any] | None = None
                        plan_error: Exception | None = None
                        if stage.frozen_plan_source is not None and METHODS[method].family == "slotrag":
                            try:
                                frozen_plan, plan_provenance = self._load_or_create_frozen_plan(
                                    stage_name,
                                    dataset,
                                    question,
                                    stage.frozen_plan_source,
                                )
                            except FrozenPlanPreparationError as exc:
                                plan_error = exc
                                plan_provenance = exc.provenance
                            except Exception as exc:
                                plan_error = exc
                        index_provider_before = self._provider_snapshot()
                        index_cache_before = self.embedding_cache.snapshot()
                        retriever: HybridRetriever | None = None
                        index_build_ms = 0.0
                        index_bytes = 0
                        index_error: Exception | None = None
                        if plan_error is None and METHODS[method].family != "graphrag":
                            index_started = time.perf_counter()
                            try:
                                retriever = self._retriever(question)
                                retriever.build_index()
                            except Exception as exc:
                                index_error = exc
                            index_build_ms = (time.perf_counter() - index_started) * 1000
                            if retriever is not None:
                                index_bytes = sum(len(passage.text.encode("utf-8")) for passage in retriever.passages)
                                index_bytes += len(retriever.passages) * self.app_config.embedding.dimension * 8
                        index_provider_after = self._provider_snapshot()
                        index_cache_after = self.embedding_cache.snapshot()
                        index_delta = {
                            name: _stats_delta(index_provider_before[name], index_provider_after[name])
                            for name in index_provider_before
                        }
                        index_cache_delta = (
                            index_cache_after[0] - index_cache_before[0],
                            index_cache_after[1] - index_cache_before[1],
                        )
                        before = index_provider_after
                        cache_before = index_cache_after
                        started = time.perf_counter()
                        rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
                        if plan_error is not None:
                            result = ExecutionResult(
                                status="failed",
                                error=f"{plan_error.__class__.__name__}: {plan_error}",
                            )
                        elif index_error is not None:
                            result = ExecutionResult(status="failed", error=f"{index_error.__class__.__name__}: {index_error}")
                        else:
                            try:
                                with _question_deadline(self.suite.budget.question_timeout_seconds):
                                    result = run_method(
                                        method,
                                        dataset=dataset,
                                        question=question,
                                        retriever=_BudgetedRetriever(retriever, self.suite.budget.max_retrieval_calls) if retriever else None,  # type: ignore[arg-type]
                                        client=_BudgetedAgnes(self.agnes, self.suite.budget.max_llm_calls),
                                        config=self.app_config,
                                        seed=seed,
                                        max_steps=self.suite.budget.max_steps,
                                        max_retrieval_calls=self.suite.budget.max_retrieval_calls,
                                        frozen_plan=frozen_plan,
                                    )
                            except BenchmarkBudgetExceeded as exc:
                                result = ExecutionResult(status="budget_exceeded", error=str(exc))
                            except Exception as exc:
                                result = ExecutionResult(status="failed", error=f"{exc.__class__.__name__}: {exc}")
                        wall_ms = (time.perf_counter() - started) * 1000
                        rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
                        result, provider_delta = self._instrument(
                            result,
                            before,
                            cache_before,
                            wall_ms,
                            max(rss_after - rss_before, 0.0),
                            index_build_ms,
                            index_bytes,
                            index_delta,
                            index_cache_delta,
                        )
                        result = result.model_copy(update={"metrics": result.metrics.model_copy(update={
                            "llm_budget_utilization": result.metrics.llm_calls / self.suite.budget.max_llm_calls,
                            "retrieval_budget_utilization": result.metrics.retrieval_calls / self.suite.budget.max_retrieval_calls,
                            "step_budget_utilization": result.metrics.steps_executed / self.suite.budget.max_steps,
                        })})
                        if result.metrics.llm_calls > self.suite.budget.max_llm_calls or result.metrics.retrieval_calls > self.suite.budget.max_retrieval_calls or wall_ms / 1000 > self.suite.budget.question_timeout_seconds:
                            result = result.model_copy(update={"status": "budget_exceeded", "error": result.error or "benchmark budget exceeded"})
                        record = {
                            "schema_version": 15,
                            "stage": stage_name,
                            "dataset": dataset,
                            "method": method,
                            "method_label": method_label,
                            "seed": seed,
                            "question_id": question.id,
                            "stratum": question.metadata.get("stratum"),
                            "attempt_index": attempt_index,
                            "recorded_at": datetime.now(timezone.utc).isoformat(),
                            "budget": self.suite.budget.model_dump(mode="json"),
                            "answers": question.answers,
                            "result": result.model_dump(mode="json"),
                            "scores": score_record(dataset, question, result),
                            "provider_delta": provider_delta,
                            "index_provider_delta": index_delta,
                            "plan_provenance": plan_provenance,
                            "failure_category": _failure_category(result.status, result.error, result.answer),
                        }
                        _atomic_json(attempt_dir / f"attempt-{attempt_index:04d}.json", record)
                        _atomic_json(item_path, record)
                        counts["completed"] += 1
                        if result.status in {"failed", "budget_exceeded"}:
                            counts["failed"] += 1
                        elif result.status == "empty":
                            counts["empty"] += 1
                        elif result.status == "unsupported_operation":
                            counts["unsupported"] += 1
        self.embedding_cache.flush()
        _atomic_json(self.output_dir / "progress.json", {"stage": stage_name, **counts})
        return counts

    def _write_manifest(self, stage_name: str, datasets: list[str], methods: list[str]) -> None:
        manifest_path = self.output_dir / "manifest.json"
        request = {"stage": stage_name, "datasets": datasets, "methods": methods}
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            stages = manifest.setdefault("stages_requested", [])
            requests = manifest.setdefault("run_requests", [])
            if stage_name not in stages:
                stages.append(stage_name)
            if request not in requests:
                requests.append(request)
            _atomic_json(manifest_path, manifest)
            return
        root = Path.cwd()
        audit_path = self.output_dir / "dataset-audit.json"
        audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else None
        manifest = {
            "material_passport": {
                "origin_skill": "academic-research-suite/experiment-agent",
                "origin_mode": "run",
                "verification_status": "UNVERIFIED",
                "version_label": "slotrag_benchmark_v1",
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
            "initial_stage": stage_name,
            "stages_requested": [stage_name],
            "run_requests": [request],
            "code_revision": _git_revision(root),
            "code_dirty": _git_dirty(root),
            "source_fingerprint_sha256": _source_fingerprint(root),
            "baseline_revisions": {
                "PlanRAG": _git_revision(root / "baseline" / "PlanRAG"),
                "ircot": _git_revision(root / "baseline" / "ircot"),
                "graph_rag": _git_revision(root / "baseline" / "graph_rag"),
            },
            "suite": self.suite.model_dump(mode="json"),
            "provider_config": self.app_config.public_dict(),
            "dataset_audit": audit,
            "dataset_audit_sha256": hashlib.sha256(audit_path.read_bytes()).hexdigest() if audit_path.exists() else None,
            "environment": {
                "python": os.sys.version,
                "python_executable": os.sys.executable,
                "platform": os.uname().sysname + " " + os.uname().release,
                "cpu_count": os.cpu_count(),
                "memory_bytes": os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"),
                "gpus": _gpu_inventory(),
                "packages": _package_versions(),
            },
        }
        _atomic_json(manifest_path, manifest)
