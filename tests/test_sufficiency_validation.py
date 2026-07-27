import json

import pytest

from slotrag.benchmarking.sufficiency_validation import (
    build_frozen_runtime_artifact,
    evaluate_frozen_sufficiency,
    write_immutable_validation_report,
)
from slotrag.models import BindingRow
from slotrag.sufficiency import EvidenceContext, SufficiencyExample


def _calibrator(*, weight: float, intercept: float) -> dict[str, object]:
    return {
        "feature_schema_version": 2,
        "feature_names": ["row_count"],
        "means": [0.0],
        "scales": [1.0],
        "weights": [weight],
        "intercept": intercept,
        "sufficient_threshold": 0.5,
        "partial_threshold": 0.3,
    }


def test_frozen_sufficiency_selection_is_evaluated_without_validation_selection(tmp_path):
    rows = []
    for index, label in enumerate((0, 1, 0, 1)):
        question_id = f"validation-{index}"
        example = SufficiencyExample(
            example_id=f"toy:{question_id}:S1:0",
            label=label,
            context=EvidenceContext(
                retrieval_backend="bm25",
                extracted_rows=(
                    [BindingRow(
                        slot_id="S1",
                        bindings={"answer": "alpha"},
                        source_id=f"p{index}",
                        source_span="alpha",
                        confidence=1.0,
                    )]
                    if label
                    else []
                ),
            ),
        ).model_dump(mode="json")
        rows.append({
            **example,
            "dataset": "toy",
            "question_id": question_id,
            "supervision": "strong_gold_evidence",
            "retrieval_protocol": "global_corpus",
            "retrieval_backend": "bm25",
        })
    examples_path = tmp_path / "examples.jsonl"
    examples_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    selected_name = "structural_backend_raw@l2=0.1"
    legacy_name = "legacy_v1@l2=0.1"
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(json.dumps({
        "schema_version": 2,
        "experiment": "toy-v65",
        "dataset": "toy",
        "source_split": "train",
        "provider_calls": 0,
        "holdout_used_for_selection": False,
        "requires_disjoint_development_confirmation": True,
        "selected_feature_group": selected_name,
        "candidates": {
            selected_name: {
                "feature_group": "structural_backend_raw",
                "inner_cv": {"brier_score": 0.1},
                "inner_predictions": [{"question_id": "old-fit"}],
                "holdout_predictions": [{"question_id": "old-holdout"}],
                "final_calibrator": _calibrator(weight=10.0, intercept=-5.0),
            },
            legacy_name: {
                "feature_group": "legacy_v1",
                "inner_cv": {"brier_score": 0.2},
                "inner_predictions": [{"question_id": "old-fit"}],
                "holdout_predictions": [{"question_id": "old-holdout"}],
                "final_calibrator": _calibrator(weight=0.0, intercept=0.0),
            },
        },
    }), encoding="utf-8")

    report = evaluate_frozen_sufficiency(
        examples_path=examples_path,
        selection_artifact_paths=[selection_path],
        bootstrap_iterations=200,
        seed=2027,
    )

    dataset = report["datasets"]["toy"]
    assert report["provider_calls"] == 0
    assert report["validation_used_for_selection"] is False
    assert dataset["validation_question_overlap_count"] == 0
    assert dataset["selected_candidate"] == selected_name
    assert dataset["comparator_candidate"] == legacy_name
    assert dataset["selected_metrics"]["brier_score"] < dataset["comparator_metrics"]["brier_score"]
    assert dataset["paired_brier_delta"]["mean"] < 0.0
    assert len(dataset["predictions"]) == 4


def test_validation_report_is_immutable(tmp_path):
    output_path = tmp_path / "validation.json"

    write_immutable_validation_report(output_path, {"schema_version": 1, "provider_calls": 0})

    assert json.loads(output_path.read_text(encoding="utf-8"))["provider_calls"] == 0
    with pytest.raises(FileExistsError, match="immutable validation output"):
        write_immutable_validation_report(output_path, {"schema_version": 2})


def test_runtime_artifact_merges_selected_calibrators_without_refitting(tmp_path):
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(json.dumps({
        "schema_version": 2,
        "dataset": "toy",
        "source_split": "train",
        "holdout_used_for_selection": False,
        "requires_disjoint_development_confirmation": True,
        "selected_feature_group": "full_v2@l2=0.01",
        "candidates": {
            "full_v2@l2=0.01": {
                "feature_group": "full_v2",
                "inner_cv": {"brier_score": 0.1},
                "inner_predictions": [{"question_id": "fit-1"}, {"question_id": "fit-2"}],
                "holdout_predictions": [{"question_id": "holdout-1"}],
                "final_calibrator": _calibrator(weight=1.0, intercept=0.0),
            },
        },
    }), encoding="utf-8")

    artifact = build_frozen_runtime_artifact(
        selection_artifact_paths=[selection_path],
        retrieval_protocol="global_corpus",
        retrieval_backend="bm25",
        created_at="2026-07-27T00:00:00+00:00",
    )

    assert artifact["source_split"] == "train"
    assert artifact["retrieval_protocol"] == "global_corpus"
    assert artifact["retrieval_backend"] == "bm25"
    assert artifact["example_counts"] == {"toy": 2}
    assert artifact["calibrators"]["toy"]["weights"] == [1.0]
    assert artifact["training_manifest_sha256"]
