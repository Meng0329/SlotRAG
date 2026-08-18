import hashlib
import json

from slotrag.benchmarking.statistics import (
    aggregate,
    failure_report,
    macro_average,
    paired_bootstrap,
    seed_variance,
    stratified_aggregate,
    summarize_run,
)
from slotrag.models import RunMetrics, SlotPlan


def _record(method, question_id, score, seed=2027, label=None):
    return {
        "dataset": "hotpotqa",
        "method": method,
        "method_label": label or method,
        "question_id": question_id,
        "stratum": "bridge" if question_id == "q1" else "comparison",
        "seed": seed,
        "scores": {
            "primary_score": score,
            "em": score,
            "f1": score,
            "accuracy": None,
            "drop_em": None,
            "drop_f1": None,
            "evidence_recall": None,
            "evidence_mrr": None,
        },
        "result": {"status": "ok", "error": None, "metrics": RunMetrics().model_dump(mode="json")},
    }


def test_statistics_include_macro_seed_variance_and_paired_comparisons():
    records = [
        _record("slotrag", "q1", 1.0),
        _record("slotrag", "q2", 0.5),
        _record("hybrid", "q1", 0.0),
        _record("hybrid", "q2", 0.0),
        _record("slotrag-random", "q1", 0.2, 1, "slotrag-random@1"),
        _record("slotrag-random", "q2", 0.4, 1, "slotrag-random@1"),
        _record("slotrag-random", "q1", 0.4, 2, "slotrag-random@2"),
        _record("slotrag-random", "q2", 0.6, 2, "slotrag-random@2"),
    ]
    summaries = aggregate(records)
    assert any(row["method"] == "slotrag" and row["primary_score"] == 0.75 for row in summaries)
    macro = macro_average(summaries)
    assert any(row["method"] == "slotrag" for row in macro)
    assert "frontier_guard_checks" in macro[0]
    assert "frontier_guard_interventions" in macro[0]
    assert "frontier_candidates_pruned" in macro[0]
    variance = seed_variance(summaries)
    assert variance[0]["seed_count"] == 2
    comparisons = paired_bootstrap(records, iterations=100, seed=7)
    assert {row["comparison"] for row in comparisons} == {"hybrid", "slotrag-random"}
    hybrid = next(row for row in comparisons if row["comparison"] == "hybrid")
    assert hybrid["wins"] == 2
    assert hybrid["win_rate"] == 1.0
    assert hybrid["cliffs_delta"] == 1.0


def test_paired_bootstrap_marks_single_pair_as_insufficient():
    comparisons = paired_bootstrap(
        [_record("slotrag", "q1", 1.0), _record("hybrid", "q1", 0.0)],
        iterations=100,
        seed=7,
    )
    assert comparisons == [{
        "dataset": "hotpotqa",
        "reference": "slotrag",
        "comparison": "hybrid",
        "count": 1,
        "mean_difference": 1.0,
        "median_difference": 1.0,
        "wins": 1,
        "ties": 0,
        "losses": 0,
        "win_rate": 1.0,
        "cliffs_delta": 1.0,
        "ci_low": None,
        "ci_high": None,
        "p_value": None,
        "p_holm": None,
    }]


def test_stratified_and_attempt_failure_reports_do_not_hide_retries():
    records = [_record("slotrag", "q1", 1.0), _record("slotrag", "q2", 0.0)]
    strata = stratified_aggregate(records)
    assert {(row["stratum"], row["count"]) for row in strata} == {("bridge", 1), ("comparison", 1)}

    failed_attempt = _record("slotrag", "q1", 0.0)
    failed_attempt["result"]["status"] = "failed"
    failed_attempt["failure_category"] = "provider_http_5xx"
    rows = failure_report([failed_attempt, records[0]])
    assert any(row["failure_category"] == "provider_http_5xx" and row["count"] == 1 for row in rows)
    assert any(row["failure_category"] == "ok" and row["count"] == 1 for row in rows)


