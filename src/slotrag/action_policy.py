"""Explainable physical action selection over calibrated evidence state."""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal, Sequence

from pydantic import Field

from .models import BindingRow, StrictModel
from .sufficiency import SufficiencyFeatures, SufficiencyPrediction, SufficiencyStatus


Action = Literal[
    "STOP_SLOT",
    "RETRIEVE_SLOT_ONLY",
    "RETRIEVE_QUESTION_PLUS_SLOT",
    "EXPAND_TOPK",
    "REWRITE_QUERY",
    "SWITCH_RETRIEVER",
    "EXPAND_BINDING_BEAM",
    "BACKTRACK",
    "ANSWER",
    "ABSTAIN",
]


class ActionPolicyContext(StrictModel):
    sufficiency: SufficiencyPrediction
    has_rows: bool = False
    answerable: bool = False
    retrieval_calls_used: int = Field(default=0, ge=0)
    retrieval_call_budget: int = Field(default=0, ge=0)
    token_budget_used: int = Field(default=0, ge=0)
    token_budget: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0)
    latency_budget_ms: float = Field(default=0.0, ge=0)
    binding_beam_width: int = Field(default=1, ge=1)
    max_binding_beam_width: int = Field(default=8, ge=1)
    can_backtrack: bool = False
    query_rewrite_available: bool = True
    alternate_retriever_available: bool = True


class ActionCandidate(StrictModel):
    action: Action
    expected_quality_gain: float
    retrieval_calls: float = 0.0
    tokens: float = 0.0
    latency_ms: float = 0.0
    utility: float
    rationale: str


class ActionDecision(StrictModel):
    policy_name: Literal["utility", "rule", "fixed_topk", "legacy", "oracle"]
    action: Action
    selected: ActionCandidate
    candidates: list[ActionCandidate]


class ActionPolicyExample(StrictModel):
    example_id: str = Field(min_length=1)
    context: ActionPolicyContext
    action_quality: dict[str, float] = Field(default_factory=dict)
    action_cost: dict[str, dict[str, float]] = Field(default_factory=dict)
    baseline_action: Action | None = None
    oracle_action: Action | None = None


class ActionPolicyReport(StrictModel):
    policy_name: Literal["utility", "rule", "fixed_topk", "legacy", "oracle"]
    example_count: int
    action_accuracy: float
    mean_quality: float
    mean_regret: float
    mean_retrieval_calls: float
    mean_tokens: float
    mean_latency_ms: float
    action_usage: dict[str, int]
    gain_tie_loss: dict[str, int]


