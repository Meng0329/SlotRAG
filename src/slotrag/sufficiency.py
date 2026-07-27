"""Evidence sufficiency features for calibrated physical retrieval decisions."""

from __future__ import annotations

import math
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Literal, Sequence

import numpy as np

from pydantic import Field, model_validator

from .models import BindingRow, RetrievalResult, StrictModel


def _normalized(value: object) -> str:
    ascii_value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", ascii_value.casefold()))


def _tokens(value: object) -> set[str]:
    return set(_normalized(value).split())


class EvidenceContext(StrictModel):
    """Observable state after one slot retrieval/extraction attempt."""

    retrieval_results: list[RetrievalResult] = Field(default_factory=list)
    retrieval_backend: Literal["bm25", "hybrid", "unknown"] = "unknown"
    predicate: str = ""
    requested_variables: list[str] = Field(default_factory=list)
    bound_variables: dict[str, str] = Field(default_factory=dict)
    join_variables: list[str] = Field(default_factory=list)
    extracted_rows: list[BindingRow] = Field(default_factory=list)
    remaining_plan_depth: int = Field(default=0, ge=0)
    retrieval_calls_used: int = Field(default=0, ge=0)
    retrieval_budget: int = Field(default=0, ge=0)


class SufficiencyFeatures(StrictModel):
    top1_score: float = 0.0
    topk_score: float = 0.0
    topk_min_score: float = 0.0
    top1_top2_margin: float = 0.0
    score_entropy: float = 0.0
    backend_top1_score: float = 0.0
    backend_top1_top2_margin: float = 0.0
    backend_margin_ratio: float = 0.0
    backend_top1_share: float = 0.0
    backend_relative_entropy: float = 0.0
    backend_score_iqr_ratio: float = 0.0
    backend_top1_robust_zscore: float = 0.0
    backend_rank_discounted_mass: float = 0.0
    score_source_bm25: float = 0.0
    score_source_dense: float = 0.0
    score_source_reranker: float = 0.0
    score_source_fused: float = 0.0
    sparse_dense_agreement: float = 0.0
    reranker_agreement: float = 0.0
    new_entity_coverage: float = 0.0
    source_diversity: float = 0.0
    predicate_coverage: float = 0.0
    bound_variable_coverage: float = 0.0
    join_edge_coverage: float = 0.0
    extraction_consistency: float = 0.0
    row_count: int = 0
    remaining_plan_depth: int = 0
    budget_remaining: int = 0
    budget_fraction: float = 0.0
    retrieval_count: int = 0

    def vector(self, feature_names: tuple[str, ...]) -> list[float]:
        values = self.model_dump(mode="python")
        return [float(values[name]) for name in feature_names]


SufficiencyStatus = Literal["SUFFICIENT", "PARTIAL", "INSUFFICIENT"]

