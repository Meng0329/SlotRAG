from slotrag.benchmarking.metrics import boolean_accuracy, drop_scores, evidence_scores
from slotrag.models import EvidenceRecord, ExecutionResult, QuestionRecord


def test_drop_numeric_mismatch_blocks_partial_token_credit():
    assert drop_scores("12 yards", ["10 yards"]) == (0.0, 0.0)
    assert drop_scores("9", ["9"]) == (1.0, 1.0)


def test_strategyqa_boolean_accuracy_accepts_yes_no_and_true_false():
    assert boolean_accuracy("Yes", ["True"]) == 1.0
    assert boolean_accuracy("No", ["true"]) == 0.0


def test_evidence_metrics_canonicalize_chunk_ids():
    question = QuestionRecord(
        id="q",
        question="Who?",
        gold_evidence=["Doc#0"],
        metadata={"evidence_available": True},
    )
    result = ExecutionResult(
        evidence=[EvidenceRecord(source_id="Doc#0#chunk-1", source_span="Fact", slot_id="S1", bindings={})]
    )
    assert evidence_scores(result, question) == (1.0, 1.0)

