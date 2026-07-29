"""Build hybrid (sparse+dense) index using raw httpx, bypassing fcntl/flock rate limiters."""
from __future__ import annotations

import os
import hashlib
import json
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, ContextManager, Iterator

import httpx

from slotrag.benchmarking.corpus import (
    SharedCorpusIndex,
    CorpusManifest,
    _aggregate_passages,
    _sha256_lines,
    _index_id,
    _estimate_passage_build,
    _write_passage_artifact,
    CorpusBuildCostError,
)
from slotrag.benchmarking.datasets import DATASETS, load_all_questions
from slotrag.config import AppConfig, RetrievalConfig
from slotrag.models import QuestionRecord, Passage
from slotrag.retrieval import (
    EmbeddingCache,
    FieldedSparseBM25Index,
    HybridRetriever,
    SparseBM25Index,
    SparseAccessMode,
)
from slotrag.concurrency import exclusive_file_lock, atomic_write_json


class NoopRateLimiter:
    """Bypass file-lock rate limiting (no sleep, no I/O)."""
    def acquire(self) -> float:
        return 0.0


class NoopConcurrencyLimiter:
    """Bypass file-lock concurrency limiting."""
    @contextmanager
    def permit(self) -> Iterator[None]:
        yield


def build_hybrid_index(
    questions: list[QuestionRecord],
    *,
    dataset: str,
    split: str,
    retrieval: RetrievalConfig,
    embedding_url: str,
    embedding_api_key: str,
    embedding_model: str,
    embedding_dim: int,
    embedding_batch: int = 32,
    manifest_path: Path | None = None,
    index_dir: Path | None = None,
    operational_rpm: float | None = None,
    max_build_minutes: float | None = None,
    reuse_persisted: bool = True,
) -> SharedCorpusIndex:
    started = time.perf_counter()
    aggregation_started = time.perf_counter()
    passages = _aggregate_passages(
        questions,
        dataset=dataset,
        chunk_tokens=retrieval.chunk_tokens,
        chunk_overlap=retrieval.chunk_overlap,
    )
    aggregation_latency_ms = (time.perf_counter() - aggregation_started) * 1000

    manifest_path = Path(manifest_path) if manifest_path else None
    index_dir = Path(index_dir) if index_dir else (manifest_path.parent if manifest_path else None)
    if manifest_path is None and index_dir is not None:
        manifest_path = index_dir / "manifest.json"
    if index_dir is not None:
        index_dir.mkdir(parents=True, exist_ok=True)

    passage_artifact = index_dir / "passages.jsonl" if index_dir else None
    sparse_artifact = index_dir / "bm25.pkl" if index_dir else None
    embedding_artifact = index_dir / "embeddings.json" if index_dir else None
    backend = "hybrid"
    question_ids = sorted(q.id for q in questions)
    passage_ids = sorted(p.id for p in passages)
    question_ids_sha256 = _sha256_lines(question_ids)
    passage_ids_sha256 = _sha256_lines(passage_ids)
    index_id = _index_id(
        passages, dataset=dataset, split=split,
        retrieval=retrieval, retrieval_backend=backend,
    )

    lock_context = exclusive_file_lock(manifest_path) if manifest_path else nullcontext()
    with lock_context:
        raw_manifest: dict[str, Any] = {}
        passage_artifact_sha256: str | None = None
        passage_artifact_reused = False
        reuse_reason = "not_requested" if not reuse_persisted else "persisted_artifacts_missing"

        if reuse_persisted and manifest_path and passage_artifact:
            if manifest_path.exists() and passage_artifact.exists():
                try:
                    raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    reuse_reason = f"manifest_invalid:{type(exc).__name__}"
                else:
                    incompatible_fields = [
                        name for name, valid in (
                            ("schema_version", raw_manifest.get("schema_version") == 3),
                            ("index_id_version", raw_manifest.get("index_id_version") == 2),
                            ("index_id", raw_manifest.get("index_id") == index_id),
                            ("retrieval_backend", raw_manifest.get("retrieval_backend") == backend),
                            ("chunk_count", raw_manifest.get("chunk_count") == len(passages)),
                            ("question_ids_sha256", raw_manifest.get("question_ids_sha256") == question_ids_sha256),
                            ("passage_ids_sha256", raw_manifest.get("passage_ids_sha256") == passage_ids_sha256),
                            ("passage_artifact", raw_manifest.get("passage_artifact") == passage_artifact.name),
                        ) if not valid
                    ]
                    expected_checksum = raw_manifest.get("passage_artifact_sha256")
                    if incompatible_fields:
                        reuse_reason = "manifest_incompatible:" + ",".join(incompatible_fields)
                    elif not isinstance(expected_checksum, str) or len(expected_checksum) != 64:
                        reuse_reason = "passage_checksum_missing"
                    else:
                        try:
                            actual = _sha256_hex(passage_artifact)
                        except OSError as exc:
                            reuse_reason = f"passage_checksum_failed:{type(exc).__name__}"
                        else:
                            if actual == expected_checksum:
                                passage_artifact_sha256 = actual
                                passage_artifact_reused = True
                                reuse_reason = "passage_verified"
                            else:
                                reuse_reason = "passage_checksum_mismatch"
            elif not manifest_path.exists():
                reuse_reason = "manifest_missing"
            else:
                reuse_reason = "passage_artifact_missing"
        elif reuse_persisted:
            reuse_reason = "persistence_disabled"

        if index_dir and embedding_artifact and backend == "hybrid":
            index_cache = EmbeddingCache(embedding_artifact)
        else:
            index_cache = EmbeddingCache()

        # --- DENSE EMBEDDING via raw httpx (no rate-limiter deadlocks) ---
        missing_count = sum(1 for p in passages if index_cache.get(p.text) is None)
        if missing_count > 0:
            print(f"  Embedding {missing_count}/{len(passages)} passages (batch={embedding_batch})...", flush=True)
            embed_t0 = time.perf_counter()
            client = httpx.Client(timeout=httpx.Timeout(120.0))
            headers = {
                "Authorization": f"Bearer {embedding_api_key}",
                "Content-Type": "application/json",
            }
            url = f"{embedding_url.rstrip('/')}/embeddings"
            missing_texts = [p.text for p in passages if index_cache.get(p.text) is None]
            done = 0
            total = len(missing_texts)
            for start in range(0, total, embedding_batch):
                batch = missing_texts[start:start + embedding_batch]
                payload = {"model": embedding_model, "input": batch, "encoding_format": "float"}
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
                for row in body["data"]:
                    idx = row["index"]
                    text = batch[idx]
                    vector = [float(v) for v in row["embedding"]]
                    index_cache.put(text, vector)
                done += len(batch)
                if done % 500 == 0 or done == total:
                    e_elapsed = time.perf_counter() - embed_t0
                    rate = done / e_elapsed
                    pct = done * 100 / total
                    eta = (total - done) / rate / 60
                    print(f"  Embedding: {done}/{total} ({pct:.0f}%) {rate:.0f} vec/s, ETA {eta:.0f}min", flush=True)
            index_cache.flush()
            embed_elapsed = time.perf_counter() - embed_t0
            print(f"  Embedding complete: {total} passages in {embed_elapsed/60:.1f} min ({total/embed_elapsed:.0f} vec/s)", flush=True)
        # --- END DENSE EMBEDDING ---

        # Build sparse index
        sparse_started = time.perf_counter()
        sparse_index_class = (
            FieldedSparseBM25Index
            if retrieval.sparse_index_mode == "bm25f"
            else SparseBM25Index
        )
        sparse_index: SparseBM25Index | FieldedSparseBM25Index | None = None
        sparse_index_reused = False
        sparse_index_sha256: str | None = None
        if not passages:
            sparse_index_reused = passage_artifact_reused
        elif passage_artifact_reused and sparse_artifact and sparse_artifact.exists():
            expected_sparse_checksum = raw_manifest.get("sparse_index_sha256")
            sparse_metadata_valid = (
                raw_manifest.get("sparse_index_artifact") == sparse_artifact.name
                and raw_manifest.get("sparse_index_format") == sparse_index_class.artifact_format
                and raw_manifest.get("sparse_index_engine") == sparse_index_class.engine
                and raw_manifest.get("sparse_index_engine_version") == sparse_index_class.engine_version
                and raw_manifest.get("sparse_index_mode", "body") == retrieval.sparse_index_mode
                and isinstance(expected_sparse_checksum, str)
                and len(expected_sparse_checksum) == 64
            )
            if sparse_metadata_valid:
                try:
                    sparse_index = sparse_index_class.load(
                        sparse_artifact,
                        expected_passage_count=len(passages),
                        expected_sha256=expected_sparse_checksum,
                    )
                except (OSError, ValueError, TypeError) as exc:
                    reuse_reason = f"sparse_index_invalid:{type(exc).__name__}"
                else:
                    sparse_index_reused = True
                    sparse_index_sha256 = expected_sparse_checksum
            else:
                reuse_reason = "sparse_metadata_incompatible"
        elif passage_artifact_reused:
            reuse_reason = "sparse_artifact_missing"

        # Create retriever with cache already populated
        from slotrag.providers import EmbeddingClient
        embedding_client = EmbeddingClient(
            cfg.embedding,
            rate_limiter=NoopRateLimiter(),
            concurrency_limiter=NoopConcurrencyLimiter(),
        )

        retriever = HybridRetriever(
            passages,
            embedding_client,
            None,  # reranker_client
            bm25_k=retrieval.bm25_k,
            dense_k=retrieval.dense_k,
            final_k=retrieval.final_k,
            rrf_k=retrieval.rrf_k,
            bm25_weight=retrieval.bm25_weight,
            dense_weight=retrieval.dense_weight,
            rerank_enabled=False,
            cache=index_cache,
            dense_enabled=True,
            sparse_index=sparse_index,
            sparse_index_mode=retrieval.sparse_index_mode,
            sparse_title_weight=retrieval.sparse_title_weight,
        )
        sparse_index_latency_ms = (time.perf_counter() - sparse_started) * 1000

        dense_started = time.perf_counter()
        retriever.build_index()  # should be no-op since cache is populated
        dense_index_latency_ms = (time.perf_counter() - dense_started) * 1000
        dense_index_reused = missing_count == 0

        artifact_started = time.perf_counter()
        if passage_artifact and not passage_artifact_reused:
            passage_artifact_sha256 = _write_passage_artifact(passage_artifact, passages)
        if sparse_artifact and passages and not sparse_index_reused:
            sparse_index_sha256 = retriever.save_sparse_index(sparse_artifact)
        artifact_write_latency_ms = (time.perf_counter() - artifact_started) * 1000

        fully_reused = bool(
            index_dir and passage_artifact_reused and sparse_index_reused and dense_index_reused
        )
        if fully_reused:
            reuse_reason = "fully_reused"
        elif not passage_artifact_reused and reuse_reason in {
            "not_requested", "persisted_artifacts_missing", "manifest_missing", "passage_artifact_missing",
        }:
            reuse_reason = "created_new_index"

        build_latency_ms = (time.perf_counter() - started) * 1000
        if index_dir:
            index_bytes = sum(
                path.stat().st_size
                for path in (passage_artifact, sparse_artifact, embedding_artifact)
                if path is not None and path.exists()
            )
            index_storage = "json+bm25+embedding_cache"
        else:
            index_bytes = sum(len(p.text.encode("utf-8")) for p in passages)
            index_bytes += len(passages) * embedding_dim * 8
            index_storage = "in_memory"

        manifest = CorpusManifest(
            dataset=dataset, split=split, source_scope="full_split",
            source_question_count=len(questions),
            document_count=len({p.doc_id or p.id for p in passages}),
            chunk_count=len(passages), index_bytes=index_bytes,
            build_latency_ms=build_latency_ms, query_count=0, query_latency_ms=0.0,
            question_ids_sha256=question_ids_sha256,
            passage_ids_sha256=passage_ids_sha256, index_id=index_id,
            retrieval_backend=backend, reused_persisted_index=fully_reused,
            passage_artifact_reused=passage_artifact_reused,
            sparse_index_reused=sparse_index_reused,
            reuse_reason=reuse_reason,
            passage_artifact=passage_artifact.name if passage_artifact else None,
            passage_artifact_sha256=passage_artifact_sha256,
            sparse_index_artifact=sparse_artifact.name if sparse_artifact and passages else None,
            sparse_index_sha256=sparse_index_sha256,
            sparse_index_format=sparse_index_class.artifact_format if passages else None,
            sparse_index_engine=sparse_index_class.engine if passages else None,
            sparse_index_engine_version=sparse_index_class.engine_version if passages else None,
            sparse_index_mode=retrieval.sparse_index_mode,
            sparse_title_weight=retrieval.sparse_title_weight,
            embedding_artifact=embedding_artifact.name if embedding_artifact else None,
            index_storage=index_storage,
            aggregation_latency_ms=aggregation_latency_ms,
            sparse_index_latency_ms=sparse_index_latency_ms,
            dense_index_latency_ms=dense_index_latency_ms,
            artifact_write_latency_ms=artifact_write_latency_ms,
            build_estimate=_estimate_passage_build(
                len(passages), dense_enabled=True, embedding_batch_size=embedding_batch,
                operational_rpm=None, missing_dense_passage_count=missing_count,
            ),
        )
        index = SharedCorpusIndex(retriever, manifest, manifest_path=manifest_path)
        index.persist_manifest()
        return index


