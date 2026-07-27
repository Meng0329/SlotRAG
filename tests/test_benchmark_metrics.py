from slotrag.benchmarking.metrics import extract_answer_span, score_record
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


def test_extract_answer_span_removes_qwen_thinking_suffix():
    raw = "reasoning transcript\n</think>\n\nLazio"
    assert extract_answer_span(raw) == "Lazio"


def test_extract_answer_span_prefers_last_final_marker():
    raw = "Answer: an intermediate guess\nFinal Answer: Rome\nDone."
    assert extract_answer_span(raw) == "Rome"


def test_extract_answer_span_prefers_last_answer_tag_outside_thinking():
    raw = "<think><answer>wrong</answer></think><answer>first</answer><final>Rome</final>"
    assert extract_answer_span(raw) == "Rome"


def test_score_record_preserves_raw_length_but_scores_final_span():
    result = _result("d1#0").model_copy(update={"answer": "long reasoning\n</think>\nalpha"})
    scores = score_record("hotpotqa", _question(available=False), result)
    assert scores["prediction_raw_chars"] > len(scores["prediction_scored"])
    assert scores["prediction_scored"] == "alpha"
    assert scores["f1"] == 1.0


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


def test_evidence_quality_metrics_strip_shared_corpus_prefix():
    scores = score_record(
        "hotpotqa",
        _question(available=True, gold=["Austrian Pinscher#0"]),
        _result("hotpotqa:Austrian Pinscher:Austrian Pinscher#0"),
    )
    assert scores["evidence_recall"] == 1.0
    assert scores["evidence_hit_at_1"] == 1.0
