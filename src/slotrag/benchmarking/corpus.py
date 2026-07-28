"""Stable retrieval-protocol and shared-corpus interfaces for benchmark runs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from collections import defaultdict
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

from ..concurrency import atomic_write_json, exclusive_file_lock
from ..data import chunk_passages, sha256_file
from ..models import Passage, QuestionRecord, RetrievalResult
from ..retrieval import (
    EmbeddingCache,
    FieldedSparseBM25Index,
    HybridRetriever,
    SparseBM25Index,
)
from ..config import RetrievalConfig


RetrievalProtocol = Literal["local_context", "global_corpus"]


class CorpusManifest(BaseModel):
    """Immutable build metadata plus runtime query counters for one corpus index."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 3
    protocol: Literal["global_corpus"] = "global_corpus"
    dataset: str = Field(min_length=1)
    split: str = Field(min_length=1)
    source_scope: Literal["full_split", "stage_sample", "external"] = "full_split"
    source_question_count: int = Field(ge=0)
    document_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    index_bytes: int = Field(ge=0)
    build_latency_ms: float = Field(ge=0)
    query_count: int = Field(ge=0)
    query_latency_ms: float = Field(ge=0)
    question_ids_sha256: str = Field(min_length=64, max_length=64)
    passage_ids_sha256: str = Field(min_length=64, max_length=64)
    available_evidence_policy: str = "all_question_passages_excluding_gold_annotations"
    gold_evidence_not_used: bool = True
    index_storage: Literal[
        "in_memory",
        "json",
        "json+embedding_cache",
        "json+bm25",
        "json+bm25+embedding_cache",
    ] = "in_memory"
    index_id: str = Field(default="", min_length=0, max_length=64)
    index_id_version: int = 2
    retrieval_backend: Literal["hybrid", "bm25"] = "hybrid"
    reused_persisted_index: bool = False
    passage_artifact_reused: bool = False
    sparse_index_reused: bool = False
    reuse_reason: str = "not_requested"
    passage_artifact: str | None = None
    passage_artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    sparse_index_artifact: str | None = None
    sparse_index_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    sparse_index_format: str | None = None
    sparse_index_engine: str | None = None
    sparse_index_engine_version: str | None = None
    sparse_index_mode: Literal["body", "bm25f"] = "body"
    sparse_title_weight: float = Field(default=2.0, gt=0)
    embedding_artifact: str | None = None
    aggregation_latency_ms: float = Field(default=0.0, ge=0)
    sparse_index_latency_ms: float = Field(default=0.0, ge=0)
    dense_index_latency_ms: float = Field(default=0.0, ge=0)
    artifact_write_latency_ms: float = Field(default=0.0, ge=0)
    build_estimate: dict[str, Any] = Field(default_factory=dict)


class CorpusBuildCostError(RuntimeError):
    """Raised before provider work when a shared-index build exceeds its budget."""

    def __init__(self, estimate: dict[str, Any], max_build_minutes: float) -> None:
        self.estimate = estimate
        self.max_build_minutes = max_build_minutes
        super().__init__(
            "shared corpus build exceeds cost gate: "
            f"{estimate.get('lower_bound_minutes', 0):.2f} min > {max_build_minutes:.2f} min"
        )


def _sha256_lines(values: Sequence[str]) -> str:
    payload = "\n".join(values).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _index_id(
    passages: Sequence[Passage],
    *,
    dataset: str,
    split: str,
    retrieval: RetrievalConfig,
    retrieval_backend: str,
) -> str:
    retrieval_payload = retrieval.model_dump(mode="json")
    if retrieval.sparse_index_mode == "body":
        retrieval_payload.pop("sparse_index_mode", None)
        retrieval_payload.pop("sparse_title_weight", None)
    header = {
        "index_id_version": 2,
        "dataset": dataset,
        "split": split,
        "retrieval_backend": retrieval_backend,
        "retrieval": retrieval_payload,
    }
    digest = hashlib.sha256(json.dumps(header, ensure_ascii=True, sort_keys=True).encode("utf-8"))
    for passage in passages:
        digest.update(b"\n")
        digest.update(json.dumps(
            passage.model_dump(mode="json"),
            ensure_ascii=True,
            sort_keys=True,
        ).encode("utf-8"))
    return digest.hexdigest()