def test_schema5_reports_grounding_and_operator_rewrite_metrics_without_backfilling_legacy():
    current = _record("slotrag", "q1", 1.0)
    current["schema_version"] = 5
    current["result"]["metrics"] = RunMetrics(
        grounding_rejections=2,
        operator_rewrites=1,
    ).model_dump(mode="json")
    legacy = _record("hybrid", "q1", 1.0)
    legacy["schema_version"] = 4

    rows = aggregate([current, legacy])
    current_summary = next(row for row in rows if row["method"] == "slotrag")
    legacy_summary = next(row for row in rows if row["method"] == "hybrid")

    assert current_summary["grounding_rejections"] == 2
    assert current_summary["operator_rewrites"] == 1
    assert legacy_summary["grounding_rejections"] is None
    assert legacy_summary["operator_rewrites"] is None


def test_schema6_reports_typed_plan_templates_without_backfilling_schema5():
    current = _record("slotrag", "q1", 1.0)
    current["schema_version"] = 6
    current["result"]["metrics"] = RunMetrics(
        typed_plan_templates=1,
    ).model_dump(mode="json")
    legacy = _record("hybrid", "q1", 1.0)
    legacy["schema_version"] = 5

    rows = aggregate([current, legacy])
    current_summary = next(row for row in rows if row["method"] == "slotrag")
    legacy_summary = next(row for row in rows if row["method"] == "hybrid")

    assert current_summary["typed_plan_templates"] == 1
    assert legacy_summary["typed_plan_templates"] is None


def test_schema7_reports_direct_plan_templates_without_backfilling_schema6():
    current = _record("slotrag", "q1", 1.0)
    current["schema_version"] = 7
    current["result"]["metrics"] = RunMetrics(
        direct_plan_templates=1,
    ).model_dump(mode="json")
    legacy = _record("hybrid", "q1", 1.0)
    legacy["schema_version"] = 6

    rows = aggregate([current, legacy])
    current_summary = next(row for row in rows if row["method"] == "slotrag")
    legacy_summary = next(row for row in rows if row["method"] == "hybrid")

    assert current_summary["direct_plan_templates"] == 1
    assert legacy_summary["direct_plan_templates"] is None


def test_schema8_reports_answer_span_normalizations_without_backfilling_schema7():
    current = _record("slotrag", "q1", 1.0)
    current["schema_version"] = 8
    current["result"]["metrics"] = RunMetrics(
        answer_span_normalizations=1,
    ).model_dump(mode="json")
    legacy = _record("hybrid", "q1", 1.0)
    legacy["schema_version"] = 7

    rows = aggregate([current, legacy])
    current_summary = next(row for row in rows if row["method"] == "slotrag")
    legacy_summary = next(row for row in rows if row["method"] == "hybrid")

    assert current_summary["answer_span_normalizations"] == 1
    assert legacy_summary["answer_span_normalizations"] is None


def test_schema10_reports_polar_answer_normalizations_without_backfilling_schema9():
    current = _record("slotrag", "q1", 1.0)
    current["schema_version"] = 10
    current["result"]["metrics"] = RunMetrics(
        polar_answer_normalizations=1,
    ).model_dump(mode="json")
    legacy = _record("hybrid", "q1", 1.0)
    legacy["schema_version"] = 9

    rows = aggregate([current, legacy])
    current_summary = next(row for row in rows if row["method"] == "slotrag")
    legacy_summary = next(row for row in rows if row["method"] == "hybrid")

    assert current_summary["polar_answer_normalizations"] == 1
    assert legacy_summary["polar_answer_normalizations"] is None


def test_schema11_reports_field_extremum_templates_without_backfilling_schema10():
    current = _record("slotrag", "q1", 1.0)
    current["schema_version"] = 11
    current["result"]["metrics"] = RunMetrics(
        field_extremum_templates=1,
    ).model_dump(mode="json")
    legacy = _record("hybrid", "q1", 1.0)
    legacy["schema_version"] = 10

    rows = aggregate([current, legacy])
    current_summary = next(row for row in rows if row["method"] == "slotrag")
    legacy_summary = next(row for row in rows if row["method"] == "hybrid")

    assert current_summary["field_extremum_templates"] == 1
    assert legacy_summary["field_extremum_templates"] is None


