#!/usr/bin/env python3
"""Compare method-only results with a frozen baseline on identical questions."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np


QUALITY_METRICS = (
    "primary_score",
    "em",
    "f1",
    "accuracy",
    "drop_em",
    "drop_f1",
    "evidence_recall",
    "evidence_mrr",
    "evidence_recall_at_1",
    "evidence_recall_at_5",
    "evidence_recall_at_10",
    "evidence_precision_at_1",
    "evidence_precision_at_5",
    "evidence_precision_at_10",
    "evidence_hit_at_1",
    "evidence_hit_at_5",
    "evidence_hit_at_10",
    "evidence_ndcg_at_10",
)
COST_METRICS = (
    "documents_accessed",
    "unique_documents_accessed",
    "passages_processed",
    "unique_passages_accessed",
    "llm_calls",
    "retrieval_calls",
    "dual_query_expansions",
    "dual_query_skips",
    "dual_query_confidence_skips",
    "embedding_calls",
    "reranker_calls",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "provider_calls",
    "wall_latency_ms",
    "latency_ms",
    "compilation_latency_ms",
    "execution_latency_ms",
    "materialization_latency_ms",
    "generation_latency_ms",
    "retry_count",
    "structured_output_failures",
    "structured_output_repairs",
    "grounding_rejections",
    "evidence_only_fallbacks",
    "deterministic_answers",
    "plan_slot_count",
    "plan_join_count",
    "plan_operator_count",
    "steps_executed",
    "frozen_plan_replays",
    "direct_grounded_anchor_projections",
    "grounded_entity_anchor_substitutions",
    "query_grounded_anchor_contexts",
    "role_projected_extraction_contracts",
)
ALL_METRICS = QUALITY_METRICS + COST_METRICS


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _float(row: dict[str, str], key: str) -> float | None:
    value = row.get(key, "")
    if value in {"", "None", "null", "nan"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _holm(rows: list[dict[str, Any]]) -> None:
    ranked = sorted(
        ((index, row) for index, row in enumerate(rows) if row.get("p_value") is not None),
        key=lambda item: item[1]["p_value"],
    )
    running = 0.0
    for rank, (index, row) in enumerate(ranked):
        running = max(running, min(row["p_value"] * (len(ranked) - rank), 1.0))
        rows[index]["p_holm"] = running


def _bootstrap(differences: np.ndarray, *, seed: int, iterations: int = 10_000) -> tuple[float, float, float]:
    if len(differences) < 2:
        return (None, None, None)  # type: ignore[return-value]
    rng = np.random.default_rng(seed)
    samples = differences[rng.integers(0, len(differences), size=(iterations, len(differences)))].mean(axis=1)
    p_value = min(1.0, 2 * min(float(np.mean(samples <= 0)), float(np.mean(samples >= 0))))
    return (float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5)), p_value)


def compare(candidate_path: Path, baseline_path: Path, output_dir: Path, candidate_methods: set[str]) -> dict[str, Any]:
    candidate = _read(candidate_path)
    baseline = _read(baseline_path)
    baseline_by_key = {
        (row["dataset"], row["question_id"]): row
        for row in baseline
        if row.get("method") == "slotrag"
    }
    selected = [row for row in candidate if row.get("method") in candidate_methods]
    paired: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str], list[tuple[dict[str, str], dict[str, str]]]] = defaultdict(list)
    for row in selected:
        reference = baseline_by_key.get((row.get("dataset", ""), row.get("question_id", "")))
        if reference is not None:
            grouped[(row["dataset"], row["method"])].append((row, reference))
    for (dataset, method), pairs in sorted(grouped.items()):
        primary_diffs = np.asarray(
            [(_float(candidate_row, "primary_score") or 0.0) - (_float(reference_row, "primary_score") or 0.0) for candidate_row, reference_row in pairs],
            dtype=float,
        )
        ci_low, ci_high, p_value = _bootstrap(primary_diffs, seed=2027 + len(paired))
        paired.append({
            "dataset": dataset,
            "reference": "slotrag@main_comparison",
            "comparison": method,
            "count": len(pairs),
            "mean_difference_candidate_minus_reference": float(primary_diffs.mean()) if len(primary_diffs) else None,
            "median_difference": float(np.median(primary_diffs)) if len(primary_diffs) else None,
            "wins": int(np.sum(primary_diffs > 0)),
            "ties": int(np.sum(np.isclose(primary_diffs, 0.0))),
            "losses": int(np.sum(primary_diffs < 0)),
            "ci_low": ci_low,
            "ci_high": ci_high,
            "p_value": p_value,
            "p_holm": None,
        })
        for metric in ALL_METRICS:
            candidate_values = [_float(candidate_row, metric) for candidate_row, _ in pairs]
            reference_values = [_float(reference_row, metric) for _, reference_row in pairs]
            valid = [(left, right) for left, right in zip(candidate_values, reference_values) if left is not None and right is not None]
            if not valid:
                continue
            left = np.asarray([item[0] for item in valid], dtype=float)
            right = np.asarray([item[1] for item in valid], dtype=float)
            metric_rows.append({
                "dataset": dataset,
                "method": method,
                "metric": metric,
                "count": len(valid),
                "candidate_mean": float(left.mean()),
                "reference_mean": float(right.mean()),
                "delta_candidate_minus_reference": float((left - right).mean()),
                "candidate_ok_rate": float(np.mean([candidate_row.get("status") == "ok" for candidate_row, _ in pairs])),
                "reference_ok_rate": float(np.mean([reference_row.get("status") == "ok" for _, reference_row in pairs])),
            })
    _holm(paired)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "paired_primary.json").write_text(json.dumps(paired, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "metric_comparison.json").write_text(json.dumps(metric_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, rows in (("paired_primary.csv", paired), ("metric_comparison.csv", metric_rows)):
        if not rows:
            (output_dir / name).write_text("\n", encoding="utf-8")
            continue
        with (output_dir / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    report = {
        "candidate_path": str(candidate_path),
        "baseline_path": str(baseline_path),
        "candidate_methods": sorted(candidate_methods),
        "candidate_record_count": len(candidate),
        "baseline_record_count": len(baseline),
        "paired_primary_count": len(paired),
        "metric_row_count": len(metric_rows),
        "paired_primary": paired,
    }
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-per-question", type=Path, required=True)
    parser.add_argument("--baseline-per-question", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--candidate-method", action="append", required=True)
    args = parser.parse_args()
    report = compare(args.candidate_per_question, args.baseline_per_question, args.output_dir, set(args.candidate_method))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
