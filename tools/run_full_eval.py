#!/usr/bin/env python3
"""Full-scale evaluation of question_grounded slotrag on complete eval splits.

hotpotqa: 7405 questions, 2wikimultihop: 12576 questions
~14h at 8 workers, includes checkpoint/resume support.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

env_path = Path(".env")
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
os.environ.setdefault("SLOTRAG_EMBEDDING_API_KEY", "lgw-fe4c5edc0f436c40fbf305029e8caa42c9890468b39a1611cd1f80a9e97e0b44")

from slotrag.config import AppConfig
from slotrag.benchmarking.datasets import DATASETS, load_all_questions, load_sample
from slotrag.benchmarking.metrics import score_record
from slotrag.providers import EmbeddingClient, RerankerClient

import slotrag.retrieval as _retrieval
_orig_search_batch = _retrieval.HybridRetriever.search_batch

def _patched_search_batch(self, queries, *, top_k=None, sparse_access_modes=None):
    modes = sparse_access_modes or ["configured"] * len(queries)
    if len(modes) != len(queries):
        raise ValueError("sparse access modes must match the query count")
    if not queries:
        return []
    if self.dense_enabled or (self.rerank_enabled and self.reranker_client):
        return [self.search(query, top_k=top_k) for query in queries]
    return _orig_search_batch(self, queries, top_k=top_k, sparse_access_modes=sparse_access_modes)

_retrieval.HybridRetriever.search_batch = _patched_search_batch


class NullRateLimiter:
    def acquire(self):
        return 0.0

class NullConcurrencyLimiter:
    def __init__(self, *a, **kw):
        pass
    def permit(self):
        return self
    def __enter__(self):
        return None
    def __exit__(self, *a):
        pass


_reranker_lock = threading.Lock()
_orig_rerank = RerankerClient.rerank
def _safe_rerank(self, query, documents, top_n=None):
    with _reranker_lock:
        return _orig_rerank(self, query, documents, top_n=top_n)
RerankerClient.rerank = _safe_rerank

_embed_lock = threading.Lock()
_orig_embed = EmbeddingClient.embed
def _safe_embed(self, inputs, **kwargs):
    with _embed_lock:
        return _orig_embed(self, inputs, **kwargs)
EmbeddingClient.embed = _safe_embed


CHECKPOINT_FILE = "runs/slotrag-v74-qwen-hybrid-reranker-v6/full_eval_checkpoint.json"
PROGRESS_FILE = "runs/slotrag-v74-qwen-hybrid-reranker-v6/full_eval_progress.jsonl"

# Global flag for graceful shutdown
_shutdown_requested = False

def signal_handler(signum, frame):
    global _shutdown_requested
    print(f"\n[FULL_EVAL] Signal {signum} received, finishing current items...", flush=True)
    _shutdown_requested = True

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


def build_llm_client(cfg):
    from slotrag.providers import AgnesClient
    import httpx
    client = httpx.Client(timeout=httpx.Timeout(cfg.agnes.timeout_seconds + 5.0))
    agnes = AgnesClient(cfg.agnes, client, rate_limiter=NullRateLimiter(), concurrency_limiter=NullConcurrencyLimiter())
    return agnes, client


def build_embedding_client(cfg):
    return EmbeddingClient(cfg.embedding, rate_limiter=NullRateLimiter(), concurrency_limiter=NullConcurrencyLimiter())


def build_reranker_client(cfg):
    import httpx
    client = httpx.Client(timeout=httpx.Timeout(cfg.reranker.timeout_seconds + 5.0))
    reranker = RerankerClient(cfg.reranker, client, rate_limiter=NullRateLimiter(), concurrency_limiter=NullConcurrencyLimiter())
    return reranker, client


def load_shared_index(dataset, index_stage, cfg, *, reranker_client=None, rerank_enabled=False):
    import numpy as np
    index_dir = Path("runs/slotrag-global-index-v74-hybrid") / index_stage / dataset
    manifest_path = index_dir / "manifest.json"
    print(f"  Loading shared index from {index_dir}...", flush=True)
    manifest_data = json.loads(manifest_path.read_text())

    passages_path = index_dir / manifest_data["passage_artifact"]
    from slotrag.models import Passage
    passages_list = []
    for line in passages_path.read_text().strip().split("\n"):
        if line:
            passages_list.append(Passage(**json.loads(line)))
    print(f"  {len(passages_list)} passages", flush=True)

    from slotrag.retrieval import SparseBM25Index, FieldedSparseBM25Index
    sparse_artifact = index_dir / "bm25.pkl"
    sparse_index = None
    if sparse_artifact.exists():
        try:
            sparse_index = FieldedSparseBM25Index.load(
                sparse_artifact, expected_passage_count=manifest_data["chunk_count"],
                expected_sha256=manifest_data["sparse_index_sha256"])
        except Exception:
            sparse_index = SparseBM25Index.load(
                sparse_artifact, expected_passage_count=manifest_data["chunk_count"],
                expected_sha256=manifest_data["sparse_index_sha256"])

    npy_path = index_dir / "embeddings.npy"
    idx_path = index_dir / "embeddings_index.json"
    print(f"  Loading dense vectors from {npy_path}...", flush=True)
    t0 = time.time()
    vectors_2d = np.load(npy_path, mmap_mode="r")
    print(f"  Loaded {vectors_2d.shape} in {time.time() - t0:.1f}s", flush=True)
    hash_keys: list[str] = json.loads(idx_path.read_bytes())
    hash_to_row: dict[str, int] = {k: i for i, k in enumerate(hash_keys)}
    print(f"  Hash index loaded ({len(hash_keys)} keys)", flush=True)

    from slotrag.retrieval import HybridRetriever
    dummy_client = EmbeddingClient(cfg.embedding, rate_limiter=NullRateLimiter(), concurrency_limiter=NullConcurrencyLimiter())
    print(f"  Building retriever: dense_k={cfg.retrieval.dense_k}, bm25_k={cfg.retrieval.bm25_k}, "
          f"rerank_enabled={rerank_enabled}, reranker.top_n={cfg.reranker.top_n}", flush=True)
    retriever = HybridRetriever(
        passages_list, dummy_client,
        bm25_k=cfg.retrieval.bm25_k, dense_k=cfg.retrieval.dense_k, final_k=cfg.retrieval.final_k,
        rrf_k=cfg.retrieval.rrf_k, bm25_weight=cfg.retrieval.bm25_weight, dense_weight=cfg.retrieval.dense_weight,
        rerank_enabled=rerank_enabled, reranker_client=reranker_client,
        cache=None, dense_enabled=True, sparse_index=sparse_index,
    )

    print(f"  Setting passage vectors via hash lookup...", flush=True)
    t0 = time.time()
    vectors = []
    missing = 0
    for p in passages_list:
        h = hashlib.sha256(p.text.encode("utf-8")).hexdigest()
        row = hash_to_row.get(h)
        if row is not None:
            vectors.append(vectors_2d[row])
        else:
            vectors.append(None)
            missing += 1
    if missing:
        print(f"  WARNING: {missing}/{len(passages_list)} passages have no embedding", flush=True)
    retriever._passage_vectors = [v for v in vectors if v is not None]
    print(f"  Done in {time.time() - t0:.1f}s: {len(retriever._passage_vectors)} vectors", flush=True)

    from slotrag.benchmarking.corpus import CorpusManifest, SharedCorpusIndex as SCI
    manifest = CorpusManifest(**manifest_data)
    index = SCI(retriever, manifest, manifest_path=manifest_path)
    index.build_index()
    print(f"  Shared index ready in {time.time() - t0:.1f}s", flush=True)
    return index


def process_question(method, dataset, question, cfg, index, output_dir, stage_name, seed):
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in question.id)[:80]
    digest = hashlib.sha256(question.id.encode()).hexdigest()[:12]
    item_filename = f"{safe_id}-{digest}.json"
    method_dir = output_dir / "items" / stage_name / dataset / method
    method_dir.mkdir(parents=True, exist_ok=True)
    item_path = method_dir / item_filename

    if item_path.exists():
        try:
            existing = json.loads(item_path.read_text())
            if existing.get("result", {}).get("status") == "ok":
                return existing
        except Exception:
            pass

    from slotrag.providers import AgnesClient
    import httpx
    hc = httpx.Client(timeout=httpx.Timeout(cfg.agnes.timeout_seconds + 5.0))
    try:
        agnes = AgnesClient(cfg.agnes, hc, rate_limiter=NullRateLimiter(), concurrency_limiter=NullConcurrencyLimiter())
        from slotrag.benchmarking.runner import _BudgetedRetriever, _BudgetedAgnes
        budgeted_retriever = _BudgetedRetriever(index, 16)
        budgeted_agnes = _BudgetedAgnes(agnes, 48)

        t0 = time.perf_counter()
        from slotrag.benchmarking.methods import run_method
        result = run_method(
            method, dataset=dataset, question=question,
            retriever=budgeted_retriever, client=budgeted_agnes, config=cfg,
            seed=seed, max_steps=8, max_retrieval_calls=16,
        )
        wall_ms = (time.perf_counter() - t0) * 1000
        scores = score_record(dataset, question, result)

        record = {
            "schema_version": 1,
            "stage": stage_name, "dataset": dataset, "method": method,
            "seed": seed, "question_id": question.id, "question": question.question,
            "wall_ms": wall_ms,
            "result": {"status": result.status, "answer": result.answer, "error": result.error,
                       "metrics": result.metrics.model_dump(mode="json") if result.metrics else None},
            "scores": scores,
        }
        item_path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
        return record
    finally:
        hc.close()


def append_progress(progress_file: Path, entry: dict):
    with open(progress_file, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_checkpoint(checkpoint_file: Path) -> set[str]:
    """Load completed question IDs from checkpoint."""
    if checkpoint_file.exists():
        try:
            data = json.loads(checkpoint_file.read_text())
            return set(data.get("completed_ids", []))
        except Exception:
            return set()
    return set()


def save_checkpoint(checkpoint_file: Path, completed_ids: set[str], stats: dict):
    checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_file.write_text(json.dumps({
        "completed_ids": sorted(completed_ids),
        "stats": stats,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }, ensure_ascii=False, indent=2))


def main():
    index_stage = "qo_v74_development_hybrid"
    stage_name = "qo_v74_full_eval"
    cfg = AppConfig.from_yaml("configs/default.yaml")

    cfg.retrieval.dense_k = 100
    cfg.retrieval.bm25_k = 100
    cfg.retrieval.bm25_weight = 0.5
    cfg.retrieval.dense_weight = 0.5
    cfg.reranker.top_n = 50

    datasets = ["hotpotqa", "2wikimultihop"]
    methods = ["slotrag"]  # Now with question_grounded_retrieval=True
    seed = 314159

    output_dir = Path("runs/slotrag-v74-qwen-hybrid-reranker-v6")
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_file = output_dir / "full_eval_progress.jsonl"
    checkpoint_file = output_dir / "full_eval_checkpoint.json"

    reranker_client, reranker_http = build_reranker_client(cfg)

    # Build item list
    all_items = []
    total_count = 0

    for dataset in datasets:
        print(f"\n{'=' * 60}", flush=True)
        print(f"DATASET: {dataset} — loading full evaluation split", flush=True)
        print(f"{'=' * 60}", flush=True)

        # Load all questions from the evaluation split (held-out test set)
        # hotpotqa: hotpotqa_validation.jsonl (7405), 2wikimultihop: 2wikimultihop_dev.jsonl (12576)
        questions = load_all_questions(DATASETS[dataset], Path("benchmark"), split="evaluation")
        print(f"  {len(questions)} questions loaded from evaluation split", flush=True)

        # Pre-warm data files
        print(f"  Warming data files...", flush=True)
        for warm_path in [
            f"runs/slotrag-global-index-v74-hybrid/{index_stage}/{dataset}/embeddings.npy",
        ]:
            with open(warm_path, "rb") as f:
                f.read(1024 * 1024)  # Read 1MB to warm page cache
        print(f"  Data files warmed", flush=True)

        index = load_shared_index(dataset, index_stage, cfg, reranker_client=reranker_client, rerank_enabled=True)

        for method in methods:
            for q in questions:
                all_items.append((method, dataset, q, index))

        total_count += len(questions) * len(methods)

    print(f"\nTotal work items: {total_count}", flush=True)

    # Load checkpoint
    completed_ids = load_checkpoint(checkpoint_file)
    pending = [(m, d, q, idx) for m, d, q, idx in all_items if q.id not in completed_ids]
    print(f"  Completed: {len(completed_ids)}, Pending: {len(pending)}", flush=True)

    if not pending:
        print("All items already completed!", flush=True)
        return

    max_workers = 8
    completed_count = len(completed_ids)
    stats = {"total": total_count, "ok": completed_count, "failed": 0, "by_method": {}}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for method, dataset, question, index in pending:
            future = executor.submit(process_question, method, dataset, question, cfg, index,
                                     output_dir, stage_name, seed)
            futures[future] = (method, dataset, question)

        for future in as_completed(futures):
            if _shutdown_requested:
                print(f"\n[FULL_EVAL] Shutdown requested, cancelling remaining {len(futures) - len(set(futures.keys()) & {future})} futures...", flush=True)
                break

            method, dataset, question = futures[future]
            try:
                record = future.result()
                completed_count += 1
                stats["total"] += 1
                if record.get("result", {}).get("status") == "ok":
                    stats["ok"] += 1
                    em = record.get("scores", {}).get("em", 0) or 0
                    f1 = record.get("scores", {}).get("f1", 0) or 0
                    print(f"[{completed_count}/{total_count}] {dataset}/{method}: OK (EM={em:.2%}, F1={f1:.2%})", flush=True)
                else:
                    stats["failed"] += 1
                    err = record.get("result", {}).get("error", "")
                    print(f"[{completed_count}/{total_count}] {dataset}/{method}: FAILED: {err}", flush=True)
                key = f"{dataset}/{method}"
                ms = stats["by_method"].setdefault(key, {"ok": 0, "failed": 0, "total": 0})
                ms["total"] += 1
                if record.get("result", {}).get("status") == "ok":
                    ms["ok"] += 1
                else:
                    ms["failed"] += 1

                # Track completed ID
                completed_ids.add(question.id)

                # Append to progress log
                append_progress(progress_file, {
                    "id": question.id,
                    "dataset": dataset,
                    "method": method,
                    "status": record.get("result", {}).get("status"),
                    "em": record.get("scores", {}).get("em"),
                    "f1": record.get("scores", {}).get("f1"),
                })

                # Save checkpoint every 100 items
                if completed_count % 100 == 0:
                    save_checkpoint(checkpoint_file, completed_ids, stats)
                    # Compute running stats
                    from collections import Counter
                    by_ds = Counter()
                    by_ds_ok = Counter()
                    ds_ems = {}
                    ds_f1s = {}
                    p = Path(progress_file)
                    if p.exists():
                        for line in p.read_text().strip().split("\n"):
                            if not line: continue
                            entry = json.loads(line)
                            ds = entry["dataset"]
                            by_ds[ds] += 1
                            if entry.get("status") == "ok":
                                by_ds_ok[ds] += 1
                                ds_ems.setdefault(ds, []).append(entry.get("em", 0) or 0)
                                ds_f1s.setdefault(ds, []).append(entry.get("f1", 0) or 0)
                    for ds in sorted(by_ds):
                        n_ok = by_ds_ok.get(ds, 0)
                        n_total = by_ds[ds]
                        em_avg = sum(ds_ems.get(ds, [0])) / n_ok * 100 if n_ok else 0
                        f1_avg = sum(ds_f1s.get(ds, [0])) / n_ok * 100 if n_ok else 0
                        print(f"  [{ds:20s}] ok={n_ok:4d}/{n_total:4d} EM={em_avg:6.2f}% F1={f1_avg:6.2f}%", flush=True)

            except Exception as e:
                completed_count += 1
                stats["total"] += 1
                stats["failed"] += 1
                print(f"[{completed_count}/{total_count}] {dataset}/{method}: EXCEPTION: {type(e).__name__}: {e}", flush=True)

    # Final save
    save_checkpoint(checkpoint_file, completed_ids, stats)

    reranker_http.close()

    # Compute final summary
    from collections import Counter
    by_ds = Counter()
    by_ds_ok = Counter()
    ds_ems = {}
    ds_f1s = {}
    if progress_file.exists():
        for line in progress_file.read_text().strip().split("\n"):
            if not line: continue
            entry = json.loads(line)
            ds = entry["dataset"]
            by_ds[ds] += 1
            if entry.get("status") == "ok":
                by_ds_ok[ds] += 1
                ds_ems.setdefault(ds, []).append(entry.get("em", 0) or 0)
                ds_f1s.setdefault(ds, []).append(entry.get("f1", 0) or 0)

    print(f"\n{'=' * 60}", flush=True)
    print("FULL EVAL SUMMARY", flush=True)
    print(f"{'=' * 60}", flush=True)
    for ds in ["hotpotqa", "2wikimultihop"]:
        n_ok = by_ds_ok.get(ds, 0)
        n_total = by_ds.get(ds, 0)
        em_avg = sum(ds_ems.get(ds, [0])) / n_ok * 100 if n_ok else 0
        f1_avg = sum(ds_f1s.get(ds, [0])) / n_ok * 100 if n_ok else 0
        print(f"{ds:20s}: ok={n_ok:5d}/{n_total:5d} EM={em_avg:6.2f}% F1={f1_avg:6.2f}%", flush=True)

    print(f"\nTotal: {stats['ok']}/{stats['total']} ok ({stats['ok'] / max(stats['total'], 1):.1%})", flush=True)
    print(f"SOTA Thresholds (90%): hotpotqa EM≥61.20% F1≥72.78% | 2wiki EM≥65.70% F1≥73.79%", flush=True)


if __name__ == "__main__":
    main()