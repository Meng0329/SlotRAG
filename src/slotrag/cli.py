from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from .config import AppConfig
from .baseline import run_whole_question_baseline
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
app.add_typer(data_app, name="data")


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
def data_fetch(config: Path = typer.Option(Path("configs/default.yaml"), exists=True, readable=True), output: Optional[Path] = typer.Option(None), url: Optional[str] = typer.Option(None), sha256: Optional[str] = typer.Option(None)) -> None:
    """Download and checksum the configured QO-Bench archive/file."""
    cfg = load_config(config)
    destination = output or cfg.data.cache_dir / "qobench.download"
    path = fetch_dataset(url or cfg.data.qobench_url, destination, sha256 or cfg.data.qobench_sha256)
    typer.echo(f"downloaded: {path}")


@data_app.command("normalize")
def data_normalize(source: Path = typer.Argument(..., exists=True, readable=True), output: Path = typer.Option(Path("data/processed/qobench.jsonl"))) -> None:
    """Normalize JSON/JSONL records into the SlotRAG question schema."""
    path = normalize_jsonl(load_questions(source), output)
    typer.echo(f"normalized: {path}")


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
            if mode != "slotrag":
                raise ValueError("mode must be slotrag or baseline")
            plan, compiler_result = SlotCompiler(agnes).compile(question.question)
            materializer = SlotMaterializer(agnes, retriever)
            result = AdaptiveExecutor(materializer, default_slot_cost=cfg.execution.default_slot_cost, unbound_argument_cost=cfg.execution.unbound_argument_cost, max_replans=cfg.execution.max_replans, random_seed=cfg.execution.random_seed).execute(plan, strategy=strategy)
            result = result.model_copy(update={"metrics": result.metrics.model_copy(update={"llm_calls": result.metrics.llm_calls + 1, "prompt_tokens": result.metrics.prompt_tokens + compiler_result.usage.prompt_tokens, "completion_tokens": result.metrics.completion_tokens + compiler_result.usage.completion_tokens, "latency_ms": result.metrics.latency_ms + compiler_result.latency_ms})})
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
