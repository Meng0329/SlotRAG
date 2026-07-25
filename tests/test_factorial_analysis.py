import csv

import pytest

from slotrag.benchmarking.factorial import FactorialAnalysisError, analyze_factorial_csv, analyze_factorial_rows


_METHODS = {
    ("off", "slot"): "slotrag",
    ("off", "always"): "slotrag-dual-query-retrieval",
    ("off", "unbound"): "slotrag-adaptive-dual-query-retrieval",
    ("on", "slot"): "slotrag-grounded-role-projection",
    ("on", "always"): "slotrag-grounded-dual-query-retrieval",
    ("on", "unbound"): "slotrag-grounded-adaptive-dual-query-retrieval",
}


def _rows():
    rows = []
    # Off/slot=0; grounding=+1; always=+2; unbound=+3; interactions are +4/+5.
    scores = {
        ("off", "slot"): 0.0,
        ("off", "always"): 2.0,
        ("off", "unbound"): 3.0,
        ("on", "slot"): 1.0,
        ("on", "always"): 7.0,
        ("on", "unbound"): 9.0,
    }
    for dataset in ("alpha", "beta"):
        for question_id in ("q1", "q2"):
            for cell, method in _METHODS.items():
                rows.append({
                    "dataset": dataset,
                    "question_id": question_id,
                    "base_method": method,
                    "primary_score": scores[cell],
                })
    return rows


def test_factorial_analysis_recovers_preregistered_main_and_interaction_effects():
    report = analyze_factorial_rows(_rows(), metrics=["primary_score"], iterations=200, seed=7)

    contrasts = {
        row["contrast"]: row
        for row in report["contrasts"]
        if row["scope"] == "overall" and row["metric"] == "primary_score"
    }

    assert contrasts["grounding_main"]["estimate"] == pytest.approx(4.0)
    assert contrasts["always_minus_slot"]["estimate"] == pytest.approx(4.0)
    assert contrasts["unbound_minus_slot"]["estimate"] == pytest.approx(5.5)
    assert contrasts["grounding_x_always"]["estimate"] == pytest.approx(4.0)
    assert contrasts["grounding_x_unbound"]["estimate"] == pytest.approx(5.0)
    assert all(row["p_holm"] is not None for row in contrasts.values())
    assert all(row["count"] == 4 for row in contrasts.values())


def test_factorial_analysis_rejects_duplicate_or_missing_cell_records():
    duplicate = _rows()
    duplicate.append(dict(duplicate[0]))
    with pytest.raises(FactorialAnalysisError, match="duplicate"):
        analyze_factorial_rows(duplicate, metrics=["primary_score"], iterations=100)

    missing = _rows()[1:]
    with pytest.raises(FactorialAnalysisError, match="missing"):
        analyze_factorial_rows(missing, metrics=["primary_score"], iterations=100)


def test_factorial_analysis_writes_machine_readable_artifacts(tmp_path):
    source = tmp_path / "per_question.csv"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_rows()[0]))
        writer.writeheader()
        writer.writerows(_rows())

    report = analyze_factorial_csv(source, tmp_path / "analysis", metrics=["primary_score"], iterations=100, seed=7)

    assert report["input"]["sha256"]
    assert (tmp_path / "analysis" / "factorial_analysis.json").is_file()
    assert (tmp_path / "analysis" / "factorial_cell_means.csv").is_file()
    assert (tmp_path / "analysis" / "factorial_contrasts.csv").is_file()
