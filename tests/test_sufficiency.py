import pytest
import json

from slotrag.models import BindingRow, Passage, RetrievalResult
from slotrag.sufficiency import (
    EvidenceContext,
    EvidenceSufficiencyCalibrator,
    SufficiencyCalibrationArtifact,
    SufficiencyExample,
    extract_features,
    load_calibration_artifact,
)


def test_extract_features_covers_retrieval_agreement_evidence_and_budget_signals():
    context = EvidenceContext(
        retrieval_results=[
            RetrievalResult(
                passage=Passage(id="p1", doc_id="d1", text="Ada founded OpenAI."),
                score=0.90,
                bm25_score=4.0,
                dense_score=0.80,
                rerank_score=0.95,
            ),
            RetrievalResult(
                passage=Passage(id="p2", doc_id="d2", text="OpenAI was founded by Ada."),
                score=0.70,
                bm25_score=2.0,
                dense_score=0.60,
                rerank_score=0.65,
            ),
        ],
        predicate="Founded",
        requested_variables=["company"],
        bound_variables={"person": "Ada"},
        join_variables=["person"],
        extracted_rows=[BindingRow(
            slot_id="S1",
            bindings={"person": "Ada", "company": "OpenAI"},
            source_id="p1",
            source_span="Ada founded OpenAI.",
            confidence=0.9,
        )],
        remaining_plan_depth=2,
        retrieval_calls_used=1,
        retrieval_budget=4,
    )

    features = extract_features(context)

    assert features.top1_score == 0.95
    assert features.topk_score > 0.0
    assert features.top1_top2_margin == pytest.approx(0.30)
    assert 0.0 <= features.score_entropy <= 1.0
    assert features.sparse_dense_agreement == 1.0
    assert features.reranker_agreement == 1.0
    assert features.new_entity_coverage == 1.0
    assert features.source_diversity == 1.0
    assert features.predicate_coverage == 1.0
    assert features.bound_variable_coverage == 1.0
    assert features.join_edge_coverage == 1.0
    assert features.extraction_consistency > 0.8
    assert features.row_count == 1
    assert features.remaining_plan_depth == 2
    assert features.budget_remaining == 3
    assert features.budget_fraction == 0.75


def test_backend_features_use_raw_bm25_when_fused_rrf_scores_are_constant():
    context = EvidenceContext(
        retrieval_backend="bm25",
        retrieval_results=[
            RetrievalResult(
                passage=Passage(id="p1", text="Alpha evidence."),
                score=0.00819672131147541,
                bm25_score=30.0,
            ),
            RetrievalResult(
                passage=Passage(id="p2", text="Beta evidence."),
                score=0.00819672131147541,
                bm25_score=10.0,
            ),
            RetrievalResult(
                passage=Passage(id="p3", text="Gamma evidence."),
                score=0.00819672131147541,
                bm25_score=5.0,
            ),
        ],
    )

    features = extract_features(context)

    assert features.top1_score == pytest.approx(0.00819672131147541)
    assert features.top1_top2_margin == 0.0
    assert features.backend_top1_score == 30.0
    assert features.backend_top1_top2_margin == 20.0
    assert features.backend_margin_ratio == pytest.approx(2 / 3)
    assert features.backend_top1_share > 0.5
    assert 0.0 <= features.backend_relative_entropy <= 1.0
    assert 0.0 <= features.backend_score_iqr_ratio <= 1.0
    assert 0.0 <= features.backend_rank_discounted_mass <= 1.0
    assert features.score_source_bm25 == 1.0
    assert features.score_source_fused == 0.0


def test_backend_shape_features_are_invariant_to_positive_score_scaling():
    def features(scale: float):
        return extract_features(EvidenceContext(
            retrieval_backend="bm25",
            retrieval_results=[
                RetrievalResult(
                    passage=Passage(id=f"p{index}", text="evidence"),
                    score=0.008,
                    bm25_score=score * scale,
                )
                for index, score in enumerate((10.0, 5.0, 1.0))
            ],
        ))

    small = features(1.0)
    large = features(100.0)

    assert large.backend_top1_score == small.backend_top1_score * 100
    assert large.backend_top1_top2_margin == small.backend_top1_top2_margin * 100
    assert large.backend_margin_ratio == pytest.approx(small.backend_margin_ratio)
    assert large.backend_top1_share == pytest.approx(small.backend_top1_share)
    assert large.backend_relative_entropy == pytest.approx(small.backend_relative_entropy)
    assert large.backend_score_iqr_ratio == pytest.approx(small.backend_score_iqr_ratio)
    assert large.backend_rank_discounted_mass == pytest.approx(
        small.backend_rank_discounted_mass
    )


def test_sparse_dense_agreement_detects_reversed_rankings():
    context = EvidenceContext(
        retrieval_results=[
            RetrievalResult(
                passage=Passage(id=f"p{index}", text="evidence"),
                score=0.5,
                bm25_score=bm25,
                dense_score=dense,
            )
            for index, (bm25, dense) in enumerate(((3.0, 1.0), (2.0, 2.0), (1.0, 3.0)))
        ],
    )

    features = extract_features(context)

    assert features.sparse_dense_agreement == pytest.approx(0.0)


