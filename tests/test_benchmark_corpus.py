import json

import pytest

from slotrag.benchmarking.corpus import (
    CorpusBuildCostError,
    SharedCorpusIndex,
    _aggregate_passages,
    estimate_corpus_build,
)
from slotrag.config import RetrievalConfig
from slotrag.models import Passage, QuestionRecord
from slotrag.retrieval import EmbeddingCache, SparseBM25Index


class _FakeEmbeddingConfig:
    batch_size = 8


class _FakeEmbedding:
    config = _FakeEmbeddingConfig()

    def embed(self, texts):
        values = [texts] if isinstance(texts, str) else texts
        return [[1.0, 0.0] if "alpha" in value.lower() else [0.0, 1.0] for value in values]


class _CountingEmbedding(_FakeEmbedding):
    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return super().embed(texts)


def test_shared_corpus_aggregates_full_split_and_records_query_telemetry(tmp_path):
    questions = [
        QuestionRecord(
            id="q1",
            question="What is alpha?",
            passages=[Passage(id="p1", doc_id="d1", text="Alpha is a river.")],
            gold_evidence=["p1"],
        ),
        QuestionRecord(
            id="q2",
            question="What is beta?",
            passages=[Passage(id="p2", doc_id="d2", text="Beta is a letter.")],
            gold_evidence=["p2"],
        ),
    ]

    index = SharedCorpusIndex.from_questions(
        questions,
        dataset="toy",
        split="train",
        retrieval=RetrievalConfig(bm25_k=4, dense_k=4, final_k=2, chunk_tokens=32, chunk_overlap=0),
        embedding_client=_FakeEmbedding(),
        reranker_client=None,
        rerank_enabled=False,
        cache=EmbeddingCache(tmp_path / "embeddings.json"),
        manifest_path=tmp_path / "corpus" / "manifest.json",
    )

    assert index.manifest.protocol == "global_corpus"
    assert index.manifest.source_question_count == 2
    assert index.manifest.document_count == 2
    assert index.manifest.chunk_count == 2
    assert {passage.metadata["evidence_scope"] for passage in index.passages} == {"available"}
    assert all("gold_evidence" not in passage.metadata for passage in index.passages)

    results = index.search("alpha")
    assert results
    assert results[0].passage.metadata["source_question_ids"] == ["q1"]
    index.persist_manifest()

    manifest = json.loads((tmp_path / "corpus" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["query_count"] == 1
    assert manifest["query_latency_ms"] >= 0
    assert manifest["index_bytes"] > 0


def test_shared_corpus_builds_and_reuses_bm25f_index(tmp_path):
    questions = [
        QuestionRecord(
            id="q1",
            question="What is Xylophone?",
            passages=[
                Passage(id="p1", doc_id="Xylophone", text="A musical instrument reference."),
                Passage(id="p2", doc_id="Unrelated", text="xylophone xylophone in the body."),
                Passage(id="p3", doc_id="Third", text="A separate document."),
                Passage(id="p4", doc_id="Fourth", text="Another document."),
                Passage(id="p5", doc_id="Fifth", text="One more document."),
            ],
        )
    ]
    retrieval = RetrievalConfig(
        bm25_k=5,
        dense_k=5,
        final_k=2,
        chunk_tokens=32,
        chunk_overlap=0,
        sparse_index_mode="bm25f",
        sparse_title_weight=4.0,
    )

    first = SharedCorpusIndex.from_questions(
        questions,
        dataset="toy",
        split="train",
        retrieval=retrieval,
        embedding_client=None,
        reranker_client=None,
        rerank_enabled=False,
        retrieval_backend="bm25",
        index_dir=tmp_path / "index",
    )
    second = SharedCorpusIndex.from_questions(
        questions,
        dataset="toy",
        split="train",
        retrieval=retrieval,
        embedding_client=None,
        reranker_client=None,
        rerank_enabled=False,
        retrieval_backend="bm25",
        index_dir=tmp_path / "index",
    )

    assert first.manifest.sparse_index_mode == "bm25f"
    assert first.search("xylophone")[0].passage.metadata["source_passage_id"] == "p1"
    assert second.manifest.reused_persisted_index is True


def test_shared_corpus_batch_search_counts_logical_queries(tmp_path):
    questions = [
        QuestionRecord(
            id="q1",
            question="What is alpha?",
            passages=[
                Passage(id="p1", doc_id="Alpha", text="Alpha is a river."),
                Passage(id="p2", doc_id="Beta", text="Beta is a letter."),
            ],
        )
    ]
    index = SharedCorpusIndex.from_questions(
        questions,
        dataset="toy",
        split="train",
        retrieval=RetrievalConfig(
            bm25_k=2,
            dense_k=1,
            final_k=2,
            chunk_tokens=32,
            chunk_overlap=0,
        ),
        embedding_client=None,
        reranker_client=None,
        rerank_enabled=False,
        retrieval_backend="bm25",
        index_dir=tmp_path / "index",
    )

    rankings = index.search_batch(
        ["alpha", "beta"],
        top_k=1,
        sparse_access_modes=["body", "configured"],
    )

    assert len(rankings) == 2
    assert all(len(ranked) == 1 for ranked in rankings)
    assert index.stats_snapshot()[0] == 2


def test_shared_corpus_reuses_persisted_artifacts_without_reembedding(tmp_path):
    questions = [
        QuestionRecord(
            id="q1",
            question="What is alpha?",
            passages=[Passage(id="p1", doc_id="d1", text="Alpha is a river.")],
            gold_evidence=["p1"],
        )
    ]
    retrieval = RetrievalConfig(bm25_k=4, dense_k=4, final_k=2, chunk_tokens=32, chunk_overlap=0)
    first_embedding = _CountingEmbedding()
    first = SharedCorpusIndex.from_questions(
        questions,
        dataset="toy",
        split="train",
        retrieval=retrieval,
        embedding_client=first_embedding,
        reranker_client=None,
        rerank_enabled=False,
        index_dir=tmp_path / "index",
    )
    assert first.manifest.reused_persisted_index is False
    assert first_embedding.calls == 1

    second_embedding = _CountingEmbedding()
    second = SharedCorpusIndex.from_questions(
        questions,
        dataset="toy",
        split="train",
        retrieval=retrieval,
        embedding_client=second_embedding,
        reranker_client=None,
        rerank_enabled=False,
        index_dir=tmp_path / "index",
    )
    assert second.manifest.reused_persisted_index is True
    assert second_embedding.calls == 0
    assert second.search("alpha")
    assert second_embedding.calls == 1


def test_shared_corpus_accumulates_duplicate_provenance_without_copying_each_occurrence(monkeypatch):
    shared = Passage(id="p1", doc_id="d1", text="Alpha is shared evidence.")
    questions = [
        QuestionRecord(id=f"q{index:03d}", question="What is alpha?", passages=[shared])
        for index in range(100)
    ]

    def fail_model_copy(*_args, **_kwargs):
        raise AssertionError("duplicate provenance must not copy the Passage on every occurrence")

    monkeypatch.setattr(Passage, "model_copy", fail_model_copy)

    passages = _aggregate_passages(
        questions,
        dataset="toy",
        chunk_tokens=32,
        chunk_overlap=0,
    )

    assert len(passages) == 1
    assert passages[0].metadata["source_question_ids"] == [f"q{index:03d}" for index in range(100)]


def test_bm25_shared_corpus_reuses_checksum_verified_sparse_index(tmp_path, monkeypatch):
    questions = [
        QuestionRecord(
            id="q1",
            question="What is alpha?",
            passages=[
                Passage(id="p1", doc_id="d1", text="Alpha is a river."),
                Passage(id="p2", doc_id="d2", text="Beta is a letter."),
            ],
        )
    ]
    retrieval = RetrievalConfig(bm25_k=4, dense_k=4, final_k=2, chunk_tokens=32, chunk_overlap=0)
    first = SharedCorpusIndex.from_questions(
        questions,
        dataset="toy",
        split="train",
        retrieval=retrieval,
        embedding_client=None,
        reranker_client=None,
        rerank_enabled=False,
        retrieval_backend="bm25",
        index_dir=tmp_path / "index",
    )
    first_results = first.search("alpha")

    assert first.manifest.reused_persisted_index is False
    assert first.manifest.sparse_index_reused is False
    assert first.manifest.sparse_index_artifact == "bm25.pkl"
    assert len(first.manifest.sparse_index_sha256 or "") == 64
    assert first.manifest.index_storage == "json+bm25"
    assert (tmp_path / "index" / "bm25.pkl").exists()

    def fail_build(cls, passages):
        raise AssertionError(f"warm reuse rebuilt BM25 for {len(passages)} passages")

    monkeypatch.setattr(SparseBM25Index, "build", classmethod(fail_build))
    second = SharedCorpusIndex.from_questions(
        questions,
        dataset="toy",
        split="train",
        retrieval=retrieval,
        embedding_client=None,
        reranker_client=None,
        rerank_enabled=False,
        retrieval_backend="bm25",
        index_dir=tmp_path / "index",
    )
    second_results = second.search("alpha")

    assert second.manifest.reused_persisted_index is True
    assert second.manifest.sparse_index_reused is True
    assert [result.passage.id for result in second_results] == [
        result.passage.id for result in first_results
    ]
    assert [result.bm25_score for result in second_results] == [
        result.bm25_score for result in first_results
    ]


def test_bm25_shared_corpus_rebuilds_a_corrupted_sparse_index(tmp_path, monkeypatch):
    questions = [
        QuestionRecord(
            id="q1",
            question="What is alpha?",
            passages=[Passage(id="p1", doc_id="d1", text="Alpha is a river.")],
        )
    ]
    retrieval = RetrievalConfig(chunk_tokens=32, chunk_overlap=0)
    SharedCorpusIndex.from_questions(
        questions,
        dataset="toy",
        split="train",
        retrieval=retrieval,
        embedding_client=None,
        reranker_client=None,
        rerank_enabled=False,
        retrieval_backend="bm25",
        index_dir=tmp_path / "index",
    )
    (tmp_path / "index" / "bm25.pkl").write_bytes(b"corrupted")

    original_build = SparseBM25Index.build.__func__
    build_calls = 0

    def count_build(cls, passages):
        nonlocal build_calls
        build_calls += 1
        return original_build(cls, passages)

    monkeypatch.setattr(SparseBM25Index, "build", classmethod(count_build))
    rebuilt = SharedCorpusIndex.from_questions(
        questions,
        dataset="toy",
        split="train",
        retrieval=retrieval,
        embedding_client=None,
        reranker_client=None,
        rerank_enabled=False,
        retrieval_backend="bm25",
        index_dir=tmp_path / "index",
    )

    assert build_calls == 1
    assert rebuilt.manifest.reused_persisted_index is False
    assert rebuilt.manifest.passage_artifact_reused is True
    assert rebuilt.manifest.sparse_index_reused is False
    assert rebuilt.manifest.reuse_reason == "sparse_index_invalid:ValueError"
    assert len(rebuilt.manifest.sparse_index_sha256 or "") == 64
    assert rebuilt.search("alpha")


def test_shared_corpus_cost_gate_runs_before_embedding_calls(tmp_path):
    questions = [
        QuestionRecord(
            id="q1",
            question="What is alpha?",
            passages=[Passage(id="p1", doc_id="d1", text="Alpha is a river.")],
        )
    ]
    retrieval = RetrievalConfig(chunk_tokens=32, chunk_overlap=0)
    estimate = estimate_corpus_build(
        questions,
        dataset="toy",
        retrieval=retrieval,
        embedding_batch_size=1,
        operational_rpm=2,
    )
    assert estimate["embedding_batches"] == 1
    assert estimate["lower_bound_minutes"] == pytest.approx(0.5)

    embedding = _CountingEmbedding()
    with pytest.raises(CorpusBuildCostError):
        SharedCorpusIndex.from_questions(
            questions,
            dataset="toy",
            split="train",
            retrieval=retrieval,
            embedding_client=embedding,
            reranker_client=None,
            rerank_enabled=False,
            index_dir=tmp_path / "blocked-index",
            embedding_batch_size=1,
            operational_rpm=2,
            max_build_minutes=0.25,
        )
    assert embedding.calls == 0
