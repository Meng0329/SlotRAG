from slotrag.models import Passage
import numpy as np

from slotrag.retrieval import (
    EmbeddingCache,
    FieldedSparseBM25Index,
    HybridRetriever,
    _top_k_indices,
)


class FakeEmbeddingConfig:
    batch_size = 8


class FakeEmbedding:
    config = FakeEmbeddingConfig()

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        values = [texts] if isinstance(texts, str) else texts
        self.calls.append(list(values))
        return [[1.0, 0.0] if "alpha" in value else [0.0, 1.0] for value in values]


def test_hybrid_retrieval_is_deterministic_without_reranker():
    passages = [Passage(id="p1", text="alpha fact"), Passage(id="p2", text="beta fact")]
    retriever = HybridRetriever(passages, FakeEmbedding(), reranker_client=None, final_k=2, bm25_k=2, dense_k=2, rerank_enabled=False)
    first = [item.passage.id for item in retriever.search("alpha")]
    second = [item.passage.id for item in retriever.search("alpha")]
    assert first == second == ["p1", "p2"]


def test_top_k_selection_avoids_full_sort_and_preserves_stable_ties():
    scores = np.asarray([1.0, 3.0, 3.0, 2.0, 0.0])

    assert _top_k_indices(scores, 3) == [1, 2, 3]
    assert _top_k_indices(scores, 10) == [1, 2, 3, 0, 4]
    assert _top_k_indices(np.asarray([3.0, 2.0, 2.0, 2.0]), 2) == [0, 1]


def test_sparse_batch_search_matches_individual_rankings():
    passages = [
        Passage(id="p1", doc_id="Alpha", text="alpha beta"),
        Passage(id="p2", doc_id="Beta", text="beta gamma"),
        Passage(id="p3", doc_id="Gamma", text="gamma delta"),
        Passage(id="p4", doc_id="Delta", text="delta epsilon"),
        Passage(id="p5", doc_id="Epsilon", text="epsilon alpha"),
    ]
    for mode in ("body", "bm25f"):
        retriever = HybridRetriever(
            passages,
            embedding_client=None,
            reranker_client=None,
            bm25_k=4,
            final_k=3,
            dense_enabled=False,
            rerank_enabled=False,
            sparse_index_mode=mode,
            sparse_title_weight=2.0,
        )
        queries = ["alpha", "beta gamma", "missing"]

        individual = [retriever.search(query, top_k=3) for query in queries]
        batched = retriever.search_batch(queries, top_k=3)

        assert [
            [(item.passage.id, item.score, item.bm25_score) for item in ranked]
            for ranked in batched
        ] == [
            [(item.passage.id, item.score, item.bm25_score) for item in ranked]
            for ranked in individual
        ]


def test_hybrid_retriever_builds_passage_index_before_query():
    embedding = FakeEmbedding()
    passages = [Passage(id="p1", text="alpha fact"), Passage(id="p2", text="beta fact")]
    retriever = HybridRetriever(passages, embedding, reranker_client=None, rerank_enabled=False)

    retriever.build_index()
    assert embedding.calls == [["alpha fact", "beta fact"]]

    retriever.search("alpha")
    assert embedding.calls == [["alpha fact", "beta fact"], ["alpha"]]


def test_bm25_only_retrieval_does_not_call_embedding_client():
    embedding = FakeEmbedding()
    passages = [Passage(id="p1", text="alpha fact"), Passage(id="p2", text="beta fact")]
    retriever = HybridRetriever(
        passages,
        embedding_client=None,
        reranker_client=None,
        final_k=2,
        bm25_k=2,
        dense_k=0,
        rerank_enabled=False,
        dense_enabled=False,
    )

    retriever.build_index()
    results = retriever.search("alpha")

    assert [item.passage.id for item in results] == ["p1", "p2"]
    assert embedding.calls == []


def test_embedding_cache_flush_merges_entries_from_concurrent_instances(tmp_path):
    path = tmp_path / "embeddings.json"
    first = EmbeddingCache(path)
    second = EmbeddingCache(path)

    first.put("alpha", [1.0, 0.0])
    second.put("beta", [0.0, 1.0])
    first.flush()
    second.flush()

    merged = EmbeddingCache(path)
    assert merged.get("alpha") == [1.0, 0.0]
    assert merged.get("beta") == [0.0, 1.0]


def test_fielded_sparse_index_promotes_title_matches_and_round_trips(tmp_path):
    passages = [
        Passage(id="target", doc_id="Xylophone", text="A musical instrument reference."),
        Passage(id="body", doc_id="Unrelated", text="xylophone xylophone in the body."),
        Passage(id="d2", doc_id="Other Two", text="A separate document."),
        Passage(id="d3", doc_id="Other Three", text="Another separate document."),
        Passage(id="d4", doc_id="Other Four", text="Yet another document."),
    ]
    index = FieldedSparseBM25Index.build(passages, title_weight=4.0)

    scores = index.get_scores(["xylophone"])
    assert scores[0] > scores[1]

    path = tmp_path / "bm25f.pkl"
    checksum = index.save(path)
    restored = FieldedSparseBM25Index.load(
        path,
        expected_passage_count=len(passages),
        expected_sha256=checksum,
    )
    assert restored.title_weight == 4.0
    assert restored.get_scores(["xylophone"]).tolist() == scores.tolist()
