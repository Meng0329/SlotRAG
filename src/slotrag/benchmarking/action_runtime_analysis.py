"""Auditable 2x2 runtime-action summaries from immutable benchmark records."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from statistics import fmean
from typing import Any, Iterable

from ..models import RunMetrics


_SCORE_FIELDS = (
    "primary_score",
    "em",
    "f1",
    "evidence_recall",
    "evidence_ndcg_at_10",
)
_METRIC_FIELDS = (
    "retrieval_calls",
    "prompt_tokens",
    "completion_tokens",
    "wall_latency_ms",
    "physical_action_decisions",
    "physical_action_executions",
    "physical_action_extra_retrieval_calls",
    "physical_action_rows_added",
    "evidence_sufficiency_decisions",
    "binding_beam_decisions",
    "binding_contexts_pruned",
)


def _mean(values: Iterable[float | int | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    return fmean(present) if present else None


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _answer(record: dict[str, Any]) -> str:
    scores = record.get("scores") or {}
    value = scores.get("prediction_scored")
    if value is None:
        value = (record.get("result") or {}).get("answer")
    return str(value or "").strip()


def _evidence_signature(record: dict[str, Any]) -> str:
    evidence = (record.get("result") or {}).get("evidence") or []
    normalized = sorted(
        (
            str(item.get("source_id") or ""),
            str(item.get("slot_id") or ""),
            _canonical(item.get("bindings") or {}),
        )
        for item in evidence
        if isinstance(item, dict)
    )
    return _canonical(normalized)


def _row_signature(record: dict[str, Any]) -> str:
    rows = (record.get("result") or {}).get("rows") or []
    return _canonical(sorted((_canonical(row) for row in rows)))


def _record_key(record: dict[str, Any]) -> tuple[str, int]:
    return str(record.get("question_id") or ""), int(record.get("seed", 0))


def analyze_runtime_records(
    records: Iterable[dict[str, Any]],
    *,
    reference_method: str = "slotrag",
) -> dict[str, Any]:
    """Summarize action execution coverage and paired method effects."""
    materialized = sorted(
        list(records),
        key=lambda row: (
            str(row.get("dataset")),
            str(row.get("method")),
            *_record_key(row),
        ),
    )
    if not materialized:
        raise ValueError("runtime action analysis requires at least one record")
    fingerprint = hashlib.sha256(_canonical(materialized).encode("utf-8")).hexdigest()
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in materialized:
        grouped[(str(record.get("dataset")), str(record.get("method")))].append(record)

    cells: list[dict[str, Any]] = []
    for (dataset, method), rows in sorted(grouped.items()):
        selected: Counter[str] = Counter()
        executed: Counter[str] = Counter()
        unexecuted: Counter[str] = Counter()
        matched = 0
        statuses: Counter[str] = Counter()
        parsed_metrics: list[RunMetrics] = []
        for row in rows:
            result = row.get("result") or {}
            statuses[str(result.get("status") or "unknown")] += 1
            metrics = RunMetrics.model_validate(result.get("metrics") or {})
            parsed_metrics.append(metrics)
            row_selected = Counter(metrics.physical_action_selected)
            row_executed = Counter(metrics.physical_action_executed)
            selected.update(row_selected)
            executed.update(row_executed)
            matched += sum((row_selected & row_executed).values())
            unexecuted.update(row_selected - row_executed)
        selected_count = sum(selected.values())
        score_means = {
            field: _mean((row.get("scores") or {}).get(field) for row in rows)
            for field in _SCORE_FIELDS
        }
        metric_means = {
            field: _mean(getattr(metrics, field) for metrics in parsed_metrics)
            for field in _METRIC_FIELDS
        }
        cells.append({
            "dataset": dataset,
            "method": method,
            "count": len(rows),
            "status_counts": dict(sorted(statuses.items())),
            **score_means,
            **metric_means,
            "total_tokens": _mean(
                metrics.prompt_tokens + metrics.completion_tokens
                for metrics in parsed_metrics
            ),
            "selected_action_usage": dict(sorted(selected.items())),
            "executed_action_usage": dict(sorted(executed.items())),
            "unexecuted_action_usage": dict(sorted(unexecuted.items())),
            "selected_action_execution_coverage": (
                matched / selected_count if selected_count else None
            ),
        })

    comparisons: list[dict[str, Any]] = []
    datasets = sorted({dataset for dataset, _method in grouped})
    for dataset in datasets:
        reference_rows = grouped.get((dataset, reference_method))
        if not reference_rows:
            continue
        reference_index = {_record_key(row): row for row in reference_rows}
        if len(reference_index) != len(reference_rows):
            raise ValueError(f"duplicate reference question/seed records for {dataset}")
        methods = sorted(method for candidate_dataset, method in grouped if candidate_dataset == dataset)
        for method in methods:
            if method == reference_method:
                continue
            treatment_rows = grouped[(dataset, method)]
            treatment_index = {_record_key(row): row for row in treatment_rows}
            if len(treatment_index) != len(treatment_rows):
                raise ValueError(f"duplicate treatment question/seed records for {dataset}/{method}")
            keys = sorted(reference_index.keys() & treatment_index.keys())
            deltas: list[float] = []
            answer_matches = 0
            row_matches = 0
            evidence_matches = 0
            for key in keys:
                reference = reference_index[key]
                treatment = treatment_index[key]
                reference_score = (reference.get("scores") or {}).get("primary_score")
                treatment_score = (treatment.get("scores") or {}).get("primary_score")
                if reference_score is None or treatment_score is None:
                    continue
                deltas.append(float(treatment_score) - float(reference_score))
                answer_matches += _answer(treatment) == _answer(reference)
                row_matches += _row_signature(treatment) == _row_signature(reference)
                evidence_matches += _evidence_signature(treatment) == _evidence_signature(reference)
            comparisons.append({
                "dataset": dataset,
                "reference": reference_method,
                "treatment": method,
                "paired_count": len(deltas),
                "mean_primary_delta_treatment_minus_reference": _mean(deltas),
                "gain_tie_loss": {
                    "gain": sum(value > 0 and not math.isclose(value, 0.0) for value in deltas),
                    "tie": sum(math.isclose(value, 0.0) for value in deltas),
                    "loss": sum(value < 0 and not math.isclose(value, 0.0) for value in deltas),
                },
                "answer_exact_match_rate": answer_matches / len(deltas) if deltas else None,
                "row_exact_match_rate": row_matches / len(deltas) if deltas else None,
                "evidence_exact_match_rate": evidence_matches / len(deltas) if deltas else None,
                "missing_reference_pairs": len(treatment_index.keys() - reference_index.keys()),
                "missing_treatment_pairs": len(reference_index.keys() - treatment_index.keys()),
            })

    return {
        "schema_version": 1,
        "analysis": "slotrag-2x2-runtime-action-audit",
        "reference_method": reference_method,
        "record_count": len(materialized),
        "record_fingerprint_sha256": fingerprint,
        "cells": cells,
        "comparisons": comparisons,
    }


__all__ = ["analyze_runtime_records"]
