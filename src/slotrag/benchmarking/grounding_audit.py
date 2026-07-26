from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .factorial import CELL_METHODS, FactorialAnalysisError, _as_float, _contrast_values, _index_rows


_MECHANISM_COUNTERS = (
    "direct_grounded_anchor_projections",
    "role_projected_extraction_contracts",
    "known_binding_fields_projected",
    "protected_anchor_rejections",
    "grounding_rejections",
    "evidence_surface_grounding_repairs",
)


def _delta(on: float | None, off: float | None) -> float | None:
    return None if on is None or off is None else float(on - off)


def _candidate_classification(primary: float, em: float | None) -> str:
    primary_tie = bool(np.isclose(primary, 0.0))
    em_tie = em is None or bool(np.isclose(em, 0.0))
    if primary_tie:
        return "factor_only_no_candidate_change"
    if not em_tie:
        return "candidate_exact_gain" if em > 0 else "candidate_exact_loss"
    return "candidate_overlap_only_gain" if primary > 0 else "candidate_overlap_only_loss"


def _stratified_delta(
    indexed: dict[tuple[str, str], dict[str, dict[str, Any]]],
    metric: str,
) -> float | None:
    by_dataset: dict[str, list[float]] = defaultdict(list)
    for (dataset, _question_id), method_rows in indexed.items():
        off = _as_float(method_rows[CELL_METHODS[("off", "slot")]].get(metric))
        on = _as_float(method_rows[CELL_METHODS[("on", "slot")]].get(metric))
        value = _delta(on, off)
        if value is None:
            return None
        by_dataset[dataset].append(value)
    return float(np.mean([np.mean(values) for values in by_dataset.values()]))


def analyze_grounding_changes(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Identify non-tie grounding contrasts and audit the selected slot-only pair."""
    indexed = _index_rows(rows)
    cases: list[dict[str, Any]] = []
    classifications: Counter[str] = Counter()
    for (dataset, question_id), method_rows in sorted(indexed.items()):
        primary_values: dict[tuple[str, str], float] = {}
        for cell, method in CELL_METHODS.items():
            value = _as_float(method_rows[method].get("primary_score"))
            if value is None:
                raise FactorialAnalysisError(
                    f"primary_score is missing: {dataset}/{question_id}/{method}"
                )
            primary_values[cell] = value
        grounding_main = _contrast_values(primary_values)["grounding_main"]
        if np.isclose(grounding_main, 0.0):
            continue

        off_row = method_rows[CELL_METHODS[("off", "slot")]]
        on_row = method_rows[CELL_METHODS[("on", "slot")]]
        candidate_delta = {
            metric: _delta(_as_float(on_row.get(metric)), _as_float(off_row.get(metric)))
            for metric in ("primary_score", "em", "f1")
        }
        classification = _candidate_classification(
            candidate_delta["primary_score"] or 0.0,
            candidate_delta["em"],
        )
        classifications[classification] += 1
        cells = []
        for (grounding, retrieval), method in CELL_METHODS.items():
            row = method_rows[method]
            cells.append({
                "grounding": grounding,
                "retrieval": retrieval,
                "method": method,
                "status": row.get("status"),
                "failure_category": row.get("failure_category"),
                "prediction_scored": row.get("prediction_scored"),
                "scores": {
                    metric: _as_float(row.get(metric))
                    for metric in ("primary_score", "em", "f1")
                },
                "mechanism_counters": {
                    counter: _as_float(row.get(counter))
                    for counter in _MECHANISM_COUNTERS
                },
            })
        cases.append({
            "dataset": dataset,
            "question_id": question_id,
            "grounding_main": grounding_main,
            "candidate_delta": candidate_delta,
            "classification": classification,
            "candidate_status_changed": off_row.get("status") != on_row.get("status"),
            "any_factor_status_changed": any(
                method_rows[CELL_METHODS[("off", retrieval)]].get("status")
                != method_rows[CELL_METHODS[("on", retrieval)]].get("status")
                for retrieval in ("slot", "always", "unbound")
            ),
            "cells": cells,
        })

    return {
        "schema_version": 1,
        "selection": {
            "contrast": "grounding_main",
            "tie_rule": "numpy.isclose(value, 0.0)",
            "candidate_pair": {
                "control": CELL_METHODS[("off", "slot")],
                "treatment": CELL_METHODS[("on", "slot")],
            },
        },
        "summary": {
            "question_count": len(indexed),
            "nonzero_grounding_main_count": len(cases),
            "classification_counts": dict(sorted(classifications.items())),
            "candidate_overall": {
                f"{metric}_delta": _stratified_delta(indexed, metric)
                for metric in ("primary_score", "em", "f1")
            },
        },
        "cases": cases,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(run_dir: Path, path: Path) -> dict[str, str]:
    return {"path": str(path.relative_to(run_dir)), "sha256": _sha256(path)}


def _only_path(paths: Iterable[Path], description: str) -> Path:
    matches = sorted(paths)
    if len(matches) != 1:
        raise FactorialAnalysisError(f"expected one {description}, found {len(matches)}")
    return matches[0]


def _sample_index(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            question_id = str(record.get("question_id") or record.get("id") or record.get("_id") or "")
            if question_id:
                records[question_id] = record
    return records


def audit_grounding_run(run_dir: Path, stage: str) -> dict[str, Any]:
    """Write an auditable index for every non-tie grounding-factor question."""
    per_question = run_dir / "summaries" / stage / "per_question.csv"
    with per_question.open(encoding="utf-8", newline="") as handle:
        report = analyze_grounding_changes(csv.DictReader(handle))

    samples: dict[str, dict[str, dict[str, Any]]] = {}
    for case in report["cases"]:
        dataset = case["dataset"]
        if dataset not in samples:
            samples[dataset] = _sample_index(run_dir / "samples" / stage / f"{dataset}.jsonl")
        sample = samples[dataset].get(case["question_id"])
        if sample is None:
            raise FactorialAnalysisError(f"sample is missing: {dataset}/{case['question_id']}")
        case["question"] = sample.get("question")
        case["answers"] = sample.get("answers") or sample.get("answer")
        for cell in case["cells"]:
            method = cell["method"]
            item_dir = run_dir / "items" / stage / dataset / method
            item = _only_path(
                (path for path in item_dir.glob("*.json") if path.name.startswith(f"{case['question_id']}-")),
                f"final record for {dataset}/{case['question_id']}/{method}",
            )
            stem = item.stem
            attempt = _only_path(
                (run_dir / "attempts" / stage / dataset / method / stem).glob("attempt-*.json"),
                f"attempt for {dataset}/{case['question_id']}/{method}",
            )
            trace = _only_path(
                (run_dir / "traces" / stage / dataset / method / stem).glob("attempt-*.jsonl"),
                f"trace for {dataset}/{case['question_id']}/{method}",
            )
            cell["artifacts"] = {
                "final": _artifact(run_dir, item),
                "attempt": _artifact(run_dir, attempt),
                "trace": _artifact(run_dir, trace),
            }

    report["stage"] = stage
    report["input"] = {
        "per_question_path": str(per_question.relative_to(run_dir)),
        "per_question_sha256": _sha256(per_question),
    }
    report["analysis"] = {
        "implementation": "slotrag.benchmarking.grounding_audit",
        "implementation_sha256": _sha256(Path(__file__)),
    }
    output = run_dir / "summaries" / stage / "grounding_mechanism_audit.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
