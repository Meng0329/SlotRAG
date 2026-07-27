#!/usr/bin/env python3
"""Run a provider-free global-corpus protocol smoke and persist its artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from slotrag.benchmarking.corpus import SharedCorpusIndex
from slotrag.config import RetrievalConfig
from slotrag.models import Passage, QuestionRecord
from slotrag.retrieval import EmbeddingCache


class _FakeEmbedding:
    class _Config:
        batch_size = 8

    config = _Config()

    def embed(self, texts):
        values = [texts] if isinstance(texts, str) else texts
        return [[1.0, 0.0] if "alpha" in value.casefold() else [0.0, 1.0] for value in values]


def run(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    questions = [
        QuestionRecord(
            id="smoke-q1",
            question="What is alpha?",
            passages=[Passage(id="p1", doc_id="doc-alpha", text="Alpha is a river.")],
            gold_evidence=["p1"],
        ),
        QuestionRecord(
            id="smoke-q2",
            question="What is beta?",
            passages=[Passage(id="p2", doc_id="doc-beta", text="Beta is a letter.")],
            gold_evidence=["p2"],
        ),
        QuestionRecord(
            id="smoke-q3",
            question="What is gamma?",
            passages=[Passage(id="p3", doc_id="doc-gamma", text="Gamma is a symbol.")],
            gold_evidence=["p3"],
        ),
    ]
    index = SharedCorpusIndex.from_questions(
        questions,
        dataset="protocol-smoke",
        split="evaluation",
        retrieval=RetrievalConfig(bm25_k=6, dense_k=6, final_k=2, chunk_tokens=64, chunk_overlap=0),
        embedding_client=_FakeEmbedding(),
        reranker_client=None,
        rerank_enabled=False,
        cache=EmbeddingCache(output_dir / "embeddings.json"),
        manifest_path=output_dir / "corpus" / "manifest.json",
    )
    results = index.search("alpha")
    index.persist_manifest()
    summary = {
        "schema_version": 1,
        "protocol": "global_corpus",
        "provider_calls": 0,
        "source_question_count": index.manifest.source_question_count,
        "document_count": index.manifest.document_count,
        "chunk_count": index.manifest.chunk_count,
        "retrieved_ids": [result.passage.id for result in results],
        "retrieved_source_question_ids": [
            result.passage.metadata["source_question_ids"] for result in results
        ],
        "manifest": "corpus/manifest.json",
    }
    (output_dir / "smoke.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("runs/slotrag-global-corpus-protocol-smoke-v55"),
    )
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
