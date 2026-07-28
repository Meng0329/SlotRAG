from __future__ import annotations

import hashlib
import math
import os
import pickle
import re
import tempfile
from collections import Counter, defaultdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Iterable, Literal

import numpy as np
from rank_bm25 import BM25Okapi

from .concurrency import locked_update_json
from .models import Passage, RetrievalResult, Slot
from .providers import EmbeddingClient, RerankerClient


TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)
SparseAccessMode = Literal["configured", "body"]
SPARSE_ACCESS_MODES = frozenset({"configured", "body"})

try:
    RANK_BM25_VERSION = version("rank-bm25")
except PackageNotFoundError:  # pragma: no cover - import already proves the package exists
    RANK_BM25_VERSION = "unknown"


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def _top_k_indices(scores: np.ndarray, top_k: int) -> list[int]:
    """Select a stable top-k without sorting the full corpus."""

    if top_k <= 0 or scores.size == 0:
        return []
    limit = min(top_k, int(scores.size))
    if limit == scores.size:
        return [int(index) for index in np.argsort(-scores, kind="stable")]
    threshold = float(np.partition(scores, int(scores.size) - limit)[int(scores.size) - limit])
    greater = [int(index) for index in np.flatnonzero(scores > threshold)]
    tied = [int(index) for index in np.flatnonzero(scores == threshold)]
    candidates = [*greater, *tied[: limit - len(greater)]]
    return sorted(
        candidates,
        key=lambda index: (-float(scores[index]), index),
    )


def _batch_bm25_top_k(
    weighted_indexes: list[tuple[BM25Okapi, float]],
    queries: list[list[str]],
    *,
    top_k: int,
    query_field_weights: list[list[float]] | None = None,
) -> list[list[tuple[int, float]]]:
    """Score a query batch after one filtered-postings scan per BM25 field."""

    if not weighted_indexes:
        return [[] for _query in queries]
    if query_field_weights is not None:
        if len(query_field_weights) != len(queries):
            raise ValueError("query field weights must match the query count")
        if any(len(weights) != len(weighted_indexes) for weights in query_field_weights):
            raise ValueError("query field weights must match the sparse field count")
    wanted_terms = {term for query in queries for term in query}
    field_postings: list[dict[str, tuple[np.ndarray, np.ndarray]]] = []
    for index, _weight in weighted_indexes:
        raw: dict[str, tuple[list[int], list[float]]] = {
            term: ([], []) for term in wanted_terms if index.idf.get(term)
        }
        if raw:
            for document_index, frequencies in enumerate(index.doc_freqs):
                for term, frequency in frequencies.items():
                    posting = raw.get(term)
                    if posting is not None:
                        posting[0].append(document_index)
                        posting[1].append(float(frequency))
        field_postings.append({
            term: (
                np.asarray(document_indexes, dtype=np.int64),
                np.asarray(frequencies, dtype=float),
            )
            for term, (document_indexes, frequencies) in raw.items()
        })

    corpus_size = int(weighted_indexes[0][0].corpus_size)
    output: list[list[tuple[int, float]]] = []
    for query_index, query in enumerate(queries):
        scores = np.zeros(corpus_size, dtype=float)
        counts = Counter(query)
        for field_index, ((index, configured_weight), postings) in enumerate(
            zip(weighted_indexes, field_postings)
        ):
            weight = (
                query_field_weights[query_index][field_index]
                if query_field_weights is not None
                else configured_weight
            )
            if weight == 0:
                continue
            document_lengths = np.asarray(index.doc_len, dtype=float)
            for term, multiplicity in counts.items():
                posting = postings.get(term)
                if posting is None:
                    continue
                document_indexes, frequencies = posting
                denominator = frequencies + index.k1 * (
                    1 - index.b
                    + index.b * document_lengths[document_indexes] / index.avgdl
                )
                scores[document_indexes] += (
                    weight
                    * multiplicity
                    * float(index.idf.get(term) or 0.0)
                    * frequencies
                    * (index.k1 + 1)
                    / denominator
                )
        ranked = _top_k_indices(scores, top_k)
        output.append([(index, float(scores[index])) for index in ranked])
    return output


