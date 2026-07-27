#!/usr/bin/env python3
"""Offline headroom and failure analysis for SlotRAG benchmark artifacts.

The analyzer is deliberately provider-free. It consumes immutable item JSON and
the normalized sample JSONL stored beside a run. Missing telemetry is reported
as ``N/A`` instead of being reconstructed from a guess.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ERROR_CATEGORIES = (
    "PLAN_ERROR",
    "PLAN_UNCOMPILABLE",
    "RETRIEVAL_MISS",
    "EVIDENCE_PARTIAL",
    "EVIDENCE_INSUFFICIENT",
    "EXTRACTION_ERROR",
    "BINDING_PRUNED",
    "JOIN_FAILURE",
    "ANSWER_GENERATION_ERROR",
    "METRIC_OR_ADAPTER_ERROR",
    "UNKNOWN",
)

MECHANISM_FIELDS = (
    "frontier_guard_interventions",
    "frontier_candidates_pruned",
    "protected_anchor_rejections",
    "binding_contexts_pruned",
    "grounding_rejections",
    "structured_output_failures",
    "structured_output_repairs",
    "semantic_role_type_rejections",
    "semantic_role_type_abstentions",
    "dual_query_expansions",
    "dual_query_guard_fallbacks",
    "query_anchor_plan_repairs",
    "evidence_surface_grounding_repairs",
    "local_plan_repairs",
    "operator_rewrites",
    "plan_fallbacks",
    "reoptimizations",
)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _canonical_id(value: object) -> str:
    return str(value or "").split("#chunk-", 1)[0]


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return float(statistics.fmean(values)) if values else None


def _normalize(value: object) -> str:
    text = str(value or "").casefold()
    return " ".join("".join(char if char.isalnum() else " " for char in text).split())


def _answer_in_text(answers: list[str], text: str) -> bool:
    normalized_text = _normalize(text)
    return bool(normalized_text and any(_normalize(answer) in normalized_text for answer in answers))


def _sample_index(run_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted((run_dir / "samples").rglob("*.jsonl")):
        dataset = path.stem
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            dataset_name = str(metadata.get("dataset") or dataset)
            question_id = str(record.get("id") or "")
            if question_id:
                index[(dataset_name, question_id)] = record
    return index


def _item_records(run_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    samples = _sample_index(run_dir)
    records: list[dict[str, Any]] = []
    load_errors: list[str] = []
    for path in sorted((run_dir / "items").rglob("*.json")):
        item = _read_json(path)
        if item is None:
            load_errors.append(str(path))
            continue
        dataset = str(item.get("dataset") or "")
        question_id = str(item.get("question_id") or item.get("id") or "")
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        scores = item.get("scores") if isinstance(item.get("scores"), dict) else {}
        metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
        sample = samples.get((dataset, question_id), {})
        records.append({
            "run": run_dir.name,
            "run_dir": str(run_dir),
            "path": str(path),
            "stage": str(item.get("stage") or "unknown"),
            "dataset": dataset,
            "method": str(item.get("method") or item.get("method_label") or "unknown"),
            "question_id": question_id,
            "stratum": str(item.get("stratum") or (sample.get("metadata", {}) or {}).get("stratum") or "unknown"),
            "item": item,
            "result": result,
            "scores": scores,
            "metrics": metrics,
            "sample": sample,
        })
    return records, load_errors


def _primary(record: dict[str, Any]) -> float | None:
    return _number(record["scores"].get("primary_score"))


def _evidence_ids(record: dict[str, Any]) -> set[str]:
    return {
        _canonical_id(item.get("source_id"))
        for item in record["result"].get("evidence", [])
        if isinstance(item, dict) and item.get("source_id")
    }


def _gold_ids(record: dict[str, Any]) -> set[str]:
    sample = record["sample"]
    values = sample.get("gold_evidence") if isinstance(sample, dict) else None
    if not isinstance(values, list):
        values = record["item"].get("gold_evidence", [])
    return {_canonical_id(value) for value in values if value}


def _available_passages(record: dict[str, Any]) -> list[dict[str, Any]]:
    passages = record["sample"].get("passages", []) if isinstance(record["sample"], dict) else []
    return [item for item in passages if isinstance(item, dict) and item.get("text")]


def _answers(record: dict[str, Any]) -> list[str]:
    values = record["sample"].get("answers") if isinstance(record["sample"], dict) else None
    if not isinstance(values, list):
        values = record["item"].get("answers", [])
    return [str(value) for value in values if value is not None]


def _rows_contain_answer(record: dict[str, Any]) -> bool:
    answers = _answers(record)
    rows = record["result"].get("rows", [])
    if not answers or not isinstance(rows, list):
        return False
    return any(_answer_in_text(answers, json.dumps(row, ensure_ascii=False)) for row in rows)


def _has_metric_error(record: dict[str, Any]) -> bool:
    score = _primary(record)
    return score is None or not 0.0 <= score <= 1.0


def classify_error(record: dict[str, Any]) -> str:
    """Classify one item with a stable, precedence-ordered taxonomy."""
    if _has_metric_error(record):
        return "METRIC_OR_ADAPTER_ERROR"
    result = record["result"]
    metrics = record["metrics"]
    error = str(result.get("error") or "").casefold()
    status = str(result.get("status") or "ok")
    primary = _primary(record) or 0.0
    if metrics.get("plan_validation_errors") or "uncompil" in error or "schema" in error and "plan" in error:
        return "PLAN_UNCOMPILABLE"
    if "plan" in error or "no join path" in error and "plan" in error:
        return "PLAN_ERROR"
    if _number(metrics.get("binding_contexts_pruned")) and _number(metrics.get("binding_contexts_pruned")) > 0 and primary < 1.0:
        return "BINDING_PRUNED"
    if "join path" in error or "join failure" in error or "join" in error and status == "failed":
        return "JOIN_FAILURE"
    if _number(metrics.get("structured_output_failures")) and _number(metrics.get("structured_output_failures")) > 0 and primary < 1.0:
        return "EXTRACTION_ERROR"

    evidence_ids = _evidence_ids(record)
    gold_ids = _gold_ids(record)
    if gold_ids:
        overlap = len(evidence_ids & gold_ids)
        if overlap == 0 and primary < 1.0:
            return "RETRIEVAL_MISS"
        if overlap < len(gold_ids) and primary < 1.0:
            return "EVIDENCE_PARTIAL"
    elif not evidence_ids and primary < 1.0:
        return "EVIDENCE_INSUFFICIENT"
    if primary < 1.0 and _rows_contain_answer(record):
        return "ANSWER_GENERATION_ERROR"
    if status == "failed" and primary < 1.0:
        return "UNKNOWN"
    if primary < 1.0:
        return "ANSWER_GENERATION_ERROR" if evidence_ids else "EVIDENCE_INSUFFICIENT"
    return "UNKNOWN"


def _mechanism_value(record: dict[str, Any], field: str) -> float:
    return _number(record["metrics"].get(field)) or 0.0


def _coverage(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    total = len(records)
    for field in MECHANISM_FIELDS:
        affected = [record for record in records if _mechanism_value(record, field) > 0]
        if not affected:
            continue
        headroom = [max(0.0, 1.0 - (_primary(record) or 0.0)) for record in affected]
        output.append({
            "run": records[0]["run"] if records else "",
            "mechanism": field,
            "total_questions": total,
            "affected_questions": len(affected),
            "coverage": len(affected) / total if total else None,
            "mean_trigger_value": _mean(_mechanism_value(record, field) for record in affected),
            "affected_headroom_to_perfect": _mean(headroom),
            "theoretical_max_average_gain": sum(headroom) / total if total else None,
            "affected_gain_ceiling": sum(headroom),
        })
    return output


def _pairwise(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(record["dataset"], record["question_id"])].append(record)
    pairs: list[dict[str, Any]] = []
    for (dataset, question_id), group in sorted(grouped.items()):
        by_method = {record["method"]: record for record in group}
        for left_method, right_method in itertools.combinations(sorted(by_method), 2):
            left = by_method[left_method]
            right = by_method[right_method]
            left_score = _primary(left)
            right_score = _primary(right)
            if left_score is None or right_score is None:
                continue
            delta = left_score - right_score
            pairs.append({
                "run": left["run"],
                "dataset": dataset,
                "question_id": question_id,
                "left_method": left_method,
                "right_method": right_method,
                "delta_primary": delta,
                "wins": int(delta > 0),
                "ties": int(math.isclose(delta, 0.0)),
                "losses": int(delta < 0),
            })
    return pairs


def _pairwise_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["run"], row["left_method"], row["right_method"])].append(row)
    output: list[dict[str, Any]] = []
    for (run, left, right), values in sorted(grouped.items()):
        deltas = [float(row["delta_primary"]) for row in values]
        output.append({
            "run": run,
            "left_method": left,
            "right_method": right,
            "question_count": len(values),
            "mean_delta_primary": _mean(deltas),
            "wins": sum(row["wins"] for row in values),
            "ties": sum(row["ties"] for row in values),
            "losses": sum(row["losses"] for row in values),
        })
    return output


def _slices(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for record in records:
        score = _primary(record)
        if score is not None:
            grouped[(record["dataset"], record["method"], record["stratum"])].append(score)
    return [
        {
            "dataset": dataset,
            "method": method,
            "stratum": stratum,
            "count": len(values),
            "mean_primary": _mean(values),
        }
        for (dataset, method, stratum), values in sorted(grouped.items())
    ]


def _counterfactuals(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counters = Counter()
    denominators = Counter()
    for record in records:
        denominators["gold_supporting_evidence_current_generator"] += 1
        denominators["current_retrieval_oracle_answerability"] += 1
        denominators["gold_logical_plan_current_executor"] += 1
        denominators["current_plan_gold_slot_bindings"] += 1
        denominators["full_evidence_answer_topk"] += 1
        denominators["rows_correct_final_wrong"] += 1
        passages = _available_passages(record)
        answers = _answers(record)
        evidence_ids = _evidence_ids(record)
        gold_ids = _gold_ids(record)
        available_ids = {_canonical_id(item.get("id")) for item in passages if item.get("id")}
        answer_in_available = any(_answer_in_text(answers, str(item.get("text") or "")) for item in passages)
        answer_in_retrieved = any(_answer_in_text(answers, str(item.get("source_span") or "")) for item in record["result"].get("evidence", []) if isinstance(item, dict))
        primary = _primary(record) or 0.0
        if gold_ids and gold_ids.issubset(available_ids) and primary < 1.0:
            counters["gold_supporting_evidence_current_generator"] += 1
        if answer_in_retrieved:
            counters["current_retrieval_oracle_answerability"] += 1
        if answer_in_available and not answer_in_retrieved:
            counters["full_evidence_answer_topk"] += 1
        if _rows_contain_answer(record) and primary < 1.0:
            counters["rows_correct_final_wrong"] += 1
        if record["item"].get("gold_plan") is not None:
            counters["gold_logical_plan_current_executor"] += int(record["result"].get("status") == "ok")
        if _rows_contain_answer(record):
            counters["current_plan_gold_slot_bindings"] += 1

    names = (
        "gold_supporting_evidence_current_generator",
        "current_retrieval_oracle_answerability",
        "gold_logical_plan_current_executor",
        "current_plan_gold_slot_bindings",
        "full_evidence_answer_topk",
        "rows_correct_final_wrong",
    )
    output: list[dict[str, Any]] = []
    for name in names:
        denominator = denominators[name]
        available = name in {"gold_logical_plan_current_executor"} and counters[name] == 0
        output.append({
            "name": name,
            "count": counters[name],
            "denominator": denominator,
            "rate": counters[name] / denominator if denominator else None,
            "status": "N/A" if available else "estimated",
        })
    return output


def _budget_signature(record: dict[str, Any]) -> tuple[float, float] | None:
    budget = record["item"].get("budget")
    if not isinstance(budget, dict):
        return None
    steps = _number(budget.get("max_steps"))
    retrieval = _number(budget.get("max_retrieval_calls"))
    if steps is None or retrieval is None:
        return None
    return steps, retrieval


def _budget_marginal_gains(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if _budget_signature(record) is not None and _primary(record) is not None:
            grouped[(record["dataset"], record["question_id"], record["method"])].append(record)
    output: list[dict[str, Any]] = []
    for (dataset, question_id, method), values in sorted(grouped.items()):
        values = sorted(values, key=lambda row: _budget_signature(row) or (0.0, 0.0))
        for low, high in zip(values, values[1:]):
            low_budget = _budget_signature(low)
            high_budget = _budget_signature(high)
            if low_budget == high_budget:
                continue
            output.append({
                "dataset": dataset,
                "question_id": question_id,
                "method": method,
                "low_budget": {"max_steps": low_budget[0], "max_retrieval_calls": low_budget[1]},
                "high_budget": {"max_steps": high_budget[0], "max_retrieval_calls": high_budget[1]},
                "delta_primary": (_primary(high) or 0.0) - (_primary(low) or 0.0),
            })
    return output


def _retrieval_relationships(records: list[dict[str, Any]]) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    for record in records:
        metrics = record["metrics"]
        keys = ("retrieval_top_k", "top_k", "final_k", "reranker_score", "top1_score", "score_margin", "score_entropy")
        values = {key: _number(metrics.get(key)) for key in keys if _number(metrics.get(key)) is not None}
        if values:
            values.update({"dataset": record["dataset"], "method": record["method"], "primary_score": _primary(record)})
            observations.append(values)
    if not observations:
        return {"status": "N/A", "reason": "existing item schema has no ranked retrieval telemetry", "observations": []}
    return {"status": "estimated", "observations": observations}


def _error_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "run": record["run"],
            "dataset": record["dataset"],
            "method": record["method"],
            "question_id": record["question_id"],
            "category": classify_error(record),
            "status": record["result"].get("status"),
            "error": record["result"].get("error"),
            "primary_score": _primary(record),
            "path": record["path"],
        }
        for record in records
        if classify_error(record) != "UNKNOWN" or (_primary(record) or 0.0) < 1.0
    ]


def _conclusions(
    records: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
    pairwise_summary: list[dict[str, Any]],
    counterfactuals: list[dict[str, Any]],
) -> dict[str, Any]:
    useful_fields = {
        "frontier_guard_interventions",
        "protected_anchor_rejections",
        "binding_contexts_pruned",
        "grounding_rejections",
        "structured_output_failures",
        "semantic_role_type_rejections",
        "dual_query_expansions",
        "query_anchor_plan_repairs",
        "evidence_surface_grounding_repairs",
        "local_plan_repairs",
        "operator_rewrites",
    }
    useful = [row for row in coverage if row["mechanism"] in useful_fields]
    top_useful = max(useful, key=lambda row: row.get("theoretical_max_average_gain") or 0.0, default=None)
    total_pairs = sum(int(row.get("question_count") or 0) for row in pairwise_summary)
    ties = sum(int(row.get("ties") or 0) for row in pairwise_summary)
    counterfactual_by_name = {row["name"]: row for row in counterfactuals}
    return {
        "largest_useful_mechanism": top_useful["mechanism"] if top_useful else None,
        "largest_useful_mechanism_ceiling": top_useful.get("theoretical_max_average_gain") if top_useful else None,
        "largest_useful_mechanism_coverage": top_useful.get("coverage") if top_useful else None,
        "current_retrieval_oracle_answerability_rate": counterfactual_by_name.get("current_retrieval_oracle_answerability", {}).get("rate"),
        "rows_correct_final_wrong_rate": counterfactual_by_name.get("rows_correct_final_wrong", {}).get("rate"),
        "full_evidence_answer_topk_rate": counterfactual_by_name.get("full_evidence_answer_topk", {}).get("rate"),
        "pairwise_tie_rate": ties / total_pairs if total_pairs else None,
        "sparse_guard_fields": [
            {"mechanism": row["mechanism"], "coverage": row["coverage"]}
            for row in coverage
            if row["mechanism"] in {"frontier_guard_interventions", "protected_anchor_rejections"}
        ],
        "planner_oracle_status": "N/A: no gold logical plans in analyzed historical items",
        "benchmark_sufficiency": "insufficient: local_context and adapted historical protocols; global-corpus evidence absent",
        "recommended_focus": "shared-corpus retrieval telemetry first, then extraction/generation verification; do not add sparse guards",
    }


def analyze_run_dirs(run_dirs: Iterable[Path]) -> dict[str, Any]:
    """Analyze one or more immutable run directories without provider calls."""
    all_records: list[dict[str, Any]] = []
    load_errors: list[str] = []
    run_summaries: list[dict[str, Any]] = []
    for path in run_dirs:
        path = Path(path)
        records, errors = _item_records(path)
        all_records.extend(records)
        load_errors.extend(errors)
        run_summaries.append({
            "run": path.name,
            "path": str(path),
            "item_count": len(records),
            "load_error_count": len(errors),
            "sample_count": len(_sample_index(path)),
            "manifest_sha256": hashlib.sha256((path / "manifest.json").read_bytes()).hexdigest() if (path / "manifest.json").exists() else None,
        })
    pairs = _pairwise(all_records)
    errors = _error_rows(all_records)
    error_counts = Counter(row["category"] for row in errors)
    pairwise_summary = _pairwise_summary(pairs)
    coverage = _coverage(all_records)
    counterfactuals = _counterfactuals(all_records)
    return {
        "schema_version": 1,
        "runs": run_summaries,
        "record_count": len(all_records),
        "load_errors": load_errors,
        "pairwise": pairs,
        "pairwise_summary": pairwise_summary,
        "coverage": coverage,
        "slices": _slices(all_records),
        "errors": errors,
        "error_counts": dict(sorted(error_counts.items())),
        "counterfactuals": counterfactuals,
        "budget_marginal_gains": _budget_marginal_gains(all_records),
        "retrieval_relationships": _retrieval_relationships(all_records),
        "category_vocabulary": list(ERROR_CATEGORIES),
        "conclusions": _conclusions(all_records, coverage, pairwise_summary, counterfactuals),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        if not fields:
            handle.write("\n")
            return
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(report: dict[str, Any], output_dir: Path, *, command: str = "") -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "headroom.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for key in ("pairwise", "pairwise_summary", "coverage", "slices", "errors", "counterfactuals", "budget_marginal_gains"):
        _write_csv(output_dir / f"{key}.csv", report.get(key, []))
    retrieval = report.get("retrieval_relationships", {})
    _write_csv(output_dir / "retrieval_relationships.csv", retrieval.get("observations", []))
    summary_lines = [
        "# SlotRAG Optimization Audit v54",
        "",
        "This report is generated from immutable run items and does not call any provider.",
        f"Command: `{command}`" if command else "",
        f"Records: **{report.get('record_count', 0)}**",
        "",
        "## Findings",
        "",
    ]
    conclusions = report.get("conclusions", {})
    top_mechanism = conclusions.get("largest_useful_mechanism")
    if top_mechanism:
        top = next(row for row in report.get("coverage", []) if row["mechanism"] == top_mechanism)
        summary_lines.append(
            f"- Largest useful mechanism headroom is `{top['mechanism']}` with coverage "
            f"{top['coverage']:.3f} and optimistic average ceiling {top['theoretical_max_average_gain']:.4f}."
        )
    else:
        summary_lines.append("- No mechanism telemetry was active in the analyzed records.")
    summary_lines.append(
        f"- Current-retrieval answerability estimate: {conclusions.get('current_retrieval_oracle_answerability_rate')!s}; "
        f"rows-correct/final-wrong estimate: {conclusions.get('rows_correct_final_wrong_rate')!s}."
    )
    summary_lines.append(
        f"- Pairwise tie rate: {conclusions.get('pairwise_tie_rate')!s}; sparse guard coverage: "
        f"{conclusions.get('sparse_guard_fields', [])}."
    )
    summary_lines.append(f"- Recommended focus: {conclusions.get('recommended_focus')}")
    summary_lines.append(f"- Planner oracle status: {conclusions.get('planner_oracle_status')}")
    summary_lines.append(f"- Benchmark sufficiency: {conclusions.get('benchmark_sufficiency')}")
    retrieval = report.get("retrieval_relationships", {})
    summary_lines.append(
        "- Retrieval score/top-k relationships: "
        + ("available in telemetry." if retrieval.get("status") != "N/A" else "N/A in existing item schema; this is a protocol gap.")
    )
    summary_lines.append("- Existing historical records are local/adapted evidence and are not sufficient for a global-corpus publication claim.")
    summary_lines.extend(["", "## Error Counts", ""])
    for category, count in sorted(report.get("error_counts", {}).items()):
        summary_lines.append(f"- `{category}`: {count}")
    summary_lines.extend(["", "## Counterfactuals", "", "| Counterfactual | Count | Denominator | Status |", "| --- | ---: | ---: | --- |"])
    for row in report.get("counterfactuals", []):
        summary_lines.append(f"| {row['name']} | {row['count']} | {row['denominator']} | {row['status']} |")
    summary_lines.extend([
        "",
        "## Interpretation Boundary",
        "",
        "- A ceiling is an oracle diagnostic, not an achieved improvement.",
        "- Missing ranked-retrieval, slot-binding and generator traces are reported as unavailable.",
        "- No evaluation threshold or sample was selected from these outputs.",
        "",
    ])
    (output_dir / "REPORT.md").write_text("\n".join(line for line in summary_lines if line is not None) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", action="append", type=Path, required=True, help="Immutable run directory; repeat for multiple runs")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = analyze_run_dirs(args.run_dir)
    import sys

    write_outputs(report, args.output_dir, command=" ".join(sys.argv))
    print(json.dumps({"record_count": report["record_count"], "output_dir": str(args.output_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