def test_schema12_reports_polar_comparison_templates_without_backfilling_schema11():
    current = _record("slotrag", "q1", 1.0)
    current["schema_version"] = 12
    current["result"]["metrics"] = RunMetrics(
        polar_comparison_templates=1,
    ).model_dump(mode="json")
    legacy = _record("hybrid", "q1", 1.0)
    legacy["schema_version"] = 11

    rows = aggregate([current, legacy])
    current_summary = next(row for row in rows if row["method"] == "slotrag")
    legacy_summary = next(row for row in rows if row["method"] == "hybrid")

    assert current_summary["polar_comparison_templates"] == 1
    assert legacy_summary["polar_comparison_templates"] is None


def test_schema13_reports_polar_row_consensus_without_backfilling_schema12():
    current = _record("slotrag", "q1", 1.0)
    current["schema_version"] = 13
    current["result"]["metrics"] = RunMetrics(
        polar_row_consensus=1,
    ).model_dump(mode="json")
    legacy = _record("hybrid", "q1", 1.0)
    legacy["schema_version"] = 12

    rows = aggregate([current, legacy])
    current_summary = next(row for row in rows if row["method"] == "slotrag")
    legacy_summary = next(row for row in rows if row["method"] == "hybrid")

    assert current_summary["polar_row_consensus"] == 1
    assert legacy_summary["polar_row_consensus"] is None


def test_schema14_reports_typed_extraction_metrics_without_backfilling_schema13():
    current = _record("slotrag", "q1", 1.0)
    current["schema_version"] = 14
    current["result"]["metrics"] = RunMetrics(
        typed_extraction_contracts=1,
        typed_extraction_answers=1,
        typed_extraction_abstentions=0,
    ).model_dump(mode="json")
    legacy = _record("hybrid", "q1", 1.0)
    legacy["schema_version"] = 13

    rows = aggregate([current, legacy])
    current_summary = next(row for row in rows if row["method"] == "slotrag")
    legacy_summary = next(row for row in rows if row["method"] == "hybrid")

    assert current_summary["typed_extraction_contracts"] == 1
    assert current_summary["typed_extraction_answers"] == 1
    assert current_summary["typed_extraction_abstentions"] == 0
    assert legacy_summary["typed_extraction_contracts"] is None
    assert legacy_summary["typed_extraction_answers"] is None
    assert legacy_summary["typed_extraction_abstentions"] is None


def test_schema15_reports_frozen_plan_replays_without_backfilling_schema14():
    current = _record("slotrag", "q1", 1.0)
    current["schema_version"] = 15
    current["result"]["metrics"] = RunMetrics(frozen_plan_replays=1).model_dump(mode="json")
    legacy = _record("hybrid", "q1", 1.0)
    legacy["schema_version"] = 14

    rows = aggregate([current, legacy])
    current_summary = next(row for row in rows if row["method"] == "slotrag")
    legacy_summary = next(row for row in rows if row["method"] == "hybrid")

    assert current_summary["frozen_plan_replays"] == 1
    assert legacy_summary["frozen_plan_replays"] is None


def test_schema16_reports_grounded_anchor_folds_without_backfilling_schema15():
    current = _record("slotrag-anchor-folding", "q1", 1.0)
    current["schema_version"] = 16
    current["result"]["metrics"] = RunMetrics(grounded_entity_anchor_folds=1).model_dump(mode="json")
    legacy = _record("slotrag", "q1", 1.0)
    legacy["schema_version"] = 15

    rows = aggregate([current, legacy])
    current_summary = next(row for row in rows if row["method"] == "slotrag-anchor-folding")
    legacy_summary = next(row for row in rows if row["method"] == "slotrag")

    assert current_summary["grounded_entity_anchor_folds"] == 1
    assert legacy_summary["grounded_entity_anchor_folds"] is None


def test_schema17_reports_anchor_substitutions_without_backfilling_schema16():
    current = _record("slotrag-anchor-substitution", "q1", 1.0)
    current["schema_version"] = 17
    current["result"]["metrics"] = RunMetrics(
        grounded_entity_anchor_substitutions=1,
    ).model_dump(mode="json")
    legacy = _record("slotrag-anchor-folding", "q1", 1.0)
    legacy["schema_version"] = 16

    rows = aggregate([current, legacy])
    current_summary = next(row for row in rows if row["method"] == "slotrag-anchor-substitution")
    legacy_summary = next(row for row in rows if row["method"] == "slotrag-anchor-folding")

    assert current_summary["grounded_entity_anchor_substitutions"] == 1
    assert legacy_summary["grounded_entity_anchor_substitutions"] is None


