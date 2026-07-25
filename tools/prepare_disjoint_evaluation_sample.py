#!/usr/bin/env python3
"""Prepare a stratified evaluation sample disjoint from a prior sample directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import heapq
from collections import Counter
from pathlib import Path
from typing import Any

from slotrag.benchmarking.datasets import DATASETS, _allocate_quotas, adapt_record, iter_jsonl
from slotrag.data import normalize_jsonl, sha256_file


def _record_id(record: dict[str, Any], index: int) -> str:
    return str(record.get("id") or record.get("_id") or f"q-{index}")


def _load_ids(path: Path) -> set[str]:
    return {
        str(json.loads(line)["id"])
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def select_disjoint(
    dataset: str,
    benchmark_root: Path,
    source_sample: Path,
    output_sample: Path,
    *,
    split: str,
    size: int,
    seed: int,
) -> dict[str, Any]:
    spec = DATASETS[dataset]
    excluded = _load_ids(source_sample)
    available: dict[str, list[tuple[int, str, dict[str, Any]]]] = {}
    for index, record in iter_jsonl(spec.path(benchmark_root, split)):
        record_id = _record_id(record, index)
        if record_id in excluded:
            continue
        available.setdefault(spec.stratifier(record), []).append((index, record_id, record))
    quotas = _allocate_quotas(Counter({key: len(value) for key, value in available.items()}), size)
    selected: list[tuple[int, str, dict[str, Any]]] = []
    for stratum, records in available.items():
        quota = quotas[stratum]
        heap: list[tuple[int, str, int, dict[str, Any]]] = []
        for index, record_id, record in records:
            score = int.from_bytes(
                hashlib.sha256(f"{seed}:disjoint:{dataset}:{record_id}".encode()).digest(),
                "big",
            )
            item = (-score, record_id, index, record)
            if len(heap) < quota:
                heapq.heappush(heap, item)
            elif item > heap[0]:
                heapq.heapreplace(heap, item)
        selected.extend((index, record_id, record) for _, record_id, index, record in heap)
    selected.sort(key=lambda item: (-int.from_bytes(hashlib.sha256(f"{seed}:disjoint:{dataset}:{item[1]}".encode()).digest(), "big"), item[1]))
    questions = [adapt_record(spec, record, index, split=split) for index, _, record in selected]
    output_sample.parent.mkdir(parents=True, exist_ok=True)
    normalize_jsonl(questions, output_sample)
    chosen = {record_id for _, record_id, _ in selected}
    return {
        "dataset": dataset,
        "split": split,
        "seed": seed,
        "requested": size,
        "selected": len(selected),
        "excluded_count": len(excluded),
        "overlap_count": len(chosen & excluded),
        "source_sample": str(source_sample),
        "source_sha256": sha256_file(source_sample),
        "output_sample": str(output_sample),
        "output_sha256": sha256_file(output_sample),
        "strata": dict(sorted(Counter(q.metadata.get("stratum", "unknown") for q in questions).items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-root", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--split", default="evaluation")
    parser.add_argument("--size", type=int, default=100)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    reports = []
    for dataset in DATASETS:
        report = select_disjoint(
            dataset,
            args.benchmark_root,
            args.source_dir / f"{dataset}.jsonl",
            args.output_dir / f"{dataset}.jsonl",
            split=args.split,
            size=args.size,
            seed=args.seed,
        )
        if report["selected"] != args.size or report["overlap_count"]:
            raise SystemExit(f"invalid disjoint sample: {report}")
        reports.append(report)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    audit = {
        "schema_version": 1,
        "split": args.split,
        "size_per_dataset": args.size,
        "seed": args.seed,
        "source_dir": str(args.source_dir),
        "output_dir": str(args.output_dir),
        "datasets": reports,
        "total_overlap_count": sum(item["overlap_count"] for item in reports),
    }
    (args.output_dir.parent / "disjoint-sample-audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
