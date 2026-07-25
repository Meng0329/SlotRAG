from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from ..models import RunMetrics, SlotPlan


METRICS = [
    "primary_score",
    "em",
    "f1",
    "accuracy",
    "drop_f1",
    "drop_em",
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
    "retrieved_evidence_count",
    "retrieved_document_count",
    "evidence_text_chars",
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
    "compilation_llm_calls",
    "compilation_prompt_tokens",
    "compilation_completion_tokens",
    "extraction_llm_calls",
    "extraction_prompt_tokens",
    "extraction_completion_tokens",
    "planning_llm_calls",
    "planning_prompt_tokens",
    "planning_completion_tokens",
    "reasoning_llm_calls",
    "reasoning_prompt_tokens",
    "reasoning_completion_tokens",
    "generation_llm_calls",
    "generation_prompt_tokens",
    "generation_completion_tokens",
    "total_tokens",
    "llm_calls_with_shared_compile",
    "total_tokens_with_shared_compile",
    "provider_calls_with_shared_compile",
    "wall_latency_with_shared_compile_ms",
    "latency_ms",
    "wall_latency_ms",
    "provider_latency_ms",
    "compilation_latency_ms",
    "execution_latency_ms",
    "materialization_latency_ms",
    "generation_latency_ms",
    "retry_count",
    "cache_hits",
    "cache_misses",
    "materialization_requests",
    "materialization_cache_hits",
    "binding_contexts_pruned",
    "evidence_only_fallbacks",
    "answer_reconciliations",
    "answer_span_normalizations",
    "polar_answer_normalizations",
    "polar_row_consensus",
    "typed_extraction_contracts",
    "typed_extraction_answers",
    "typed_extraction_abstentions",
    "frozen_plan_replays",
    "grounded_entity_anchor_folds",
    "grounded_entity_anchor_substitutions",
    "direct_grounded_anchor_projections",
    "query_grounded_anchor_contexts",
    "query_anchor_plan_repairs",
    "evidence_surface_grounding_repairs",
    "role_projected_extraction_contracts",
    "known_binding_fields_projected",
    "protected_anchor_rejections",
    "extraction_thinking_disabled",
    "bound_role_signatures",
    "extraction_length_finishes",
    "semantic_role_type_contracts",
    "semantic_role_type_rejections",
    "semantic_role_type_abstentions",
    "anchor_window_contracts",
    "anchor_window_selected_passages",
    "anchor_window_dropped_passages",
    "anchor_window_input_chars",
    "anchor_window_output_chars",
    "anchor_window_char_reduction_rate",
    "anchor_window_fallbacks",
    "anchor_window_predicate_normalizations",
    "deterministic_answers",
    "join_input_rows",
    "join_output_rows",
    "early_stops",
    "structured_output_failures",
    "structured_output_repairs",
    "grounding_rejections",
    "local_plan_repairs",
    "operator_rewrites",
    "plan_fallbacks",
    "heuristic_plans",
    "typed_plan_templates",
    "field_extremum_templates",
    "polar_comparison_templates",
    "direct_plan_templates",
    "operators_executed",
    "plan_slot_count",
    "plan_join_count",
    "plan_variable_count",
    "plan_output_count",
    "plan_operator_count",
    "plan_complexity",
    "steps_executed",
    "llm_budget_utilization",
    "retrieval_budget_utilization",
    "step_budget_utilization",
    "peak_rss_mb",
    "max_intermediate_binding_size",
    "reoptimizations",
    "mean_selectivity_error",
    "planner_regret",
    "index_build_latency_ms",
    "index_provider_latency_ms",
    "index_embedding_calls",
    "index_cache_hits",
    "index_cache_misses",
    "index_bytes",
    "materialization_reuse_rate",
    "cache_hit_rate",
    "provider_calls",
    "index_cache_hit_rate",
    "total_latency_with_index_ms",
    "total_provider_calls_with_index",
    "phase_token_coverage",
]

LATENCY_METRICS = {
    "latency_ms",
    "wall_latency_ms",
    "provider_latency_ms",
    "index_build_latency_ms",
    "compilation_latency_ms",
    "execution_latency_ms",
    "materialization_latency_ms",
    "generation_latency_ms",
    "wall_latency_with_shared_compile_ms",
}


