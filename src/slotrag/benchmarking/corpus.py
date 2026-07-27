"""Stable retrieval-protocol and shared-corpus interfaces for benchmark runs."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

from ..concurrency import atomic_write_json
from ..data import chunk_passages
from ..models import Passage, QuestionRecord, RetrievalResult
from ..retrieval import EmbeddingCache, HybridRetriever
from ..config import RetrievalConfig


RetrievalProtocol = Literal["local_context", "global_corpus"]


class CorpusManifest(BaseModel):
    """Immutable build metadata plus runtime query counters for one corpus index."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 2
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
    index_storage: Literal["in_memory", "json", "json+embedding_cache"] = "in_memory"
    index_id: str = Field(default="", min_length=0, max_length=64)
    retrieval_backend: Literal["hybrid", "bm25"] = "hybrid"
    reused_persisted_index: bool = False
    passage_artifact: str | None = None
    embedding_artifact: str | None = None
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
    payload = {
        "dataset": dataset,
        "split": split,
        "retrieval_backend": retrieval_backend,
        "retrieval": retrieval.model_dump(mode="json"),
        "passages": [
            {"id": passage.id, "doc_id": passage.doc_id, "text": passage.text}
            for passage in passages
        ],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()


def _estimate_passage_build(
    passage_count: int,
    *,
    dense_enabled: bool,
    embedding_batch_size: int,
    operational_rpm: float | None,
) -> dict[str, Any]:
    batches = (passage_count + embedding_batch_size - 1) // embedding_batch_size if dense_enabled else 0
    lower_bound_minutes = (batches / operational_rpm) if dense_enabled and operational_rpm else 0.0
    return {
        "dense_enabled": dense_enabled,
        "passage_count": passage_count,
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


def _safe_metadata(passage: Passage, question_id: str) -> dict[str, Any]:
    metadata = {
        key: value
        for key, value in passage.metadata.items()
        if key.casefold() not in {"gold_evidence", "gold_supporting_facts", "supporting_facts"}
    }
    metadata.update({
        "source_question_ids": [question_id],
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
    aggregated: dict[tuple[str, str, str], Passage] = {}
    for question in questions:
        chunks = chunk_passages(question.passages, chunk_tokens=chunk_tokens, overlap=chunk_overlap)
        for chunk in chunks:
            source_doc = chunk.doc_id or chunk.id
            key = (source_doc, chunk.id, chunk.text)
            existing = aggregated.get(key)
            if existing is not None:
                source_ids = sorted(set(existing.metadata.get("source_question_ids", [])) | {question.id})
                aggregated[key] = existing.model_copy(update={
                    "metadata": {**existing.metadata, "source_question_ids": source_ids},
                })
                continue
            global_id = f"{dataset}:{source_doc}:{chunk.id}"
            aggregated[key] = Passage(
                id=global_id,
                doc_id=f"{dataset}:{source_doc}",
                text=chunk.text,
                metadata=_safe_metadata(chunk, question.id),
            )
    return [aggregated[key] for key in sorted(aggregated)]


class SharedCorpusIndex:
    """A shared, queryable index with an auditable corpus manifest.

    The class intentionally exposes only ``search``, ``passages``, ``manifest`` and
    ``persist_manifest`` to benchmark callers. Dataset adaptation and planner logic
    remain outside this module.
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
        passages = _aggregate_passages(
            questions,
            dataset=dataset,
            chunk_tokens=retrieval.chunk_tokens,
            chunk_overlap=retrieval.chunk_overlap,
        )
        manifest_path = Path(manifest_path) if manifest_path else None
        index_dir = Path(index_dir) if index_dir else (manifest_path.parent if manifest_path else None)
        if manifest_path is None and index_dir is not None:
            manifest_path = index_dir / "manifest.json"
        if index_dir is not None:
            index_dir.mkdir(parents=True, exist_ok=True)
        passage_artifact = index_dir / "passages.jsonl" if index_dir else None
        embedding_artifact = index_dir / "embeddings.json" if index_dir else None
        backend = retrieval_backend
        index_id = _index_id(
            passages,
            dataset=dataset,
            split=split,
            retrieval=retrieval,
            retrieval_backend=backend,
        )
        can_reuse = False
        raw_manifest: dict[str, Any] = {}
        if reuse_persisted and manifest_path and passage_artifact and manifest_path.exists() and passage_artifact.exists():
            try:
                raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                can_reuse = (
                    raw_manifest.get("index_id") == index_id
                    and raw_manifest.get("retrieval_backend", "hybrid") == backend
                    and raw_manifest.get("chunk_count") == len(passages)
                )
            except (OSError, ValueError):
                can_reuse = False
        if can_reuse:
            try:
                persisted_passages = [
                    Passage.model_validate(json.loads(line))
                    for line in passage_artifact.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            except (OSError, ValueError):
                can_reuse = False
            else:
                if [passage.id for passage in persisted_passages] != [passage.id for passage in passages]:
                    can_reuse = False
                else:
                    passages = persisted_passages

        batch_size = embedding_batch_size or int(getattr(getattr(embedding_client, "config", None), "batch_size", 32))
        estimate = _estimate_passage_build(
            len(passages),
            dense_enabled=backend == "hybrid",
            embedding_batch_size=batch_size,
            operational_rpm=operational_rpm,
        )
        if not can_reuse and max_build_minutes is not None and estimate["lower_bound_minutes"] > max_build_minutes:
            raise CorpusBuildCostError(estimate, max_build_minutes)

        if index_dir and embedding_artifact and (can_reuse or backend == "hybrid"):
            index_cache = EmbeddingCache(embedding_artifact)
        else:
            index_cache = cache or EmbeddingCache()
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
        )
        retriever.build_index()
        build_latency_ms = (time.perf_counter() - started) * 1000
        question_ids = sorted(question.id for question in questions)
        passage_ids = sorted(passage.id for passage in passages)
        if not can_reuse and passage_artifact:
            part_path = passage_artifact.with_suffix(passage_artifact.suffix + ".part")
            part_path.write_text(
                "".join(json.dumps(passage.model_dump(mode="json"), ensure_ascii=True, sort_keys=True) + "\n" for passage in passages),
                encoding="utf-8",
            )
            part_path.replace(passage_artifact)
        if index_dir:
            index_bytes = sum(
                path.stat().st_size
                for path in (passage_artifact, embedding_artifact)
                if path is not None and path.exists()
            )
            index_storage: Literal["json", "json+embedding_cache"] = (
                "json+embedding_cache" if backend == "hybrid" else "json"
            )
        else:
            index_bytes = sum(len(passage.text.encode("utf-8")) for passage in passages)
            index_bytes += len(passages) * max(embedding_dimension if backend == "hybrid" else 0, 0) * 8
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
            question_ids_sha256=_sha256_lines(question_ids),
            passage_ids_sha256=_sha256_lines(passage_ids),
            index_id=index_id,
            retrieval_backend=backend,
            reused_persisted_index=can_reuse,
            passage_artifact=passage_artifact.name if passage_artifact else None,
            embedding_artifact=embedding_artifact.name if embedding_artifact and backend == "hybrid" else None,
            index_storage=index_storage,
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