def _estimate_passage_build(
    passage_count: int,
    *,
    dense_enabled: bool,
    embedding_batch_size: int,
    operational_rpm: float | None,
    missing_dense_passage_count: int | None = None,
) -> dict[str, Any]:
    embedding_passage_count = (
        passage_count if missing_dense_passage_count is None else missing_dense_passage_count
    ) if dense_enabled else 0
    batches = (
        (embedding_passage_count + embedding_batch_size - 1) // embedding_batch_size
        if dense_enabled else 0
    )
    lower_bound_minutes = (batches / operational_rpm) if dense_enabled and operational_rpm else 0.0
    return {
        "dense_enabled": dense_enabled,
        "passage_count": passage_count,
        "embedding_passage_count": embedding_passage_count,
        "embedding_batches": batches,
        "embedding_batch_size": embedding_batch_size,
        "operational_rpm": operational_rpm,
        "lower_bound_minutes": lower_bound_minutes,
    }


def estimate_corpus_build(
    questions: Sequence[QuestionRecord],
    *,
    dataset: str,
    retrieval: RetrievalConfig,
    retrieval_backend: Literal["hybrid", "bm25"] = "hybrid",
    embedding_batch_size: int = 32,
    operational_rpm: float | None = None,
) -> dict[str, Any]:
    """Estimate provider work without constructing an embedding client or making calls."""
    passages = _aggregate_passages(
        questions,
        dataset=dataset,
        chunk_tokens=retrieval.chunk_tokens,
        chunk_overlap=retrieval.chunk_overlap,
    )
    return _estimate_passage_build(
        len(passages),
        dense_enabled=retrieval_backend == "hybrid",
        embedding_batch_size=embedding_batch_size,
        operational_rpm=operational_rpm,
    )


def _safe_metadata(passage: Passage, question_ids: Sequence[str]) -> dict[str, Any]:
    metadata = {
        key: value
        for key, value in passage.metadata.items()
        if key.casefold() not in {"gold_evidence", "gold_supporting_facts", "supporting_facts"}
    }
    metadata.update({
        "source_question_ids": sorted(set(question_ids)),
        "source_passage_id": passage.id,
        "evidence_scope": "available",
    })
    return metadata


def _aggregate_passages(
    questions: Sequence[QuestionRecord],
    *,
    dataset: str,
    chunk_tokens: int,
    chunk_overlap: int,
) -> list[Passage]:
    """Deduplicate exact source chunks while preserving all question provenance."""
    aggregated: dict[tuple[str, str, str], tuple[str, Passage]] = {}
    source_question_ids: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for question in questions:
        chunks = chunk_passages(question.passages, chunk_tokens=chunk_tokens, overlap=chunk_overlap)
        for chunk in chunks:
            source_doc = chunk.doc_id or chunk.id
            key = (source_doc, chunk.id, chunk.text)
            aggregated.setdefault(key, (source_doc, chunk))
            source_question_ids[key].add(question.id)
    return [
        Passage(
            id=f"{dataset}:{source_doc}:{chunk.id}",
            doc_id=f"{dataset}:{source_doc}",
            text=chunk.text,
            metadata=_safe_metadata(chunk, sorted(source_question_ids[key])),
        )
        for key in sorted(aggregated)
        for source_doc, chunk in [aggregated[key]]
    ]


