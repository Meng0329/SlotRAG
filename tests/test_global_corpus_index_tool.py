import json
from pathlib import Path

import pytest

from slotrag.benchmarking.datasets import DATASETS, DatasetSpec
from slotrag.config import RetrievalConfig
from tools.build_global_corpus_index import build_global_index


def test_global_index_tool_preserves_immutable_cold_and_warm_reports(tmp_path, monkeypatch):
    repository_root = Path(__file__).resolve().parents[1]
    spec = DatasetSpec(
        name="toy",
        train_file="toy/train.jsonl",
        evaluation_file="toy/evaluation.jsonl",
        primary_metric="f1",
        stratifier=lambda record: str(record.get("type") or "unknown"),
    )
    monkeypatch.setitem(DATASETS, "toy", spec)
    dataset_path = tmp_path / "benchmark" / spec.train_file
    dataset_path.parent.mkdir(parents=True)
    dataset_path.write_text(
        json.dumps({
            "id": "q1",
            "question": "What is alpha?",
            "passages": [
                {"id": "p1", "doc_id": "d1", "text": "Alpha is a river."},
                {"id": "p2", "doc_id": "d2", "text": "Beta is a letter."},
            ],
        }) + "\n",
        encoding="utf-8",
    )
    index_dir = tmp_path / "index"
    retrieval = RetrievalConfig(chunk_tokens=32, chunk_overlap=0)

    cold = build_global_index(
        dataset="toy",
        split="train",
        benchmark_root=tmp_path / "benchmark",
        index_dir=index_dir,
        report_path=tmp_path / "cold.json",
        mode="cold",
        repository_root=repository_root,
        retrieval=retrieval,
    )
    warm = build_global_index(
        dataset="toy",
        split="train",
        benchmark_root=tmp_path / "benchmark",
        index_dir=index_dir,
        report_path=tmp_path / "warm.json",
        mode="warm",
        repository_root=repository_root,
        retrieval=retrieval,
    )

    assert cold["provider_calls"] == 0
    assert cold["corpus_manifest"]["reused_persisted_index"] is False
    assert warm["corpus_manifest"]["reused_persisted_index"] is True
    assert cold["probe"]["retrieved"] == warm["probe"]["retrieved"]
    assert (tmp_path / "cold.json").exists()
    assert (tmp_path / "warm.json").exists()
    with pytest.raises(FileExistsError, match="immutable report"):
        build_global_index(
            dataset="toy",
            split="train",
            benchmark_root=tmp_path / "benchmark",
            index_dir=index_dir,
            report_path=tmp_path / "warm.json",
            mode="warm",
            repository_root=repository_root,
            retrieval=retrieval,
        )
