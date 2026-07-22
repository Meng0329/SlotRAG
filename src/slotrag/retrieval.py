from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np
from rank_bm25 import BM25Okapi

from .concurrency import locked_update_json
from .models import Passage, RetrievalResult, Slot
from .providers import EmbeddingClient, RerankerClient


TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


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
        embedding_client: EmbeddingClient,
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
    ) -> None:
        self.passages = passages
        self.embedding_client = embedding_client
        self.reranker_client = reranker_client
        self.bm25_k, self.dense_k, self.final_k, self.rrf_k = bm25_k, dense_k, final_k, rrf_k
        self.bm25_weight, self.dense_weight = bm25_weight, dense_weight
        self.rerank_enabled = rerank_enabled
        self.cache = cache or EmbeddingCache()
        self._bm25 = BM25Okapi([tokenize(p.text) for p in passages]) if passages else None
        self._passage_vectors: list[list[float]] | None = None

    def _ensure_vectors(self) -> list[list[float]]:
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
        self._ensure_vectors()

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
            bm25_order = [int(index) for index in np.argsort(-bm25_scores, kind="stable")[:self.bm25_k]]
            bm25_ranks = {index: rank for rank, index in enumerate(bm25_order)}
            for index in bm25_order:
                candidate_scores[int(index)]["bm25"] = float(bm25_scores[index])
        query_vector = self.embedding_client.embed(query)[0]
        dense_scores = self._cosine(query_vector, self._ensure_vectors())
        dense_order = [int(index) for index in np.argsort(-dense_scores, kind="stable")[:self.dense_k]]
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
