from slotrag.benchmarking.action_headroom import analyze_action_headroom
from slotrag.sufficiency import SufficiencyCalibrationArtifact


def _context(*, rows: bool, remaining_depth: int) -> dict:
    return {
        "retrieval_results": [],
        "retrieval_backend": "bm25",
        "predicate": "Founded",
        "requested_variables": ["founder"],
        "bound_variables": {},
        "join_variables": [],
        "extracted_rows": ([{
            "slot_id": "S1",
            "bindings": {"founder": "Ada"},
            "source_id": "gold",
            "source_span": "Ada founded Alpha.",
            "confidence": 1.0,
            "retrieval_score": 1.0,
        }] if rows else []),
        "remaining_plan_depth": remaining_depth,
        "retrieval_calls_used": 1,
        "retrieval_budget": 4,
    }


def _example(
    example_id: str,
    *,
    rows: bool,
    remaining_depth: int,
    expansion_available: bool,
    recoverable: bool,
) -> dict:
    return {
        "example_id": example_id,
        "dataset": "hotpotqa",
        "question_id": example_id.split(":")[1],
        "slot_id": "S1",
        "supervision": "strong_gold_evidence",
        "label": int(rows),
        "retrieval_protocol": "global_corpus",
        "retrieval_backend": "bm25",
        "context": _context(rows=rows, remaining_depth=remaining_depth),
        "action_supervision": {
            "candidate_pool_is_counterfactual_proxy": True,
            "eligible": True,
            "gold_evidence_ids": ["gold"],
            "selected_evidence_ids": ["gold"] if rows else ["noise"],
            "candidate_evidence_ids": ["gold", "noise"] if expansion_available else ["noise"],
            "selected_count": 1,
            "candidate_count": 2 if expansion_available else 1,
            "expansion_available": expansion_available,
            "gold_selected": rows,
            "candidate_gold_available": recoverable or rows,
            "expand_topk_recoverable": recoverable,
            "topk_expansion_retrieval_calls": 1,
        },
    }


def _artifact() -> SufficiencyCalibrationArtifact:
    return SufficiencyCalibrationArtifact.model_validate({
        "schema_version": 2,
        "feature_schema_version": 2,
        "created_at": "2026-07-27T00:00:00+00:00",
        "source_split": "train",
        "retrieval_protocol": "global_corpus",
        "retrieval_backend": "bm25",
        "training_manifest_sha256": "a" * 64,
        "label_definition": "test",
        "calibrators": {
            "hotpotqa": {
                "feature_schema_version": 2,
                "feature_names": ["row_count"],
                "means": [0.0],
                "scales": [1.0],
                "weights": [2.0],
                "intercept": -1.0,
                "sufficient_threshold": 0.6,
                "partial_threshold": 0.3,
            },
        },
        "reports": {},
        "example_counts": {"hotpotqa": 4},
    })


def test_action_headroom_reports_proxy_confusion_and_selects_without_oracle():
    examples = [
        _example("hotpotqa:q1:S1:0", rows=False, remaining_depth=1, expansion_available=True, recoverable=True),
        _example("hotpotqa:q2:S1:0", rows=True, remaining_depth=1, expansion_available=True, recoverable=False),
        _example("hotpotqa:q3:S1:0", rows=False, remaining_depth=1, expansion_available=True, recoverable=False),
        _example("hotpotqa:q4:S1:0", rows=True, remaining_depth=0, expansion_available=False, recoverable=False),
    ]

    report = analyze_action_headroom(
        examples,
        calibration_artifact=_artifact(),
        role="development_selection",
        retrieval_call_penalty=0.08,
    )

    assert report["schema_version"] == 1
    assert report["example_count"] == 4
    assert report["recoverable_positive_count"] == 1
    assert report["oracle_max_mean_evidence_recovery"] == 0.25
    assert report["policies"]["fixed_topk"]["confusion"] == {
        "true_positive": 1,
        "false_positive": 2,
        "false_negative": 0,
        "true_negative": 1,
    }
    assert report["policies"]["fixed_topk"]["precision"] == 1 / 3
    assert report["policies"]["fixed_topk"]["recall"] == 1.0
    assert report["policies"]["status_safe"]["predicted_expansions"] == 2
    assert report["policies"]["status_safe"]["precision"] == 0.5
    assert report["policies"]["status_safe"]["recall"] == 1.0
    assert report["policies"]["current_utility"]["predicted_expansions"] == 2
    assert report["policies"]["no_expansion"]["predicted_expansions"] == 0
    assert report["policies"]["oracle_candidate_pool"]["predicted_expansions"] == 1
    assert report["selected_policy"] in {
        "current_utility", "status_safe", "rule", "fixed_topk", "no_expansion"
    }
    assert report["selected_policy"] != "oracle_candidate_pool"
    assert report["strata"]["by_status"]["SUFFICIENT"]["recoverable_positive_count"] == 0


def test_action_headroom_requires_frozen_policy_for_validation():
    examples = [
        _example("hotpotqa:q5:S1:0", rows=False, remaining_depth=1, expansion_available=True, recoverable=True),
    ]

    report = analyze_action_headroom(
        examples,
        calibration_artifact=_artifact(),
        role="disjoint_validation",
        selected_policy="status_safe",
    )

    assert report["selected_policy"] == "status_safe"
    assert report["validation_used_for_selection"] is False