class SparseBM25Index:
    """Checksum-verifiable persistence boundary for the rank_bm25 state."""

    artifact_format = "slotrag-rank-bm25-pickle-v1"
    engine = "rank_bm25.BM25Okapi"
    engine_version = RANK_BM25_VERSION

    def __init__(self, index: BM25Okapi, *, passage_count: int) -> None:
        self._index = index
        self.passage_count = passage_count

    @classmethod
    def build(cls, passages: Iterable[Passage]) -> "SparseBM25Index":
        values = list(passages)
        return cls(
            BM25Okapi([tokenize(passage.text) for passage in values]),
            passage_count=len(values),
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        expected_passage_count: int,
        expected_sha256: str,
    ) -> "SparseBM25Index":
        source = Path(path)
        actual_sha256 = cls._sha256(source)
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"sparse index checksum mismatch: expected {expected_sha256}, got {actual_sha256}"
            )
        try:
            with source.open("rb") as handle:
                payload = pickle.load(handle)  # noqa: S301 - checksum-verified local artifact
        except (pickle.UnpicklingError, EOFError, AttributeError, ImportError, IndexError, TypeError) as exc:
            raise ValueError("sparse index artifact could not be decoded") from exc
        if not isinstance(payload, dict):
            raise ValueError("sparse index artifact must contain an object")
        if payload.get("artifact_format") != cls.artifact_format:
            raise ValueError("sparse index artifact format mismatch")
        if payload.get("engine") != cls.engine:
            raise ValueError("sparse index engine mismatch")
        if payload.get("engine_version") != cls.engine_version:
            raise ValueError("sparse index engine version mismatch")
        passage_count = int(payload.get("passage_count") or 0)
        if passage_count != expected_passage_count:
            raise ValueError(
                f"sparse index passage count mismatch: expected {expected_passage_count}, got {passage_count}"
            )
        index = payload.get("index")
        if not isinstance(index, BM25Okapi) or int(getattr(index, "corpus_size", -1)) != passage_count:
            raise ValueError("sparse index payload is not a compatible BM25Okapi index")
        return cls(index, passage_count=passage_count)

    def save(self, path: str | Path) -> str:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".part",
        )
        part_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                pickle.dump({
                    "artifact_format": self.artifact_format,
                    "engine": self.engine,
                    "engine_version": self.engine_version,
                    "passage_count": self.passage_count,
                    "index": self._index,
                }, handle, protocol=pickle.HIGHEST_PROTOCOL)
                handle.flush()
                os.fsync(handle.fileno())
            digest = self._sha256(part_path)
            os.replace(part_path, destination)
            return digest
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            part_path.unlink(missing_ok=True)
            raise

    def get_scores(self, query_tokens: list[str]) -> np.ndarray:
        return self._index.get_scores(query_tokens)

    def batch_top_k(
        self,
        queries: list[list[str]],
        *,
        top_k: int,
        access_modes: list[SparseAccessMode] | None = None,
    ) -> list[list[tuple[int, float]]]:
        if access_modes is not None and len(access_modes) != len(queries):
            raise ValueError("sparse access modes must match the query count")
        if access_modes is not None and any(
            mode not in SPARSE_ACCESS_MODES for mode in access_modes
        ):
            raise ValueError("unsupported sparse access mode")
        return _batch_bm25_top_k([(self._index, 1.0)], queries, top_k=top_k)