def _sha256_hex(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1048576), b""):
            d.update(block)
    return d.hexdigest()


if __name__ == "__main__":
    from slotrag.config import AppConfig
    cfg = AppConfig.from_yaml("configs/default.yaml")
    split = "train"
    index_root = Path("runs/slotrag-global-index-v74-hybrid")

    for dataset in ["hotpotqa", "2wikimultihop"]:
        index_dir = index_root / "qo_v74_development_hybrid" / dataset
        manifest_path = index_dir / "manifest.json"
        print(f"\n=== {dataset} ===", flush=True)
        t0 = time.time()
        questions = load_all_questions(DATASETS[dataset], Path("benchmark"), split=split)
        print(f"  {len(questions)} questions loaded in {time.time()-t0:.1f}s", flush=True)
        t0 = time.time()
        index = build_hybrid_index(
            questions,
            dataset=dataset, split=split,
            retrieval=cfg.retrieval,
            embedding_url=cfg.embedding.base_url,
            embedding_api_key=os.environ.get("SLOTRAG_EMBEDDING_API_KEY", "test-key"),
            embedding_model=cfg.embedding.model,
            embedding_dim=cfg.embedding.dimension,
            embedding_batch=32,
            manifest_path=manifest_path,
            index_dir=index_dir,
            max_build_minutes=180,
        )
        m = index.manifest
        elapsed = time.time() - t0
        print(f"  ✅ {dataset} done in {elapsed/60:.1f} min", flush=True)
        print(f"  Chunks: {m.chunk_count} | Reuse: {m.reuse_reason}", flush=True)

    print("\n=== ALL DONE ===", flush=True)
