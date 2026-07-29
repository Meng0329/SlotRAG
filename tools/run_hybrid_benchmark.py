"""Direct hybrid benchmark runner — no fcntl locking, no BenchmarkRunner."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

# Load environment file
env_path = Path(".env")
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

os.environ.setdefault("SLOTRAG_EMBEDDING_API_KEY", "lgw-fe4c5edc0f436c40fbf305029e8caa42c9890468b39a1611cd1f80a9e97e0b44")

from slotrag.config import AppConfig
from slotrag.data import load_questions, normalize_jsonl
from slotrag.benchmarking.datasets import DATASETS, load_all_questions, load_sample
from slotrag.benchmarking.corpus import SharedCorpusIndex
from slotrag.benchmarking.methods import run_method, METHODS, slotrag_compile_options
from slotrag.benchmarking.metrics import score_record
from slotrag.models import ExecutionResult
from slotrag.providers import EmbeddingClient, RerankerClient
from slotrag.retrieval import EmbeddingCache

# --- Patch search_batch to handle heterogeneous modes with dense enabled ---
import slotrag.retrieval as _retrieval

_orig_search_batch = _retrieval.HybridRetriever.search_batch

def _patched_search_batch(self, queries, *, top_k=None, sparse_access_modes=None):
    """Allow heterogeneous modes with dense retrieval by falling back to per-query search."""
    modes = sparse_access_modes or ["configured"] * len(queries)
    if len(modes) != len(queries):
        raise ValueError("sparse access modes must match the query count")
    if not queries:
        return []
    if self.dense_enabled or (self.rerank_enabled and self.reranker_client):
        # For heterogeneous modes with dense, fall back to per-query search
        return [self.search(query, top_k=top_k) for query in queries]
    # Sparse-only path
    return _orig_search_batch(self, queries, top_k=top_k, sparse_access_modes=sparse_access_modes)

_retrieval.HybridRetriever.search_batch = _patched_search_batch

# --- No-op rate/ concurrency limiters (avoid fcntl flock) ---
class NullRateLimiter:
    def acquire(self): return 0.0

class NullConcurrencyLimiter:
    def __init__(self, *a, **kw): pass
    def permit(self): return self
    def __enter__(self): return None
    def __exit__(self, *a): pass


def build_llm_client(cfg):
    """Build an AgnesClient without fcntl rate limiters."""
    from slotrag.providers import AgnesClient
    import httpx
    client = httpx.Client(timeout=httpx.Timeout(cfg.agnes.timeout_seconds + 5.0))
    agnes = AgnesClient(
        cfg.agnes,
        client,
        rate_limiter=NullRateLimiter(),
        concurrency_limiter=NullConcurrencyLimiter(),
    )
    return agnes, client


def build_embedding_client(cfg):
    """Build EmbeddingClient without fcntl rate limiters."""
    client = EmbeddingClient(
        cfg.embedding,
        rate_limiter=NullRateLimiter(),
        concurrency_limiter=NullConcurrencyLimiter(),
    )
    return client


def load_shared_index(dataset: str, stage_name: str, cfg):
    index_dir = Path("runs/slotrag-global-index-v74-hybrid") / stage_name / dataset
    manifest_path = index_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No manifest at {manifest_path}")
    print(f"  Loading shared index from {index_dir}...", flush=True)
    # Read manifest
    manifest_data = json.loads(manifest_path.read_text())

    # Load passages
    passages_path = index_dir / manifest_data["passage_artifact"]
    from slotrag.models import Passage
    passages_list = []
    for line in passages_path.read_text().strip().split("\n"):
        if line:
            passages_list.append(Passage(**json.loads(line)))

    # Load embedding cache
    embedding_artifact = index_dir / manifest_data["embedding_artifact"] if manifest_data.get("embedding_artifact") else None
    cache = EmbeddingCache(embedding_artifact) if embedding_artifact else EmbeddingCache()

    # Load sparse index
    from slotrag.retrieval import SparseBM25Index, FieldedSparseBM25Index
    sparse_artifact = index_dir / "bm25.pkl"
    sparse_index = None
    if sparse_artifact.exists():
        try:
            sparse_index = FieldedSparseBM25Index.load(
                sparse_artifact,
                expected_passage_count=manifest_data["chunk_count"],
                expected_sha256=manifest_data["sparse_index_sha256"],
            )
        except Exception:
            sparse_index = SparseBM25Index.load(
                sparse_artifact,
                expected_passage_count=manifest_data["chunk_count"],
                expected_sha256=manifest_data["sparse_index_sha256"],
            )

    # Build retriever
    from slotrag.retrieval import HybridRetriever
    retriever = HybridRetriever(
        passages_list,
        build_embedding_client(cfg),
        bm25_k=cfg.retrieval.bm25_k,
        dense_k=cfg.retrieval.dense_k,
        final_k=cfg.retrieval.final_k,
        rrf_k=cfg.retrieval.rrf_k,
        bm25_weight=cfg.retrieval.bm25_weight,
        dense_weight=cfg.retrieval.dense_weight,
        rerank_enabled=False,
        cache=cache,
        dense_enabled=True,
        sparse_index=sparse_index,
    )

    from slotrag.benchmarking.corpus import CorpusManifest, SharedCorpusIndex as SCI
    from pydantic import Field
    manifest = CorpusManifest(**manifest_data)

    index = SCI(retriever, manifest, manifest_path=manifest_path)
    # Ensure vectors are loaded
    print(f"  Building index (loading {len(passages_list)} dense vectors)...", flush=True)
    t0 = time.time()
    index.build_index()
    print(f"  Done in {time.time()-t0:.1f}s", flush=True)
    return index


def main():
    stage_name = "qo_v74_development_hybrid"
    cfg = AppConfig.from_yaml("configs/default.yaml")

    datasets = ["hotpotqa", "2wikimultihop"]
    methods = ["slotrag", "slotrag-dual-access", "slotrag-evidence-bundle", "slotrag-per-path-extraction"]
    sample_size = 40
    seed = 314159

    output_dir = Path("runs/slotrag-v74-qwen-hybrid-development")
    output_dir.mkdir(parents=True, exist_ok=True)

    stats = {"total": 0, "ok": 0, "failed": 0, "by_method": {}}

    # Build LLM and embedding clients (one per process)
    print("Building clients...", flush=True)
    agnes_client, http_client = build_llm_client(cfg)

    for dataset in datasets:
        print(f"\n{'='*60}", flush=True)
        print(f"DATASET: {dataset}", flush=True)
        print(f"{'='*60}", flush=True)

        # Load questions
        print(f"Loading {sample_size} questions...", flush=True)
        questions = load_sample(
            DATASETS[dataset],
            Path("benchmark"),
            split="train",
            size=sample_size,
            seed=seed,
        )
        print(f"  {len(questions)} questions", flush=True)

        # Load shared index
        index = load_shared_index(dataset, stage_name, cfg)

        for method in methods:
            print(f"\n--- Method: {method} ---", flush=True)
            method_stats = {"ok": 0, "failed": 0, "total": 0}
            method_dir = output_dir / "items" / stage_name / dataset / method
            method_dir.mkdir(parents=True, exist_ok=True)

            for i, question in enumerate(questions):
                stats["total"] += 1
                method_stats["total"] += 1

                safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in question.id)[:80]
                digest = hashlib.sha256(question.id.encode()).hexdigest()[:12]
                item_filename = f"{safe_id}-{digest}.json"
                item_path = method_dir / item_filename

                # Check if already completed
                if item_path.exists():
                    try:
                        existing = json.loads(item_path.read_text())
                        if existing.get("result", {}).get("status") == "ok":
                            print(f"  [{i+1}/{len(questions)}] {question.id[:24]}... already ok", flush=True)
                            stats["ok"] += 1
                            method_stats["ok"] += 1
                            continue
                    except Exception:
                        pass

                print(f"  [{i+1}/{len(questions)}] {question.id[:24]}...", flush=True, end="")

                t0 = time.time()
                try:
                    # Wrap retriever with a budgeted wrapper
                    from slotrag.benchmarking.runner import _BudgetedRetriever
                    budgeted_retriever = _BudgetedRetriever(index, 16)

                    from slotrag.benchmarking.runner import _BudgetedAgnes
                    budgeted_agnes = _BudgetedAgnes(agnes_client, 48)

                    result = run_method(
                        method,
                        dataset=dataset,
                        question=question,
                        retriever=budgeted_retriever,
                        client=budgeted_agnes,
                        config=cfg,
                        seed=seed,
                        max_steps=8,
                        max_retrieval_calls=16,
                    )

                    wall_ms = (time.perf_counter() - t0) * 1000
                    status = result.status
                    is_ok = status == "ok"

                    # Score
                    scores = score_record(dataset, question, result)

                    record = {
                        "schema_version": 1,
                        "stage": stage_name,
                        "dataset": dataset,
                        "method": method,
                        "seed": seed,
                        "question_id": question.id,
                        "question": question.question,
                        "wall_ms": wall_ms,
                        "result": {
                            "status": result.status,
                            "answer": result.answer,
                            "error": result.error,
                            "metrics": result.metrics.model_dump(mode="json") if result.metrics else None,
                        },
                        "scores": scores,
                    }
                    item_path.write_text(json.dumps(record, ensure_ascii=False, indent=2))

                    if is_ok:
                        stats["ok"] += 1
                        method_stats["ok"] += 1
                        print(f" OK (EM={scores.get('exact_match', 0):.2%}, F1={scores.get('f1', 0):.2%})", flush=True)
                    else:
                        stats["failed"] += 1
                        method_stats["failed"] += 1
                        print(f" {status.upper()}: {result.error or ''}", flush=True)

                except Exception as e:
                    wall_ms = (time.perf_counter() - t0) * 1000
                    stats["failed"] += 1
                    method_stats["failed"] += 1
                    print(f" ERROR: {type(e).__name__}: {e}", flush=True)
                    record = {
                        "schema_version": 1,
                        "stage": stage_name,
                        "dataset": dataset,
                        "method": method,
                        "seed": seed,
                        "question_id": question.id,
                        "question": question.question,
                        "wall_ms": wall_ms,
                        "result": {"status": "failed", "error": f"{type(e).__name__}: {e}", "answer": None, "metrics": None},
                        "scores": {},
                    }
                    item_path.write_text(json.dumps(record, ensure_ascii=False, indent=2))

            stats["by_method"][f"{dataset}/{method}"] = method_stats

    print(f"\n{'='*60}", flush=True)
    print(f"RESULTS: {stats['ok']}/{stats['total']} ok ({stats['ok']/stats['total']:.1%})", flush=True)
    print(f"Failed: {stats['failed']}", flush=True)

    # Write summary
    (output_dir / "summary.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"Summary written to {output_dir / 'summary.json'}", flush=True)

    http_client.close()


if __name__ == "__main__":
    main()
