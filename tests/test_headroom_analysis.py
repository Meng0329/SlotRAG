from __future__ import annotations

import json
from pathlib import Path

from tools.analyze_slotrag_headroom import analyze_run_dirs


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")


def _sample(question_id: str) -> dict[str, object]:
    return {
        "id": question_id,
        "question": "Which city?",
        "answers": ["Paris"],
        "gold_evidence": ["gold#0"],
        "passages": [
            {"id": "gold#0", "doc_id": "gold", "text": "The answer is Paris."},
            {"id": "distractor#0", "doc_id": "distractor", "text": "The answer is London."},
        ],
        "metadata": {"dataset": "demo", "stratum": "short", "evidence_available": True},
    }


def _item(
    run: Path,
    *,
    method: str,
    question_id: str,
    primary: float,
    prediction: str,
    evidence: list[dict[str, object]],
    metrics: dict[str, object] | None = None,
    status: str = "ok",
    error: str | None = None,
    budget: dict[str, object] | None = None,
) -> None:
    payload = {
        "schema_version": 28,
        "stage": "demo",
        "dataset": "demo",
        "method": method,
        "question_id": question_id,
        "stratum": "short",
        "answers": ["Paris"],
        "budget": budget or {"max_steps": 4, "max_retrieval_calls": 4},
        "result": {
            "status": status,
            "error": error,
            "answer": prediction,
            "rows": [{"answer": "Paris"}] if evidence else [],
            "evidence": evidence,
            "metrics": metrics or {},
            "plan": {"slots": [{"id": "S1"}], "joins": [], "outputs": ["?answer"]},
        },
        "scores": {
            "prediction_scored": prediction,
            "primary_score": primary,
            "em": primary,
            "f1": primary,
            "evidence_metric_status": "computed",
            "evidence_recall_at_10": 1.0 if evidence else 0.0,
        },
    }
    item_path = run / "items" / "demo" / method / f"{question_id}-{method}.json"
    _write_json(item_path, payload)


def _run_with_sample(tmp_path: Path, name: str) -> Path:
    run = tmp_path / name
    sample_path = run / "samples" / "demo" / "demo.jsonl"
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    sample_path.write_text(json.dumps(_sample("q1")) + "\n", encoding="utf-8")
    return run


def test_headroom_reports_pairs_coverage_errors_and_counterfactuals(tmp_path: Path) -> None:
    run = _run_with_sample(tmp_path, "v1")
    _item(
        run,
        method="candidate",
        question_id="q1",
        primary=0.0,
        prediction="London",
        evidence=[{"source_id": "distractor#0", "source_span": "The answer is London."}],
        metrics={"binding_contexts_pruned": 1, "frontier_guard_interventions": 1},
    )
    _item(
        run,
        method="reference",
        question_id="q1",
        primary=1.0,
        prediction="Paris",
        evidence=[{"source_id": "gold#0", "source_span": "The answer is Paris."}],
    )

    report = analyze_run_dirs([run])

    pair = report["pairwise"][0]
    assert pair["wins"] == 0
    assert pair["ties"] == 0
    assert pair["losses"] == 1
    coverage = {row["mechanism"]: row for row in report["coverage"]}
    assert coverage["binding_contexts_pruned"]["affected_questions"] == 1
    assert report["errors"][0]["category"] == "BINDING_PRUNED"
    counterfactuals = {row["name"]: row for row in report["counterfactuals"]}
    assert counterfactuals["full_evidence_answer_topk"]["count"] == 1
    assert counterfactuals["rows_correct_final_wrong"]["count"] == 1


def test_headroom_reports_budget_marginal_gain_and_missing_retrieval_fields(tmp_path: Path) -> None:
    low = _run_with_sample(tmp_path, "low")
    high = _run_with_sample(tmp_path, "high")
    _item(
        low,
        method="slotrag",
        question_id="q1",
        primary=0.0,
        prediction="London",
        evidence=[],
        budget={"max_steps": 2, "max_retrieval_calls": 2},
    )
    _item(
        high,
        method="slotrag",
        question_id="q1",
        primary=1.0,
        prediction="Paris",
        evidence=[{"source_id": "gold#0", "source_span": "The answer is Paris."}],
        budget={"max_steps": 4, "max_retrieval_calls": 4},
    )

    report = analyze_run_dirs([low, high])

    assert report["budget_marginal_gains"][0]["delta_primary"] == 1.0
    assert report["retrieval_relationships"]["status"] == "N/A"
