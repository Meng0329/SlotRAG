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
from slotrag.models import RunMetrics


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
