import json

from slotrag.benchmarking.corpus import SharedCorpusIndex
from slotrag.config import RetrievalConfig
from slotrag.models import Passage, QuestionRecord
from slotrag.retrieval import EmbeddingCache


class _FakeEmbeddingConfig:
    batch_size = 8


class _FakeEmbedding:
    config = _FakeEmbeddingConfig()

    def embed(self, texts):
        values = [texts] if isinstance(texts, str) else texts
        return [[1.0, 0.0] if "alpha" in value.lower() else [0.0, 1.0] for value in values]


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
