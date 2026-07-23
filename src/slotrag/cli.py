from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from .config import AppConfig
from .baseline import run_whole_question_baseline
from .benchmarking.config import BenchmarkSuite
from .benchmarking.baselines import audit_baselines
from .benchmarking.datasets import audit_suite
from .benchmarking.record_audit import audit_run_records
from .benchmarking.publication_gate import audit_publication_readiness
from .benchmarking.runner import BenchmarkRunner
from .benchmarking.statistics import summarize_run
from .data import chunk_passages, fetch_dataset, load_questions, normalize_jsonl
from .doctor import check_services
from .evaluation import result_row, summarize, write_csv, write_jsonl
from .generation import generate_answer
from .manifest import build_manifest
from .planner import AdaptiveExecutor, SlotCompiler, SlotMaterializer
from .providers import provider_clients
from .retrieval import EmbeddingCache, HybridRetriever

app = typer.Typer(help="SlotRAG research prototype")
data_app = typer.Typer(help="Dataset operations")
benchmark_app = typer.Typer(help="Reproducible multi-dataset benchmark operations")
app.add_typer(data_app, name="data")
app.add_typer(benchmark_app, name="benchmark")


def load_config(config: Path) -> AppConfig:
    return AppConfig.from_yaml(config)


@app.command()
def doctor(config: Path = typer.Option(Path("configs/default.yaml"), exists=True, readable=True), network: bool = typer.Option(True, "--network/--no-network")) -> None:
    """Check configuration and, optionally, all three configured services."""
    cfg = load_config(config)
    typer.echo(json.dumps(cfg.public_dict(), ensure_ascii=False, indent=2))
    if not network:
        typer.echo("configuration: OK")
        return
    statuses = check_services(cfg)
    failed = False
    for status in statuses:
        typer.echo(f"{status.name}: {'OK' if status.ok else 'FAIL'} ({status.message})")
        failed = failed or not status.ok
    if failed:
        raise typer.Exit(code=1)


@data_app.command("fetch")
def data_fetch(
    url: str = typer.Option(..., help="Public dataset URL"),
    output: Path = typer.Option(..., help="Destination file"),
    sha256: str = typer.Option("", help="Optional expected SHA-256"),
) -> None:
    """Download a public dataset file with an optional checksum."""
    path = fetch_dataset(url, output, sha256)
    typer.echo(f"downloaded: {path}")


@data_app.command("normalize")
def data_normalize(source: Path = typer.Argument(..., exists=True, readable=True), output: Path = typer.Option(Path("data/processed/questions.jsonl"))) -> None:
    """Normalize JSON/JSONL records into the SlotRAG question schema."""
    path = normalize_jsonl(load_questions(source), output)
    typer.echo(f"normalized: {path}")


def load_benchmark_suite(path: Path) -> BenchmarkSuite:
    return BenchmarkSuite.from_yaml(path)


@benchmark_app.command("audit")
def benchmark_audit(
    suite: Path = typer.Option(Path("configs/experiments/pilot.yaml"), exists=True, readable=True),
    output: Optional[Path] = typer.Option(None, help="Optional JSON report path"),
) -> None:
    """Validate all configured public dataset splits and report checksums."""
    cfg = load_benchmark_suite(suite)
    report = audit_suite(cfg.benchmark_root, cfg.datasets)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    typer.echo(payload)


@benchmark_app.command("baseline-audit")
def benchmark_baseline_audit(
    suite: Path = typer.Option(Path("configs/experiments/pilot.yaml"), exists=True, readable=True),
    output: Optional[Path] = typer.Option(None, help="Optional JSON report path"),
) -> None:
    """Audit baseline provenance, entrypoints, and dataset comparability."""
    cfg = load_benchmark_suite(suite)
    report = audit_baselines(Path.cwd(), cfg.datasets)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    typer.echo(payload)


@benchmark_app.command("records-audit")
def benchmark_records_audit(
    stage: str = typer.Argument(...),
    output_dir: Path = typer.Option(Path("runs/pilot-v1"), exists=True, file_okay=False),
    require_trace: bool = typer.Option(False, "--require-trace/--allow-missing-trace"),
    output: Optional[Path] = typer.Option(None, help="Optional JSON report path"),
) -> None:
    """Check immutable final, attempt, trace, and manifest completeness."""
    report = audit_run_records(output_dir, stage, require_trace=require_trace)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    typer.echo(payload)


