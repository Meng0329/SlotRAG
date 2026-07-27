"""Leakage-resistant validation for frozen evidence-sufficiency models."""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import tempfile
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any, Sequence

from ..sufficiency import (
    EvidenceSufficiencyCalibrator,
    SufficiencyCalibrationArtifact,
    SufficiencyExample,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_examples(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid validation example at line {line_number}: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"validation example at line {line_number} must be an object")
        rows.append(row)
    if not rows:
        raise ValueError("validation examples must not be empty")
    return rows


def _candidate_question_ids(candidates: dict[str, Any]) -> set[str]:
    return {
        str(prediction["question_id"])
        for candidate in candidates.values()
        if isinstance(candidate, dict)
        for field in ("inner_predictions", "holdout_predictions")
        for prediction in candidate.get(field, [])
        if isinstance(prediction, dict) and prediction.get("question_id")
    }


def _legacy_comparator(candidates: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    legacy = [
        (name, candidate)
        for name, candidate in candidates.items()
        if isinstance(candidate, dict) and candidate.get("feature_group") == "legacy_v1"
    ]
    if not legacy:
        raise ValueError("selection artifact has no frozen legacy_v1 comparator")
    return min(
        legacy,
        key=lambda item: (
            float((item[1].get("inner_cv") or {}).get("brier_score", math.inf)),
            item[0],
        ),
    )


def _paired_bootstrap(
    deltas: Sequence[float],
    *,
    iterations: int,
    seed: int,
) -> dict[str, Any]:
    if iterations < 100:
        raise ValueError("bootstrap_iterations must be at least 100")
    if not deltas:
        raise ValueError("paired bootstrap requires at least one delta")
    generator = random.Random(seed)
    count = len(deltas)
    estimates = sorted(
        fmean(deltas[generator.randrange(count)] for _ in range(count))
        for _ in range(iterations)
    )
    lower_index = max(0, math.floor(0.025 * (iterations - 1)))
    upper_index = min(iterations - 1, math.ceil(0.975 * (iterations - 1)))
    return {
        "mean": fmean(deltas),
        "confidence_interval_95": [estimates[lower_index], estimates[upper_index]],
        "iterations": iterations,
        "seed": seed,
        "unit": "slot_materialization_example",
        "definition": "selected squared error minus frozen legacy_v1 squared error",
    }


def evaluate_frozen_sufficiency(
    *,
    examples_path: str | Path,
    selection_artifact_paths: Sequence[str | Path],
    bootstrap_iterations: int = 10_000,
    seed: int = 2027,
) -> dict[str, Any]:
    """Evaluate pre-selected calibrators on disjoint labeled examples without fitting."""
    examples_source = Path(examples_path)
    raw_examples = _read_examples(examples_source)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in raw_examples:
        dataset = str(row.get("dataset") or "")
        if not dataset:
            raise ValueError("every validation example requires a dataset")
        if row.get("supervision") != "strong_gold_evidence":
            raise ValueError("validation requires strong_gold_evidence supervision")
        grouped[dataset].append(row)

    selections: dict[str, tuple[Path, dict[str, Any]]] = {}
    for value in selection_artifact_paths:
        path = Path(value)
        artifact = json.loads(path.read_text(encoding="utf-8"))
        dataset = str(artifact.get("dataset") or "")
        if not dataset:
            raise ValueError(f"selection artifact has no dataset: {path}")
        if dataset in selections:
            raise ValueError(f"duplicate selection artifact for dataset: {dataset}")
        if artifact.get("holdout_used_for_selection") is not False:
            raise ValueError(f"selection artifact used holdout data: {path}")
        selections[dataset] = (path, artifact)

    missing = sorted(set(grouped) - set(selections))
    extra = sorted(set(selections) - set(grouped))
    if missing or extra:
        raise ValueError(f"dataset/artifact mismatch; missing={missing}, extra={extra}")

    dataset_reports: dict[str, Any] = {}
    for dataset, rows in sorted(grouped.items()):
        artifact_path, artifact = selections[dataset]
        candidates = artifact.get("candidates")
        if not isinstance(candidates, dict) or not candidates:
            raise ValueError(f"selection artifact has no candidates: {artifact_path}")
        selected_name = str(artifact.get("selected_feature_group") or "")
        selected_candidate = candidates.get(selected_name)
        if not isinstance(selected_candidate, dict):
            raise ValueError(f"selected candidate is missing: {selected_name}")
        comparator_name, comparator_candidate = _legacy_comparator(candidates)
        try:
            selected = EvidenceSufficiencyCalibrator.from_dict(selected_candidate["final_calibrator"])
            comparator = EvidenceSufficiencyCalibrator.from_dict(comparator_candidate["final_calibrator"])
        except KeyError as exc:
            raise ValueError(f"frozen candidate has no final_calibrator: {exc}") from exc

        examples = [
            SufficiencyExample.model_validate({
                "example_id": row["example_id"],
                "label": row["label"],
                "context": row["context"],
            })
            for row in rows
        ]
        validation_question_ids = {str(row.get("question_id") or "") for row in rows}
        source_question_ids = _candidate_question_ids(candidates)
        overlap = sorted(validation_question_ids & source_question_ids)
        if overlap:
            raise ValueError(
                f"validation questions overlap selection data for {dataset}: {', '.join(overlap[:10])}"
            )

        predictions: list[dict[str, Any]] = []
        brier_deltas: list[float] = []
        for row, example in zip(rows, examples, strict=True):
            selected_prediction = selected.predict(example.context)
            comparator_prediction = comparator.predict(example.context)
            brier_deltas.append(
                (selected_prediction.probability - example.label) ** 2
                - (comparator_prediction.probability - example.label) ** 2
            )
            predictions.append({
                "example_id": example.example_id,
                "question_id": str(row["question_id"]),
                "label": example.label,
                "selected_probability": selected_prediction.probability,
                "selected_status": selected_prediction.status,
                "comparator_probability": comparator_prediction.probability,
                "comparator_status": comparator_prediction.status,
            })

        protocols = sorted({str(row.get("retrieval_protocol")) for row in rows})
        backends = sorted({str(row.get("retrieval_backend")) for row in rows})
        dataset_reports[dataset] = {
            "selection_artifact": str(artifact_path),
            "selection_artifact_sha256": _sha256(artifact_path),
            "selected_candidate": selected_name,
            "comparator_candidate": comparator_name,
            "selection_metric": artifact.get("selection_metric"),
            "validation_example_count": len(examples),
            "validation_question_count": len(validation_question_ids),
            "validation_question_overlap_count": len(overlap),
            "retrieval_protocols": protocols,
            "retrieval_backends": backends,
            "selected_metrics": selected.evaluate(examples).model_dump(mode="json"),
            "comparator_metrics": comparator.evaluate(examples).model_dump(mode="json"),
            "paired_brier_delta": _paired_bootstrap(
                brier_deltas,
                iterations=bootstrap_iterations,
                seed=seed,
            ),
            "predictions": predictions,
        }

    return {
        "schema_version": 1,
        "experiment": "frozen-sufficiency-disjoint-validation",
        "provider_calls": 0,
        "validation_used_for_selection": False,
        "examples_path": str(examples_source),
        "examples_sha256": _sha256(examples_source),
        "bootstrap_iterations": bootstrap_iterations,
        "seed": seed,
        "datasets": dataset_reports,
    }


def write_immutable_validation_report(path: str | Path, report: dict[str, Any]) -> None:
    """Atomically create a validation report and refuse replacement."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".part",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, target)
        except FileExistsError as exc:
            raise FileExistsError(f"immutable validation output already exists: {target}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def build_frozen_runtime_artifact(
    *,
    selection_artifact_paths: Sequence[str | Path],
    retrieval_protocol: str,
    retrieval_backend: str,
    created_at: str,
) -> dict[str, Any]:
    """Merge selected, already-fitted candidates into the runner artifact format."""
    calibrators: dict[str, dict[str, Any]] = {}
    reports: dict[str, dict[str, Any]] = {}
    example_counts: dict[str, int] = {}
    source_digests: list[dict[str, str]] = []
    for value in selection_artifact_paths:
        path = Path(value)
        artifact = json.loads(path.read_text(encoding="utf-8"))
        dataset = str(artifact.get("dataset") or "")
        if not dataset:
            raise ValueError(f"selection artifact has no dataset: {path}")
        if dataset in calibrators:
            raise ValueError(f"duplicate selection artifact for dataset: {dataset}")
        if artifact.get("source_split") != "train":
            raise ValueError(f"selection artifact is not train-derived: {path}")
        if artifact.get("holdout_used_for_selection") is not False:
            raise ValueError(f"selection artifact used holdout data: {path}")
        selected_name = str(artifact.get("selected_feature_group") or "")
        candidate = (artifact.get("candidates") or {}).get(selected_name)
        if not isinstance(candidate, dict):
            raise ValueError(f"selected candidate is missing: {selected_name}")
        payload = candidate.get("final_calibrator")
        if not isinstance(payload, dict):
            raise ValueError(f"selected candidate has no final_calibrator: {selected_name}")
        calibrator = EvidenceSufficiencyCalibrator.from_dict(payload)
        fit_predictions = candidate.get("inner_predictions") or []
        if not fit_predictions:
            raise ValueError(f"selected candidate has no fit predictions: {selected_name}")
        calibrators[dataset] = calibrator.to_dict()
        reports[dataset] = {
            "selection_artifact": str(path),
            "selection_artifact_sha256": _sha256(path),
            "selected_candidate": selected_name,
            "feature_group": candidate.get("feature_group"),
            "inner_cv": candidate.get("inner_cv"),
            "holdout_used_for_selection": False,
        }
        example_counts[dataset] = len(fit_predictions)
        source_digests.append({"dataset": dataset, "sha256": _sha256(path)})
    if not calibrators:
        raise ValueError("at least one selection artifact is required")
    source_digests.sort(key=lambda value: value["dataset"])
    training_manifest_sha256 = hashlib.sha256(
        json.dumps(source_digests, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    artifact = SufficiencyCalibrationArtifact(
        created_at=created_at,
        source_split="train",
        retrieval_protocol=retrieval_protocol,
        retrieval_backend=retrieval_backend,
        training_manifest_sha256=training_manifest_sha256,
        label_definition=(
            "selected evidence intersects gold supporting evidence and extraction emits "
            "a complete requested-variable row grounded in gold evidence; "
            "candidate selection was fit-only and question-grouped"
        ),
        calibrators=calibrators,
        reports=reports,
        example_counts=example_counts,
    )
    return artifact.model_dump(mode="json")


__all__ = [
    "build_frozen_runtime_artifact",
    "evaluate_frozen_sufficiency",
    "write_immutable_validation_report",
]
