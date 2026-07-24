#!/usr/bin/env python3
"""Prepare deterministic benchmark samples disjoint from prior run samples.

The benchmark runner normally samples by stage size and suite seed.  For a
held-out ablation, that can overlap a larger main-comparison sample.  This
tool applies the same stratified quota policy after excluding question IDs
from one or more prior sample directories, then writes normalized JSONL and a
machine-readable audit beside the samples.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from slotrag.benchmarking.config import BenchmarkSuite
from slotrag.benchmarking.datasets import (
    DATASETS,
    _allocate_quotas,
    _record_id,
    adapt_record,
    iter_jsonl,
)
from slotrag.data import normalize_jsonl


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_excluded(sample_dirs: list[Path], dataset: str) -> set[str]:
    excluded: set[str] = set()
    for directory in sample_dirs:
        for path in sorted(directory.rglob(f"{dataset}.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    excluded.add(str(json.loads(line)["id"]))
    return excluded


def _select_records(spec: Any, source: Path, size: int, seed: int, excluded: set[str]) -> tuple[list[Any], dict[str, Any]]:
    available: dict[str, list[tuple[int, str, int, dict[str, Any]]]] = defaultdict(list)
    source_count = 0
    excluded_count = 0
    for index, record in iter_jsonl(source):
        source_count += 1
        record_id = _record_id(record, index)
        if record_id in excluded:
            excluded_count += 1
            continue
        stratum = spec.stratifier(record)
        score = int.from_bytes(
            hashlib.sha256(f"{seed}:{spec.name}:{record_id}".encode("utf-8")).digest(),
            "big",
        )
        available[stratum].append((score, record_id, index, record))
    counts = {key: len(values) for key, values in available.items()}
    quotas = _allocate_quotas(counts, size)
    selected: list[tuple[int, str, int, dict[str, Any]]] = []
    for stratum, quota in quotas.items():
        selected.extend(sorted(available[stratum], key=lambda item: (item[0], item[1], item[2]))[:quota])
    selected.sort(key=lambda item: (item[0], item[1], item[2]))
    if len(selected) != size:
        raise RuntimeError(
            f"cannot select {size} records from {source}; available={len(selected)} after exclusions"
        )
    records = [adapt_record(spec, record, index, split="evaluation") for _, _, index, record in selected]
    audit = {
        "source": str(source),
        "source_sha256": _sha256(source),
        "source_records": source_count,
        "excluded_records": excluded_count,
        "available_records": source_count - excluded_count,
        "selected_records": len(records),
        "selected_ids": [record.id for record in records],
        "selected_strata": {key: sum(1 for record in records if spec.stratifier(record.model_dump()) == key) for key in quotas},
        "quotas": quotas,
    }
    return records, audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--exclude-sample-dir",
        action="append",
        type=Path,
        default=[],
        help="Directory containing prior stage sample subdirectories; repeatable.",
    )
    args = parser.parse_args()
    suite = BenchmarkSuite.from_yaml(args.suite)
    stage = suite.stage(args.stage)
    if stage.split != "evaluation":
        raise SystemExit("disjoint sample preparation is restricted to evaluation split")
    sample_dir = args.output_dir / "samples" / args.stage
    sample_dir.mkdir(parents=True, exist_ok=True)
    audits: dict[str, Any] = {}
    all_selected: dict[str, set[str]] = {}
    for dataset in suite.datasets:
        spec = DATASETS[dataset]
        source = spec.path(suite.benchmark_root, stage.split)
        excluded = _load_excluded(args.exclude_sample_dir, dataset)
        records, audit = _select_records(spec, source, stage.sample_size, suite.seed, excluded)
        normalize_jsonl(records, sample_dir / f"{dataset}.jsonl")
        selected_ids = {record.id for record in records}
        overlap = sorted(selected_ids & excluded)
        if overlap:
            raise RuntimeError(f"selection overlap for {dataset}: {overlap[:3]}")
        all_selected[dataset] = selected_ids
        audit["excluded_from"] = [str(path) for path in args.exclude_sample_dir]
        audit["overlap_count"] = len(overlap)
        audits[dataset] = audit
    audit_path = args.output_dir / "sample-audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "suite": str(args.suite),
                "stage": args.stage,
                "split": stage.split,
                "sample_size": stage.sample_size,
                "seed": suite.seed,
                "excluded_sample_dirs": [str(path) for path in args.exclude_sample_dir],
                "datasets": audits,
                "all_overlap_count": sum(int(item["overlap_count"]) for item in audits.values()),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"stage": args.stage, "sample_dir": str(sample_dir), "audit": str(audit_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
