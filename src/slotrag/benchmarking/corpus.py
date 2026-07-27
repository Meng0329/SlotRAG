"""Stable retrieval-protocol and shared-corpus interfaces for benchmark runs."""

from __future__ import annotations

import hashlib
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

    schema_version: int = 1
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
    index_storage: Literal["in_memory"] = "in_memory"


def _sha256_lines(values: Sequence[str]) -> str:
    payload = "\n".join(values).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
        embedding_client: Any,
        reranker_client: Any | None,
        rerank_enabled: bool,
        cache: EmbeddingCache | None = None,
        manifest_path: Path | None = None,
        source_scope: Literal["full_split", "stage_sample", "external"] = "full_split",
        embedding_dimension: int = 0,
    ) -> "SharedCorpusIndex":
        started = time.perf_counter()
        passages = _aggregate_passages(
            questions,
            dataset=dataset,
            chunk_tokens=retrieval.chunk_tokens,
            chunk_overlap=retrieval.chunk_overlap,
        )
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
            rerank_enabled=rerank_enabled,
            cache=cache,
        )
        retriever.build_index()
        build_latency_ms = (time.perf_counter() - started) * 1000
        question_ids = sorted(question.id for question in questions)
        passage_ids = sorted(passage.id for passage in passages)
        index_bytes = sum(len(passage.text.encode("utf-8")) for passage in passages)
        index_bytes += len(passages) * max(embedding_dimension, 0) * 8
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
