import csv
import json

from slotrag.benchmarking.grounding_audit import (
    analyze_grounding_changes,
    audit_grounding_run,
)
from slotrag.benchmarking.factorial import CELL_METHODS


def _question_rows(question_id, scores):
    rows = []
    for cell, method in CELL_METHODS.items():
        primary, em, f1 = scores[cell]
        rows.append({
            "dataset": "dataset-a",
            "question_id": question_id,
            "method": method,
            "base_method": method,
            "status": "ok",
            "failure_category": "ok",
            "prediction_scored": f"{question_id}-{cell[0]}-{cell[1]}",
            "primary_score": primary,
            "em": em,
            "f1": f1,
            "direct_grounded_anchor_projections": int(cell[0] == "on"),
            "role_projected_extraction_contracts": int(cell[0] == "on"),
            "known_binding_fields_projected": int(cell[0] == "on"),
            "protected_anchor_rejections": 0,
            "grounding_rejections": 0,
            "evidence_surface_grounding_repairs": 0,
        })
    return rows


def _constant_cells(off_slot, on_slot, *, off_always=None, on_always=None):
    off_always = off_slot if off_always is None else off_always
    on_always = on_slot if on_always is None else on_always
    return {
        ("off", "slot"): off_slot,
        ("off", "always"): off_always,
        ("off", "unbound"): off_slot,
        ("on", "slot"): on_slot,
        ("on", "always"): on_always,
        ("on", "unbound"): on_slot,
    }


def test_grounding_audit_classifies_exact_overlap_and_factor_only_changes():
    rows = []
    rows += _question_rows("exact", _constant_cells((0, 0, 0), (1, 1, 1)))
    rows += _question_rows("overlap", _constant_cells((0, 0, 0), (0.5, 0, 0.5)))
    rows += _question_rows(
        "factor-only",
        _constant_cells((0, 0, 0), (0, 0, 0), off_always=(0, 0, 0), on_always=(1, 1, 1)),
    )
    rows += _question_rows("tie", _constant_cells((1, 1, 1), (1, 1, 1)))

    report = analyze_grounding_changes(rows)

    assert report["summary"] == {
        "question_count": 4,
        "nonzero_grounding_main_count": 3,
        "classification_counts": {
            "candidate_exact_gain": 1,
            "candidate_overlap_only_gain": 1,
            "factor_only_no_candidate_change": 1,
        },
        "candidate_overall": {
            "primary_score_delta": 0.375,
            "em_delta": 0.25,
            "f1_delta": 0.375,
        },
    }
    assert [case["question_id"] for case in report["cases"]] == [
        "exact",
        "factor-only",
        "overlap",
    ]
    assert {case["question_id"]: case["classification"] for case in report["cases"]} == {
        "exact": "candidate_exact_gain",
        "factor-only": "factor_only_no_candidate_change",
        "overlap": "candidate_overlap_only_gain",
    }
    assert len(report["cases"][0]["cells"]) == 6


def test_grounding_run_audit_indexes_immutable_artifacts(tmp_path):
    run_dir = tmp_path / "run"
    summary_dir = run_dir / "summaries" / "factorial_ablation"
    sample_dir = run_dir / "samples" / "factorial_ablation"
    summary_dir.mkdir(parents=True)
    sample_dir.mkdir(parents=True)
    rows = _question_rows("q1", _constant_cells((0, 0, 0), (1, 1, 1)))
    with (summary_dir / "per_question.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (sample_dir / "dataset-a.jsonl").write_text(
        json.dumps({"id": "q1", "question": "Question?", "answers": ["Answer"]}) + "\n",
        encoding="utf-8",
    )
    for method in CELL_METHODS.values():
        stem = "q1-deadbeef"
        item = run_dir / "items" / "factorial_ablation" / "dataset-a" / method / f"{stem}.json"
        attempt = run_dir / "attempts" / "factorial_ablation" / "dataset-a" / method / stem / "attempt-0001.json"
        trace = run_dir / "traces" / "factorial_ablation" / "dataset-a" / method / stem / "attempt-0001.jsonl"
        item.parent.mkdir(parents=True, exist_ok=True)
        attempt.parent.mkdir(parents=True, exist_ok=True)
        trace.parent.mkdir(parents=True, exist_ok=True)
        item.write_text("{}\n", encoding="utf-8")
        attempt.write_text("{}\n", encoding="utf-8")
        trace.write_text("{}\n", encoding="utf-8")

    report = audit_grounding_run(run_dir, "factorial_ablation")

    assert report["input"]["per_question_sha256"]
    assert report["analysis"]["implementation_sha256"]
    assert report["cases"][0]["question"] == "Question?"
    assert report["cases"][0]["answers"] == ["Answer"]
    for cell in report["cases"][0]["cells"]:
        assert set(cell["artifacts"]) == {"final", "attempt", "trace"}
        assert all(entry["sha256"] for entry in cell["artifacts"].values())
    assert (summary_dir / "grounding_mechanism_audit.json").is_file()