def test_schema18_reports_role_projection_without_backfilling_schema17():
    current = _record("slotrag-role-projected-substitution", "q1", 1.0)
    current["schema_version"] = 18
    current["result"]["metrics"] = RunMetrics(
        role_projected_extraction_contracts=2,
        known_binding_fields_projected=1,
        protected_anchor_rejections=1,
    ).model_dump(mode="json")
    legacy = _record("slotrag-anchor-substitution", "q1", 1.0)
    legacy["schema_version"] = 17

    rows = aggregate([current, legacy])
    current_summary = next(
        row for row in rows if row["method"] == "slotrag-role-projected-substitution"
    )
    legacy_summary = next(row for row in rows if row["method"] == "slotrag-anchor-substitution")

    assert current_summary["role_projected_extraction_contracts"] == 2
    assert current_summary["known_binding_fields_projected"] == 1
    assert current_summary["protected_anchor_rejections"] == 1
    assert legacy_summary["role_projected_extraction_contracts"] is None
    assert legacy_summary["known_binding_fields_projected"] is None
    assert legacy_summary["protected_anchor_rejections"] is None


def test_schema20_reports_direct_anchor_projection_without_backfilling_schema19():
    current = _record("slotrag-grounded-role-projection", "q1", 1.0)
    current["schema_version"] = 20
    current["result"]["metrics"] = RunMetrics(
        direct_grounded_anchor_projections=1,
    ).model_dump(mode="json")
    legacy = _record("slotrag-role-projected-substitution", "q1", 1.0)
    legacy["schema_version"] = 19

    rows = aggregate([current, legacy])
    current_summary = next(
        row for row in rows if row["method"] == "slotrag-grounded-role-projection"
    )
    legacy_summary = next(
        row for row in rows if row["method"] == "slotrag-role-projected-substitution"
    )

    assert current_summary["direct_grounded_anchor_projections"] == 1
    assert legacy_summary["direct_grounded_anchor_projections"] is None


def test_schema21_reports_extraction_phase_controls_without_backfilling_schema20():
    current = _record("slotrag-lean-grounded-role-projection", "q1", 1.0)
    current["schema_version"] = 21
    current["result"]["metrics"] = RunMetrics(
        extraction_thinking_disabled=2,
        bound_role_signatures=2,
        extraction_length_finishes=1,
    ).model_dump(mode="json")
    legacy = _record("slotrag-grounded-role-projection", "q1", 1.0)
    legacy["schema_version"] = 20

    rows = aggregate([current, legacy])
    current_summary = next(
        row for row in rows if row["method"] == "slotrag-lean-grounded-role-projection"
    )
    legacy_summary = next(
        row for row in rows if row["method"] == "slotrag-grounded-role-projection"
    )

    assert current_summary["extraction_thinking_disabled"] == 2
    assert current_summary["bound_role_signatures"] == 2
    assert current_summary["extraction_length_finishes"] == 1
    assert legacy_summary["extraction_thinking_disabled"] is None
    assert legacy_summary["bound_role_signatures"] is None
    assert legacy_summary["extraction_length_finishes"] is None


def test_schema22_reports_role_type_filter_without_backfilling_schema21():
    current = _record("slotrag-grounded-role-type-filter", "q1", 1.0)
    current["schema_version"] = 22
    current["result"]["metrics"] = RunMetrics(
        semantic_role_type_contracts=2,
        semantic_role_type_rejections=1,
        semantic_role_type_abstentions=1,
    ).model_dump(mode="json")
    legacy = _record("slotrag-grounded-role-projection", "q1", 1.0)
    legacy["schema_version"] = 21

    rows = aggregate([current, legacy])
    current_summary = next(
        row for row in rows if row["method"] == "slotrag-grounded-role-type-filter"
    )
    legacy_summary = next(
        row for row in rows if row["method"] == "slotrag-grounded-role-projection"
    )

    assert current_summary["semantic_role_type_contracts"] == 2
    assert current_summary["semantic_role_type_rejections"] == 1
    assert current_summary["semantic_role_type_abstentions"] == 1
    assert legacy_summary["semantic_role_type_contracts"] is None
    assert legacy_summary["semantic_role_type_rejections"] is None
    assert legacy_summary["semantic_role_type_abstentions"] is None