class FieldedSparseBM25Index:
    """A compact BM25F-style index over document title and passage body."""

    artifact_format = "slotrag-fielded-rank-bm25-pickle-v1"
    engine = "rank_bm25.BM25Okapi(title+body)"
    engine_version = RANK_BM25_VERSION

    def __init__(
        self,
        body_index: BM25Okapi,
        title_index: BM25Okapi,
        *,
        passage_count: int,
        title_weight: float,
    ) -> None:
        self._body_index = body_index
        self._title_index = title_index
        self.passage_count = passage_count
        self.title_weight = title_weight

    @staticmethod
    def _title(passage: Passage) -> str:
        metadata_title = passage.metadata.get("doc_id")
        if metadata_title:
            return str(metadata_title)
        doc_id = passage.doc_id or passage.id
        return str(doc_id).split(":", 1)[-1]

    @classmethod
    def build(
        cls,
        passages: Iterable[Passage],
        *,
        title_weight: float = 2.0,
    ) -> "FieldedSparseBM25Index":
        values = list(passages)
        if not values:
            raise ValueError("fielded sparse index requires at least one passage")
        return cls(
            BM25Okapi([tokenize(passage.text) for passage in values]),
            BM25Okapi([tokenize(cls._title(passage)) for passage in values]),
            passage_count=len(values),
            title_weight=title_weight,
        )

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        expected_passage_count: int,
        expected_sha256: str,
    ) -> "FieldedSparseBM25Index":
        source = Path(path)
        actual_sha256 = SparseBM25Index._sha256(source)
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"sparse index checksum mismatch: expected {expected_sha256}, got {actual_sha256}"
            )
        try:
            with source.open("rb") as handle:
                payload = pickle.load(handle)  # noqa: S301 - checksum-verified local artifact
        except (pickle.UnpicklingError, EOFError, AttributeError, ImportError, IndexError, TypeError) as exc:
            raise ValueError("fielded sparse index artifact could not be decoded") from exc
        if not isinstance(payload, dict) or payload.get("artifact_format") != cls.artifact_format:
            raise ValueError("fielded sparse index artifact format mismatch")
        if payload.get("engine") != cls.engine or payload.get("engine_version") != cls.engine_version:
            raise ValueError("fielded sparse index engine mismatch")
        passage_count = int(payload.get("passage_count") or 0)
        if passage_count != expected_passage_count:
            raise ValueError(
                f"sparse index passage count mismatch: expected {expected_passage_count}, got {passage_count}"
            )
        body_index = payload.get("body_index")
        title_index = payload.get("title_index")
        if not all(
            isinstance(index, BM25Okapi)
            and int(getattr(index, "corpus_size", -1)) == passage_count
            for index in (body_index, title_index)
        ):
            raise ValueError("fielded sparse index payload is incompatible")
        return cls(
            body_index,
            title_index,
            passage_count=passage_count,
            title_weight=float(payload.get("title_weight") or 0.0),
        )

    def save(self, path: str | Path) -> str:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".part",
        )
        part_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                pickle.dump({
                    "artifact_format": self.artifact_format,
                    "engine": self.engine,
                    "engine_version": self.engine_version,
                    "passage_count": self.passage_count,
                    "title_weight": self.title_weight,
                    "body_index": self._body_index,
                    "title_index": self._title_index,
                }, handle, protocol=pickle.HIGHEST_PROTOCOL)
                handle.flush()
                os.fsync(handle.fileno())
            digest = SparseBM25Index._sha256(part_path)
            os.replace(part_path, destination)
            return digest
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            part_path.unlink(missing_ok=True)
            raise

    def get_scores(self, query_tokens: list[str]) -> np.ndarray:
        return (
            self._body_index.get_scores(query_tokens)
            + self.title_weight * self._title_index.get_scores(query_tokens)
        )

    def batch_top_k(
        self,
        queries: list[list[str]],
        *,
        top_k: int,
        access_modes: list[SparseAccessMode] | None = None,
    ) -> list[list[tuple[int, float]]]:
        modes = access_modes or ["configured"] * len(queries)
        if len(modes) != len(queries):
            raise ValueError("sparse access modes must match the query count")
        if any(mode not in SPARSE_ACCESS_MODES for mode in modes):
            raise ValueError("unsupported sparse access mode")
        return _batch_bm25_top_k(
            [
                (self._body_index, 1.0),
                (self._title_index, self.title_weight),
            ],
            queries,
            top_k=top_k,
            query_field_weights=[
                [1.0, 0.0] if mode == "body" else [1.0, self.title_weight]
                for mode in modes
            ],
        )