def load_records(output_dir: Path, stage: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    root = output_dir / "items" / stage
    if not root.exists():
        return records
    for path in sorted(root.rglob("*.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def load_attempt_records(output_dir: Path, stage: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    root = output_dir / "attempts" / stage
    if not root.exists():
        return records
    for path in sorted(root.rglob("attempt-*.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _frozen_plan_audit(
    output_dir: Path,
    stage: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    snapshot_paths = sorted((output_dir / "plans" / stage).rglob("*.json")) if (output_dir / "plans" / stage).exists() else []
    snapshots: list[dict[str, Any]] = []
    invalid_snapshot_count = 0
    for path in snapshot_paths:
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            plan = SlotPlan.model_validate(snapshot["plan"])
            plan_payload = plan.model_dump(mode="json")
            if snapshot.get("status") != "ok" or snapshot.get("plan_sha256") != _canonical_sha256(plan_payload):
                raise ValueError("invalid status or plan hash")
            snapshots.append(snapshot)
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            invalid_snapshot_count += 1

    replay_records: list[dict[str, Any]] = []
    missing_provenance_count = 0
    missing_result_plan_count = 0
    plan_hash_mismatch_count = 0
    pair_hashes: dict[tuple[str, str], set[str]] = defaultdict(set)
    effective_pair_hashes: dict[tuple[str, str], set[str]] = defaultdict(set)
    snapshot_hashes = {str(snapshot["plan_sha256"]) for snapshot in snapshots}
    unknown_snapshot_hash_count = 0
    missing_effective_plan_hash_count = 0
    for record in records:
        raw_metrics = record.get("result", {}).get("metrics", {})
        if record.get("schema_version", 1) < 15 or not raw_metrics.get("frozen_plan_replays"):
            continue
        replay_records.append(record)
        provenance = record.get("plan_provenance")
        if not isinstance(provenance, dict) or provenance.get("status") != "ok" or not provenance.get("plan_sha256"):
            missing_provenance_count += 1
            continue
        provenance_hash = str(provenance["plan_sha256"])
        pair_key = (str(record.get("dataset")), str(record.get("question_id")))
        pair_hashes[pair_key].add(provenance_hash)
        effective_hash = provenance.get("effective_plan_sha256")
        if not effective_hash:
            if record.get("schema_version", 1) >= 16:
                missing_effective_plan_hash_count += 1
            effective_hash = provenance_hash
        effective_hash = str(effective_hash)
        effective_pair_hashes[pair_key].add(effective_hash)
        if snapshot_hashes and provenance_hash not in snapshot_hashes:
            unknown_snapshot_hash_count += 1
        result_plan = record.get("result", {}).get("plan")
        if result_plan is None:
            missing_result_plan_count += 1
            continue
        try:
            normalized_plan = SlotPlan.model_validate(result_plan).model_dump(mode="json")
        except ValueError:
            plan_hash_mismatch_count += 1
            continue
        if _canonical_sha256(normalized_plan) != effective_hash:
            plan_hash_mismatch_count += 1

    compiler_metrics = [
        RunMetrics.model_validate(snapshot.get("compiler_metrics", {}))
        for snapshot in snapshots
    ]
    provider_attempts = [int(snapshot.get("provider_delta", {}).get("attempts", 0)) for snapshot in snapshots]
    provider_retries = [
        sum(
            int(value.get("retries", 0))
            for value in snapshot.get("provider_delta", {}).values()
            if isinstance(value, dict)
        )
        for snapshot in snapshots
    ]
    provider_latencies = [
        sum(
            float(value.get("latency_ms", 0.0))
            for value in snapshot.get("provider_delta", {}).values()
            if isinstance(value, dict)
        )
        for snapshot in snapshots
    ]
    wall_latencies = [float(snapshot.get("wall_latency_ms", 0.0)) for snapshot in snapshots]
    total_tokens = [metrics.prompt_tokens + metrics.completion_tokens for metrics in compiler_metrics]

    attempt_paths = sorted((output_dir / "plan_attempts" / stage).rglob("attempt-*.json")) if (output_dir / "plan_attempts" / stage).exists() else []
    failed_plan_attempts = 0
    for path in attempt_paths:
        try:
            failed_plan_attempts += json.loads(path.read_text(encoding="utf-8")).get("status") != "ok"
        except (OSError, json.JSONDecodeError):
            failed_plan_attempts += 1

    def total(values: list[int | float]) -> int | float:
        return sum(values)

    def mean(values: list[int | float]) -> float | None:
        return float(np.mean(values)) if values else None

    def percentile(values: list[int | float], q: float) -> float | None:
        return float(np.percentile(values, q)) if values else None

    shared_compiler = {
        "llm_calls_total": int(total([metrics.llm_calls for metrics in compiler_metrics])),
        "llm_calls_mean": mean([metrics.llm_calls for metrics in compiler_metrics]),
        "prompt_tokens_total": int(total([metrics.prompt_tokens for metrics in compiler_metrics])),
        "completion_tokens_total": int(total([metrics.completion_tokens for metrics in compiler_metrics])),
        "total_tokens_total": int(total(total_tokens)),
        "total_tokens_mean": mean(total_tokens),
        "total_tokens_p95": percentile(total_tokens, 95),
        "compilation_latency_ms_total": float(total([metrics.compilation_latency_ms for metrics in compiler_metrics])),
        "compilation_latency_ms_mean": mean([metrics.compilation_latency_ms for metrics in compiler_metrics]),
        "compilation_latency_ms_p50": percentile([metrics.compilation_latency_ms for metrics in compiler_metrics], 50),
        "compilation_latency_ms_p95": percentile([metrics.compilation_latency_ms for metrics in compiler_metrics], 95),
        "compilation_latency_ms_p99": percentile([metrics.compilation_latency_ms for metrics in compiler_metrics], 99),
        "wall_latency_ms_total": float(total(wall_latencies)),
        "wall_latency_ms_mean": mean(wall_latencies),
        "wall_latency_ms_p50": percentile(wall_latencies, 50),
        "wall_latency_ms_p95": percentile(wall_latencies, 95),
        "wall_latency_ms_p99": percentile(wall_latencies, 99),
        "provider_attempts_total": int(total(provider_attempts)),
        "provider_attempts_mean": mean(provider_attempts),
        "provider_retries_total": int(total(provider_retries)),
        "provider_latency_ms_total": float(total(provider_latencies)),
        "provider_latency_ms_p95": percentile(provider_latencies, 95),
        "structured_output_failures_total": int(total([metrics.structured_output_failures for metrics in compiler_metrics])),
        "structured_output_repairs_total": int(total([metrics.structured_output_repairs for metrics in compiler_metrics])),
        "plan_fallbacks_total": int(total([metrics.plan_fallbacks for metrics in compiler_metrics])),
        "heuristic_plans_total": int(total([metrics.heuristic_plans for metrics in compiler_metrics])),
        "typed_plan_templates_total": int(total([metrics.typed_plan_templates for metrics in compiler_metrics])),
        "field_extremum_templates_total": int(total([metrics.field_extremum_templates for metrics in compiler_metrics])),
        "polar_comparison_templates_total": int(total([metrics.polar_comparison_templates for metrics in compiler_metrics])),
        "direct_plan_templates_total": int(total([metrics.direct_plan_templates for metrics in compiler_metrics])),
        "plan_slot_count_mean": mean([metrics.plan_slot_count for metrics in compiler_metrics]),
        "plan_join_count_mean": mean([metrics.plan_join_count for metrics in compiler_metrics]),
        "plan_complexity_mean": mean([metrics.plan_complexity for metrics in compiler_metrics]),
    }
    return {
        "enabled": bool(snapshot_paths or replay_records or attempt_paths),
        "snapshot_count": len(snapshot_paths),
        "valid_snapshot_count": len(snapshots),
        "invalid_snapshot_count": invalid_snapshot_count,
        "imported_snapshot_count": sum(snapshot.get("preparation_mode") == "imported" for snapshot in snapshots),
        "source_methods": sorted({str(snapshot.get("source_method")) for snapshot in snapshots}),
        "plan_attempt_count": len(attempt_paths),
        "failed_plan_attempt_count": failed_plan_attempts,
        "replay_record_count": len(replay_records),
        "replay_question_count": len(pair_hashes),
        "missing_provenance_count": missing_provenance_count,
        "missing_result_plan_count": missing_result_plan_count,
        "missing_effective_plan_hash_count": missing_effective_plan_hash_count,
        "plan_hash_mismatch_count": plan_hash_mismatch_count,
        "unknown_snapshot_hash_count": unknown_snapshot_hash_count,
        "inconsistent_pair_count": sum(len(hashes) != 1 for hashes in pair_hashes.values()),
        "effective_plan_variant_question_count": sum(len(hashes) > 1 for hashes in effective_pair_hashes.values()),
        "effective_plan_variant_count": sum(max(len(hashes) - 1, 0) for hashes in effective_pair_hashes.values()),
        "max_effective_plan_variants_per_question": max(
            (len(hashes) for hashes in effective_pair_hashes.values()),
            default=0,
        ),
        "shared_compiler": shared_compiler,
    }


def _fallback_failure_category(record: dict[str, Any]) -> str:
    if category := record.get("failure_category"):
        return str(category)
    result = record.get("result", {})
    status = result.get("status", "failed")
    if status in {"ok", "empty", "budget_exceeded", "unsupported_operation"}:
        return str(status)
    return "other"


def _flat(record: dict[str, Any]) -> dict[str, Any]:
    result = record["result"]
    metrics = RunMetrics().model_dump(mode="python")
    metrics.update(result.get("metrics", {}))
    scores = dict(record.get("scores", {}))
    total_cache_lookups = metrics["cache_hits"] + metrics["cache_misses"]
    total_index_cache_lookups = metrics["index_cache_hits"] + metrics["index_cache_misses"]
    materialization_requests = metrics["materialization_requests"]
    schema_version = record.get("schema_version", 1)
    shared_index_excluded = schema_version >= 3 and record.get("method") != "graphrag"
    phase_names = [
        f"{phase}_{suffix}"
        for phase in ("compilation", "extraction", "planning", "reasoning", "generation")
        for suffix in ("llm_calls", "prompt_tokens", "completion_tokens")
    ]
    phase_metrics = {name: metrics[name] if schema_version >= 4 else None for name in phase_names}
    schema5_metrics = {
        name: metrics[name] if schema_version >= 5 else None
        for name in ("grounding_rejections", "operator_rewrites")
    }
    schema6_metrics = {
        "typed_plan_templates": metrics["typed_plan_templates"] if schema_version >= 6 else None,
    }
    schema7_metrics = {
        "direct_plan_templates": metrics["direct_plan_templates"] if schema_version >= 7 else None,
    }
    schema8_metrics = {
        "answer_span_normalizations": metrics["answer_span_normalizations"] if schema_version >= 8 else None,
    }
    schema10_metrics = {
        "polar_answer_normalizations": metrics["polar_answer_normalizations"] if schema_version >= 10 else None,
    }
    schema11_metrics = {
        "field_extremum_templates": metrics["field_extremum_templates"] if schema_version >= 11 else None,
    }
    schema12_metrics = {
        "polar_comparison_templates": metrics["polar_comparison_templates"] if schema_version >= 12 else None,
    }
    schema13_metrics = {
        "polar_row_consensus": metrics["polar_row_consensus"] if schema_version >= 13 else None,
    }
    schema14_metrics = {
        name: metrics[name] if schema_version >= 14 else None
        for name in (
            "typed_extraction_contracts",
            "typed_extraction_answers",
            "typed_extraction_abstentions",
        )
    }
    schema15_metrics = {
        "frozen_plan_replays": metrics["frozen_plan_replays"] if schema_version >= 15 else None,
    }
    schema16_metrics = {
        "grounded_entity_anchor_folds": metrics["grounded_entity_anchor_folds"] if schema_version >= 16 else None,
    }
    schema17_metrics = {
        "grounded_entity_anchor_substitutions": (
            metrics["grounded_entity_anchor_substitutions"] if schema_version >= 17 else None
        ),
    }
    schema18_metrics = {
        name: metrics[name] if schema_version >= 18 else None
        for name in (
            "role_projected_extraction_contracts",
            "known_binding_fields_projected",
            "protected_anchor_rejections",
        )
    }
    schema20_metrics = {
        "direct_grounded_anchor_projections": (
            metrics["direct_grounded_anchor_projections"] if schema_version >= 20 else None
        ),
    }
    schema21_metrics = {
        name: metrics[name] if schema_version >= 21 else None
        for name in (
            "extraction_thinking_disabled",
            "bound_role_signatures",
            "extraction_length_finishes",
        )
    }
    schema22_metrics = {
        name: metrics[name] if schema_version >= 22 else None
        for name in (
            "semantic_role_type_contracts",
            "semantic_role_type_rejections",
            "semantic_role_type_abstentions",
        )
    }
    schema23_metrics = {
        name: metrics[name] if schema_version >= 23 else None
        for name in (
            "anchor_window_contracts",
            "anchor_window_selected_passages",
            "anchor_window_dropped_passages",
            "anchor_window_input_chars",
            "anchor_window_output_chars",
            "anchor_window_fallbacks",
        )
    }
    schema23_metrics["anchor_window_char_reduction_rate"] = (
        1.0 - metrics["anchor_window_output_chars"] / metrics["anchor_window_input_chars"]
        if schema_version >= 23 and metrics["anchor_window_input_chars"]
        else None
    )
    schema24_metrics = {
        "anchor_window_predicate_normalizations": (
            metrics["anchor_window_predicate_normalizations"] if schema_version >= 24 else None
        ),
    }
    schema25_metrics = {
        "query_grounded_anchor_contexts": (
            metrics["query_grounded_anchor_contexts"] if schema_version >= 25 else None
        ),
    }
    schema26_metrics = {
        name: metrics[name] if schema_version >= 26 else None
        for name in (
            "query_anchor_plan_repairs",
            "evidence_surface_grounding_repairs",
        )
    }
    phase_tokens = sum(
        metrics[f"{phase}_{token_type}_tokens"]
        for phase in ("compilation", "extraction", "planning", "reasoning", "generation")
        for token_type in ("prompt", "completion")
    )
    total_tokens = metrics["prompt_tokens"] + metrics["completion_tokens"]
    plan_provenance = record.get("plan_provenance") or {}
    shared_compiler_metrics: RunMetrics | None = None
    if metrics["frozen_plan_replays"] and isinstance(plan_provenance, dict):
        try:
            shared_compiler_metrics = RunMetrics.model_validate(plan_provenance.get("compiler_metrics", {}))
        except ValueError:
            shared_compiler_metrics = None
    shared_agnes_attempts = 0
    shared_wall_latency_ms = 0.0
    if shared_compiler_metrics is not None:
        provider_delta = plan_provenance.get("provider_delta", {})
        agnes_delta = provider_delta.get("agnes", {}) if isinstance(provider_delta, dict) else {}
        shared_agnes_attempts = int(
            agnes_delta.get("attempts", shared_compiler_metrics.llm_calls)
            if isinstance(agnes_delta, dict)
            else shared_compiler_metrics.llm_calls
        )
        shared_wall_latency_ms = float(
            plan_provenance.get("wall_latency_ms", shared_compiler_metrics.compilation_latency_ms)
        )
    shared_total_tokens = (
        shared_compiler_metrics.prompt_tokens + shared_compiler_metrics.completion_tokens
        if shared_compiler_metrics is not None
        else None
    )
    return {
        "dataset": record["dataset"],
        "method": record["method_label"],
        "base_method": record["method"],
        "question_id": record["question_id"],
        "stratum": str(record.get("stratum") or "unknown"),
        "seed": record["seed"],
        "status": result["status"],
        "failure_category": _fallback_failure_category(record),
        "attempt_index": record.get("attempt_index", 1),
        "plan_sha256": plan_provenance.get("plan_sha256"),
        "effective_plan_sha256": plan_provenance.get("effective_plan_sha256"),
        "frozen_plan_source": plan_provenance.get("source_method"),
        "frozen_plan_preparation_mode": plan_provenance.get("preparation_mode"),
        "cost_scope": "execution_only_shared_plan_excluded" if metrics["frozen_plan_replays"] else "end_to_end",
        "latency_scope": "online_only" if shared_index_excluded else "includes_index",
        "evidence_metric_status": scores.get(
            "evidence_metric_status",
            "computed" if scores.get("evidence_recall") is not None else "N/A",
        ),
        **scores,
        **metrics,
        **phase_metrics,
        **schema5_metrics,
        **schema6_metrics,
        **schema7_metrics,
        **schema8_metrics,
        **schema10_metrics,
        **schema11_metrics,
        **schema12_metrics,
        **schema13_metrics,
        **schema14_metrics,
        **schema15_metrics,
        **schema16_metrics,
        **schema17_metrics,
        **schema18_metrics,
        **schema20_metrics,
        **schema21_metrics,
        **schema22_metrics,
        **schema23_metrics,
        **schema24_metrics,
        **schema25_metrics,
        **schema26_metrics,
        "unique_documents_accessed": metrics["unique_documents_accessed"] if schema_version >= 4 else None,
        "unique_passages_accessed": metrics["unique_passages_accessed"] if schema_version >= 4 else None,
        "total_tokens": total_tokens,
        "llm_calls_with_shared_compile": (
            metrics["llm_calls"] + shared_agnes_attempts
            if shared_compiler_metrics is not None else None
        ),
        "total_tokens_with_shared_compile": (
            total_tokens + shared_total_tokens
            if shared_total_tokens is not None else None
        ),
        "provider_calls_with_shared_compile": (
            metrics["llm_calls"] + metrics["embedding_calls"] + metrics["reranker_calls"] + shared_agnes_attempts
            if shared_compiler_metrics is not None else None
        ),
        "wall_latency_with_shared_compile_ms": (
            metrics["wall_latency_ms"] + shared_wall_latency_ms
            if shared_compiler_metrics is not None else None
        ),
        "max_intermediate_binding_size": max(metrics["intermediate_binding_sizes"], default=0),
        "mean_selectivity_error": _mean(metrics["slot_selectivity_errors"]),
        "materialization_reuse_rate": (
            metrics["materialization_cache_hits"] / materialization_requests
            if materialization_requests else None
        ),
        "cache_hit_rate": metrics["cache_hits"] / total_cache_lookups if total_cache_lookups else None,
        "provider_calls": metrics["llm_calls"] + metrics["embedding_calls"] + metrics["reranker_calls"],
        "index_cache_hit_rate": (
            metrics["index_cache_hits"] / total_index_cache_lookups
            if total_index_cache_lookups else None
        ),
        "total_latency_with_index_ms": (
            metrics["wall_latency_ms"] + metrics["index_build_latency_ms"]
            if shared_index_excluded else metrics["wall_latency_ms"]
        ),
        "total_provider_calls_with_index": (
            metrics["llm_calls"] + metrics["embedding_calls"] + metrics["reranker_calls"] + metrics["index_embedding_calls"]
        ),
        "phase_token_coverage": phase_tokens / total_tokens if schema_version >= 4 and total_tokens else None,
    }


def _mean(values: list[float]) -> float | None:
    return float(np.mean(values)) if values else None


def _aggregate_rows(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(str(row[key]) for key in keys)].append(row)
    output: list[dict[str, Any]] = []
    for group, group_rows in sorted(grouped.items()):
        summary: dict[str, Any] = {
            **dict(zip(keys, group)),
            "count": len(group_rows),
            "failed": sum(row["status"] in {"failed", "budget_exceeded"} for row in group_rows),
            "empty": sum(row["status"] == "empty" for row in group_rows),
            "unsupported": sum(row["status"] == "unsupported_operation" for row in group_rows),
            "success_rate": _mean([float(row["status"] == "ok") for row in group_rows]),
            "primary_valid_count": sum(row.get("primary_score") is not None for row in group_rows),
            "evidence_labeled_count": sum(row.get("evidence_metric_status") == "computed" for row in group_rows),
        }
        failures: dict[str, int] = defaultdict(int)
        for row in group_rows:
            failures[row["failure_category"]] += 1
        summary["failure_categories"] = json.dumps(dict(sorted(failures.items())), ensure_ascii=False)
        for metric in METRICS:
            values = [float(row[metric]) for row in group_rows if row.get(metric) is not None]
            summary[metric] = _mean(values)
            if metric in LATENCY_METRICS and values:
                summary[f"{metric}_p50"] = float(np.percentile(values, 50))
                summary[f"{metric}_p95"] = float(np.percentile(values, 95))
                summary[f"{metric}_p99"] = float(np.percentile(values, 99))
        output.append(summary)
    return output


def aggregate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _aggregate_rows([_flat(record) for record in records], ("dataset", "method"))


def stratified_aggregate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _aggregate_rows([_flat(record) for record in records], ("dataset", "stratum", "method"))


def failure_report(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [_flat(record) for record in records]
    totals: dict[tuple[str, str], int] = defaultdict(int)
    grouped: dict[tuple[str, str, str, str], int] = defaultdict(int)
    for row in rows:
        totals[(row["dataset"], row["method"])] += 1
        grouped[(row["dataset"], row["method"], row["status"], row["failure_category"])] += 1
    return [
        {
            "dataset": dataset,
            "method": method,
            "status": status,
            "failure_category": category,
            "count": count,
            "rate": count / totals[(dataset, method)],
        }
        for (dataset, method, status, category), count in sorted(grouped.items())
    ]


def macro_average(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dataset_method_seed: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in summaries:
        dataset_method_seed[(row["dataset"], row["method"].split("@", 1)[0])].append(row)
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    datasets_by_method: dict[str, set[str]] = defaultdict(set)
    for (dataset, method), rows in dataset_method_seed.items():
        datasets_by_method[method].add(dataset)
        for metric in METRICS:
            values = [float(row[metric]) for row in rows if row.get(metric) is not None]
            if values:
                grouped[method][metric].append(float(np.mean(values)))
    return [
        {
            "method": method,
            "dataset_count": len(datasets_by_method[method]),
            **{metric: _mean(values) for metric, values in metrics.items()},
        }
        for method, metrics in sorted(grouped.items())
    ]


def seed_variance(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in summaries:
        if "@" in row["method"] and row.get("primary_score") is not None:
            grouped[(row["dataset"], row["method"].split("@", 1)[0])].append(float(row["primary_score"]))
    return [
        {
            "dataset": dataset,
            "method": method,
            "seed_count": len(values),
            "primary_mean": float(np.mean(values)),
            "primary_std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
            "primary_min": min(values),
            "primary_max": max(values),
        }
        for (dataset, method), values in sorted(grouped.items())
    ]


def _holm(pairs: list[dict[str, Any]]) -> None:
    for pair in pairs:
        pair["p_holm"] = None
    ranked = sorted(
        ((index, pair) for index, pair in enumerate(pairs) if pair["p_value"] is not None),
        key=lambda item: item[1]["p_value"],
    )
    adjusted: dict[int, float] = {}
    running = 0.0
    total = len(ranked)
    for rank, (index, pair) in enumerate(ranked):
        running = max(running, min(pair["p_value"] * (total - rank), 1.0))
        adjusted[index] = running
    for index, value in adjusted.items():
        pairs[index]["p_holm"] = value


def paired_bootstrap(records: list[dict[str, Any]], *, reference: str = "slotrag", iterations: int = 10_000, seed: int = 2027) -> list[dict[str, Any]]:
    rows = [_flat(record) for record in records]
    raw_values: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in rows:
        raw_values[(row["dataset"], row["base_method"], row["question_id"])].append(float(row["primary_score"]))
    by_dataset_method: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    for (dataset, method, question_id), values in raw_values.items():
        by_dataset_method[(dataset, method)][question_id] = float(np.mean(values))
    datasets = sorted({row["dataset"] for row in rows})
    methods = sorted({row["base_method"] for row in rows if row["base_method"] != reference})
    rng = np.random.default_rng(seed)
    comparisons: list[dict[str, Any]] = []
    for dataset in datasets:
        reference_values = by_dataset_method.get((dataset, reference), {})
        for method in methods:
            candidate_values = by_dataset_method.get((dataset, method), {})
            ids = sorted(set(reference_values) & set(candidate_values))
            if not ids:
                continue
            reference_array = np.asarray([reference_values[item] for item in ids], dtype=float)
            candidate_array = np.asarray([candidate_values[item] for item in ids], dtype=float)
            differences = reference_array - candidate_array
            wins = int(np.sum(differences > 0))
            ties = int(np.sum(np.isclose(differences, 0.0)))
            losses = len(ids) - wins - ties
            pairwise = reference_array[:, None] - candidate_array[None, :]
            cliffs_delta = float((np.sum(pairwise > 0) - np.sum(pairwise < 0)) / pairwise.size)
            effect = {
                "median_difference": float(np.median(differences)),
                "wins": wins,
                "ties": ties,
                "losses": losses,
                "win_rate": wins / len(ids),
                "cliffs_delta": cliffs_delta,
            }
            if len(ids) < 2:
                comparisons.append({
                    "dataset": dataset,
                    "reference": reference,
                    "comparison": method,
                    "count": len(ids),
                    "mean_difference": float(differences.mean()),
                    **effect,
                    "ci_low": None,
                    "ci_high": None,
                    "p_value": None,
                })
                continue
            indices = rng.integers(0, len(differences), size=(iterations, len(differences)))
            bootstrap = differences[indices].mean(axis=1)
            p_value = min(1.0, 2 * min(float(np.mean(bootstrap <= 0)), float(np.mean(bootstrap >= 0))))
            comparisons.append({
                "dataset": dataset,
                "reference": reference,
                "comparison": method,
                "count": len(ids),
                "mean_difference": float(differences.mean()),
                **effect,
                "ci_low": float(np.percentile(bootstrap, 2.5)),
                "ci_high": float(np.percentile(bootstrap, 97.5)),
                "p_value": p_value,
            })
    _holm(comparisons)
    return comparisons


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _retrieval_report(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    columns = [
        "dataset",
        "method",
        "count",
        "primary_score",
        "evidence_labeled_count",
        "evidence_recall_at_1",
        "evidence_recall_at_5",
        "evidence_recall_at_10",
        "evidence_precision_at_5",
        "evidence_ndcg_at_10",
        "documents_accessed",
        "unique_documents_accessed",
        "passages_processed",
        "unique_passages_accessed",
        "retrieved_document_count",
        "retrieval_calls",
        "llm_calls",
        "llm_calls_with_shared_compile",
        "provider_calls",
        "provider_calls_with_shared_compile",
        "total_tokens",
        "total_tokens_with_shared_compile",
        "compilation_llm_calls",
        "extraction_llm_calls",
        "planning_llm_calls",
        "reasoning_llm_calls",
        "generation_llm_calls",
        "wall_latency_ms",
        "wall_latency_with_shared_compile_ms",
        "wall_latency_ms_p95",
        "index_build_latency_ms",
        "index_provider_latency_ms",
        "index_embedding_calls",
        "index_bytes",
        "cache_hit_rate",
        "index_cache_hit_rate",
        "materialization_reuse_rate",
        "grounding_rejections",
        "operator_rewrites",
        "typed_plan_templates",
        "field_extremum_templates",
        "polar_comparison_templates",
        "direct_plan_templates",
        "answer_span_normalizations",
        "polar_row_consensus",
        "typed_extraction_contracts",
        "typed_extraction_answers",
        "typed_extraction_abstentions",
        "frozen_plan_replays",
        "grounded_entity_anchor_folds",
        "grounded_entity_anchor_substitutions",
        "direct_grounded_anchor_projections",
        "role_projected_extraction_contracts",
        "known_binding_fields_projected",
        "protected_anchor_rejections",
        "semantic_role_type_contracts",
        "semantic_role_type_rejections",
        "semantic_role_type_abstentions",
        "anchor_window_contracts",
        "anchor_window_selected_passages",
        "anchor_window_dropped_passages",
        "anchor_window_input_chars",
        "anchor_window_output_chars",
        "anchor_window_char_reduction_rate",
        "anchor_window_fallbacks",
        "anchor_window_predicate_normalizations",
        "query_grounded_anchor_contexts",
        "query_anchor_plan_repairs",
        "evidence_surface_grounding_repairs",
        "operators_executed",
        "structured_output_failures",
        "plan_fallbacks",
        "llm_budget_utilization",
        "retrieval_budget_utilization",
    ]
    return [{key: row.get(key) for key in columns} for row in summaries]


def _expected_record_count(output_dir: Path, stage: str) -> int | None:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        suite = manifest["suite"]
        stage_config = suite["stages"][stage]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None
    requests = [request for request in manifest.get("run_requests", []) if request.get("stage") == stage]
    pairs: set[tuple[str, str]] = set()
    if requests:
        for request in requests:
            pairs.update((dataset, method) for dataset in request.get("datasets", []) for method in request.get("methods", []))
    else:
        pairs.update((dataset, method) for dataset in suite.get("datasets", []) for method in stage_config.get("methods", []))
    random_seed_count = len(suite.get("random_seeds", [])) or 1
    expected = 0
    for dataset, method in pairs:
        sample_path = output_dir / "samples" / stage / f"{dataset}.jsonl"
        try:
            sample_size = sum(1 for line in sample_path.read_text(encoding="utf-8").splitlines() if line.strip())
        except OSError:
            sample_size = int(stage_config.get("sample_size", 0))
        expected += sample_size * (random_seed_count if method == "slotrag-random" else 1)
    return expected


def _validity_report(output_dir: Path, stage: str, records: list[dict[str, Any]], attempt_count: int) -> dict[str, Any]:
    expected = _expected_record_count(output_dir, stage)
    statuses: dict[str, int] = defaultdict(int)
    for record in records:
        statuses[str(record.get("result", {}).get("status", "missing"))] += 1
    return {
        "expected_record_count": expected,
        "observed_record_count": len(records),
        "missing_record_count": max(expected - len(records), 0) if expected is not None else None,
        "completion_rate": len(records) / expected if expected else None,
        "attempt_count": attempt_count,
        "retry_attempt_count": max(attempt_count - len(records), 0),
        "status_counts": dict(sorted(statuses.items())),
        "evidence_labeled_record_count": sum(
            record.get("scores", {}).get("evidence_metric_status") == "computed"
            or record.get("scores", {}).get("evidence_recall") is not None
            for record in records
        ),
        "schema_versions": sorted({record.get("schema_version", 1) for record in records}),
    }


def summarize_run(output_dir: Path, stage: str) -> dict[str, Any]:
    records = load_records(output_dir, stage)
    attempts = load_attempt_records(output_dir, stage)
    attempt_records = attempts or records
    per_question = [_flat(record) for record in records]
    summaries = aggregate(records)
    stratified = stratified_aggregate(records)
    macro = macro_average(summaries)
    variance = seed_variance(summaries)
    comparisons = paired_bootstrap(records) if records else []
    failures = failure_report(attempt_records)
    retrieval = _retrieval_report(summaries)
    validity = _validity_report(output_dir, stage, records, len(attempts))
    frozen_plan_audit = _frozen_plan_audit(output_dir, stage, records)
    report = {
        "stage": stage,
        "record_count": len(records),
        "attempt_count": len(attempts),
        "failure_report_source": "immutable_attempts" if attempts else "final_records_legacy_fallback",
        "validity": validity,
        "summary": summaries,
        "stratified_summary": stratified,
        "macro_average": macro,
        "failure_report": failures,
        "seed_variance": variance,
        "paired_bootstrap": comparisons,
        "frozen_plan_audit": frozen_plan_audit,
    }
    summary_dir = output_dir / "summaries" / stage
    summary_dir.mkdir(parents=True, exist_ok=True)
    (summary_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(summary_dir / "per_question.csv", per_question)
    _write_csv(summary_dir / "metrics.csv", summaries)
    _write_csv(summary_dir / "stratified_metrics.csv", stratified)
    _write_csv(summary_dir / "macro_metrics.csv", macro)
    _write_csv(summary_dir / "retrieval_metrics.csv", retrieval)
    _write_csv(summary_dir / "failure_report.csv", failures)
    _write_csv(summary_dir / "seed_variance.csv", variance)
    _write_csv(summary_dir / "paired_bootstrap.csv", comparisons)
    frozen_plan_row = {
        key: value
        for key, value in frozen_plan_audit.items()
        if key != "shared_compiler"
    }
    frozen_plan_row.update({
        f"shared_compiler_{key}": value
        for key, value in frozen_plan_audit["shared_compiler"].items()
    })
    _write_csv(summary_dir / "frozen_plan_metrics.csv", [frozen_plan_row])
    (summary_dir / "frozen_plan_audit.json").write_text(
        json.dumps(frozen_plan_audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# SlotRAG Experiment Report",
        "",
        f"- Stage: `{stage}`",
        f"- Final records: {len(records)}",
        f"- Immutable attempts: {len(attempts)}",
        f"- Failure report source: {'immutable attempts' if attempts else 'legacy final-record fallback'}",
        f"- Expected records: {validity['expected_record_count'] if validity['expected_record_count'] is not None else 'N/A'}",
        f"- Completion rate: {validity['completion_rate'] if validity['completion_rate'] is not None else 'N/A'}",
        f"- Frozen plan snapshots/replays: {frozen_plan_audit['snapshot_count']}/{frozen_plan_audit['replay_record_count']}",
        f"- Imported snapshots/effective-plan variant questions/extra variants: {frozen_plan_audit['imported_snapshot_count']}/{frozen_plan_audit['effective_plan_variant_question_count']}/{frozen_plan_audit['effective_plan_variant_count']}",
        f"- Frozen plan hash mismatches/inconsistent pairs: {frozen_plan_audit['plan_hash_mismatch_count']}/{frozen_plan_audit['inconsistent_pair_count']}",
        "- Evidence quality metrics are N/A for datasets without gold evidence labels.",
        "",
        "## Method Summary",
        "",
    ]
    for row in summaries:
        lines.append(
            f"- {row['dataset']} / {row['method']}: primary={row['primary_score']}, "
            f"failed={row['failed']}/{row['count']}, unsupported={row['unsupported']}"
        )
    (summary_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