def test_schema23_reports_anchor_windows_without_backfilling_schema22():
    current = _record("slotrag-anchor-window-projection", "q1", 1.0)
    current["schema_version"] = 23
    current["result"]["metrics"] = RunMetrics(
        anchor_window_contracts=2,
        anchor_window_selected_passages=2,
        anchor_window_dropped_passages=6,
        anchor_window_input_chars=1000,
        anchor_window_output_chars=250,
        anchor_window_fallbacks=0,
    ).model_dump(mode="json")
    legacy = _record("slotrag-grounded-role-projection", "q1", 1.0)
    legacy["schema_version"] = 22

    rows = aggregate([current, legacy])
    current_summary = next(row for row in rows if row["method"] == "slotrag-anchor-window-projection")
    legacy_summary = next(row for row in rows if row["method"] == "slotrag-grounded-role-projection")

    assert current_summary["anchor_window_contracts"] == 2
    assert current_summary["anchor_window_selected_passages"] == 2
    assert current_summary["anchor_window_dropped_passages"] == 6
    assert current_summary["anchor_window_input_chars"] == 1000
    assert current_summary["anchor_window_output_chars"] == 250
    assert current_summary["anchor_window_char_reduction_rate"] == 0.75
    assert current_summary["anchor_window_fallbacks"] == 0
    assert legacy_summary["anchor_window_contracts"] is None
    assert legacy_summary["anchor_window_char_reduction_rate"] is None


def test_schema24_reports_predicate_normalizations_without_backfilling_schema23():
    current = _record("slotrag-normalized-anchor-window-projection", "q1", 1.0)
    current["schema_version"] = 24
    current["result"]["metrics"] = RunMetrics(
        anchor_window_contracts=1,
        anchor_window_predicate_normalizations=1,
    ).model_dump(mode="json")
    legacy = _record("slotrag-anchor-window-projection", "q1", 1.0)
    legacy["schema_version"] = 23

    rows = aggregate([current, legacy])
    current_summary = next(
        row for row in rows if row["method"] == "slotrag-normalized-anchor-window-projection"
    )
    legacy_summary = next(row for row in rows if row["method"] == "slotrag-anchor-window-projection")

    assert current_summary["anchor_window_predicate_normalizations"] == 1
    assert legacy_summary["anchor_window_predicate_normalizations"] is None


def test_schema25_reports_query_anchor_context_without_backfilling_schema24():
    current = _record("slotrag-context-normalized-anchor-window-projection", "q1", 1.0)
    current["schema_version"] = 25
    current["result"]["metrics"] = RunMetrics(query_grounded_anchor_contexts=1).model_dump(mode="json")
    legacy = _record("slotrag-normalized-anchor-window-projection", "q1", 1.0)
    legacy["schema_version"] = 24

    rows = aggregate([current, legacy])
    current_summary = next(
        row for row in rows if row["method"] == "slotrag-context-normalized-anchor-window-projection"
    )
    legacy_summary = next(row for row in rows if row["method"] == "slotrag-normalized-anchor-window-projection")

    assert current_summary["query_grounded_anchor_contexts"] == 1
    assert legacy_summary["query_grounded_anchor_contexts"] is None


def test_schema26_reports_plan_and_surface_repairs_without_backfilling_schema25():
    current = _record("slotrag-repaired-context-anchor-window-projection", "q1", 1.0)
    current["schema_version"] = 26
    current["result"]["metrics"] = RunMetrics(
        query_anchor_plan_repairs=1,
        evidence_surface_grounding_repairs=1,
    ).model_dump(mode="json")
    legacy = _record("slotrag-context-normalized-anchor-window-projection", "q1", 1.0)
    legacy["schema_version"] = 25

    rows = aggregate([current, legacy])
    current_summary = next(
        row for row in rows if row["method"] == "slotrag-repaired-context-anchor-window-projection"
    )
    legacy_summary = next(
        row for row in rows if row["method"] == "slotrag-context-normalized-anchor-window-projection"
    )

    assert current_summary["query_anchor_plan_repairs"] == 1
    assert current_summary["evidence_surface_grounding_repairs"] == 1
    assert legacy_summary["query_anchor_plan_repairs"] is None
    assert legacy_summary["evidence_surface_grounding_repairs"] is None