class PhysicalActionPolicy:
    """A deterministic utility policy; weights are explicit and development-tunable."""

    def __init__(
        self,
        *,
        quality_weight: float = 1.0,
        retrieval_call_penalty: float = 0.08,
        token_penalty: float = 0.00005,
        latency_penalty: float = 0.0005,
    ) -> None:
        self.quality_weight = quality_weight
        self.retrieval_call_penalty = retrieval_call_penalty
        self.token_penalty = token_penalty
        self.latency_penalty = latency_penalty

    def _candidate(
        self,
        action: Action,
        *,
        gain: float,
        calls: float = 0.0,
        tokens: float = 0.0,
        latency_ms: float = 0.0,
        rationale: str,
    ) -> ActionCandidate:
        utility = (
            self.quality_weight * gain
            - self.retrieval_call_penalty * calls
            - self.token_penalty * tokens
            - self.latency_penalty * latency_ms
        )
        return ActionCandidate(
            action=action,
            expected_quality_gain=gain,
            retrieval_calls=calls,
            tokens=tokens,
            latency_ms=latency_ms,
            utility=utility,
            rationale=rationale,
        )

    def candidates(self, context: ActionPolicyContext) -> list[ActionCandidate]:
        prediction = context.sufficiency
        features = prediction.features
        probability = prediction.probability
        remaining_calls = max(context.retrieval_call_budget - context.retrieval_calls_used, 0)
        candidates: list[ActionCandidate] = []
        if context.answerable and context.has_rows:
            candidates.append(self._candidate(
                "ANSWER",
                gain=probability,
                tokens=32,
                latency_ms=15,
                rationale="structured rows are answerable and calibrated evidence is available",
            ))
        if prediction.status == "SUFFICIENT" and context.has_rows:
            candidates.append(self._candidate(
                "STOP_SLOT",
                gain=probability * 0.95,
                rationale="slot evidence is sufficient; stop further expansion",
            ))
        if remaining_calls > 0:
            uncertainty = max(1.0 - probability, 0.0)
            candidates.append(self._candidate(
                "EXPAND_TOPK",
                gain=uncertainty * (0.35 + 0.35 * features.score_entropy),
                calls=1,
                tokens=512,
                latency_ms=120,
                rationale="uncertainty and score dispersion leave recoverable evidence headroom",
            ))
            candidates.append(self._candidate(
                "RETRIEVE_QUESTION_PLUS_SLOT",
                gain=uncertainty * (0.25 + 0.25 * (1.0 - features.predicate_coverage)),
                calls=1,
                tokens=256,
                latency_ms=110,
                rationale="query context may recover predicate coverage",
            ))
            if context.query_rewrite_available:
                candidates.append(self._candidate(
                    "REWRITE_QUERY",
                    gain=uncertainty * (0.20 + 0.30 * (1.0 - features.bound_variable_coverage)),
                    calls=1,
                    tokens=256,
                    latency_ms=100,
                    rationale="bound-variable or predicate coverage is incomplete",
                ))
            if context.alternate_retriever_available:
                candidates.append(self._candidate(
                    "SWITCH_RETRIEVER",
                    gain=uncertainty * (0.15 + 0.25 * (1.0 - features.sparse_dense_agreement)),
                    calls=1,
                    tokens=128,
                    latency_ms=90,
                    rationale="retriever disagreement indicates a complementary ranking may help",
                ))
        if context.binding_beam_width < context.max_binding_beam_width and features.extraction_consistency > 0:
            candidates.append(self._candidate(
                "EXPAND_BINDING_BEAM",
                gain=max(1.0 - features.new_entity_coverage, 0.0) * 0.35,
                calls=0,
                tokens=128,
                latency_ms=20,
                rationale="rows exist but requested entities are not fully covered",
            ))
        if context.can_backtrack:
            candidates.append(self._candidate(
                "BACKTRACK",
                gain=max(1.0 - features.join_edge_coverage, 0.0) * 0.45,
                calls=1,
                tokens=128,
                latency_ms=80,
                rationale="join-edge coverage is incomplete and an alternate path is available",
            ))
        candidates.append(self._candidate(
            "ABSTAIN",
            gain=0.0,
            rationale="avoid an unsupported answer when evidence cannot be established",
        ))
        return candidates

    def decide(self, context: ActionPolicyContext) -> ActionDecision:
        candidates = self.candidates(context)
        selected = max(candidates, key=lambda item: (item.utility, item.expected_quality_gain, item.action))
        return ActionDecision(
            policy_name="utility",
            action=selected.action,
            selected=selected,
            candidates=candidates,
        )

    def decide_rule(self, context: ActionPolicyContext) -> ActionDecision:
        prediction = context.sufficiency
        if context.answerable and context.has_rows and prediction.status == "SUFFICIENT":
            action: Action = "ANSWER"
        elif context.retrieval_calls_used < context.retrieval_call_budget:
            action = "EXPAND_TOPK"
        else:
            action = "ABSTAIN"
        candidates = self.candidates(context)
        selected = next(candidate for candidate in candidates if candidate.action == action)
        return ActionDecision(policy_name="rule", action=action, selected=selected, candidates=candidates)

    def decide_fixed_topk(self, context: ActionPolicyContext) -> ActionDecision:
        action: Action = "ANSWER" if context.answerable and context.has_rows else (
            "EXPAND_TOPK" if context.retrieval_calls_used < context.retrieval_call_budget else "ABSTAIN"
        )
        candidates = self.candidates(context)
        selected = next(candidate for candidate in candidates if candidate.action == action)
        return ActionDecision(policy_name="fixed_topk", action=action, selected=selected, candidates=candidates)

    def decide_legacy(self, context: ActionPolicyContext) -> ActionDecision:
        action: Action = "ANSWER" if context.answerable and context.has_rows else (
            "RETRIEVE_SLOT_ONLY" if context.retrieval_calls_used < context.retrieval_call_budget else "ABSTAIN"
        )
        candidates = self.candidates(context)
        candidate = next((item for item in candidates if item.action == action), self._candidate(action, gain=0.0, rationale="legacy fixed strategy"))
        return ActionDecision(policy_name="legacy", action=action, selected=candidate, candidates=candidates)

    def decide_oracle(self, example: ActionPolicyExample) -> ActionDecision:
        candidates = self.candidates(example.context)
        quality = example.action_quality
        selected = max(
            candidates,
            key=lambda item: (quality.get(item.action, 0.0), -item.retrieval_calls, item.action),
        )
        return ActionDecision(policy_name="oracle", action=selected.action, selected=selected, candidates=candidates)


