from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np


class FactorialAnalysisError(ValueError):
    """Raised when a factorial result table is not a balanced paired design."""


CELL_METHODS = {
    ("off", "slot"): "slotrag",
    ("off", "always"): "slotrag-dual-query-retrieval",
    ("off", "unbound"): "slotrag-adaptive-dual-query-retrieval",
    ("on", "slot"): "slotrag-grounded-role-projection",
    ("on", "always"): "slotrag-grounded-dual-query-retrieval",
    ("on", "unbound"): "slotrag-grounded-adaptive-dual-query-retrieval",
}

CONTRASTS = (
    "grounding_main",
    "always_minus_slot",
    "unbound_minus_slot",
    "grounding_x_always",
    "grounding_x_unbound",
)


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _seed(seed: int, metric: str, contrast: str, scope: str) -> int:
    payload = f"{seed}:{metric}:{contrast}:{scope}".encode("utf-8")
    return (seed + int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")) % (2**63 - 1)


def _holm(rows: list[dict[str, Any]]) -> None:
    ranked = sorted(enumerate(rows), key=lambda item: float(item[1]["p_value"]))
    adjusted: dict[int, float] = {}
    running = 0.0
    total = len(ranked)
    for rank, (index, row) in enumerate(ranked):
        running = max(running, min(1.0, float(row["p_value"]) * (total - rank)))
        adjusted[index] = running
    for index, value in adjusted.items():
        rows[index]["p_holm"] = value


def _contrast_values(values: dict[tuple[str, str], float]) -> dict[str, float]:
    off_slot = values[("off", "slot")]
    off_always = values[("off", "always")]
    off_unbound = values[("off", "unbound")]
    on_slot = values[("on", "slot")]
    on_always = values[("on", "always")]
    on_unbound = values[("on", "unbound")]
    return {
        "grounding_main": (on_slot + on_always + on_unbound - off_slot - off_always - off_unbound) / 3,
        "always_minus_slot": (off_always + on_always - off_slot - on_slot) / 2,
        "unbound_minus_slot": (off_unbound + on_unbound - off_slot - on_slot) / 2,
        "grounding_x_always": (on_always - on_slot) - (off_always - off_slot),
        "grounding_x_unbound": (on_unbound - on_slot) - (off_unbound - off_slot),
    }


def _summary(
    grouped: dict[str, list[float]],
    *,
    metric: str,
    contrast: str,
    scope: str,
    iterations: int,
    seed: int,
) -> dict[str, Any]:
    arrays = [np.asarray(grouped[dataset], dtype=float) for dataset in sorted(grouped)]
    estimate = float(np.mean([array.mean() for array in arrays]))
    count = sum(len(array) for array in arrays)
    values = np.concatenate(arrays)
    is_tie = np.isclose(values, 0.0)
    wins = int(np.sum((values > 0) & ~is_tie))
    ties = int(np.sum(is_tie))
    losses = int(np.sum((values < 0) & ~is_tie))
    if count < 2:
        ci_low = None
        ci_high = None
        p_value = None
    else:
        rng = np.random.default_rng(_seed(seed, metric, contrast, scope))
        bootstrap_means = []
        sign_flip_means = []
        for array in arrays:
            indices = rng.integers(0, len(array), size=(iterations, len(array)))
            bootstrap_means.append(array[indices].mean(axis=1))
            signs = rng.choice(np.asarray([-1.0, 1.0]), size=(iterations, len(array)))
            sign_flip_means.append((array * signs).mean(axis=1))
        bootstrap = np.mean(np.stack(bootstrap_means, axis=0), axis=0)
        null = np.mean(np.stack(sign_flip_means, axis=0), axis=0)
        ci_low = float(np.percentile(bootstrap, 2.5))
        ci_high = float(np.percentile(bootstrap, 97.5))
        p_value = float((np.sum(np.abs(null) >= abs(estimate)) + 1) / (iterations + 1))
    return {
        "metric": metric,
        "contrast": contrast,
        "scope": scope,
        "datasets": sorted(grouped),
        "count": count,
        "estimate": estimate,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "p_value": p_value,
        "p_holm": None,
        "wins": wins,
        "ties": ties,
        "losses": losses,
    }


def _index_rows(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    expected_methods = set(CELL_METHODS.values())
    indexed: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        dataset = str(row.get("dataset") or "")
        question_id = str(row.get("question_id") or "")
        method = str(row.get("base_method") or row.get("method") or "")
        if not dataset or not question_id:
            raise FactorialAnalysisError("rows must contain dataset and question_id")
        if method not in expected_methods:
            continue
        key = (dataset, question_id)
        if method in indexed[key]:
            raise FactorialAnalysisError(f"duplicate factorial record: {dataset}/{question_id}/{method}")
        indexed[key][method] = row
    if not indexed:
        raise FactorialAnalysisError("no configured factorial records found")
    for (dataset, question_id), method_rows in sorted(indexed.items()):
        missing = sorted(expected_methods - set(method_rows))
        if missing:
            raise FactorialAnalysisError(
                f"missing factorial cell records: {dataset}/{question_id}: {', '.join(missing)}"
            )
    return indexed


def analyze_factorial_rows(
    rows: Iterable[dict[str, Any]],
    *,
    metrics: Iterable[str],
    iterations: int = 10_000,
    seed: int = 27_182,
) -> dict[str, Any]:
    if iterations < 100:
        raise ValueError("iterations must be at least 100")
    indexed = _index_rows(rows)
    metrics = list(dict.fromkeys(metrics))
    if not metrics:
        raise ValueError("at least one metric is required")

    cell_rows: list[dict[str, Any]] = []
    contrast_rows: list[dict[str, Any]] = []
    availability: dict[str, dict[str, int]] = {}
    for metric in metrics:
        values_by_unit: dict[tuple[str, str], dict[tuple[str, str], float]] = {}
        missing_values = 0
        for unit, method_rows in indexed.items():
            values: dict[tuple[str, str], float] = {}
            for cell, method in CELL_METHODS.items():
                value = _as_float(method_rows[method].get(metric))
                if value is None:
                    break
                values[cell] = value
            if len(values) == len(CELL_METHODS):
                values_by_unit[unit] = values
            else:
                missing_values += 1
        availability[metric] = {
            "complete_question_count": len(values_by_unit),
            "missing_metric_question_count": missing_values,
        }
        if not values_by_unit:
            continue

        for cell, method in CELL_METHODS.items():
            by_dataset: dict[str, list[float]] = defaultdict(list)
            for (dataset, _question_id), values in values_by_unit.items():
                by_dataset[dataset].append(values[cell])
            for dataset, values in sorted(by_dataset.items()):
                cell_rows.append({
                    "metric": metric,
                    "scope": dataset,
                    "grounding": cell[0],
                    "retrieval": cell[1],
                    "method": method,
                    "count": len(values),
                    "mean": float(np.mean(values)),
                })
            cell_rows.append({
                "metric": metric,
                "scope": "overall",
                "grounding": cell[0],
                "retrieval": cell[1],
                "method": method,
                "count": sum(len(values) for values in by_dataset.values()),
                "mean": float(np.mean([np.mean(values) for values in by_dataset.values()])),
            })

        contrast_by_dataset: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for (dataset, _question_id), values in values_by_unit.items():
            for contrast, value in _contrast_values(values).items():
                contrast_by_dataset[dataset][contrast].append(value)
        overall_rows: list[dict[str, Any]] = []
        for contrast in CONTRASTS:
            grouped = {dataset: values[contrast] for dataset, values in contrast_by_dataset.items()}
            overall_rows.append(_summary(
                grouped,
                metric=metric,
                contrast=contrast,
                scope="overall",
                iterations=iterations,
                seed=seed,
            ))
            for dataset, values in sorted(contrast_by_dataset.items()):
                contrast_rows.append(_summary(
                    {dataset: values[contrast]},
                    metric=metric,
                    contrast=contrast,
                    scope=dataset,
                    iterations=iterations,
                    seed=seed,
                ))
        if metric == "primary_score":
            _holm(overall_rows)
        contrast_rows.extend(overall_rows)

    if availability.get("primary_score", {}).get("missing_metric_question_count"):
        raise FactorialAnalysisError("primary_score is missing for one or more complete factorial questions")
    return {
        "schema_version": 1,
        "design": {
            "cells": [
                {"grounding": grounding, "retrieval": retrieval, "method": method}
                for (grounding, retrieval), method in CELL_METHODS.items()
            ],
            "contrasts": list(CONTRASTS),
            "stratified_by": "dataset",
        },
        "iterations": iterations,
        "seed": seed,
        "question_count": len(indexed),
        "availability": availability,
        "cell_means": cell_rows,
        "contrasts": contrast_rows,
    }


def analyze_factorial_csv(
    per_question_path: Path,
    output_dir: Path,
    *,
    metrics: Iterable[str],
    iterations: int = 10_000,
    seed: int = 27_182,
) -> dict[str, Any]:
    with per_question_path.open(encoding="utf-8", newline="") as handle:
        report = analyze_factorial_rows(
            list(csv.DictReader(handle)),
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
        "implementation": "slotrag.benchmarking.factorial",
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (output_dir / "factorial_analysis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for name, rows in (("factorial_cell_means.csv", report["cell_means"]), ("factorial_contrasts.csv", report["contrasts"])):
        path = output_dir / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
            if rows:
                writer.writeheader()
                writer.writerows(rows)
    return report