def test_schema31_reports_executable_action_effects_without_backfilling_schema30():
    current = _record("slotrag-qo", "q1", 1.0)
    current["schema_version"] = 31
    current["result"]["metrics"] = RunMetrics(
        evidence_sufficiency_decisions=2,
        physical_action_executions=2,
        physical_action_extra_retrieval_calls=1,
        physical_action_rows_added=1,
    ).model_dump(mode="json")
    legacy = _record("slotrag", "q1", 1.0)
    legacy["schema_version"] = 30

    rows = aggregate([current, legacy])
    current_summary = next(row for row in rows if row["method"] == "slotrag-qo")
    legacy_summary = next(row for row in rows if row["method"] == "slotrag")

    assert current_summary["evidence_sufficiency_decisions"] == 2
    assert current_summary["physical_action_executions"] == 2
    assert current_summary["physical_action_extra_retrieval_calls"] == 1
    assert current_summary["physical_action_rows_added"] == 1
    assert legacy_summary["physical_action_executions"] is None
    assert legacy_summary["physical_action_extra_retrieval_calls"] is None
    assert legacy_summary["physical_action_rows_added"] is None


def test_schema32_reports_dual_access_and_complementary_effects_without_backfill():
    current = _record("slotrag-dual-access", "q1", 1.0)
    current["schema_version"] = 32
    current["result"]["metrics"] = RunMetrics(
        dual_access_batches=2,
        dual_access_logical_queries=4,
        dual_access_candidate_union=15,
        dual_access_candidate_overlap=3,
        complementary_retrieval_actions=1,
        complementary_retrieval_novel_passages=2,
        complementary_retrieval_novel_rows=1,
    ).model_dump(mode="json")
    legacy = _record("slotrag", "q1", 1.0)
    legacy["schema_version"] = 31

    rows = aggregate([current, legacy])
    current_summary = next(row for row in rows if row["method"] == "slotrag-dual-access")
    legacy_summary = next(row for row in rows if row["method"] == "slotrag")

    assert current_summary["dual_access_batches"] == 2
    assert current_summary["dual_access_logical_queries"] == 4
    assert current_summary["dual_access_mean_union_size"] == 7.5
    assert current_summary["dual_access_mean_overlap_size"] == 1.5
    assert current_summary["complementary_retrieval_actions"] == 1
    assert current_summary["complementary_retrieval_novel_passages"] == 2
    assert current_summary["complementary_retrieval_novel_rows"] == 1
    assert legacy_summary["dual_access_batches"] is None
    assert legacy_summary["complementary_retrieval_actions"] is None


