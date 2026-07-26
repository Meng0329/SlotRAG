import csv

import pytest

from tools.analyze_fixed_main import analyze_fixed_main


def _write(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _rows(method, offset):
    return [
        {
            "dataset": dataset,
            "method": method,
            "base_method": method,
            "question_id": question_id,
            "status": "ok",
            "primary_score": str(offset + index),
            "em": str(offset + index),
        }
        for dataset in ("alpha", "beta")
        for question_id, index in (("q1", 0), ("q2", 1))
    ]


def test_analyze_fixed_main_writes_stratified_paired_report(tmp_path):
    candidate = tmp_path / "candidate.csv"
    baseline = tmp_path / "baseline.csv"
    _write(candidate, _rows("guard", 2))
    _write(baseline, _rows("slotrag", 0))

    report = analyze_fixed_main(
        candidate,
        baseline,
        tmp_path / "analysis",
        candidate_method="guard",
        baseline_methods=("slotrag",),
        iterations=200,
        seed=7,
    )

    primary = [
        row
        for row in report["paired_analysis"]["contrasts"]
        if row["metric"] == "primary_score" and row["scope"] == "overall"
    ]
    assert primary[0]["estimate"] == pytest.approx(2.0)
    assert primary[0]["count"] == 4
    assert primary[0]["p_value"] is not None
    assert (tmp_path / "analysis" / "paired_input.csv").is_file()
    assert (tmp_path / "analysis" / "paired_analysis.json").is_file()
    assert (tmp_path / "analysis" / "paired_contrasts.csv").is_file()


def test_analyze_fixed_main_rejects_missing_cross_run_question(tmp_path):
    candidate = tmp_path / "candidate.csv"
    baseline = tmp_path / "baseline.csv"
    _write(candidate, _rows("guard", 2))
    _write(baseline, _rows("slotrag", 0)[:-1])

    with pytest.raises(ValueError, match="question key mismatch"):
        analyze_fixed_main(
            candidate,
            baseline,
            tmp_path / "analysis",
            candidate_method="guard",
            baseline_methods=("slotrag",),
            iterations=200,
            seed=7,
        )