class EmbeddingCache:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self.values: dict[str, list[float]] = {}
        self.hits = 0
        self.misses = 0
        if self.path and self.path.exists():
            try:
                import json
                self.values = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.values = {}

    def get(self, text: str) -> list[float] | None:
        value = self.values.get(hashlib.sha256(text.encode("utf-8")).hexdigest())
        if value is None:
            self.misses += 1
        else:
            self.hits += 1
        return value

    def put(self, text: str, vector: list[float]) -> None:
        self.values[hashlib.sha256(text.encode("utf-8")).hexdigest()] = vector

    def flush(self) -> None:
        if self.path:
            def merge(current: dict[str, list[float]]) -> dict[str, list[float]]:
                current.update(self.values)
                return current

            self.values = locked_update_json(
                self.path,
                merge,
                default={},
                ensure_ascii=True,
                indent=None,
            )

    def snapshot(self) -> tuple[int, int]:
        return self.hits, self.misses


class HybridRetriever:
    def __init__(
        self,
        passages: list[Passage],
        embedding_client: EmbeddingClient | None,
        reranker_client: RerankerClient | None = None,
        *,
        bm25_k: int = 50,
        dense_k: int = 50,
        final_k: int = 10,
        rrf_k: int = 60,
        bm25_weight: float = 0.5,
        dense_weight: float = 0.5,
        rerank_enabled: bool = True,
        cache: EmbeddingCache | None = None,
        dense_enabled: bool = True,
        sparse_index: SparseBM25Index | FieldedSparseBM25Index | None = None,
        sparse_index_mode: str = "body",
        sparse_title_weight: float = 2.0,
    ) -> None:
        self.passages = passages
        self.embedding_client = embedding_client
        self.reranker_client = reranker_client
        self.bm25_k, self.dense_k, self.final_k, self.rrf_k = bm25_k, dense_k, final_k, rrf_k
        self.bm25_weight, self.dense_weight = bm25_weight, dense_weight
        self.rerank_enabled = rerank_enabled
        self.dense_enabled = dense_enabled
        self.cache = cache or EmbeddingCache()
        if sparse_index is not None and sparse_index.passage_count != len(passages):
            raise ValueError("sparse index passage count does not match passages")
        if sparse_index is not None:
            self._bm25 = sparse_index
        elif passages and sparse_index_mode == "bm25f":
            self._bm25 = FieldedSparseBM25Index.build(
                passages,
                title_weight=sparse_title_weight,
            )
        else:
            self._bm25 = SparseBM25Index.build(passages) if passages else None
        self._passage_vectors: list[list[float]] | None = None

    def _ensure_vectors(self) -> list[list[float]]:
        if not self.dense_enabled:
            return []
        if self.embedding_client is None:
            raise RuntimeError("dense retrieval is enabled but no embedding client was provided")
        if self._passage_vectors is None:
            missing = [p.text for p in self.passages if self.cache.get(p.text) is None]
            if missing:
                for start in range(0, len(missing), self.embedding_client.config.batch_size):
                    for text, vector in zip(missing[start:start + self.embedding_client.config.batch_size], self.embedding_client.embed(missing[start:start + self.embedding_client.config.batch_size])):
                        self.cache.put(text, vector)
                self.cache.flush()
            vectors = [self.cache.get(p.text) for p in self.passages]
            if any(vector is None for vector in vectors):
                raise RuntimeError("embedding cache did not produce vectors for all passages")
            self._passage_vectors = [vector for vector in vectors if vector is not None]
        return self._passage_vectors

    def build_index(self) -> None:
        """Materialize the shared passage index before online query timing starts."""
        if self.dense_enabled:
            self._ensure_vectors()

    def save_sparse_index(self, path: str | Path) -> str | None:
        return self._bm25.save(path) if self._bm25 is not None else None

    @staticmethod
    def _cosine(query: list[float], values: list[list[float]]) -> np.ndarray:
        q = np.asarray(query, dtype=float)
        matrix = np.asarray(values, dtype=float)
        q_norm = np.linalg.norm(q)
        norms = np.linalg.norm(matrix, axis=1)
        if q_norm == 0:
            return np.zeros(len(values))
        return (matrix @ q) / np.maximum(norms * q_norm, 1e-12)

    def search(self, query: str, *, top_k: int | None = None) -> list[RetrievalResult]:
        if not self.passages:
            return []
        top_k = top_k or self.final_k
        candidate_scores: dict[int, dict[str, float]] = defaultdict(dict)
        bm25_ranks: dict[int, int] = {}
        dense_ranks: dict[int, int] = {}
        if self._bm25:
            bm25_scores = self._bm25.get_scores(tokenize(query))
            bm25_order = _top_k_indices(bm25_scores, self.bm25_k)
            bm25_ranks = {index: rank for rank, index in enumerate(bm25_order)}
            for index in bm25_order:
                candidate_scores[int(index)]["bm25"] = float(bm25_scores[index])
        if self.dense_enabled:
            if self.embedding_client is None:
                raise RuntimeError("dense retrieval is enabled but no embedding client was provided")
            query_vector = self.embedding_client.embed(query)[0]
            dense_scores = self._cosine(query_vector, self._ensure_vectors())
            dense_order = _top_k_indices(dense_scores, self.dense_k)
            dense_ranks = {index: rank for rank, index in enumerate(dense_order)}
            for index in dense_order:
                candidate_scores[int(index)]["dense"] = float(dense_scores[index])
        ranked = []
        for index, scores in candidate_scores.items():
            score = 0.0
            if "bm25" in scores:
                score += self.bm25_weight / (self.rrf_k + 1 + bm25_ranks[index])
            if "dense" in scores:
                score += self.dense_weight / (self.rrf_k + 1 + dense_ranks[index])
            ranked.append(RetrievalResult(passage=self.passages[index], score=score, bm25_score=scores.get("bm25"), dense_score=scores.get("dense")))
        ranked.sort(key=lambda result: result.score, reverse=True)
        ranked = ranked[:max(top_k, self.reranker_client.config.top_n if self.rerank_enabled and self.reranker_client else top_k)]
        if self.rerank_enabled and self.reranker_client:
            reranked = self.reranker_client.rerank(query, [result.passage.text for result in ranked], top_n=top_k)
            by_index = {item.index: item for item in reranked}
            ranked = [ranked[item.index].model_copy(update={"score": item.score, "rerank_score": item.score}) for item in reranked if item.index in by_index]
        return ranked[:top_k]

    def search_batch(
        self,
        queries: list[str],
        *,
        top_k: int | None = None,
        sparse_access_modes: list[SparseAccessMode] | None = None,
    ) -> list[list[RetrievalResult]]:
        """Execute sparse-only batches with one filtered inverted-index scan."""

        modes = sparse_access_modes or ["configured"] * len(queries)
        if len(modes) != len(queries):
            raise ValueError("sparse access modes must match the query count")
        if any(mode not in SPARSE_ACCESS_MODES for mode in modes):
            raise ValueError("unsupported sparse access mode")
        if not queries:
            return []
        if self.dense_enabled or (self.rerank_enabled and self.reranker_client):
            if any(mode != "configured" for mode in modes):
                raise ValueError(
                    "heterogeneous sparse access modes require sparse-only retrieval"
                )
            return [self.search(query, top_k=top_k) for query in queries]
        if not self.passages or self._bm25 is None:
            return [[] for _query in queries]
        output_k = top_k or self.final_k
        candidate_k = min(self.bm25_k, len(self.passages))
        rankings = self._bm25.batch_top_k(
            [tokenize(query) for query in queries],
            top_k=candidate_k,
            access_modes=modes,
        )
        output: list[list[RetrievalResult]] = []
        for ranked in rankings:
            results = [
                RetrievalResult(
                    passage=self.passages[index],
                    score=self.bm25_weight / (self.rrf_k + 1 + rank),
                    bm25_score=bm25_score,
                )
                for rank, (index, bm25_score) in enumerate(ranked)
            ]
            output.append(results[:output_k])
        return output
