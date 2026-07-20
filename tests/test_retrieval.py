from slotrag.models import Passage
from slotrag.retrieval import HybridRetriever


class FakeEmbeddingConfig:
    batch_size = 8


class FakeEmbedding:
    config = FakeEmbeddingConfig()

    def embed(self, texts):
        values = [texts] if isinstance(texts, str) else texts
        return [[1.0, 0.0] if "alpha" in value else [0.0, 1.0] for value in values]


def test_hybrid_retrieval_is_deterministic_without_reranker():
    passages = [Passage(id="p1", text="alpha fact"), Passage(id="p2", text="beta fact")]
    retriever = HybridRetriever(passages, FakeEmbedding(), reranker_client=None, final_k=2, bm25_k=2, dense_k=2, rerank_enabled=False)
    first = [item.passage.id for item in retriever.search("alpha")]
    second = [item.passage.id for item in retriever.search("alpha")]
    assert first == second == ["p1", "p2"]
