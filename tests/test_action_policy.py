from slotrag.action_policy import (
    ActionPolicyContext,
    ActionPolicyExample,
    PhysicalActionPolicy,
    evaluate_action_policy,
)
from slotrag.sufficiency import SufficiencyFeatures, SufficiencyPrediction


def test_utility_policy_answers_when_calibrated_evidence_is_sufficient():
    prediction = SufficiencyPrediction(
        status="SUFFICIENT",
        probability=0.92,
        raw_logit=2.44,
        features=SufficiencyFeatures(
            top1_score=0.92,
            topk_score=0.80,
            topk_min_score=0.60,
            predicate_coverage=1.0,
            new_entity_coverage=1.0,
            extraction_consistency=0.95,
            row_count=1,
            remaining_plan_depth=0,
            budget_remaining=2,
            budget_fraction=0.5,
        ),
    )

    decision = PhysicalActionPolicy().decide(ActionPolicyContext(
        sufficiency=prediction,
        has_rows=True,
        answerable=True,
        retrieval_calls_used=2,
        retrieval_call_budget=4,
    ))

    assert decision.action == "ANSWER"
    assert decision.policy_name == "utility"
    assert decision.candidates
    assert decision.selected.utility == max(candidate.utility for candidate in decision.candidates)


def test_policy_evaluation_reports_quality_cost_and_oracle_regret():
    prediction = SufficiencyPrediction(
        status="PARTIAL",
        probability=0.45,
        raw_logit=-0.2,
        features=SufficiencyFeatures(
            top1_score=0.45,
            score_entropy=0.8,
            predicate_coverage=0.4,
            extraction_consistency=0.5,
            remaining_plan_depth=1,
            budget_remaining=2,
        ),
    )
    example = ActionPolicyExample(
        example_id="q1",
        context=ActionPolicyContext(
            sufficiency=prediction,
            has_rows=False,
            answerable=False,
            retrieval_calls_used=1,
            retrieval_call_budget=3,
            max_binding_beam_width=1,
            topk_expansion_available=True,
        ),
        action_quality={
            "EXPAND_TOPK": 0.8,
            "REWRITE_QUERY": 0.7,
            "ABSTAIN": 0.0,
        },
        baseline_action="ABSTAIN",
        oracle_action="EXPAND_TOPK",
    )

    report = evaluate_action_policy([example], PhysicalActionPolicy(), policy_name="utility")
    oracle = evaluate_action_policy([example], PhysicalActionPolicy(), policy_name="oracle")

    assert report.example_count == 1
    assert report.action_accuracy == 1.0
    assert report.mean_quality == 0.8
    assert report.mean_regret == 0.0
    assert report.action_usage["EXPAND_TOPK"] == 1
    assert report.gain_tie_loss == {"gain": 1, "tie": 0, "loss": 0}
    assert oracle.mean_quality == 0.8
    assert oracle.mean_regret == 0.0


def test_legacy_decision_is_labeled_and_oracle_ignores_unlabeled_actions():
    prediction = SufficiencyPrediction(
        status="INSUFFICIENT",
        probability=0.1,
        raw_logit=-2.2,
        features=SufficiencyFeatures(),
    )
    context = ActionPolicyContext(
        sufficiency=prediction,
        retrieval_calls_used=0,
        retrieval_call_budget=1,
        query_rewrite_available=True,
    )
    policy = PhysicalActionPolicy()
    legacy = policy.decide_legacy(context)
    assert legacy.policy_name == "legacy"
    example = ActionPolicyExample(
        example_id="q2",
        context=context,
        action_quality={"REWRITE_QUERY": 0.6, "ABSTAIN": 0.0},
        oracle_action="REWRITE_QUERY",
    )
    oracle = policy.decide_oracle(example)
    assert oracle.action == "REWRITE_QUERY"


def test_action_accuracy_uses_only_examples_with_oracle_labels():
    prediction = SufficiencyPrediction(
        status="INSUFFICIENT",
        probability=0.1,
        raw_logit=-2.2,
        features=SufficiencyFeatures(),
    )
    labeled = ActionPolicyExample(
        example_id="labeled",
        context=ActionPolicyContext(
            sufficiency=prediction,
            retrieval_call_budget=1,
            query_rewrite_available=True,
        ),
        action_quality={"REWRITE_QUERY": 1.0, "ABSTAIN": 0.0},
        oracle_action="REWRITE_QUERY",
    )
    unlabeled = ActionPolicyExample(
        example_id="unlabeled",
        context=ActionPolicyContext(
            sufficiency=prediction,
            retrieval_call_budget=1,
            query_rewrite_available=True,
        ),
        action_quality={"ABSTAIN": 0.0},
    )
    report = evaluate_action_policy([labeled, unlabeled], PhysicalActionPolicy(), policy_name="oracle")
    assert report.action_accuracy == 1.0


def test_runtime_action_candidates_require_explicit_executor_capabilities():
    prediction = SufficiencyPrediction(
        status="INSUFFICIENT",
        probability=0.1,
        raw_logit=-2.2,
        features=SufficiencyFeatures(),
    )

    actions = {
        candidate.action
        for candidate in PhysicalActionPolicy().candidates(ActionPolicyContext(
            sufficiency=prediction,
            retrieval_call_budget=4,
        ))
    }

    assert actions == {"ABSTAIN"}


def test_development_selected_no_topk_mode_suppresses_expansion_only_for_utility():
    prediction = SufficiencyPrediction(
        status="INSUFFICIENT",
        probability=0.1,
        raw_logit=-2.2,
        features=SufficiencyFeatures(),
    )
    context = ActionPolicyContext(
        sufficiency=prediction,
        retrieval_calls_used=1,
        retrieval_call_budget=4,
        topk_expansion_available=True,
    )
    policy = PhysicalActionPolicy(topk_expansion_mode="disabled")

    decision = policy.decide(context)
    fixed = policy.decide_fixed_topk(context)

    assert decision.policy_name == "utility_no_topk"
    assert decision.action == "ABSTAIN"
    assert "EXPAND_TOPK" not in {candidate.action for candidate in decision.candidates}
    assert fixed.action == "EXPAND_TOPK"


def test_status_safe_mode_suppresses_topk_only_for_sufficient_states():
    sufficient = SufficiencyPrediction(
        status="SUFFICIENT",
        probability=0.7,
        raw_logit=0.8,
        features=SufficiencyFeatures(row_count=1),
    )
    partial = sufficient.model_copy(update={"status": "PARTIAL", "probability": 0.4})
    policy = PhysicalActionPolicy(topk_expansion_mode="status_safe")

    sufficient_decision = policy.decide(ActionPolicyContext(
        sufficiency=sufficient,
        has_rows=True,
        retrieval_calls_used=1,
        retrieval_call_budget=4,
        topk_expansion_available=True,
    ))
    partial_decision = policy.decide(ActionPolicyContext(
        sufficiency=partial,
        retrieval_calls_used=1,
        retrieval_call_budget=4,
        topk_expansion_available=True,
    ))

    assert sufficient_decision.policy_name == "utility_status_safe"
    assert "EXPAND_TOPK" not in {candidate.action for candidate in sufficient_decision.candidates}
    assert "EXPAND_TOPK" in {candidate.action for candidate in partial_decision.candidates}