def _write_passage_artifact(path: Path, passages: Sequence[Passage]) -> str:
    """Atomically stream a deterministic JSONL passage artifact and return its checksum."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".part",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for passage in passages:
                handle.write(json.dumps(
                    passage.model_dump(mode="json"),
                    ensure_ascii=True,
                    sort_keys=True,
                ))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        checksum = sha256_file(temporary)
        os.replace(temporary, path)
        return checksum
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


class SharedCorpusIndex:
    """A shared, queryable index with an auditable corpus manifest.

    The class exposes scalar and batched search plus corpus telemetry. Dataset
    adaptation and planner logic remain outside this module.
    """

    def __init__(
        self,
        retriever: HybridRetriever,
        manifest: CorpusManifest,
        *,
        manifest_path: Path | None = None,
    ) -> None:
        self._retriever = retriever
        self.manifest = manifest
        self.manifest_path = manifest_path
        self._query_count = 0
        self._query_latency_ms = 0.0
        self._lock = threading.Lock()

    @classmethod
    def from_questions(
        cls,
        questions: Sequence[QuestionRecord],
        *,
        dataset: str,
        split: str,
        retrieval: RetrievalConfig,
        embedding_client: Any | None,
        reranker_client: Any | None,
        rerank_enabled: bool,
        cache: EmbeddingCache | None = None,
        manifest_path: Path | None = None,
        source_scope: Literal["full_split", "stage_sample", "external"] = "full_split",
        embedding_dimension: int = 0,
        retrieval_backend: Literal["hybrid", "bm25"] = "hybrid",
        index_dir: Path | None = None,
        reuse_persisted: bool = True,
        max_build_minutes: float | None = None,
        operational_rpm: float | None = None,
        embedding_batch_size: int | None = None,
    ) -> "SharedCorpusIndex":
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
        backend = retrieval_backend
        question_ids = sorted(question.id for question in questions)
        passage_ids = sorted(passage.id for passage in passages)
        question_ids_sha256 = _sha256_lines(question_ids)
        passage_ids_sha256 = _sha256_lines(passage_ids)
        index_id = _index_id(
            passages,
            dataset=dataset,
            split=split,
            retrieval=retrieval,
            retrieval_backend=backend,
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
                            name
                            for name, valid in (
                                ("schema_version", raw_manifest.get("schema_version") == 3),
                                ("index_id_version", raw_manifest.get("index_id_version") == 2),
                                ("index_id", raw_manifest.get("index_id") == index_id),
                                ("retrieval_backend", raw_manifest.get("retrieval_backend") == backend),
                                ("chunk_count", raw_manifest.get("chunk_count") == len(passages)),
                                ("question_ids_sha256", raw_manifest.get("question_ids_sha256") == question_ids_sha256),
                                ("passage_ids_sha256", raw_manifest.get("passage_ids_sha256") == passage_ids_sha256),
                                ("passage_artifact", raw_manifest.get("passage_artifact") == passage_artifact.name),
                            )
                            if not valid
                        ]
                        expected_checksum = raw_manifest.get("passage_artifact_sha256")
                        if incompatible_fields:
                            reuse_reason = "manifest_incompatible:" + ",".join(incompatible_fields)
                        elif not isinstance(expected_checksum, str) or len(expected_checksum) != 64:
                            reuse_reason = "passage_checksum_missing"
                        else:
                            try:
                                actual_checksum = sha256_file(passage_artifact)
                            except OSError as exc:
                                reuse_reason = f"passage_checksum_failed:{type(exc).__name__}"
                            else:
                                if actual_checksum == expected_checksum:
                                    passage_artifact_sha256 = actual_checksum
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
                index_cache = cache or EmbeddingCache()
            missing_dense_passages = (
                sum(1 for passage in passages if index_cache.get(passage.text) is None)
                if backend == "hybrid" else 0
            )
            batch_size = embedding_batch_size or int(
                getattr(getattr(embedding_client, "config", None), "batch_size", 32)
            )
            estimate = _estimate_passage_build(
                len(passages),
                dense_enabled=backend == "hybrid",
                embedding_batch_size=batch_size,
                operational_rpm=operational_rpm,
                missing_dense_passage_count=missing_dense_passages,
            )
            if max_build_minutes is not None and estimate["lower_bound_minutes"] > max_build_minutes:
                raise CorpusBuildCostError(estimate, max_build_minutes)

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

            retriever = HybridRetriever(
                passages,
                embedding_client,
                reranker_client,
                bm25_k=retrieval.bm25_k,
                dense_k=retrieval.dense_k,
                final_k=retrieval.final_k,
                rrf_k=retrieval.rrf_k,
                bm25_weight=retrieval.bm25_weight,
                dense_weight=retrieval.dense_weight,
                rerank_enabled=rerank_enabled and backend == "hybrid",
                cache=index_cache,
                dense_enabled=backend == "hybrid",
                sparse_index=sparse_index,
                sparse_index_mode=retrieval.sparse_index_mode,
                sparse_title_weight=retrieval.sparse_title_weight,
            )
            sparse_index_latency_ms = (time.perf_counter() - sparse_started) * 1000

            dense_started = time.perf_counter()
            retriever.build_index()
            dense_index_latency_ms = (time.perf_counter() - dense_started) * 1000
            dense_index_reused = backend == "bm25" or missing_dense_passages == 0

            artifact_started = time.perf_counter()
            if passage_artifact and not passage_artifact_reused:
                passage_artifact_sha256 = _write_passage_artifact(passage_artifact, passages)
            if sparse_artifact and passages and not sparse_index_reused:
                sparse_index_sha256 = retriever.save_sparse_index(sparse_artifact)
            artifact_write_latency_ms = (time.perf_counter() - artifact_started) * 1000

            fully_reused = bool(
                index_dir
                and passage_artifact_reused
                and sparse_index_reused
                and dense_index_reused
            )
            if fully_reused:
                reuse_reason = "fully_reused"
            elif not passage_artifact_reused and reuse_reason in {
                "not_requested",
                "persisted_artifacts_missing",
                "manifest_missing",
                "passage_artifact_missing",
            }:
                reuse_reason = "created_new_index"

            build_latency_ms = (time.perf_counter() - started) * 1000
            if index_dir:
                index_bytes = sum(
                    path.stat().st_size
                    for path in (passage_artifact, sparse_artifact, embedding_artifact)
                    if path is not None and path.exists()
                )
                index_storage: Literal[
                    "json+bm25", "json+bm25+embedding_cache"
                ] = "json+bm25+embedding_cache" if backend == "hybrid" else "json+bm25"
            else:
                index_bytes = sum(len(passage.text.encode("utf-8")) for passage in passages)
                index_bytes += len(passages) * max(
                    embedding_dimension if backend == "hybrid" else 0,
                    0,
                ) * 8
                index_storage = "in_memory"
            manifest = CorpusManifest(
                dataset=dataset,
                split=split,
                source_scope=source_scope,
                source_question_count=len(questions),
                document_count=len({passage.doc_id or passage.id for passage in passages}),
                chunk_count=len(passages),
                index_bytes=index_bytes,
                build_latency_ms=build_latency_ms,
                query_count=0,
                query_latency_ms=0.0,
                question_ids_sha256=question_ids_sha256,
                passage_ids_sha256=passage_ids_sha256,
                index_id=index_id,
                retrieval_backend=backend,
                reused_persisted_index=fully_reused,
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
                embedding_artifact=(
                    embedding_artifact.name
                    if embedding_artifact and backend == "hybrid" else None
                ),
                index_storage=index_storage,
                aggregation_latency_ms=aggregation_latency_ms,
                sparse_index_latency_ms=sparse_index_latency_ms,
                dense_index_latency_ms=dense_index_latency_ms,
                artifact_write_latency_ms=artifact_write_latency_ms,
                build_estimate=estimate,
            )
            index = cls(retriever, manifest, manifest_path=manifest_path)
            index.persist_manifest()
            return index

    @property
    def passages(self) -> list[Passage]:
        return self._retriever.passages

    def build_index(self) -> None:
        """Keep the retriever-compatible build hook idempotent."""
        self._retriever.build_index()

    def search(self, query: str, *, top_k: int | None = None) -> list[RetrievalResult]:
        started = time.perf_counter()
        try:
            return self._retriever.search(query, top_k=top_k)
        finally:
            with self._lock:
                self._query_count += 1
                self._query_latency_ms += (time.perf_counter() - started) * 1000

    def search_batch(
        self,
        queries: list[str],
        *,
        top_k: int | None = None,
    ) -> list[list[RetrievalResult]]:
        """Execute a physical batch while accounting for each logical query."""

        started = time.perf_counter()
        try:
            return self._retriever.search_batch(queries, top_k=top_k)
        finally:
            with self._lock:
                self._query_count += len(queries)
                self._query_latency_ms += (time.perf_counter() - started) * 1000

    def stats_snapshot(self) -> tuple[int, float]:
        with self._lock:
            return self._query_count, self._query_latency_ms

    def persist_manifest(self) -> None:
        if self.manifest_path is None:
            return
        query_count, query_latency_ms = self.stats_snapshot()
        self.manifest = self.manifest.model_copy(update={
            "query_count": query_count,
            "query_latency_ms": query_latency_ms,
        })
        atomic_write_json(self.manifest_path, self.manifest.model_dump(mode="json"))