def test_summarize_run_audits_shared_frozen_plan_cost_and_pair_hashes(tmp_path):
    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "Answer", "arguments": ["?answer"]}],
        "outputs": ["?answer"],
    })
    plan_payload = plan.model_dump(mode="json")
    plan_sha256 = hashlib.sha256(json.dumps(
        plan_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    compiler_metrics = RunMetrics(
        llm_calls=1,
        prompt_tokens=11,
        completion_tokens=3,
        compilation_llm_calls=1,
        compilation_prompt_tokens=11,
        compilation_completion_tokens=3,
        compilation_latency_ms=12.5,
    ).model_dump(mode="json")
    provenance = {
        "status": "ok",
        "source_method": "slotrag",
        "plan_sha256": plan_sha256,
        "compiler_metrics": compiler_metrics,
        "wall_latency_ms": 20.0,
        "provider_delta": {
            "attempts": 2,
            "agnes": {"attempts": 2, "successes": 1, "retries": 1, "latency_ms": 18.0, "request_ids": ["r1"]},
        },
    }
    for method in ("slotrag", "slotrag-typed-extraction"):
        record = _record(method, "q1", 1.0)
        record["schema_version"] = 15
        record["result"]["plan"] = plan_payload
        record["result"]["metrics"] = RunMetrics(frozen_plan_replays=1).model_dump(mode="json")
        record["plan_provenance"] = provenance
        item_path = tmp_path / "items" / "test" / "hotpotqa" / method / "q1.json"
        item_path.parent.mkdir(parents=True, exist_ok=True)
        item_path.write_text(json.dumps(record), encoding="utf-8")

    snapshot = {
        "status": "ok",
        "source_method": "slotrag",
        "plan_sha256": plan_sha256,
        "plan": plan_payload,
        "compiler_metrics": compiler_metrics,
        "wall_latency_ms": 20.0,
        "provider_delta": {
            "attempts": 2,
            "agnes": {"attempts": 2, "successes": 1, "retries": 1, "latency_ms": 18.0, "request_ids": ["r1"]},
        },
    }
    snapshot_path = tmp_path / "plans" / "test" / "hotpotqa" / "q1.json"
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    report = summarize_run(tmp_path, "test")
    audit = report["frozen_plan_audit"]

    assert audit["enabled"] is True
    assert audit["snapshot_count"] == 1
    assert audit["invalid_snapshot_count"] == 0
    assert audit["replay_record_count"] == 2
    assert audit["replay_question_count"] == 1
    assert audit["plan_hash_mismatch_count"] == 0
    assert audit["inconsistent_pair_count"] == 0
    assert audit["shared_compiler"]["llm_calls_total"] == 1
    assert audit["shared_compiler"]["total_tokens_total"] == 14
    assert audit["shared_compiler"]["provider_attempts_total"] == 2
    assert audit["shared_compiler"]["provider_retries_total"] == 1
    slotrag_summary = next(row for row in report["summary"] if row["method"] == "slotrag")
    assert slotrag_summary["llm_calls_with_shared_compile"] == 2
    assert slotrag_summary["total_tokens_with_shared_compile"] == 14
    assert slotrag_summary["wall_latency_with_shared_compile_ms"] == 20
    assert slotrag_summary["provider_calls_with_shared_compile"] == 2
    summary_dir = tmp_path / "summaries" / "test"
    assert (summary_dir / "frozen_plan_audit.json").exists()
    assert (summary_dir / "frozen_plan_metrics.csv").exists()


def test_frozen_plan_audit_distinguishes_shared_source_from_effective_variants(tmp_path):
    source_plan = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "Person", "arguments": ["Alpha", "?entity"]},
            {"id": "S2", "predicate": "Answer", "arguments": ["?entity", "?answer"]},
        ],
        "joins": [["S1.entity", "S2.entity"]],
        "outputs": ["?answer"],
    })
    effective_plan = SlotPlan.model_validate({
        "slots": [{
            "id": "S2",
            "predicate": "Answer",
            "arguments": ["?entity", "?answer"],
            "constraints": {"entity": "Alpha"},
        }],
        "outputs": ["?answer"],
    })

    def plan_hash(plan):
        return hashlib.sha256(json.dumps(
            plan.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()

    source_hash = plan_hash(source_plan)
    for method, result_plan in (("slotrag", source_plan), ("slotrag-anchor-folding", effective_plan)):
        record = _record(method, "q1", 1.0)
        record["schema_version"] = 16
        record["result"]["plan"] = result_plan.model_dump(mode="json")
        record["result"]["metrics"] = RunMetrics(frozen_plan_replays=1).model_dump(mode="json")
        record["plan_provenance"] = {
            "status": "ok",
            "source_method": "slotrag",
            "plan_sha256": source_hash,
            "effective_plan_sha256": plan_hash(result_plan),
        }
        path = tmp_path / "items" / "test" / "hotpotqa" / method / "q1.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")

    snapshot_path = tmp_path / "plans" / "test" / "hotpotqa" / "q1.json"
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_text(json.dumps({
        "status": "ok",
        "source_method": "slotrag",
        "plan_sha256": source_hash,
        "plan": source_plan.model_dump(mode="json"),
        "preparation_mode": "imported",
    }), encoding="utf-8")

    audit = summarize_run(tmp_path, "test")["frozen_plan_audit"]

    assert audit["plan_hash_mismatch_count"] == 0
    assert audit["inconsistent_pair_count"] == 0
    assert audit["effective_plan_variant_question_count"] == 1
    assert audit["effective_plan_variant_count"] == 1
    assert audit["max_effective_plan_variants_per_question"] == 2
    assert audit["imported_snapshot_count"] == 1


def test_summarize_run_writes_complete_analysis_artifacts(tmp_path):
    record = _record("slotrag", "q1", 1.0)
    record["scores"]["evidence_recall"] = 1.0
    item_path = tmp_path / "items" / "test" / "hotpotqa" / "slotrag" / "q1.json"
    item_path.parent.mkdir(parents=True)
    item_path.write_text(json.dumps(record), encoding="utf-8")
    attempt_path = tmp_path / "attempts" / "test" / "hotpotqa" / "slotrag" / "q1" / "attempt-0001.json"
    attempt_path.parent.mkdir(parents=True)
    attempt_path.write_text(json.dumps(record), encoding="utf-8")

    report = summarize_run(tmp_path, "test")

    assert report["record_count"] == 1
    assert report["attempt_count"] == 1
    assert report["validity"]["evidence_labeled_record_count"] == 1
    summary_dir = tmp_path / "summaries" / "test"
    for filename in (
        "per_question.csv",
        "metrics.csv",
        "stratified_metrics.csv",
        "macro_metrics.csv",
        "retrieval_metrics.csv",
        "failure_report.csv",
        "seed_variance.csv",
        "paired_bootstrap.csv",
        "summary.json",
        "REPORT.md",
    ):
        assert (summary_dir / filename).exists()


def test_cohens_d_paired():
    from slotrag.benchmarking.statistics import cohens_d
    # constant shift => d = inf (zero difference variance), mean positive
    d = cohens_d([1.0, 1.0, 1.0], [0.0, 0.0, 0.0])
    assert d > 0
    # no difference => 0
    assert cohens_d([0.5, 0.5], [0.5, 0.5]) == 0.0
    # reverse shift => negative
    assert cohens_d([0.0, 0.0], [1.0, 1.0]) < 0


def test_cohens_d_requires_equal_length():
    from slotrag.benchmarking.statistics import cohens_d
    try:
        cohens_d([1.0], [1.0, 2.0])
        assert False, "should raise"
    except ValueError:
        pass


def test_mcnemar_exact():
    from slotrag.benchmarking.statistics import mcnemar
    # b=5 candidate-only wins, c=0 reference-only wins => discordant 5, exact p tiny
    cand = [1, 1, 1, 1, 1, 0, 0]
    ref = [0, 0, 0, 0, 0, 0, 0]
    r = mcnemar(cand, ref)
    assert r["candidate_only_wins_b"] == 5
    assert r["reference_only_wins_c"] == 0
    assert r["discordant_pairs"] == 5
    assert r["p_exact"] < 0.1
    # symmetric split b=c=2 => p not significant (exact two-sided ~ 1.0 realm)
    r2 = mcnemar([1, 1, 0, 0], [0, 0, 1, 1])
    assert r2["candidate_only_wins_b"] == 2 and r2["reference_only_wins_c"] == 2


def test_mcnemar_requires_equal_length():
    from slotrag.benchmarking.statistics import mcnemar
    try:
        mcnemar([1], [0, 1])
        assert False, "should raise"
    except ValueError:
        pass


def test_cluster_bootstrap_ci():
    from slotrag.benchmarking.statistics import cluster_bootstrap_ci
    # two clusters with DIFFERENT within-cluster means => cluster-level variance
    # (c1 diff 0.6, c2 diff 0.2) so resampling clusters yields nonzero se.
    a = [1.0, 1.0, 0.8, 0.8]
    b = [0.4, 0.4, 0.6, 0.6]
    cl = ["c1", "c1", "c2", "c2"]
    r = cluster_bootstrap_ci(a, b, cluster_ids=cl, iterations=4000, seed=7)
    assert r["clusters"] == 2
    assert r["mean_weighted"] > 0
    assert r["ci_low"] > 0 and r["ci_high"] > 0  # systematically positive
    assert r["se"] > 0


def test_cluster_bootstrap_ci_requires_clusters():
    from slotrag.benchmarking.statistics import cluster_bootstrap_ci
    try:
        cluster_bootstrap_ci([1.0, 1.0], [0.0, 0.0], cluster_ids=["only1"], iterations=10)
        assert False, "should raise"
    except ValueError:
        pass
