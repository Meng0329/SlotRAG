"""Development-only counterfactual analysis for bounded top-k actions."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Literal, Sequence

from ..action_policy import ActionPolicyContext, PhysicalActionPolicy
from ..sufficiency import SufficiencyCalibrationArtifact, SufficiencyExample


AnalysisRole = Literal["development_selection", "disjoint_validation"]
POLICIES = (
    "no_expansion",
    "fixed_topk",
    "rule",
    "current_utility",
    "status_safe",
    "oracle_candidate_pool",
)
POLICY_DEFINITIONS = {
    "no_expansion": "never issue the bounded top-k expansion",
    "fixed_topk": "expand every eligible materialization to the recorded larger candidate pool",
    "rule": "existing explainable rule policy from PhysicalActionPolicy.decide_rule",
    "current_utility": "current runtime utility policy with its token and latency penalties",
    "status_safe": "expand eligible PARTIAL or INSUFFICIENT states; never expand SUFFICIENT states",
    "oracle_candidate_pool": "expand exactly when recorded candidates contain unselected gold evidence",
}
SELECTABLE_POLICIES = (
    "no_expansion",
    "fixed_topk",
    "rule",
    "current_utility",
    "status_safe",
)
_SELECTION_TIEBREAK = {
    "no_expansion": 0,
    "fixed_topk": 1,
    "rule": 2,
    "current_utility": 3,
    "status_safe": 4,
}


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def _policy_metrics(
    records: Sequence[dict[str, Any]],
    policy_name: str,
    *,
    retrieval_call_penalty: float,
) -> dict[str, Any]:
    true_positive = false_positive = false_negative = true_negative = 0
    calls = 0
    for record in records:
        predicted = bool(record["policy_expands"][policy_name])
        positive = bool(record["expand_topk_recoverable"])
        if predicted:
            calls += int(record["topk_expansion_retrieval_calls"])
        if predicted and positive:
            true_positive += 1
        elif predicted:
            false_positive += 1
        elif positive:
            false_negative += 1
        else:
            true_negative += 1
    predicted_expansions = true_positive + false_positive
    count = len(records)
    precision = _ratio(true_positive, predicted_expansions)
    recall = _ratio(true_positive, true_positive + false_negative)
    f1 = _ratio(2 * precision * recall, precision + recall)
    proxy_net_utility = _ratio(
        true_positive - retrieval_call_penalty * calls,
        count,
    )
    return {
        "policy": policy_name,
        "example_count": count,
        "eligible_count": sum(bool(record["expansion_eligible"]) for record in records),
        "recoverable_positive_count": true_positive + false_negative,
        "predicted_expansions": predicted_expansions,
        "false_expansions": false_positive,
        "predicted_retrieval_calls": calls,
        "mean_retrieval_calls": _ratio(calls, count),
        "mean_proxy_evidence_gain": _ratio(true_positive, count),
        "proxy_net_utility": proxy_net_utility,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "confusion": {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "true_negative": true_negative,
        },
        "gain_tie_loss_vs_no_expansion_proxy": {
            "gain": true_positive,
            "tie": count - true_positive - false_positive,
            "loss": false_positive,
        },
    }


def _base_summary(
    records: Sequence[dict[str, Any]],
    *,
    retrieval_call_penalty: float,
) -> dict[str, Any]:
    return {
        "example_count": len(records),
        "eligible_count": sum(bool(record["expansion_eligible"]) for record in records),
        "recoverable_positive_count": sum(
            bool(record["expand_topk_recoverable"]) for record in records
        ),
        "policies": {
            policy_name: _policy_metrics(
                records,
                policy_name,
                retrieval_call_penalty=retrieval_call_penalty,
            )
            for policy_name in POLICIES
        },
    }


def _stratify(
    records: Sequence[dict[str, Any]],
    field: str,
    *,
    retrieval_call_penalty: float,
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(record[field])].append(record)
    return {
        value: _base_summary(rows, retrieval_call_penalty=retrieval_call_penalty)
        for value, rows in sorted(groups.items())
    }


def _select_policy(policies: dict[str, dict[str, Any]]) -> tuple[str, list[str]]:
    ranking = sorted(
        SELECTABLE_POLICIES,
        key=lambda name: (
            float(policies[name]["proxy_net_utility"]),
            float(policies[name]["precision"]),
            float(policies[name]["recall"]),
            -float(policies[name]["mean_retrieval_calls"]),
            _SELECTION_TIEBREAK[name],
        ),
        reverse=True,
    )
    return ranking[0], ranking


def analyze_action_headroom(
    examples: Sequence[dict[str, Any]],
    *,
    calibration_artifact: SufficiencyCalibrationArtifact,
    role: AnalysisRole,
    selected_policy: str | None = None,
    retrieval_call_penalty: float = 0.08,
) -> dict[str, Any]:
    """Evaluate expansion decisions against a candidate-pool gold recovery proxy.

    The target only says that a gold supporting passage was absent from selected top-k
    but present in the already-recorded candidate pool. It is an optimistic retrieval
    upper bound, not a provider execution or answer-quality counterfactual.
    """
    if role not in {"development_selection", "disjoint_validation"}:
        raise ValueError(f"unsupported action-headroom role: {role}")
    if retrieval_call_penalty < 0:
        raise ValueError("retrieval_call_penalty must be non-negative")
    if role == "development_selection" and selected_policy is not None:
        raise ValueError("development selection must not receive a preselected policy")
    if role == "disjoint_validation" and selected_policy not in SELECTABLE_POLICIES:
        raise ValueError("disjoint validation requires a frozen selectable policy")

    strong = [
        row for row in examples
        if row.get("supervision") == "strong_gold_evidence"
    ]
    if not strong:
        raise ValueError("action headroom requires strong_gold_evidence examples")

    physical_policy = PhysicalActionPolicy(retrieval_call_penalty=retrieval_call_penalty)
    records: list[dict[str, Any]] = []
    for row in strong:
        supervision = row.get("action_supervision")
        if not isinstance(supervision, dict):
            raise ValueError(f"missing action_supervision: {row.get('example_id')}")
        if supervision.get("candidate_pool_is_counterfactual_proxy") is not True:
            raise ValueError(f"unmarked candidate-pool proxy: {row.get('example_id')}")
        dataset = str(row.get("dataset") or "")
        calibrator = calibration_artifact.calibrator_for(dataset)
        example = SufficiencyExample.model_validate({
            "example_id": row["example_id"],
            "label": row["label"],
            "context": row["context"],
        })
        prediction = calibrator.predict(example.context)
        expansion_calls = int(supervision.get("topk_expansion_retrieval_calls") or 1)
        budget_available = (
            example.context.retrieval_calls_used + expansion_calls
            <= example.context.retrieval_budget
        )
        expansion_eligible = bool(
            supervision.get("eligible")
            and supervision.get("expansion_available")
            and int(supervision.get("candidate_count") or 0)
            > int(supervision.get("selected_count") or 0)
            and budget_available
        )
        policy_context = ActionPolicyContext(
            sufficiency=prediction,
            has_rows=bool(example.context.extracted_rows),
            answerable=(
                bool(example.context.extracted_rows)
                and example.context.remaining_plan_depth == 0
            ),
            retrieval_calls_used=example.context.retrieval_calls_used,
            retrieval_call_budget=example.context.retrieval_budget,
            topk_expansion_available=expansion_eligible,
            topk_expansion_retrieval_calls=expansion_calls,
        )
        current_decision = physical_policy.decide(policy_context)
        rule_decision = physical_policy.decide_rule(policy_context)
        recoverable = bool(supervision.get("expand_topk_recoverable"))
        if recoverable and not expansion_eligible:
            raise ValueError(
                f"recoverable proxy is not expansion eligible: {row.get('example_id')}"
            )
        records.append({
            "example_id": example.example_id,
            "dataset": dataset,
            "question_id": str(row.get("question_id") or ""),
            "question_type": str(row.get("question_type") or "unknown"),
            "slot_id": str(row.get("slot_id") or ""),
            "remaining_plan_depth": example.context.remaining_plan_depth,
            "sufficiency_status": prediction.status,
            "sufficiency_probability": prediction.probability,
            "sufficiency_features": prediction.features.model_dump(mode="json"),
            "has_rows": bool(example.context.extracted_rows),
            "expansion_eligible": expansion_eligible,
            "expand_topk_recoverable": recoverable,
            "topk_expansion_retrieval_calls": expansion_calls,
            "selected_count": int(supervision.get("selected_count") or 0),
            "candidate_count": int(supervision.get("candidate_count") or 0),
            "gold_evidence_ids": list(supervision.get("gold_evidence_ids") or []),
            "selected_evidence_ids": list(supervision.get("selected_evidence_ids") or []),
            "candidate_evidence_ids": list(supervision.get("candidate_evidence_ids") or []),
            "retrieval_protocol": row.get("retrieval_protocol"),
            "retrieval_backend": row.get("retrieval_backend"),
            "primary_score": row.get("primary_score"),
            "source_item_path": row.get("item_path"),
            "policy_actions": {
                "current_utility": current_decision.action,
                "rule": rule_decision.action,
                "fixed_topk": "EXPAND_TOPK" if expansion_eligible else "NO_EXPANSION",
                "status_safe": (
                    "EXPAND_TOPK"
                    if expansion_eligible and prediction.status != "SUFFICIENT"
                    else "NO_EXPANSION"
                ),
                "no_expansion": "NO_EXPANSION",
                "oracle_candidate_pool": (
                    "EXPAND_TOPK" if recoverable else "NO_EXPANSION"
                ),
            },
            "policy_expands": {
                "current_utility": current_decision.action == "EXPAND_TOPK",
                "rule": rule_decision.action == "EXPAND_TOPK",
                "fixed_topk": expansion_eligible,
                "status_safe": expansion_eligible and prediction.status != "SUFFICIENT",
                "no_expansion": False,
                "oracle_candidate_pool": recoverable,
            },
        })

    summary = _base_summary(records, retrieval_call_penalty=retrieval_call_penalty)
    ranking: list[str] | None = None
    if role == "development_selection":
        selected_policy, ranking = _select_policy(summary["policies"])
    assert selected_policy is not None
    status_counts = Counter(record["sufficiency_status"] for record in records)
    question_ids = sorted({record["question_id"] for record in records})
    return {
        "schema_version": 1,
        "analysis": "bounded-topk-candidate-pool-headroom",
        "role": role,
        "provider_calls": 0,
        "validation_used_for_selection": False,
        "candidate_pool_is_counterfactual_proxy": True,
        "counterfactual_limit": (
            "gold evidence in the recorded candidate pool does not guarantee that a real "
            "expanded retrieval/extraction/generation path would recover the answer"
        ),
        "retrieval_call_penalty": retrieval_call_penalty,
        "input_example_count": len(examples),
        "excluded_non_strong_count": len(examples) - len(strong),
        "example_count": len(records),
        "question_count": len(question_ids),
        "question_ids": question_ids,
        "status_counts": dict(sorted(status_counts.items())),
        "eligible_count": summary["eligible_count"],
        "recoverable_positive_count": summary["recoverable_positive_count"],
        "oracle_max_mean_evidence_recovery": _ratio(
            summary["recoverable_positive_count"], len(records)
        ),
        "policies": summary["policies"],
        "policy_definitions": POLICY_DEFINITIONS,
        "selected_policy": selected_policy,
        "policy_ranking": ranking,
        "selection_candidates": list(SELECTABLE_POLICIES),
        "oracle_excluded_from_selection": True,
        "strata": {
            "by_dataset": _stratify(
                records, "dataset", retrieval_call_penalty=retrieval_call_penalty
            ),
            "by_status": _stratify(
                records, "sufficiency_status", retrieval_call_penalty=retrieval_call_penalty
            ),
            "by_plan_depth": _stratify(
                records, "remaining_plan_depth", retrieval_call_penalty=retrieval_call_penalty
            ),
            "by_question_type": _stratify(
                records, "question_type", retrieval_call_penalty=retrieval_call_penalty
            ),
        },
        "examples": records,
    }