def _calibration_example(index: int, sufficient: bool) -> SufficiencyExample:
    score = 0.95 if sufficient else 0.10
    passage = Passage(
        id=f"p{index}",
        doc_id=f"d{index}",
        text="Ada founded OpenAI." if sufficient else "An unrelated passage.",
    )
    rows = [BindingRow(
        slot_id="S1",
        bindings={"company": "OpenAI"},
        source_id=passage.id,
        source_span=passage.text,
        confidence=0.95,
    )] if sufficient else []
    return SufficiencyExample(
        example_id=f"e{index}",
        label=int(sufficient),
        context=EvidenceContext(
            retrieval_results=[RetrievalResult(
                passage=passage,
                score=score,
                bm25_score=score,
                dense_score=score,
                rerank_score=score,
            )],
            predicate="Founded" if sufficient else "Unseen",
            requested_variables=["company"],
            extracted_rows=rows,
            remaining_plan_depth=0 if sufficient else 2,
            retrieval_calls_used=1,
            retrieval_budget=3,
        ),
    )


def test_calibrator_reports_probability_quality_and_three_state_prediction():
    examples = [_calibration_example(index, index % 2 == 0) for index in range(12)]
    calibrator = EvidenceSufficiencyCalibrator.fit(examples)

    sufficient = calibrator.predict(examples[0].context)
    insufficient = calibrator.predict(examples[1].context)
    report = calibrator.evaluate(examples, bins=4)

    assert sufficient.probability > insufficient.probability
    assert sufficient.status == "SUFFICIENT"
    assert insufficient.status == "INSUFFICIENT"
    assert 0.0 <= report.brier_score <= 1.0
    assert 0.0 <= report.expected_calibration_error <= 1.0
    assert report.example_count == len(examples)
    assert len(report.reliability_bins) == 4
    assert report.binary_precision > 0.8
    assert report.binary_recall > 0.8


def test_calibrator_fit_supports_a_preregistered_feature_subset():
    examples = [_calibration_example(index, index % 2 == 0) for index in range(12)]
    feature_names = ("backend_top1_score", "extraction_consistency", "row_count")

    calibrator = EvidenceSufficiencyCalibrator.fit(
        examples,
        feature_names=feature_names,
    )

    assert calibrator.feature_names == feature_names
    assert calibrator.feature_schema_version == 2
    assert len(calibrator.weights) == len(feature_names)
    assert calibrator.predict(examples[0].context).probability > calibrator.predict(
        examples[1].context
    ).probability


def test_calibration_artifact_loads_dataset_models_and_hash(tmp_path):
    calibrator = EvidenceSufficiencyCalibrator(intercept=1.5)
    artifact = SufficiencyCalibrationArtifact(
        created_at="2026-07-27T00:00:00+00:00",
        source_split="train",
        retrieval_protocol="global_corpus",
        retrieval_backend="bm25",
        training_manifest_sha256="a" * 64,
        label_definition="gold evidence and answer path are recoverable",
        calibrators={"hotpotqa": calibrator.to_dict()},
        reports={"hotpotqa": {"example_count": 10}},
        example_counts={"hotpotqa": 10},
    )
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(artifact.model_dump(mode="json")), encoding="utf-8")

    loaded, sha256 = load_calibration_artifact(path)

    assert loaded.calibrator_for("hotpotqa").intercept == 1.5
    assert loaded.schema_version == 2
    assert loaded.feature_schema_version == 2
    assert loaded.calibrator_for("hotpotqa").feature_schema_version == 2
    assert len(sha256) == 64
    with pytest.raises(ValueError, match="does not contain dataset"):
        loaded.calibrator_for("musique")


def test_calibration_artifact_rejects_evaluation_source():
    with pytest.raises(ValueError, match="source_split"):
        SufficiencyCalibrationArtifact.model_validate({
            "created_at": "2026-07-27T00:00:00+00:00",
            "source_split": "evaluation",
            "retrieval_protocol": "global_corpus",
            "retrieval_backend": "bm25",
            "training_manifest_sha256": "a" * 64,
            "label_definition": "invalid",
            "calibrators": {"hotpotqa": EvidenceSufficiencyCalibrator().to_dict()},
            "reports": {},
            "example_counts": {"hotpotqa": 1},
        })


def test_schema_one_calibration_artifact_remains_explicitly_legacy(tmp_path):
    calibrator = EvidenceSufficiencyCalibrator(
        feature_names=("top1_score", "row_count"),
        means=[0.0, 0.0],
        scales=[1.0, 1.0],
        weights=[1.0, 1.0],
    ).to_dict()
    calibrator.pop("feature_schema_version")
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "created_at": "2026-07-27T00:00:00+00:00",
        "source_split": "train",
        "retrieval_protocol": "global_corpus",
        "retrieval_backend": "bm25",
        "training_manifest_sha256": "a" * 64,
        "label_definition": "legacy development calibration",
        "calibrators": {"hotpotqa": calibrator},
        "reports": {},
        "example_counts": {"hotpotqa": 10},
    }), encoding="utf-8")

    artifact, _ = load_calibration_artifact(path)

    assert artifact.schema_version == 1
    assert artifact.feature_schema_version == 1
    assert artifact.calibrator_for("hotpotqa").feature_schema_version == 1


def test_calibration_artifact_rejects_mixed_feature_schemas():
    with pytest.raises(ValueError, match="feature schema"):
        SufficiencyCalibrationArtifact(
            created_at="2026-07-27T00:00:00+00:00",
            source_split="train",
            retrieval_protocol="global_corpus",
            retrieval_backend="bm25",
            training_manifest_sha256="a" * 64,
            label_definition="invalid mixed schemas",
            calibrators={"hotpotqa": {
                **EvidenceSufficiencyCalibrator().to_dict(),
                "feature_schema_version": 1,
            }},
            reports={},
            example_counts={"hotpotqa": 1},
        )
