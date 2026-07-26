import csv

import pytest

from slotrag.benchmarking.paired import PairedAnalysisError, analyze_paired_csv, analyze_paired_rows


def _rows():
    rows = []
    for dataset in ("alpha", "beta"):
        for question_id in ("q1", "q2"):
            for method, score in (("plain", 0.0), ("grounding", 1.0), ("guard", 2.0)):
                rows.append({
                    "dataset": dataset,
                    "question_id": question_id,
                    "base_method": method,
                    "primary_score": score,
                    "em": score / 2,
                })
    return rows


def test_paired_analysis_recovers_preregistered_treatment_effects():
    report = analyze_paired_rows(
        _rows(),
        comparisons=[("guard_vs_plain", "guard", "plain"), ("guard_vs_grounding", "guard", "grounding")],
        metrics=["primary_score", "em"],
        iterations=200,
        seed=7,
    )

    overall = {
        (row["metric"], row["comparison"]): row
        for row in report["contrasts"]
        if row["scope"] == "overall"
    }
    assert overall[("primary_score", "guard_vs_plain")]["estimate"] == pytest.approx(2.0)
    assert overall[("primary_score", "guard_vs_grounding")]["estimate"] == pytest.approx(1.0)
    assert overall[("em", "guard_vs_plain")]["estimate"] == pytest.approx(1.0)
    assert all(overall[("primary_score", name)]["p_holm"] is not None for name in (
        "guard_vs_plain", "guard_vs_grounding"
    ))
    assert overall[("em", "guard_vs_plain")]["p_holm"] is None
    assert all(row["count"] == 4 for row in overall.values())


def test_paired_analysis_rejects_duplicate_or_missing_method_records():
    duplicate = _rows()
    duplicate.append(dict(duplicate[0]))
    with pytest.raises(PairedAnalysisError, match="duplicate"):
        analyze_paired_rows(
            duplicate,
            comparisons=[("guard_vs_plain", "guard", "plain")],
            metrics=["primary_score"],
            iterations=100,
        )

    missing = _rows()[1:]
    with pytest.raises(PairedAnalysisError, match="missing"):
        analyze_paired_rows(
            missing,
            comparisons=[("guard_vs_plain", "guard", "plain")],
            metrics=["primary_score"],
            iterations=100,
        )


def test_paired_analysis_writes_hashed_machine_readable_artifacts(tmp_path):
    source = tmp_path / "per_question.csv"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_rows()[0]))
        writer.writeheader()
        writer.writerows(_rows())

    report = analyze_paired_csv(
        source,
        tmp_path / "analysis",
        comparisons=[("guard_vs_plain", "guard", "plain")],
        metrics=["primary_score"],
        iterations=100,
        seed=7,
    )

    assert report["input"]["sha256"]
    assert report["analysis"]["implementation_sha256"]
    assert (tmp_path / "analysis" / "paired_analysis.json").is_file()
    assert (tmp_path / "analysis" / "paired_contrasts.csv").is_file()
