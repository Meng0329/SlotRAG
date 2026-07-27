from slotrag.benchmarking.action_runtime_analysis import analyze_runtime_records
from slotrag.models import RunMetrics


def _record(method, question_id, score, *, answer, selected=(), executed=()):
    metrics = RunMetrics(
        physical_action_decisions=len(selected),
        physical_action_selected=list(selected),
        physical_action_executions=len(executed),
        physical_action_executed=list(executed),
        retrieval_calls=2,
        prompt_tokens=10,
        completion_tokens=2,
        wall_latency_ms=20,
    )
    return {
        "schema_version": 31,
        "dataset": "hotpotqa",
        "method": method,
        "method_label": method,
        "question_id": question_id,
        "seed": 2027,
        "scores": {"primary_score": score, "prediction_scored": answer},
        "result": {
            "status": "ok",
            "answer": answer,
            "rows": [{"answer": answer}],
            "evidence": [{"source_id": f"{question_id}-{answer}"}],
            "metrics": metrics.model_dump(mode="json"),
        },
    }


def test_runtime_analysis_exposes_unexecuted_actions_and_treatment_deltas():
    records = [
        _record("slotrag", "q1", 1.0, answer="A"),
        _record("slotrag", "q2", 0.0, answer="B"),
        _record("slotrag-qo", "q1", 0.0, answer="C", selected=("EXPAND_TOPK",)),
        _record("slotrag-qo", "q2", 0.0, answer="B", selected=("ABSTAIN",)),
    ]

    report = analyze_runtime_records(records)
    qo = next(row for row in report["cells"] if row["method"] == "slotrag-qo")
    comparison = report["comparisons"][0]

    assert qo["selected_action_usage"] == {"ABSTAIN": 1, "EXPAND_TOPK": 1}
    assert qo["executed_action_usage"] == {}
    assert qo["selected_action_execution_coverage"] == 0.0
    assert qo["unexecuted_action_usage"] == {"ABSTAIN": 1, "EXPAND_TOPK": 1}
    assert comparison["mean_primary_delta_treatment_minus_reference"] == -0.5
    assert comparison["gain_tie_loss"] == {"gain": 0, "tie": 1, "loss": 1}
    assert comparison["answer_exact_match_rate"] == 0.5


def test_runtime_analysis_matches_selected_and_executed_action_multisets():
    records = [
        _record("slotrag", "q1", 0.0, answer="A"),
        _record(
            "slotrag-qo",
            "q1",
            1.0,
            answer="B",
            selected=("EXPAND_TOPK", "ANSWER"),
            executed=("EXPAND_TOPK", "ANSWER"),
        ),
    ]

    qo = next(
        row for row in analyze_runtime_records(records)["cells"]
        if row["method"] == "slotrag-qo"
    )

    assert qo["selected_action_execution_coverage"] == 1.0
    assert qo["unexecuted_action_usage"] == {}
