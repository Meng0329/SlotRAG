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
    assert any(row["method"] == "slotrag" for row in macro_average(summaries))
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
