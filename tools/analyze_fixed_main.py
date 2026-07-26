#!/usr/bin/env python3
"""Analyze a candidate against fixed per-question baseline adapters.

The candidate and baseline are read from immutable per-question CSV exports. The
tool only joins identical ``(dataset, question_id)`` keys and delegates inference
to the repository's dataset-stratified paired-analysis implementation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from slotrag.benchmarking.paired import analyze_paired_rows
from slotrag.benchmarking.statistics import METRICS


LEGACY_ZERO_METRICS = {
    "frontier_guard_checks",
    "frontier_guard_interventions",
    "frontier_candidates_pruned",
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _key(row: dict[str, str]) -> tuple[str, str]:
    return (str(row.get("dataset") or ""), str(row.get("question_id") or ""))


def _selected(rows: Iterable[dict[str, str]], method: str) -> list[dict[str, str]]:
    selected = [row for row in rows if row.get("method") == method or row.get("base_method") == method]
    if not selected:
        raise ValueError(f"no rows found for method {method!r}")
    return selected


def _index(rows: Iterable[dict[str, str]], method: str) -> dict[tuple[str, str], dict[str, str]]:
    indexed: dict[tuple[str, str], dict[str, str]] = {}
    for row in _selected(rows, method):
        key = _key(row)
        if not all(key):
            raise ValueError(f"row for {method!r} is missing dataset or question_id")
        if key in indexed:
            raise ValueError(f"duplicate question key for {method!r}: {key[0]}/{key[1]}")
        indexed[key] = row
    return indexed


def _paired_rows(
    candidate_rows: list[dict[str, str]],
    baseline_rows: list[dict[str, str]],
    *,
    candidate_method: str,
    baseline_methods: tuple[str, ...],
) -> list[dict[str, str]]:
    candidate = _index(candidate_rows, candidate_method)
    baseline = {method: _index(baseline_rows, method) for method in baseline_methods}
    expected = set(candidate)
    for method, rows in baseline.items():
        if set(rows) != expected:
            missing = sorted(expected - set(rows))
            extra = sorted(set(rows) - expected)
            raise ValueError(
                f"question key mismatch for {method}: missing={missing[:3]} extra={extra[:3]}"
            )

    output: list[dict[str, str]] = []
    for key in sorted(expected):
        candidate_row = dict(candidate[key])
        candidate_row["base_method"] = candidate_method
        output.append(candidate_row)
        for method in baseline_methods:
            baseline_row = dict(baseline[method][key])
            baseline_row["base_method"] = method
            for metric in LEGACY_ZERO_METRICS:
                if metric not in baseline_row:
                    baseline_row[metric] = "0"
            output.append(baseline_row)
    return output


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", encoding="utf-8", newline="") as handle:
        if not fields:
            handle.write("\n")
            return
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _load_trigger_audit(
    candidate_per_question: list[dict[str, str]],
    baseline_per_question: list[dict[str, str]],
    *,
    candidate_method: str,
    baseline_method: str,
    candidate_items_dir: Path | None,
) -> list[dict[str, Any]]:
    baseline_index = _index(baseline_per_question, baseline_method)
    rows: list[dict[str, Any]] = []
    for row in _selected(candidate_per_question, candidate_method):
        try:
            rejection_count = float(row.get("protected_anchor_rejections") or 0.0)
        except ValueError:
            rejection_count = 0.0
        if rejection_count <= 0:
            continue
        key = _key(row)
        item: dict[str, Any] = {}
        item_path: str | None = None
        if candidate_items_dir is not None:
            matches = sorted(candidate_items_dir.glob(f"{key[0]}/{candidate_method}/{key[1]}-*.json"))
            if len(matches) == 1:
                item_path = str(matches[0])
                try:
                    item = json.loads(matches[0].read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    item = {}
        baseline = baseline_index[key]
        rows.append({
            "dataset": key[0],
            "question_id": key[1],
            "protected_anchor_rejections": rejection_count,
            "status": row.get("status"),
            "answers": item.get("answers", []),
            "candidate_prediction": row.get("prediction_scored"),
            "candidate_primary_score": row.get("primary_score"),
            "candidate_em": row.get("em"),
            "candidate_f1": row.get("f1"),
            "baseline_prediction": baseline.get("prediction_scored"),
            "baseline_primary_score": baseline.get("primary_score"),
            "baseline_em": baseline.get("em"),
            "baseline_f1": baseline.get("f1"),
            "item_path": item_path,
        })
    return rows


def _load_frontier_audit(
    candidate_per_question: list[dict[str, str]],
    baseline_per_question: list[dict[str, str]],
    *,
    candidate_method: str,
    baseline_method: str,
) -> list[dict[str, Any]]:
    baseline_index = _index(baseline_per_question, baseline_method)
    rows: list[dict[str, Any]] = []
    for row in _selected(candidate_per_question, candidate_method):
        try:
            intervention_count = float(row.get("frontier_guard_interventions") or 0.0)
        except ValueError:
            intervention_count = 0.0
        if intervention_count <= 0:
            continue
        key = _key(row)
        baseline = baseline_index[key]
        rows.append({
            "dataset": key[0],
            "question_id": key[1],
            "frontier_guard_checks": float(row.get("frontier_guard_checks") or 0.0),
            "frontier_guard_interventions": intervention_count,
            "frontier_candidates_pruned": float(row.get("frontier_candidates_pruned") or 0.0),
            "candidate_status": row.get("status"),
            "baseline_status": baseline.get("status"),
            "candidate_prediction": row.get("prediction_scored"),
            "baseline_prediction": baseline.get("prediction_scored"),
            "candidate_primary_score": row.get("primary_score"),
            "baseline_primary_score": baseline.get("primary_score"),
            "candidate_em": row.get("em"),
            "baseline_em": baseline.get("em"),
            "candidate_f1": row.get("f1"),
            "baseline_f1": baseline.get("f1"),
        })
    return rows


def analyze_fixed_main(
    candidate_path: Path,
    baseline_path: Path,
    output_dir: Path,
    *,
    candidate_method: str,
    baseline_methods: tuple[str, ...],
    candidate_items_dir: Path | None = None,
    iterations: int = 10_000,
    seed: int = 27_182,
) -> dict[str, Any]:
    if not baseline_methods:
        raise ValueError("at least one baseline method is required")
    if len(set(baseline_methods)) != len(baseline_methods):
        raise ValueError("baseline methods must be unique")

    candidate_rows = _read_csv(candidate_path)
    baseline_rows = _read_csv(baseline_path)
    paired_rows = _paired_rows(
        candidate_rows,
        baseline_rows,
        candidate_method=candidate_method,
        baseline_methods=baseline_methods,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    paired_input = output_dir / "paired_input.csv"
    _write_csv(paired_input, paired_rows)

    comparisons = [
        (f"{candidate_method}_vs_{method}", candidate_method, method)
        for method in baseline_methods
    ]
    paired_analysis = analyze_paired_rows(
        paired_rows,
        comparisons=comparisons,
        metrics=METRICS,
        iterations=iterations,
        seed=seed,
    )
    paired_analysis["input"] = {
        "candidate_path": str(candidate_path),
        "candidate_sha256": _sha256(candidate_path),
        "baseline_path": str(baseline_path),
        "baseline_sha256": _sha256(baseline_path),
        "paired_input_path": str(paired_input),
        "paired_input_sha256": _sha256(paired_input),
    }
    paired_analysis["analysis"] = {
        "implementation": "slotrag.benchmarking.paired",
        "metrics": list(METRICS),
        "iterations": iterations,
        "seed": seed,
        "primary_inference": "dataset-stratified bootstrap CI and sign-flip p-value",
        "multiple_comparisons": "Holm correction over overall primary comparisons",
    }
    paired_json = output_dir / "paired_analysis.json"
    paired_json.write_text(json.dumps(paired_analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(output_dir / "paired_contrasts.csv", paired_analysis["contrasts"])

    trigger_rows = _load_trigger_audit(
        candidate_rows,
        baseline_rows,
        candidate_method=candidate_method,
        baseline_method=baseline_methods[0],
        candidate_items_dir=candidate_items_dir,
    )
    _write_csv(output_dir / "protected_anchor_audit.csv", trigger_rows)
    trigger_summary = {
        "triggered_question_count": len(trigger_rows),
        "rejection_total": sum(float(row["protected_anchor_rejections"]) for row in trigger_rows),
        "by_dataset": dict(Counter(row["dataset"] for row in trigger_rows)),
        "exact_gain_count": sum(
            float(row.get("candidate_em") or 0) == 1 and float(row.get("baseline_em") or 0) < 1
            for row in trigger_rows
        ),
        "exact_loss_count": sum(
            float(row.get("candidate_em") or 0) < 1 and float(row.get("baseline_em") or 0) == 1
            for row in trigger_rows
        ),
        "exact_tie_count": sum(
            float(row.get("candidate_em") or 0) == float(row.get("baseline_em") or 0)
            for row in trigger_rows
        ),
    }
    trigger_json = output_dir / "protected_anchor_audit.json"
    trigger_json.write_text(json.dumps({"summary": trigger_summary, "rows": trigger_rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    frontier_rows = _load_frontier_audit(
        candidate_rows,
        baseline_rows,
        candidate_method=candidate_method,
        baseline_method=baseline_methods[0],
    )
    _write_csv(output_dir / "frontier_selection_audit.csv", frontier_rows)
    frontier_summary = {
        "triggered_question_count": len(frontier_rows),
        "checks_total": sum(float(row["frontier_guard_checks"]) for row in frontier_rows),
        "interventions_total": sum(float(row["frontier_guard_interventions"]) for row in frontier_rows),
        "candidates_pruned_total": sum(float(row["frontier_candidates_pruned"]) for row in frontier_rows),
        "by_dataset": dict(Counter(row["dataset"] for row in frontier_rows)),
        "exact_gain_count": sum(
            float(row.get("candidate_em") or 0) == 1 and float(row.get("baseline_em") or 0) < 1
            for row in frontier_rows
        ),
        "exact_loss_count": sum(
            float(row.get("candidate_em") or 0) < 1 and float(row.get("baseline_em") or 0) == 1
            for row in frontier_rows
        ),
        "exact_tie_count": sum(
            float(row.get("candidate_em") or 0) == float(row.get("baseline_em") or 0)
            for row in frontier_rows
        ),
    }
    frontier_json = output_dir / "frontier_selection_audit.json"
    frontier_json.write_text(json.dumps({"summary": frontier_summary, "rows": frontier_rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = {
        "candidate_method": candidate_method,
        "baseline_methods": list(baseline_methods),
        "candidate_record_count": len(candidate_rows),
        "baseline_record_count": len(baseline_rows),
        "paired_question_count": len(paired_rows) // (len(baseline_methods) + 1),
        "paired_record_count": len(paired_rows),
        "paired_analysis": paired_analysis,
        "protected_anchor_audit": {
            "path": str(trigger_json),
            "sha256": _sha256(trigger_json),
            **trigger_summary,
        },
        "frontier_selection_audit": {
            "path": str(frontier_json),
            "sha256": _sha256(frontier_json),
            **frontier_summary,
        },
    }
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-per-question", type=Path, required=True)
    parser.add_argument("--baseline-per-question", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--candidate-method", required=True)
    parser.add_argument("--baseline-method", action="append", required=True)
    parser.add_argument("--candidate-items-dir", type=Path)
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=27_182)
    args = parser.parse_args()
    report = analyze_fixed_main(
        args.candidate_per_question,
        args.baseline_per_question,
        args.output_dir,
        candidate_method=args.candidate_method,
        baseline_methods=tuple(args.baseline_method),
        candidate_items_dir=args.candidate_items_dir,
        iterations=args.iterations,
        seed=args.seed,
    )
    print(json.dumps({
        "candidate_method": report["candidate_method"],
        "baseline_methods": report["baseline_methods"],
        "paired_question_count": report["paired_question_count"],
        "paired_contrast_count": len(report["paired_analysis"]["contrasts"]),
        "protected_anchor_audit": report["protected_anchor_audit"],
        "frontier_selection_audit": report["frontier_selection_audit"],
        "output_dir": str(args.output_dir),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
