from slotrag.benchmarking.statistics import aggregate, macro_average, paired_bootstrap, seed_variance
from slotrag.models import RunMetrics


def _record(method, question_id, score, seed=2027, label=None):
    return {
        "dataset": "hotpotqa",
        "method": method,
        "method_label": label or method,
        "question_id": question_id,
        "seed": seed,
        "scores": {
            "primary_score": score,
            "em": score,
            "f1": score,
            "accuracy": None,
            "drop_em": None,
            "drop_f1": None,
            "evidence_recall": None,
            "evidence_mrr": None,
        },
        "result": {"status": "ok", "error": None, "metrics": RunMetrics().model_dump(mode="json")},
    }


def test_statistics_include_macro_seed_variance_and_paired_comparisons():
    records = [
        _record("slotrag", "q1", 1.0),
        _record("slotrag", "q2", 0.5),
        _record("hybrid", "q1", 0.0),
        _record("hybrid", "q2", 0.0),
        _record("slotrag-random", "q1", 0.2, 1, "slotrag-random@1"),
        _record("slotrag-random", "q2", 0.4, 1, "slotrag-random@1"),
        _record("slotrag-random", "q1", 0.4, 2, "slotrag-random@2"),
        _record("slotrag-random", "q2", 0.6, 2, "slotrag-random@2"),
    ]
    summaries = aggregate(records)
    assert any(row["method"] == "slotrag" and row["primary_score"] == 0.75 for row in summaries)
    assert any(row["method"] == "slotrag" for row in macro_average(summaries))
    variance = seed_variance(summaries)
    assert variance[0]["seed_count"] == 2
    comparisons = paired_bootstrap(records, iterations=100, seed=7)
    assert {row["comparison"] for row in comparisons} == {"hybrid", "slotrag-random"}

