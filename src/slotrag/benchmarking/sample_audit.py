"""Read-only provenance audit for persisted benchmark samples."""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from ..data import load_questions
from .datasets import DatasetSpec, _record_id, iter_jsonl


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _excluded_ids(sample_dirs: Sequence[Path], dataset: str) -> set[str]:
    excluded: set[str] = set()
    for directory in sample_dirs:
        for path in sorted(directory.rglob(f"{dataset}.jsonl")):
            excluded.update(question.id for question in load_questions(path))
    return excluded


def audit_existing_samples(
    *,
    benchmark_root: Path,
    dataset_specs: Mapping[str, DatasetSpec],
    datasets: Iterable[str],
    split: str,
    expected_size: int,
    seed: int,
    sample_dir: Path,
    excluded_sample_dirs: Sequence[Path] = (),
) -> dict[str, object]:
    """Verify persisted samples against the declared public-data split."""
    dataset_reports: dict[str, dict[str, object]] = {}
    for dataset in datasets:
        spec = dataset_specs[dataset]
        source_path = spec.path(benchmark_root, split)
        sample_path = sample_dir / f"{dataset}.jsonl"
        source_ids = {
            _record_id(record, index)
            for index, record in iter_jsonl(source_path)
        }
        questions = load_questions(sample_path)
        selected_ids = [question.id for question in questions]
        id_counts = Counter(selected_ids)
        duplicate_ids = sorted(question_id for question_id, count in id_counts.items() if count > 1)
        missing_ids = sorted(set(selected_ids) - source_ids)
        metadata_mismatch_ids = sorted({
            question.id
            for question in questions
            if question.metadata.get("dataset") != dataset
            or question.metadata.get("split") != split
        })
        excluded = _excluded_ids(excluded_sample_dirs, dataset)
        overlap_ids = sorted(set(selected_ids) & excluded)
        selected_strata = Counter(str(question.metadata.get("stratum", "unknown")) for question in questions)
        valid = not any((
            len(questions) != expected_size,
            duplicate_ids,
            missing_ids,
            metadata_mismatch_ids,
            overlap_ids,
        ))
        dataset_reports[dataset] = {
            "source": str(source_path),
            "source_sha256": _sha256(source_path),
            "source_records": len(source_ids),
            "sample": str(sample_path),
            "sample_sha256": _sha256(sample_path),
            "expected_records": expected_size,
            "selected_records": len(questions),
            "selected_ids": selected_ids,
            "selected_strata": dict(sorted(selected_strata.items())),
            "duplicate_ids": duplicate_ids,
            "missing_from_source_ids": missing_ids,
            "metadata_mismatch_ids": metadata_mismatch_ids,
            "excluded_from": [str(path) for path in excluded_sample_dirs],
            "overlap_ids": overlap_ids,
            "overlap_count": len(overlap_ids),
            "valid": valid,
        }

    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "split": split,
        "sample_size": expected_size,
        "seed": seed,
        "sample_dir": str(sample_dir),
        "excluded_sample_dirs": [str(path) for path in excluded_sample_dirs],
        "datasets": dataset_reports,
        "all_overlap_count": sum(len(report["overlap_ids"]) for report in dataset_reports.values()),
        "all_missing_from_source_count": sum(
            len(report["missing_from_source_ids"])
            for report in dataset_reports.values()
        ),
        "all_duplicate_count": sum(len(report["duplicate_ids"]) for report in dataset_reports.values()),
        "all_metadata_mismatch_count": sum(
            len(report["metadata_mismatch_ids"])
            for report in dataset_reports.values()
        ),
        "valid": all(bool(report["valid"]) for report in dataset_reports.values()),
    }
