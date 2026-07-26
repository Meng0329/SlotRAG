from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .factorial import _as_float, _holm, _summary


class PairedAnalysisError(ValueError):
    """Raised when a preregistered paired comparison is incomplete."""


def _validated_comparisons(
    comparisons: Iterable[tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    values = list(comparisons)
    if not values:
        raise ValueError("at least one paired comparison is required")
    names = [name for name, _treatment, _reference in values]
    if any(not all(item) for item in values):
        raise ValueError("comparison name, treatment, and reference must be non-empty")
    if len(names) != len(set(names)):
        raise ValueError("comparison names must be unique")
    if any(treatment == reference for _name, treatment, reference in values):
        raise ValueError("treatment and reference must differ")
    return values


def _index_rows(
    rows: Iterable[dict[str, Any]],
    methods: set[str],
) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    indexed: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        dataset = str(row.get("dataset") or "")
        question_id = str(row.get("question_id") or "")
        method = str(row.get("base_method") or row.get("method") or "")
        if method not in methods:
            continue
        if not dataset or not question_id:
            raise PairedAnalysisError("rows must contain dataset and question_id")
        key = (dataset, question_id)
        if method in indexed[key]:
            raise PairedAnalysisError(f"duplicate paired record: {dataset}/{question_id}/{method}")
        indexed[key][method] = row
    if not indexed:
        raise PairedAnalysisError("no preregistered paired records found")
    for (dataset, question_id), method_rows in sorted(indexed.items()):
        missing = sorted(methods - set(method_rows))
        if missing:
            raise PairedAnalysisError(
                f"missing paired records: {dataset}/{question_id}: {', '.join(missing)}"
            )
    return indexed


def _comparison_summary(
    grouped: dict[str, list[float]],
    *,
    metric: str,
    name: str,
    treatment: str,
    reference: str,
    scope: str,
    iterations: int,
    seed: int,
) -> dict[str, Any]:
    row = _summary(
        grouped,
        metric=metric,
        contrast=name,
        scope=scope,
        iterations=iterations,
        seed=seed,
    )
    row["comparison"] = row.pop("contrast")
    row["treatment"] = treatment
    row["reference"] = reference
    return row


def analyze_paired_rows(
    rows: Iterable[dict[str, Any]],
    *,
    comparisons: Iterable[tuple[str, str, str]],
    metrics: Iterable[str],
    iterations: int = 10_000,
    seed: int = 27_182,
) -> dict[str, Any]:
    if iterations < 100:
        raise ValueError("iterations must be at least 100")
    comparisons = _validated_comparisons(comparisons)
    metrics = list(dict.fromkeys(metrics))
    if not metrics:
        raise ValueError("at least one metric is required")
    methods = {method for _name, treatment, reference in comparisons for method in (treatment, reference)}
    indexed = _index_rows(rows, methods)

    contrast_rows: list[dict[str, Any]] = []
    availability: dict[str, dict[str, dict[str, int]]] = {}
    for metric in metrics:
        overall_rows: list[dict[str, Any]] = []
        availability[metric] = {}
        for name, treatment, reference in comparisons:
            by_dataset: dict[str, list[float]] = defaultdict(list)
            missing = 0
            for (dataset, _question_id), method_rows in indexed.items():
                treatment_value = _as_float(method_rows[treatment].get(metric))
                reference_value = _as_float(method_rows[reference].get(metric))
                if treatment_value is None or reference_value is None:
                    missing += 1
                    continue
                by_dataset[dataset].append(treatment_value - reference_value)
            count = sum(len(values) for values in by_dataset.values())
            availability[metric][name] = {
                "complete_question_count": count,
                "missing_metric_question_count": missing,
            }
            if metric == "primary_score" and missing:
                raise PairedAnalysisError(f"primary_score is missing for {name}: {missing} questions")
            if not by_dataset:
                continue
            for dataset, values in sorted(by_dataset.items()):
                contrast_rows.append(_comparison_summary(
                    {dataset: values},
                    metric=metric,
                    name=name,
                    treatment=treatment,
                    reference=reference,
                    scope=dataset,
                    iterations=iterations,
                    seed=seed,
                ))
            overall_rows.append(_comparison_summary(
                dict(by_dataset),
                metric=metric,
                name=name,
                treatment=treatment,
                reference=reference,
                scope="overall",
                iterations=iterations,
                seed=seed,
            ))
        if metric == "primary_score":
            _holm(overall_rows)
        contrast_rows.extend(overall_rows)

    return {
        "schema_version": 1,
        "design": {
            "comparisons": [
                {"name": name, "treatment": treatment, "reference": reference}
                for name, treatment, reference in comparisons
            ],
            "stratified_by": "dataset",
            "primary_holm_family": [name for name, _treatment, _reference in comparisons],
        },
        "iterations": iterations,
        "seed": seed,
        "question_count": len(indexed),
        "availability": availability,
        "contrasts": contrast_rows,
    }


def analyze_paired_csv(
    per_question_path: Path,
    output_dir: Path,
    *,
    comparisons: Iterable[tuple[str, str, str]],
    metrics: Iterable[str],
    iterations: int = 10_000,
    seed: int = 27_182,
) -> dict[str, Any]:
    with per_question_path.open(encoding="utf-8", newline="") as handle:
        report = analyze_paired_rows(
            csv.DictReader(handle),
            comparisons=comparisons,
            metrics=metrics,
            iterations=iterations,
            seed=seed,
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    report["input"] = {
        "per_question_path": str(per_question_path),
        "sha256": hashlib.sha256(per_question_path.read_bytes()).hexdigest(),
    }
    report["analysis"] = {
        "implementation": "slotrag.benchmarking.paired",
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (output_dir / "paired_analysis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    rows = report["contrasts"]
    with (output_dir / "paired_contrasts.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)
    return report