def make_runtime_sufficiency_prediction(
    rows: Sequence[BindingRow],
    *,
    remaining_plan_depth: int,
    budget_remaining: int,
) -> SufficiencyPrediction:
    """Create an explicitly proxy prediction for runtime telemetry.

    Runtime extraction currently does not expose calibrated ranked scores at the executor
    boundary. This conservative proxy is useful for tracing action choices, but is not a
    development calibration result and must not be used to tune evaluation thresholds.
    """
    confidence = sum(row.confidence for row in rows) / len(rows) if rows else 0.0
    retrieval_scores = [row.retrieval_score for row in rows if row.retrieval_score is not None]
    top_score = max(retrieval_scores, default=confidence)
    extraction_consistency = confidence if rows else 0.0
    status: SufficiencyStatus
    if rows and remaining_plan_depth == 0 and confidence >= 0.5:
        status = "SUFFICIENT"
    elif rows:
        status = "PARTIAL"
    else:
        status = "INSUFFICIENT"
    probability = min(max(0.7 * confidence + 0.3 * top_score, 0.0), 1.0)
    features = SufficiencyFeatures(
        top1_score=top_score,
        topk_score=confidence,
        topk_min_score=min(retrieval_scores, default=confidence),
        top1_top2_margin=0.0,
        score_entropy=1.0 if len(rows) > 1 else 0.0,
        sparse_dense_agreement=0.0,
        reranker_agreement=0.0,
        new_entity_coverage=1.0 if rows else 0.0,
        source_diversity=min(len({row.source_id for row in rows}) / max(len(rows), 1), 1.0),
        predicate_coverage=1.0 if rows else 0.0,
        bound_variable_coverage=1.0 if rows else 0.0,
        join_edge_coverage=1.0 if remaining_plan_depth == 0 and rows else 0.5 if rows else 0.0,
        extraction_consistency=extraction_consistency,
        row_count=len(rows),
        remaining_plan_depth=remaining_plan_depth,
        budget_remaining=budget_remaining,
        budget_fraction=min(max(budget_remaining / max(budget_remaining + 1, 1), 0.0), 1.0),
        retrieval_count=len(rows),
    )
    return SufficiencyPrediction(
        status=status,
        probability=probability,
        raw_logit=(probability - 0.5) * 8.0,
        features=features,
    )


def evaluate_action_policy(
    examples: Sequence[ActionPolicyExample],
    policy: PhysicalActionPolicy,
    *,
    policy_name: Literal["utility", "rule", "fixed_topk", "legacy", "oracle"] = "utility",
) -> ActionPolicyReport:
    if not examples:
        raise ValueError("at least one action-policy example is required")
    decisions: list[tuple[ActionPolicyExample, ActionDecision]] = []
    for example in examples:
        if policy_name == "utility":
            decision = policy.decide(example.context)
        elif policy_name == "rule":
            decision = policy.decide_rule(example.context)
        elif policy_name == "fixed_topk":
            decision = policy.decide_fixed_topk(example.context)
        elif policy_name == "legacy":
            decision = policy.decide_legacy(example.context)
        else:
            decision = policy.decide_oracle(example)
        decisions.append((example, decision))
    qualities = [example.action_quality.get(decision.action, 0.0) for example, decision in decisions]
    oracle_qualities = [
        max(example.action_quality.values(), default=0.0)
        for example, _decision in decisions
    ]
    action_usage = dict(Counter(decision.action for _example, decision in decisions))
    cost_values = [
        example.action_cost.get(decision.action, {
            "retrieval_calls": decision.selected.retrieval_calls,
            "tokens": decision.selected.tokens,
            "latency_ms": decision.selected.latency_ms,
        })
        for example, decision in decisions
    ]
    labeled_oracle = [
        decision.action == example.oracle_action
        for example, decision in decisions
        if example.oracle_action is not None
    ]
    contrasts = [
        example.action_quality.get(decision.action, 0.0) - example.action_quality.get(example.baseline_action or "ABSTAIN", 0.0)
        for example, decision in decisions
    ]
    return ActionPolicyReport(
        policy_name=policy_name,
        example_count=len(examples),
        action_accuracy=sum(labeled_oracle) / len(labeled_oracle) if labeled_oracle else 0.0,
        mean_quality=sum(qualities) / len(qualities),
        mean_regret=sum(max(oracle - quality, 0.0) for oracle, quality in zip(oracle_qualities, qualities)) / len(qualities),
        mean_retrieval_calls=sum(float(cost.get("retrieval_calls", 0.0)) for cost in cost_values) / len(cost_values),
        mean_tokens=sum(float(cost.get("tokens", 0.0)) for cost in cost_values) / len(cost_values),
        mean_latency_ms=sum(float(cost.get("latency_ms", 0.0)) for cost in cost_values) / len(cost_values),
        action_usage=action_usage,
        gain_tie_loss={
            "gain": sum(value > 0 for value in contrasts),
            "tie": sum(value == 0 for value in contrasts),
            "loss": sum(value < 0 for value in contrasts),
        },
    )


__all__ = [
    "Action",
    "ActionCandidate",
    "ActionDecision",
    "ActionPolicyContext",
    "ActionPolicyExample",
    "ActionPolicyReport",
    "PhysicalActionPolicy",
    "make_runtime_sufficiency_prediction",
    "evaluate_action_policy",
]