@benchmark_app.command("gate")
def benchmark_gate(
    stage: str = typer.Argument(...),
    output_dir: Path = typer.Option(Path("runs/pilot-v1"), exists=True, file_okay=False),
    require_trace: bool = typer.Option(True, "--require-trace/--allow-missing-trace"),
    allow_diagnostic_adapters: bool = typer.Option(False, "--allow-diagnostic-adapters"),
    allow_adapted_protocol: bool = typer.Option(False, "--allow-adapted-protocol"),
    output: Optional[Path] = typer.Option(None, help="Optional JSON report path"),
) -> None:
    """Gate a run before statistics or publication claims."""
    report = audit_publication_readiness(
        output_dir,
        stage,
        require_trace=require_trace,
        allow_diagnostic_adapters=allow_diagnostic_adapters,
        allow_adapted_protocol=allow_adapted_protocol,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    typer.echo(payload)
    if not report["analysis_ready"]:
        raise typer.Exit(code=2)
    if not report["publication_ready"] and not allow_diagnostic_adapters:
        raise typer.Exit(code=3)


@benchmark_app.command("prepare")
def benchmark_prepare(
    stage: str = typer.Argument(...),
    suite: Path = typer.Option(Path("configs/experiments/pilot.yaml"), exists=True, readable=True),
    config: Path = typer.Option(Path("configs/default.yaml"), exists=True, readable=True),
    output_dir: Path = typer.Option(Path("runs/pilot-v1")),
) -> None:
    """Create and persist the deterministic stratified sample for one stage."""
    runner = BenchmarkRunner(load_benchmark_suite(suite), load_config(config), output_dir)
    typer.echo(json.dumps(runner.prepare(stage), ensure_ascii=False, indent=2))


@benchmark_app.command("run")
def benchmark_run(
    stage: str = typer.Argument(...),
    suite: Path = typer.Option(Path("configs/experiments/pilot.yaml"), exists=True, readable=True),
    config: Path = typer.Option(Path("configs/default.yaml"), exists=True, readable=True),
    output_dir: Path = typer.Option(Path("runs/pilot-v1")),
    dataset: Optional[list[str]] = typer.Option(None, "--dataset", help="Repeat to run a configured dataset subset"),
    method: Optional[list[str]] = typer.Option(None, "--method", help="Repeat to run a configured method subset"),
) -> None:
    """Run or resume one benchmark stage with atomic per-question results."""
    runner = BenchmarkRunner(load_benchmark_suite(suite), load_config(config), output_dir)
    typer.echo(json.dumps(runner.run(stage, datasets=dataset, methods=method), ensure_ascii=False, indent=2))


@benchmark_app.command("summarize")
def benchmark_summarize(
    stage: str = typer.Argument(...),
    output_dir: Path = typer.Option(Path("runs/pilot-v1"), exists=True, file_okay=False),
) -> None:
    """Aggregate metrics and paired bootstrap comparisons for one stage."""
    report = summarize_run(output_dir, stage)
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


@benchmark_app.command("inspect-plan")
def benchmark_inspect_plan(
    dataset: str = typer.Argument(...),
    stage: str = typer.Option("preflight"),
    suite: Path = typer.Option(Path("configs/experiments/pilot.yaml"), exists=True, readable=True),
    config: Path = typer.Option(Path("configs/default.yaml"), exists=True, readable=True),
    output_dir: Path = typer.Option(Path("runs/plan-inspection")),
) -> None:
    """Compile one persisted stage sample without retrieval or materialization."""
    runner = BenchmarkRunner(load_benchmark_suite(suite), load_config(config), output_dir)
    if dataset not in runner.suite.datasets:
        raise typer.BadParameter(f"dataset is not configured: {dataset}")
    question = runner.sample(stage, dataset)[0]
    plan, metrics = SlotCompiler(runner.agnes).compile(question.question)
    typer.echo(json.dumps({
        "dataset": dataset,
        "question_id": question.id,
        "question": question.question,
        "plan": plan.model_dump(mode="json"),
        "compiler_metrics": metrics.model_dump(mode="json"),
    }, ensure_ascii=False, indent=2))


@app.command()
def run(
    dataset: Path = typer.Option(..., exists=True, readable=True),
    config: Path = typer.Option(Path("configs/default.yaml"), exists=True, readable=True),
    output_dir: Path = typer.Option(Path("runs/latest")),
    strategy: str = typer.Option("adaptive", help="adaptive, question, fixed, random, or oracle"),
    mode: str = typer.Option("slotrag", help="slotrag or baseline"),
    limit: Optional[int] = typer.Option(None, min=1),
) -> None:
    """Run SlotRAG over normalized question records."""
    if strategy not in {"adaptive", "question", "fixed", "random", "oracle"}:
        raise typer.BadParameter("strategy must be adaptive, question, fixed, random, or oracle")
    if mode not in {"slotrag", "baseline"}:
        raise typer.BadParameter("mode must be slotrag or baseline")
    cfg = load_config(config)
    questions = load_questions(dataset)[:limit]
    agnes, embedding, reranker = provider_clients(cfg)
    rows: list[dict[str, object]] = []
    for question in questions:
        try:
            passages = chunk_passages(question.passages, chunk_tokens=cfg.retrieval.chunk_tokens, overlap=cfg.retrieval.chunk_overlap)
            retriever = HybridRetriever(
                passages,
                embedding,
                reranker,
                bm25_k=cfg.retrieval.bm25_k,
                dense_k=cfg.retrieval.dense_k,
                final_k=cfg.retrieval.final_k,
                rrf_k=cfg.retrieval.rrf_k,
                bm25_weight=cfg.retrieval.bm25_weight,
                dense_weight=cfg.retrieval.dense_weight,
                rerank_enabled=cfg.reranker.enabled,
                cache=EmbeddingCache(output_dir / "embedding_cache.json"),
            )
            if mode == "baseline":
                result = run_whole_question_baseline(question, retriever, agnes)
                rows.append(result_row(question, result))
                continue
            plan, compiler_metrics = SlotCompiler(agnes).compile(question.question)
            materializer = SlotMaterializer(agnes, retriever, max_passages=cfg.execution.materialization_top_k)
            result = AdaptiveExecutor(
                materializer,
                default_slot_cost=cfg.execution.default_slot_cost,
                unbound_argument_cost=cfg.execution.unbound_argument_cost,
                max_replans=cfg.execution.max_replans,
                max_retrieval_calls=cfg.execution.max_retrieval_calls,
                max_binding_contexts=cfg.execution.max_binding_contexts,
                random_seed=cfg.execution.random_seed,
            ).execute(plan, strategy=strategy)
            result = result.model_copy(update={"plan": plan, "metrics": result.metrics.model_copy(update={
                "llm_calls": result.metrics.llm_calls + compiler_metrics.llm_calls,
                "prompt_tokens": result.metrics.prompt_tokens + compiler_metrics.prompt_tokens,
                "completion_tokens": result.metrics.completion_tokens + compiler_metrics.completion_tokens,
                "latency_ms": result.metrics.latency_ms + compiler_metrics.latency_ms,
                "structured_output_failures": result.metrics.structured_output_failures + compiler_metrics.structured_output_failures,
                "structured_output_repairs": result.metrics.structured_output_repairs + compiler_metrics.structured_output_repairs,
                "plan_fallbacks": result.metrics.plan_fallbacks + compiler_metrics.plan_fallbacks,
                "heuristic_plans": result.metrics.heuristic_plans + compiler_metrics.heuristic_plans,
                "plan_validation_errors": result.metrics.plan_validation_errors + compiler_metrics.plan_validation_errors,
                "provider_request_ids": result.metrics.provider_request_ids + compiler_metrics.provider_request_ids,
            })})
            if result.rows:
                answer, prompt, completion, latency = generate_answer(agnes, question.question, result)
                result = result.model_copy(update={"answer": answer, "metrics": result.metrics.model_copy(update={"llm_calls": result.metrics.llm_calls + 1, "prompt_tokens": result.metrics.prompt_tokens + prompt, "completion_tokens": result.metrics.completion_tokens + completion, "latency_ms": result.metrics.latency_ms + latency})})
            rows.append(result_row(question, result))
        except Exception as exc:
            from .models import ExecutionResult
            rows.append(result_row(question, ExecutionResult(status="failed", error=f"{exc.__class__.__name__}: {exc}")))
    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(rows, output_dir / "results.jsonl")
    write_csv(rows, output_dir / "results.csv")
    (output_dir / "summary.json").write_text(json.dumps(summarize(rows), indent=2), encoding="utf-8")
    (output_dir / "config.json").write_text(json.dumps(cfg.public_dict(), indent=2), encoding="utf-8")
    (output_dir / "manifest.json").write_text(json.dumps(build_manifest(cfg, dataset=dataset, strategy=strategy, mode=mode, question_count=len(questions)), indent=2), encoding="utf-8")
    typer.echo(json.dumps(summarize(rows), indent=2))


@app.command()
def evaluate(results: Path = typer.Option(..., exists=True, readable=True)) -> None:
    """Summarize a SlotRAG JSONL result file."""
    if results.suffix.lower() == ".csv":
        import csv
        with results.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    else:
        rows = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines() if line.strip()]
    typer.echo(json.dumps(summarize(rows), indent=2))


if __name__ == "__main__":
    app()
