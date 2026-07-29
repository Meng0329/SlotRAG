"""Direct hybrid benchmark runner — no fcntl locking, no BenchmarkRunner.

Uses ThreadPoolExecutor to run questions in parallel. Each worker thread
creates its own AgnesClient (httpx.Client is NOT thread-safe).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

# Load environment file — do this BEFORE any imports that check env vars
env_path = Path(".env")
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

os.environ.setdefault("SLOTRAG_EMBEDDING_API_KEY", "lgw-fe4c5edc0f436c40fbf305029e8caa42c9890468b39a1611cd1f80a9e97e0b44")

from slotrag.config import AppConfig
from slotrag.benchmarking.datasets import DATASETS, load_sample
from slotrag.benchmarking.metrics import score_record
from slotrag.providers import EmbeddingClient, RerankerClient

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
        return [self.search(query, top_k=top_k) for query in queries]
    return _orig_search_batch(self, queries, top_k=top_k, sparse_access_modes=sparse_access_modes)


_retrieval.HybridRetriever.search_batch = _patched_search_batch

# --- No-op rate/concurrency limiters (avoid fcntl flock D-state hangs) ---
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


# --- Thread-safe reranker wrapper (httpx.Client is NOT thread-safe) ---
_reranker_lock = threading.Lock()
_orig_rerank_method = RerankerClient.rerank


def _safe_rerank(self, query, documents, top_n=None):
    with _reranker_lock:
        return _orig_rerank_method(self, query, documents, top_n=top_n)


RerankerClient.rerank = _safe_rerank

# --- Thread-safe embedding wrapper (shared across all thread workers) ---
_embed_lock = threading.Lock()
_orig_embed_method = EmbeddingClient.embed


def _safe_embed(self, inputs, **kwargs):
    with _embed_lock:
        return _orig_embed_method(self, inputs, **kwargs)


EmbeddingClient.embed = _safe_embed


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
    return EmbeddingClient(
        cfg.embedding,
        rate_limiter=NullRateLimiter(),
        concurrency_limiter=NullConcurrencyLimiter(),
    )


def build_reranker_client(cfg):
    """Build RerankerClient without fcntl rate limiters."""
    import httpx
    client = httpx.Client(timeout=httpx.Timeout(cfg.reranker.timeout_seconds + 5.0))
    reranker = RerankerClient(
        cfg.reranker,
        client,
        rate_limiter=NullRateLimiter(),
        concurrency_limiter=NullConcurrencyLimiter(),
    )
    return reranker, client


def load_shared_index(
    dataset: str,
    index_stage: str,
    cfg,
    *,
    reranker_client=None,
    rerank_enabled=False,
):
    import numpy as np

    index_dir = Path("runs/slotrag-global-index-v74-hybrid") / index_stage / dataset
    manifest_path = index_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No manifest at {manifest_path}")
    print(f"  Loading shared index from {index_dir}...", flush=True)
    manifest_data = json.loads(manifest_path.read_text())

    # Load passages
    passages_path = index_dir / manifest_data["passage_artifact"]
    from slotrag.models import Passage
    passages_list = []
    for line in passages_path.read_text().strip().split("\n"):
        if line:
            passages_list.append(Passage(**json.loads(line)))
    print(f"  {len(passages_list)} passages", flush=True)

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

    # Load dense vectors (mmap)
    npy_path = index_dir / "embeddings.npy"
    idx_path = index_dir / "embeddings_index.json"
    if not npy_path.exists():
        raise FileNotFoundError(f"No embeddings.npy at {npy_path}")
    if not idx_path.exists():
        raise FileNotFoundError(f"No embeddings_index.json at {idx_path}")
    print(f"  Loading dense vectors from {npy_path}...", flush=True)
    t0 = time.time()
    vectors_2d = np.load(npy_path, mmap_mode="r")  # mmap — lazy page faults, lower peak RAM
    print(f"  Loaded {vectors_2d.shape} in {time.time() - t0:.1f}s", flush=True)

    t0 = time.time()
    hash_keys: list[str] = json.loads(idx_path.read_bytes())
    hash_to_row: dict[str, int] = {k: i for i, k in enumerate(hash_keys)}
    print(f"  Hash index loaded ({len(hash_keys)} keys) in {time.time() - t0:.1f}s", flush=True)

    # Build retriever — no cache, set _passage_vectors directly
    from slotrag.retrieval import HybridRetriever
    dummy_client = EmbeddingClient(
        cfg.embedding,
        rate_limiter=NullRateLimiter(),
        concurrency_limiter=NullConcurrencyLimiter(),
    )

    print(f"  Building retriever: dense_k={cfg.retrieval.dense_k}, bm25_k={cfg.retrieval.bm25_k}, "
          f"rerank_enabled={rerank_enabled}, reranker.top_n={cfg.reranker.top_n}", flush=True)
    retriever = HybridRetriever(
        passages_list,
        dummy_client,
        bm25_k=cfg.retrieval.bm25_k,
        dense_k=cfg.retrieval.dense_k,
        final_k=cfg.retrieval.final_k,
        rrf_k=cfg.retrieval.rrf_k,
        bm25_weight=cfg.retrieval.bm25_weight,
        dense_weight=cfg.retrieval.dense_weight,
        rerank_enabled=rerank_enabled,
        reranker_client=reranker_client,
        cache=None,
        dense_enabled=True,
        sparse_index=sparse_index,
    )

    # Set passage vectors via hash lookup
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
    # Need to set the embedding_client on the retriever or SharedCorpusIndex will complain
    index = SCI(retriever, manifest, manifest_path=manifest_path)
    index.build_index()
    print(f"  Shared index ready ({retriever.dense_enabled=}, "
          f"{len(retriever._passage_vectors) if retriever._passage_vectors else 0} vectors, "
          f"{'reranker ON' if rerank_enabled else 'reranker OFF'}) in {time.time() - t0:.1f}s",
          flush=True)
    return index


def process_question(
    method: str,
    dataset: str,
    question: Any,
    cfg: Any,
    index: Any,
    output_dir: Path,
    stage_name: str,
    seed: int,
) -> dict[str, Any]:
    """Process one question with its own LLM client."""
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in question.id)[:80]
    digest = hashlib.sha256(question.id.encode()).hexdigest()[:12]
    item_filename = f"{safe_id}-{digest}.json"
    method_dir = output_dir / "items" / stage_name / dataset / method
    method_dir.mkdir(parents=True, exist_ok=True)
    item_path = method_dir / item_filename

    # Check if already completed
    if item_path.exists():
        try:
            existing = json.loads(item_path.read_text())
            if existing.get("result", {}).get("status") == "ok":
                return existing
        except Exception:
            pass

    # Build per-question LLM client
    from slotrag.providers import AgnesClient
    import httpx

    hc = httpx.Client(timeout=httpx.Timeout(cfg.agnes.timeout_seconds + 5.0))
    try:
        agnes = AgnesClient(
            cfg.agnes,
            hc,
            rate_limiter=NullRateLimiter(),
            concurrency_limiter=NullConcurrencyLimiter(),
        )
        from slotrag.benchmarking.runner import _BudgetedRetriever, _BudgetedAgnes
        budgeted_retriever = _BudgetedRetriever(index, 16)
        budgeted_agnes = _BudgetedAgnes(agnes, 48)

        t0 = time.perf_counter()
        from slotrag.benchmarking.methods import run_method
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
        return record
    finally:
        hc.close()


def main():
    # Index on disk uses the original hybrid index
    index_stage = "qo_v74_development_hybrid"
    stage_name = "qo_v74_v5_corrected_dev"
    cfg = AppConfig.from_yaml("configs/default.yaml")

    # ====== V5: V1 retrieval + fixed generation (no thinking) + wired extraction thinking ======
    cfg.retrieval.dense_k = 100
    cfg.retrieval.bm25_k = 100
    cfg.retrieval.bm25_weight = 0.5
    cfg.retrieval.dense_weight = 0.5
    cfg.reranker.top_n = 50
    # ====================================

    datasets = ["hotpotqa", "2wikimultihop"]
    methods = [
        "slotrag",
        "slotrag-dual-access",
        "slotrag-evidence-bundle",
        "slotrag-per-path-extraction",
    ]
    sample_size = 40
    seed = 314159

    output_dir = Path("runs/slotrag-v74-qwen-hybrid-reranker-v5")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build shared reranker client (thread-safe, stateless)
    reranker_client, reranker_http = build_reranker_client(cfg)

    stats = {"total": 0, "ok": 0, "failed": 0, "by_method": {}}

    # Build work items
    all_items = []
    question_cache = {}

    for dataset in datasets:
        print(f"\n{'=' * 60}", flush=True)
        print(f"DATASET: {dataset} — loading questions & index", flush=True)
        print(f"{'=' * 60}", flush=True)

        questions = load_sample(
            DATASETS[dataset],
            Path("benchmark"),
            split="train",
            size=sample_size,
            seed=seed,
        )
        question_cache[dataset] = questions
        print(f"  {len(questions)} questions", flush=True)

        index = load_shared_index(
            dataset, index_stage, cfg,
            reranker_client=reranker_client,
            rerank_enabled=True,
        )

        for method in methods:
            for q in questions:
                all_items.append((method, dataset, q, index))

    total_items = len(all_items)
    print(f"\nTotal work items: {total_items}", flush=True)
    print(f"Using ThreadPoolExecutor(max_workers=8) — ext4 can't handle 16-way concurrent mmap page faults", flush=True)

    max_workers = 8
    completed = 0
    futures = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for method, dataset, question, index in all_items:
            future = executor.submit(
                process_question,
                method, dataset, question, cfg, index,
                output_dir, stage_name, seed,
            )
            futures.append((future, method, dataset, question))

        for future, method, dataset, question in futures:
            try:
                record = future.result()
                completed += 1
                stats["total"] += 1
                if record.get("result", {}).get("status") == "ok":
                    stats["ok"] += 1
                    em = record.get("scores", {}).get("em", 0) or 0
                    f1 = record.get("scores", {}).get("f1", 0) or 0
                    print(f"[{completed}/{total_items}] {dataset}/{method}: OK (EM={em:.2%}, F1={f1:.2%})", flush=True)
                else:
                    stats["failed"] += 1
                    err = record.get("result", {}).get("error", "")
                    print(f"[{completed}/{total_items}] {dataset}/{method}: FAILED: {err}", flush=True)

                key = f"{dataset}/{method}"
                ms = stats["by_method"].setdefault(key, {"ok": 0, "failed": 0, "total": 0})
                ms["total"] += 1
                if record.get("result", {}).get("status") == "ok":
                    ms["ok"] += 1
                else:
                    ms["failed"] += 1

            except Exception as e:
                completed += 1
                stats["total"] += 1
                stats["failed"] += 1
                print(f"[{completed}/{total_items}] {dataset}/{method}: EXCEPTION: {type(e).__name__}: {e}", flush=True)

    reranker_http.close()

    print(f"\n{'=' * 60}", flush=True)
    print(f"RESULTS: {stats['ok']}/{stats['total']} ok ({stats['ok'] / stats['total']:.1%})", flush=True)
    print(f"Failed: {stats['failed']}", flush=True)

    (output_dir / "summary.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"Summary written to {output_dir / 'summary.json'}", flush=True)


if __name__ == "__main__":
    main()
