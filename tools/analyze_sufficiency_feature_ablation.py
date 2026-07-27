#!/usr/bin/env python3
"""Run fit-only grouped CV over preregistered sufficiency feature groups."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from slotrag.concurrency import atomic_write_json
from slotrag.sufficiency import (
    EvidenceSufficiencyCalibrator,
    SUFFICIENCY_FEATURE_NAMES,
    SUFFICIENCY_FEATURE_NAMES_V1,
    SufficiencyExample,
)


STRUCTURAL_FEATURES = (
    "new_entity_coverage",
    "source_diversity",
    "predicate_coverage",
    "bound_variable_coverage",
    "join_edge_coverage",
    "extraction_consistency",
    "row_count",
    "remaining_plan_depth",
    "budget_remaining",
    "budget_fraction",
    "retrieval_count",
)
LEGACY_SCORE_FEATURES = (
    "top1_score",
    "topk_score",
    "topk_min_score",
    "top1_top2_margin",
    "score_entropy",
    "sparse_dense_agreement",
    "reranker_agreement",
)
BACKEND_RAW_FEATURES = (
    "backend_top1_score",
    "backend_top1_top2_margin",
)
BACKEND_SHAPE_FEATURES = (
    "backend_margin_ratio",
    "backend_top1_share",
    "backend_relative_entropy",
    "backend_score_iqr_ratio",
    "backend_top1_robust_zscore",
    "backend_rank_discounted_mass",
)
FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "structural_only": STRUCTURAL_FEATURES,
    "legacy_v1": SUFFICIENCY_FEATURE_NAMES_V1,
    "structural_backend_raw": STRUCTURAL_FEATURES + BACKEND_RAW_FEATURES,
    "structural_backend_shape": STRUCTURAL_FEATURES + BACKEND_SHAPE_FEATURES,
    "structural_backend_all": STRUCTURAL_FEATURES + BACKEND_RAW_FEATURES + BACKEND_SHAPE_FEATURES,
    "full_v2": SUFFICIENCY_FEATURE_NAMES,
}
REGULARIZATION_VALUES = (0.001, 0.01, 0.1, 1.0)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                example = SufficiencyExample.model_validate({
                    key: raw[key]
                    for key in ("example_id", "label", "context")
                })
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"invalid example at {path}:{line_number}: {exc}") from exc
            rows.append({
                "dataset": str(raw.get("dataset") or ""),
                "question_id": str(raw.get("question_id") or ""),
                "example": example,
            })
    if not rows:
        raise ValueError(f"no sufficiency examples found: {path}")
    return rows


def _fold(question_id: str, folds: int) -> int:
    return int(hashlib.sha256(question_id.encode("utf-8")).hexdigest(), 16) % folds


def _metrics(labels: Sequence[int], probabilities: Sequence[float], predicted: Sequence[bool]) -> dict[str, float | int]:
    label_array = np.asarray(labels, dtype=int)
    probability_array = np.asarray(probabilities, dtype=float)
    predicted_array = np.asarray(predicted, dtype=bool)
    clipped = np.clip(probability_array, 1e-12, 1 - 1e-12)
    true_positive = int(np.sum(predicted_array & (label_array == 1)))
    false_positive = int(np.sum(predicted_array & (label_array == 0)))
    false_negative = int(np.sum(~predicted_array & (label_array == 1)))
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    ece = 0.0
    for bin_index in range(10):
        lower = bin_index / 10
        upper = (bin_index + 1) / 10
        selected = (probability_array >= lower) & (
            probability_array < upper if bin_index < 9 else probability_array <= upper
        )
        count = int(np.sum(selected))
        if count:
            ece += count / len(labels) * abs(
                float(np.mean(probability_array[selected])) - float(np.mean(label_array[selected]))
            )
    return {
        "example_count": len(labels),
        "positive_count": int(np.sum(label_array == 1)),
        "negative_count": int(np.sum(label_array == 0)),
        "brier_score": float(np.mean((probability_array - label_array) ** 2)),
        "log_loss": float(-np.mean(label_array * np.log(clipped) + (1 - label_array) * np.log(1 - clipped))),
        "expected_calibration_error": ece,
        "binary_accuracy": float(np.mean(predicted_array == label_array)),
        "binary_precision": precision,
        "binary_recall": recall,
    }


def _predict_rows(
    calibrator: EvidenceSufficiencyCalibrator,
    rows: Sequence[dict[str, Any]],
) -> tuple[dict[str, float | int], list[dict[str, Any]]]:
    labels: list[int] = []
    probabilities: list[float] = []
    predicted: list[bool] = []
    output: list[dict[str, Any]] = []
    for row in rows:
        example: SufficiencyExample = row["example"]
        prediction = calibrator.predict(example.context)
        labels.append(example.label)
        probabilities.append(prediction.probability)
        predicted.append(prediction.probability >= calibrator.sufficient_threshold)
        output.append({
            "example_id": example.example_id,
            "question_id": row["question_id"],
            "label": example.label,
            "probability": prediction.probability,
            "status": prediction.status,
        })
    return _metrics(labels, probabilities, predicted), output


def analyze_feature_ablation(
    *,
    examples_path: Path,
    calibration_report_path: Path,
    output_path: Path,
    folds: int = 5,
) -> dict[str, Any]:
    if folds < 2:
        raise ValueError("folds must be at least two")
    if output_path.exists():
        raise FileExistsError(f"immutable ablation output already exists: {output_path}")
    rows = _load_rows(examples_path)
    datasets = {row["dataset"] for row in rows}
    if len(datasets) != 1:
        raise ValueError("feature ablation requires exactly one dataset")
    dataset = datasets.pop()
    report = json.loads(calibration_report_path.read_text(encoding="utf-8"))
    dataset_report = report["datasets"][dataset]
    fit_question_ids = set(dataset_report["fit_question_ids"])
    holdout_question_ids = set(dataset_report["holdout_question_ids"])
    if fit_question_ids & holdout_question_ids:
        raise ValueError("fit and holdout question ids overlap")
    fit_rows = [row for row in rows if row["question_id"] in fit_question_ids]
    holdout_rows = [row for row in rows if row["question_id"] in holdout_question_ids]
    if len(fit_rows) != dataset_report["fit_example_count"]:
        raise ValueError("fit example inventory does not match calibration report")
    if len(holdout_rows) != dataset_report["holdout_example_count"]:
        raise ValueError("holdout example inventory does not match calibration report")

    candidates: dict[str, Any] = {}
    for group_name, feature_names in FEATURE_GROUPS.items():
        for l2 in REGULARIZATION_VALUES:
            candidate_name = f"{group_name}@l2={l2:g}"
            inner_predictions: list[dict[str, Any]] = []
            completed_folds: list[int] = []
            for fold_index in range(folds):
                inner_train = [row for row in fit_rows if _fold(row["question_id"], folds) != fold_index]
                inner_validation = [row for row in fit_rows if _fold(row["question_id"], folds) == fold_index]
                if not inner_validation or len({row["example"].label for row in inner_train}) < 2:
                    continue
                calibrator = EvidenceSufficiencyCalibrator.fit(
                    [row["example"] for row in inner_train],
                    feature_names=feature_names,
                    l2=l2,
                )
                _, fold_predictions = _predict_rows(calibrator, inner_validation)
                for prediction in fold_predictions:
                    prediction["fold"] = fold_index
                    prediction["threshold"] = calibrator.sufficient_threshold
                inner_predictions.extend(fold_predictions)
                completed_folds.append(fold_index)
            if not inner_predictions:
                raise ValueError(f"candidate {candidate_name} produced no inner-CV predictions")
            inner_metrics = _metrics(
                [row["label"] for row in inner_predictions],
                [row["probability"] for row in inner_predictions],
                [row["probability"] >= row["threshold"] for row in inner_predictions],
            )
            final_calibrator = EvidenceSufficiencyCalibrator.fit(
                [row["example"] for row in fit_rows],
                feature_names=feature_names,
                l2=l2,
            )
            holdout_metrics, holdout_predictions = _predict_rows(final_calibrator, holdout_rows)
            candidates[candidate_name] = {
                "feature_group": group_name,
                "feature_names": list(feature_names),
                "feature_count": len(feature_names),
                "l2": l2,
                "inner_completed_folds": completed_folds,
                "inner_cv": inner_metrics,
                "inner_predictions": inner_predictions,
                "holdout_diagnostic": holdout_metrics,
                "holdout_predictions": holdout_predictions,
                "final_calibrator": final_calibrator.to_dict(),
            }

    selected_name = min(
        candidates,
        key=lambda name: (
            candidates[name]["inner_cv"]["brier_score"],
            candidates[name]["feature_count"],
            name,
        ),
    )
    payload = {
        "schema_version": 2,
        "experiment": "sufficiency-feature-ablation-v65",
        "provider_calls": 0,
        "source_split": "train",
        "dataset": dataset,
        "folds": folds,
        "regularization_values": list(REGULARIZATION_VALUES),
        "selection_metric": "fit-question-grouped inner-CV Brier score",
        "selected_feature_group": selected_name,
        "holdout_used_for_selection": False,
        "requires_disjoint_development_confirmation": True,
        "input": {
            "examples_path": str(examples_path),
            "examples_sha256": _sha256(examples_path),
            "calibration_report_path": str(calibration_report_path),
            "calibration_report_sha256": _sha256(calibration_report_path),
            "fit_question_count": len(fit_question_ids),
            "holdout_question_count": len(holdout_question_ids),
        },
        "candidates": candidates,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output_path, payload, ensure_ascii=False)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--examples", type=Path, required=True)
    parser.add_argument("--calibration-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args()
    payload = analyze_feature_ablation(
        examples_path=args.examples,
        calibration_report_path=args.calibration_report,
        output_path=args.output,
        folds=args.folds,
    )
    selected = payload["candidates"][payload["selected_feature_group"]]
    print(json.dumps({
        "output": str(args.output),
        "dataset": payload["dataset"],
        "selected_feature_group": payload["selected_feature_group"],
        "inner_cv": selected["inner_cv"],
        "holdout_diagnostic": selected["holdout_diagnostic"],
        "holdout_used_for_selection": False,
        "provider_calls": 0,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