SUFFICIENCY_FEATURE_SCHEMA_VERSION = 2
SUFFICIENCY_FEATURE_NAMES_V1 = (
    "top1_score",
    "topk_score",
    "topk_min_score",
    "top1_top2_margin",
    "score_entropy",
    "sparse_dense_agreement",
    "reranker_agreement",
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
SUFFICIENCY_FEATURE_NAMES = tuple(SufficiencyFeatures.model_fields)


class SufficiencyExample(StrictModel):
    example_id: str = Field(min_length=1)
    label: int = Field(ge=0, le=1)
    context: EvidenceContext


class SufficiencyPrediction(StrictModel):
    status: SufficiencyStatus
    probability: float = Field(ge=0, le=1)
    raw_logit: float
    features: SufficiencyFeatures


class ReliabilityBin(StrictModel):
    lower: float
    upper: float
    count: int
    mean_confidence: float
    empirical_rate: float
    calibration_gap: float


class CalibrationReport(StrictModel):
    example_count: int
    brier_score: float
    expected_calibration_error: float
    threshold: float
    partial_threshold: float
    binary_precision: float
    binary_recall: float
    binary_accuracy: float
    positive_count: int
    negative_count: int
    reliability_bins: list[ReliabilityBin]


class SufficiencyCalibrationArtifact(StrictModel):
    schema_version: Literal[1, 2] = 2
    feature_schema_version: Literal[1, 2] = 2
    created_at: str
    source_split: Literal["train"]
    retrieval_protocol: Literal["local_context", "global_corpus"]
    retrieval_backend: Literal["bm25", "hybrid"]
    training_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    label_definition: str = Field(min_length=1)
    calibrators: dict[str, dict[str, Any]]
    reports: dict[str, dict[str, Any]] = Field(default_factory=dict)
    example_counts: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def infer_legacy_feature_schema(cls, value: Any) -> Any:
        if isinstance(value, dict) and "feature_schema_version" not in value:
            value = {**value, "feature_schema_version": 1 if value.get("schema_version") == 1 else 2}
        return value

    @model_validator(mode="after")
    def validate_dataset_inventory(self) -> "SufficiencyCalibrationArtifact":
        if self.schema_version != self.feature_schema_version:
            raise ValueError("artifact schema and feature schema versions must match")
        if not self.calibrators:
            raise ValueError("calibrators must contain at least one dataset")
        missing = sorted(set(self.calibrators) - set(self.example_counts))
        if missing:
            raise ValueError(f"example_counts missing datasets: {', '.join(missing)}")
        if any(self.example_counts[dataset] <= 0 for dataset in self.calibrators):
            raise ValueError("every dataset calibrator requires positive development examples")
        mismatched = sorted(
            dataset
            for dataset, payload in self.calibrators.items()
            if int(payload.get("feature_schema_version", 1)) != self.feature_schema_version
        )
        if mismatched:
            raise ValueError(
                "calibrator feature schema does not match artifact for datasets: "
                + ", ".join(mismatched)
            )
        return self

    def calibrator_for(self, dataset: str) -> "EvidenceSufficiencyCalibrator":
        try:
            payload = self.calibrators[dataset]
        except KeyError as exc:
            raise ValueError(f"calibration artifact does not contain dataset: {dataset}") from exc
        return EvidenceSufficiencyCalibrator.from_dict(payload)


def load_calibration_artifact(
    path: str | Path,
) -> tuple[SufficiencyCalibrationArtifact, str]:
    source = Path(path)
    payload = source.read_bytes()
    artifact = SufficiencyCalibrationArtifact.model_validate(json.loads(payload))
    return artifact, hashlib.sha256(payload).hexdigest()


def _sigmoid(value: float | np.ndarray) -> float | np.ndarray:
    clipped = np.clip(value, -60.0, 60.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _binary_f1(labels: np.ndarray, probabilities: np.ndarray, threshold: float) -> float:
    predicted = probabilities >= threshold
    true_positive = float(np.sum(predicted & (labels == 1)))
    false_positive = float(np.sum(predicted & (labels == 0)))
    false_negative = float(np.sum(~predicted & (labels == 1)))
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _calibration_report(
    labels: Sequence[int],
    probabilities: Sequence[float],
    *,
    threshold: float,
    partial_threshold: float,
    bins: int,
) -> CalibrationReport:
    if bins <= 0:
        raise ValueError("bins must be positive")
    label_array = np.asarray(labels, dtype=int)
    probability_array = np.asarray(probabilities, dtype=float)
    if len(label_array) != len(probability_array) or not len(label_array):
        raise ValueError("labels and probabilities must be non-empty and have equal length")
    predicted = probability_array >= threshold
    true_positive = int(np.sum(predicted & (label_array == 1)))
    false_positive = int(np.sum(predicted & (label_array == 0)))
    false_negative = int(np.sum(~predicted & (label_array == 1)))
    binary_precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    binary_recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    reliability_bins: list[ReliabilityBin] = []
    ece = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        selected = (
            (probability_array >= lower)
            & ((probability_array < upper) if index < bins - 1 else (probability_array <= upper))
        )
        count = int(np.sum(selected))
        if count:
            mean_confidence = float(np.mean(probability_array[selected]))
            empirical_rate = float(np.mean(label_array[selected]))
            gap = abs(mean_confidence - empirical_rate)
            ece += count / len(label_array) * gap
        else:
            mean_confidence = 0.0
            empirical_rate = 0.0
            gap = 0.0
        reliability_bins.append(ReliabilityBin(
            lower=lower,
            upper=upper,
            count=count,
            mean_confidence=mean_confidence,
            empirical_rate=empirical_rate,
            calibration_gap=gap,
        ))
    return CalibrationReport(
        example_count=len(label_array),
        brier_score=float(np.mean((probability_array - label_array) ** 2)),
        expected_calibration_error=float(ece),
        threshold=threshold,
        partial_threshold=partial_threshold,
        binary_precision=binary_precision,
        binary_recall=binary_recall,
        binary_accuracy=float(np.mean(predicted == label_array)),
        positive_count=int(np.sum(label_array == 1)),
        negative_count=int(np.sum(label_array == 0)),
        reliability_bins=reliability_bins,
    )


class EvidenceSufficiencyCalibrator:
    """Small deterministic logistic calibrator trained only on development examples."""

    def __init__(
        self,
        *,
        feature_names: tuple[str, ...] = SUFFICIENCY_FEATURE_NAMES,
        feature_schema_version: int = SUFFICIENCY_FEATURE_SCHEMA_VERSION,
        means: Sequence[float] | None = None,
        scales: Sequence[float] | None = None,
        weights: Sequence[float] | None = None,
        intercept: float = 0.0,
        sufficient_threshold: float = 0.5,
        partial_threshold: float = 0.3,
    ) -> None:
        self.feature_names = tuple(feature_names)
        self.feature_schema_version = int(feature_schema_version)
        if self.feature_schema_version not in {1, 2}:
            raise ValueError("unsupported sufficiency feature schema version")
        unknown_features = sorted(set(self.feature_names) - set(SufficiencyFeatures.model_fields))
        if unknown_features:
            raise ValueError(f"unknown sufficiency features: {', '.join(unknown_features)}")
        if self.feature_schema_version == 1 and not set(self.feature_names).issubset(
            SUFFICIENCY_FEATURE_NAMES_V1
        ):
            raise ValueError("feature schema 1 cannot contain backend-aware features")
        width = len(self.feature_names)
        self.means = np.asarray(means if means is not None else np.zeros(width), dtype=float)
        self.scales = np.asarray(scales if scales is not None else np.ones(width), dtype=float)
        self.weights = np.asarray(weights if weights is not None else np.zeros(width), dtype=float)
        self.intercept = float(intercept)
        self.sufficient_threshold = float(sufficient_threshold)
        self.partial_threshold = float(partial_threshold)
        if len(self.means) != width or len(self.scales) != width or len(self.weights) != width:
            raise ValueError("calibrator parameter width does not match feature_names")

    @classmethod
    def fit(
        cls,
        examples: Sequence[SufficiencyExample],
        *,
        feature_names: Sequence[str] | None = None,
        learning_rate: float = 0.15,
        epochs: int = 800,
        l2: float = 1e-3,
    ) -> "EvidenceSufficiencyCalibrator":
        if not examples:
            raise ValueError("at least one development example is required")
        if learning_rate <= 0 or epochs <= 0 or l2 < 0:
            raise ValueError("learning_rate and epochs must be positive; l2 must be non-negative")
        feature_names = tuple(feature_names or SUFFICIENCY_FEATURE_NAMES)
        if not feature_names:
            raise ValueError("at least one sufficiency feature is required")
        unknown_features = sorted(set(feature_names) - set(SufficiencyFeatures.model_fields))
        if unknown_features:
            raise ValueError(f"unknown sufficiency features: {', '.join(unknown_features)}")
        matrix = np.asarray([
            extract_features(example.context).vector(feature_names)
            for example in examples
        ], dtype=float)
        labels = np.asarray([example.label for example in examples], dtype=float)
        means = matrix.mean(axis=0)
        scales = matrix.std(axis=0)
        scales[scales < 1e-9] = 1.0
        normalized = (matrix - means) / scales
        prevalence = float(np.clip(labels.mean(), 1e-4, 1 - 1e-4))
        weights = np.zeros(normalized.shape[1], dtype=float)
        intercept = math.log(prevalence / (1 - prevalence))
        for _ in range(epochs):
            probabilities = np.asarray(_sigmoid(normalized @ weights + intercept), dtype=float)
            residual = probabilities - labels
            weights -= learning_rate * (normalized.T @ residual / len(labels) + l2 * weights)
            intercept -= learning_rate * float(residual.mean())
        calibrator = cls(
            feature_names=feature_names,
            feature_schema_version=SUFFICIENCY_FEATURE_SCHEMA_VERSION,
            means=means,
            scales=scales,
            weights=weights,
            intercept=intercept,
        )
        probabilities = calibrator._predict_probability_matrix(normalized)
        candidates = np.linspace(0.05, 0.95, 19)
        best = max(candidates, key=lambda threshold: (_binary_f1(labels, probabilities, float(threshold)), -abs(float(threshold) - 0.5)))
        calibrator.sufficient_threshold = float(best)
        calibrator.partial_threshold = float(min(best, max(0.05, min(0.49, best * 0.7))))
        return calibrator

    def _normalize(self, features: SufficiencyFeatures) -> np.ndarray:
        return (np.asarray(features.vector(self.feature_names), dtype=float) - self.means) / self.scales

    def _predict_probability_matrix(self, normalized: np.ndarray) -> np.ndarray:
        return np.asarray(_sigmoid(normalized @ self.weights + self.intercept), dtype=float)

    def predict(self, context: EvidenceContext) -> SufficiencyPrediction:
        features = extract_features(context)
        raw_logit = float(self._normalize(features) @ self.weights + self.intercept)
        probability = float(_sigmoid(raw_logit))
        if probability >= self.sufficient_threshold:
            status: SufficiencyStatus = "SUFFICIENT"
        elif probability >= self.partial_threshold:
            status = "PARTIAL"
        else:
            status = "INSUFFICIENT"
        return SufficiencyPrediction(
            status=status,
            probability=probability,
            raw_logit=raw_logit,
            features=features,
        )

    def evaluate(self, examples: Sequence[SufficiencyExample], *, bins: int = 10) -> CalibrationReport:
        if not examples:
            raise ValueError("at least one example is required for evaluation")
        return _calibration_report(
            [example.label for example in examples],
            [self.predict(example.context).probability for example in examples],
            threshold=self.sufficient_threshold,
            partial_threshold=self.partial_threshold,
            bins=bins,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_schema_version": self.feature_schema_version,
            "feature_names": list(self.feature_names),
            "means": self.means.tolist(),
            "scales": self.scales.tolist(),
            "weights": self.weights.tolist(),
            "intercept": self.intercept,
            "sufficient_threshold": self.sufficient_threshold,
            "partial_threshold": self.partial_threshold,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvidenceSufficiencyCalibrator":
        return cls(
            feature_names=tuple(payload["feature_names"]),
            feature_schema_version=int(payload.get("feature_schema_version", 1)),
            means=payload["means"],
            scales=payload["scales"],
            weights=payload["weights"],
            intercept=payload["intercept"],
            sufficient_threshold=payload["sufficient_threshold"],
            partial_threshold=payload["partial_threshold"],
        )


def _rank_agreement(results: list[RetrievalResult], left: str, right: str) -> float:
    values = [
        result
        for result in results
        if getattr(result, left) is not None and getattr(result, right) is not None
    ]
    if not values:
        return 0.0
    if len(values) == 1:
        return 1.0
    left_order = [
        result.passage.id
        for result in sorted(
            values,
            key=lambda item: (-float(getattr(item, left)), item.passage.id),
        )
    ]
    right_order = [
        result.passage.id
        for result in sorted(
            values,
            key=lambda item: (-float(getattr(item, right)), item.passage.id),
        )
    ]
    right_positions = {passage_id: index for index, passage_id in enumerate(right_order)}
    squared_distance = sum(
        (index - right_positions[passage_id]) ** 2
        for index, passage_id in enumerate(left_order)
    )
    width = len(left_order)
    spearman = 1.0 - (6.0 * squared_distance) / (width * (width * width - 1))
    return max(0.0, min(1.0, (spearman + 1.0) / 2.0))


def _score_entropy(scores: list[float]) -> float:
    if len(scores) <= 1:
        return 0.0
    maximum = max(scores)
    weights = [math.exp(max(min(score - maximum, 50.0), -50.0)) for score in scores]
    total = sum(weights)
    if total <= 0:
        return 1.0
    probabilities = [weight / total for weight in weights]
    entropy = -sum(probability * math.log(probability) for probability in probabilities if probability > 0)
    return entropy / math.log(len(probabilities))


def _backend_score_values(context: EvidenceContext) -> tuple[str, list[float]]:
    results = context.retrieval_results

    def values(attribute: str) -> list[float]:
        return [
            float(value)
            for result in results
            if (value := getattr(result, attribute)) is not None
        ]

    bm25 = values("bm25_score")
    dense = values("dense_score")
    reranker = values("rerank_score")
    fused = [float(result.score) for result in results]
    if context.retrieval_backend == "bm25":
        return ("bm25", bm25) if bm25 else ("fused", fused)
    if context.retrieval_backend == "hybrid":
        if reranker:
            return "reranker", reranker
        if bm25 and dense:
            return "fused", fused
        if dense:
            return "dense", dense
        if bm25:
            return "bm25", bm25
        return "fused", fused
    if reranker:
        return "reranker", reranker
    if bm25 and not dense:
        return "bm25", bm25
    if dense and not bm25:
        return "dense", dense
    return "fused", fused


def _backend_score_profile(scores: list[float]) -> dict[str, float]:
    if not scores:
        return {
            "top1": 0.0,
            "margin": 0.0,
            "margin_ratio": 0.0,
            "top1_share": 0.0,
            "relative_entropy": 0.0,
            "iqr_ratio": 0.0,
            "top1_robust_zscore": 0.0,
            "rank_discounted_mass": 0.0,
        }
    ordered = sorted(scores, reverse=True)
    top1 = ordered[0]
    top2 = ordered[1] if len(ordered) > 1 else top1
    margin = top1 - top2
    margin_ratio = margin / max(abs(top1), abs(top2), 1e-12)

    score_array = np.asarray(scores, dtype=float)
    minimum = float(np.min(score_array))
    maximum = float(np.max(score_array))
    span = maximum - minimum
    shifted = score_array - minimum
    shifted_total = float(np.sum(shifted))
    if shifted_total <= 1e-12:
        masses = np.full(len(scores), 1.0 / len(scores), dtype=float)
    else:
        masses = shifted / shifted_total
    relative_entropy = 0.0
    if len(scores) > 1:
        relative_entropy = -float(np.sum([
            mass * math.log(mass)
            for mass in masses
            if mass > 0
        ])) / math.log(len(scores))
    q25, median, q75 = np.quantile(score_array, [0.25, 0.5, 0.75])
    iqr = float(q75 - q25)
    robust_scale = iqr if iqr > 1e-12 else span
    robust_zscore = (top1 - float(median)) / robust_scale if robust_scale > 1e-12 else 0.0
    rank_discounted_mass = sum(
        float(mass) / math.log2(rank + 2)
        for rank, mass in enumerate(masses)
    )
    return {
        "top1": top1,
        "margin": margin,
        "margin_ratio": max(0.0, min(2.0, margin_ratio)),
        "top1_share": float(np.max(masses)),
        "relative_entropy": max(0.0, min(1.0, relative_entropy)),
        "iqr_ratio": iqr / span if span > 1e-12 else 0.0,
        "top1_robust_zscore": max(0.0, min(20.0, robust_zscore)),
        "rank_discounted_mass": max(0.0, min(1.0, rank_discounted_mass)),
    }


def _coverage(values: list[str], text: str, *, empty_value: float = 1.0) -> float:
    if not values:
        return empty_value
    normalized_text = f" {_normalized(text)} "
    covered = sum(bool(value) and f" {_normalized(value)} " in normalized_text for value in values)
    return covered / len(values)


def _extraction_consistency(context: EvidenceContext, result_ids: set[str]) -> float:
    if not context.extracted_rows:
        return 0.0
    requested = {name.lstrip("?") for name in context.requested_variables}
    valid_sources = sum(row.source_id in result_ids for row in context.extracted_rows) / len(context.extracted_rows)
    required_fields = [
        sum(name in row.bindings and bool(str(row.bindings[name]).strip()) for name in requested) / len(requested)
        if requested else 1.0
        for row in context.extracted_rows
    ]
    confidence = sum(row.confidence for row in context.extracted_rows) / len(context.extracted_rows)
    signatures = {
        tuple(sorted((key, _normalized(value)) for key, value in row.bindings.items()))
        for row in context.extracted_rows
    }
    uniqueness = len(signatures) / len(context.extracted_rows)
    return valid_sources * (sum(required_fields) / len(required_fields)) * confidence * uniqueness


def extract_features(context: EvidenceContext) -> SufficiencyFeatures:
    """Compute provider-independent sufficiency features from observable runtime state."""
    results = list(context.retrieval_results)
    effective_scores = [
        float(result.rerank_score if result.rerank_score is not None else result.score)
        for result in results
    ]
    effective_scores.sort(reverse=True)
    top1 = effective_scores[0] if effective_scores else 0.0
    top2 = effective_scores[1] if len(effective_scores) > 1 else top1
    score_source, backend_scores = _backend_score_values(context)
    backend_profile = _backend_score_profile(backend_scores)
    texts = " ".join(result.passage.text for result in results)
    documents = {result.passage.doc_id or result.passage.id for result in results}
    result_ids = {result.passage.id for result in results}
    requested = [name.lstrip("?") for name in context.requested_variables]
    covered_entities = {
        name
        for row in context.extracted_rows
        for name in requested
        if name in row.bindings and bool(str(row.bindings[name]).strip())
    }
    row_bindings = {key.lstrip("?"): value for row in context.extracted_rows for key, value in row.bindings.items()}
    join_variables = [name.lstrip("?") for name in context.join_variables]
    join_coverage = _coverage(
        [row_bindings[name] for name in join_variables if name in row_bindings],
        texts,
        empty_value=1.0 if not join_variables else 0.0,
    )
    budget_remaining = max(context.retrieval_budget - context.retrieval_calls_used, 0)
    budget_fraction = budget_remaining / context.retrieval_budget if context.retrieval_budget else 0.0
    return SufficiencyFeatures(
        top1_score=top1,
        topk_score=sum(effective_scores) / len(effective_scores) if effective_scores else 0.0,
        topk_min_score=effective_scores[-1] if effective_scores else 0.0,
        top1_top2_margin=top1 - top2,
        score_entropy=_score_entropy(effective_scores),
        backend_top1_score=backend_profile["top1"],
        backend_top1_top2_margin=backend_profile["margin"],
        backend_margin_ratio=backend_profile["margin_ratio"],
        backend_top1_share=backend_profile["top1_share"],
        backend_relative_entropy=backend_profile["relative_entropy"],
        backend_score_iqr_ratio=backend_profile["iqr_ratio"],
        backend_top1_robust_zscore=backend_profile["top1_robust_zscore"],
        backend_rank_discounted_mass=backend_profile["rank_discounted_mass"],
        score_source_bm25=float(score_source == "bm25"),
        score_source_dense=float(score_source == "dense"),
        score_source_reranker=float(score_source == "reranker"),
        score_source_fused=float(score_source == "fused"),
        sparse_dense_agreement=_rank_agreement(results, "bm25_score", "dense_score"),
        reranker_agreement=_rank_agreement(results, "score", "rerank_score"),
        new_entity_coverage=(
            len(covered_entities) / len(requested)
            if requested
            else (1.0 if context.extracted_rows else 0.0)
        ),
        source_diversity=len(documents) / len(results) if results else 0.0,
        predicate_coverage=_coverage(list(_tokens(context.predicate)), texts, empty_value=0.0),
        bound_variable_coverage=_coverage(list(context.bound_variables.values()), texts),
        join_edge_coverage=join_coverage,
        extraction_consistency=_extraction_consistency(context, result_ids),
        row_count=len(context.extracted_rows),
        remaining_plan_depth=context.remaining_plan_depth,
        budget_remaining=budget_remaining,
        budget_fraction=budget_fraction,
        retrieval_count=len(results),
    )


__all__ = [
    "CalibrationReport",
    "EvidenceContext",
    "EvidenceSufficiencyCalibrator",
    "ReliabilityBin",
    "SufficiencyExample",
    "SufficiencyFeatures",
    "SufficiencyPrediction",
    "SUFFICIENCY_FEATURE_NAMES",
    "SUFFICIENCY_FEATURE_NAMES_V1",
    "SUFFICIENCY_FEATURE_SCHEMA_VERSION",
    "SufficiencyStatus",
    "SufficiencyCalibrationArtifact",
    "extract_features",
    "load_calibration_artifact",
]
