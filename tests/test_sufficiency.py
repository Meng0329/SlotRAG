import pytest

from slotrag.models import BindingRow, Passage, RetrievalResult
from slotrag.sufficiency import (
    EvidenceContext,
    EvidenceSufficiencyCalibrator,
    SufficiencyExample,
    extract_features,
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
