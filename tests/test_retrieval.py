from slotrag.models import Passage
from slotrag.retrieval import EmbeddingCache, HybridRetriever


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
