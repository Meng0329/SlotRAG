from slotrag.benchmarking.metrics import score_record
from slotrag.models import EvidenceRecord, ExecutionResult, QuestionRecord


def _question(*, available: bool, gold: list[str] | None = None) -> QuestionRecord:
    return QuestionRecord(
        id="q1",
        question="Which answer is supported?",
        answers=["alpha"],
        gold_evidence=gold or [],
        metadata={"evidence_available": available},
    )


def _result(*source_ids: str) -> ExecutionResult:
    return ExecutionResult(
        answer="alpha",
        evidence=[
            EvidenceRecord(source_id=source_id, source_span="fact", slot_id="S1", bindings={})
            for source_id in source_ids
        ],
    )


def test_evidence_quality_metrics_are_na_without_gold_labels():
    scores = score_record("musique", _question(available=False), _result("d1#0"))
    assert scores["evidence_metric_status"] == "N/A"
    assert scores["evidence_recall_at_1"] is None
    assert scores["evidence_precision_at_5"] is None
    assert scores["evidence_ndcg_at_10"] is None


def test_evidence_quality_metrics_cover_ranked_cutoffs():
    scores = score_record(
        "hotpotqa",
        _question(available=True, gold=["d1#0", "d2#0"]),
        _result("d2#0", "d3#0", "d1#0"),
    )
    assert scores["evidence_metric_status"] == "computed"
    assert scores["evidence_hit_at_1"] == 1.0
    assert scores["evidence_recall_at_1"] == 0.5
    assert scores["evidence_recall_at_5"] == 1.0
    assert scores["evidence_precision_at_5"] == 0.4
    assert scores["evidence_mrr"] == 1.0
    assert scores["evidence_ndcg_at_10"] > 0.0
