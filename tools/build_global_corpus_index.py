#!/usr/bin/env python3
"""Build or verify a provider-free persistent BM25 global-corpus index."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

from slotrag.benchmarking.corpus import SharedCorpusIndex
from slotrag.benchmarking.datasets import DATASETS, load_all_questions
from slotrag.concurrency import atomic_write_json
from slotrag.config import RetrievalConfig
from slotrag.data import sha256_file


BuildMode = Literal["cold", "warm"]


def _git_state(root: Path) -> dict[str, object]:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {"revision": revision, "dirty": bool(status.strip())}


def _source_checksums(root: Path) -> dict[str, str]:
    relative_paths = (
        "src/slotrag/benchmarking/corpus.py",
        "src/slotrag/benchmarking/datasets.py",
        "src/slotrag/retrieval.py",
        "tools/build_global_corpus_index.py",
    )
    return {path: sha256_file(root / path) for path in relative_paths}


def _combined_checksum(values: dict[str, str]) -> str:
    payload = json.dumps(values, ensure_ascii=True, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_global_index(
    *,
    dataset: str,
    split: str,
    benchmark_root: Path,
    index_dir: Path,
    report_path: Path,
    mode: BuildMode,
    repository_root: Path,
    retrieval: RetrievalConfig | None = None,
    probe_query: str | None = None,
) -> dict[str, object]:
    if dataset not in DATASETS:
        raise ValueError(f"unknown dataset: {dataset}")
    if split not in {"train", "evaluation"}:
        raise ValueError(f"unsupported split: {split}")
    if report_path.exists():
        raise FileExistsError(f"immutable report already exists: {report_path}")

    core_artifacts = tuple(index_dir / name for name in ("manifest.json", "passages.jsonl", "bm25.pkl"))
    if mode == "cold" and any(path.exists() for path in core_artifacts):
        raise FileExistsError(f"cold build refuses to overwrite existing index artifacts: {index_dir}")
    if mode == "warm" and not all(path.exists() for path in core_artifacts):
        raise FileNotFoundError(f"warm build requires a complete persistent index: {index_dir}")

    retrieval = retrieval or RetrievalConfig()
    spec = DATASETS[dataset]
    dataset_path = spec.path(benchmark_root, split)
    if not dataset_path.exists():
        raise FileNotFoundError(f"dataset split does not exist: {dataset_path}")

    wall_started = time.perf_counter()
    load_started = time.perf_counter()
    questions = load_all_questions(spec, benchmark_root, split=split)
    load_latency_ms = (time.perf_counter() - load_started) * 1000

    build_started = time.perf_counter()
    index = SharedCorpusIndex.from_questions(
        questions,
        dataset=dataset,
        split=split,
        retrieval=retrieval,
        embedding_client=None,
        reranker_client=None,
        rerank_enabled=False,
        source_scope="full_split",
        retrieval_backend="bm25",
        index_dir=index_dir,
        reuse_persisted=mode == "warm",
    )
    build_call_latency_ms = (time.perf_counter() - build_started) * 1000

    query_text = probe_query or (questions[0].question if questions else "global corpus probe")
    query_started = time.perf_counter()
    results = index.search(query_text)
    probe_latency_ms = (time.perf_counter() - query_started) * 1000
    index.persist_manifest()

    source_checksums = _source_checksums(repository_root)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    report: dict[str, object] = {
        "schema_version": 1,
        "experiment": "global-corpus-index-v72",
        "mode": mode,
        "protocol": "global_corpus",
        "retrieval_backend": "bm25",
        "provider_calls": 0,
        "dataset": dataset,
        "split": split,
        "dataset_artifact": str(dataset_path),
        "dataset_sha256": sha256_file(dataset_path),
        "source_question_count": len(questions),
        "retrieval_config": retrieval.model_dump(mode="json"),
        "git": _git_state(repository_root),
        "source_checksums": source_checksums,
        "source_fingerprint": _combined_checksum(source_checksums),
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "load_latency_ms": load_latency_ms,
            "build_call_latency_ms": build_call_latency_ms,
            "probe_latency_ms": probe_latency_ms,
            "wall_latency_ms": (time.perf_counter() - wall_started) * 1000,
            "process_max_rss_kb": usage.ru_maxrss,
            "user_cpu_seconds": usage.ru_utime,
            "system_cpu_seconds": usage.ru_stime,
        },
        "probe": {
            "query": query_text,
            "retrieved": [
                {
                    "passage_id": result.passage.id,
                    "score": result.score,
                    "bm25_score": result.bm25_score,
                }
                for result in results
            ],
        },
        "corpus_manifest": index.manifest.model_dump(mode="json"),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(report_path, report, ensure_ascii=False)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=sorted(DATASETS), required=True)
    parser.add_argument("--split", choices=("train", "evaluation"), default="train")
    parser.add_argument("--benchmark-root", type=Path, default=Path("benchmark"))
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--mode", choices=("cold", "warm"), required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--probe-query")
    parser.add_argument("--sparse-index-mode", choices=("body", "bm25f"), default="body")
    parser.add_argument("--sparse-title-weight", type=float, default=2.0)
    args = parser.parse_args()
    report = build_global_index(
        dataset=args.dataset,
        split=args.split,
        benchmark_root=args.benchmark_root,
        index_dir=args.index_dir,
        report_path=args.report,
        mode=args.mode,
        repository_root=args.repository_root,
        probe_query=args.probe_query,
        retrieval=RetrievalConfig(
            sparse_index_mode=args.sparse_index_mode,
            sparse_title_weight=args.sparse_title_weight,
        ),
    )
    manifest = report["corpus_manifest"]
    print(json.dumps({
        "report": str(args.report),
        "dataset": args.dataset,
        "mode": args.mode,
        "chunk_count": manifest["chunk_count"],
        "reused_persisted_index": manifest["reused_persisted_index"],
        "build_latency_ms": manifest["build_latency_ms"],
        "provider_calls": 0,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
