"""Run provider-free physical action policy evaluation on labeled simulations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from slotrag.action_policy import (
    ActionPolicyContext,
    ActionPolicyExample,
    PhysicalActionPolicy,
    evaluate_action_policy,
)
from slotrag.sufficiency import SufficiencyFeatures, SufficiencyPrediction


def _prediction(
    *,
    status: str,
    probability: float,
    predicate_coverage: float,
    bound_coverage: float,
    join_coverage: float,
    entities: float,
    consistency: float,
    entropy: float,
    depth: int,
) -> SufficiencyPrediction:
    return SufficiencyPrediction(
        status=status,
        probability=probability,
        raw_logit=probability * 2 - 1,
        features=SufficiencyFeatures(
            top1_score=probability,
            topk_score=probability * 0.9,
            topk_min_score=probability * 0.7,
            score_entropy=entropy,
            sparse_dense_agreement=0.8,
            reranker_agreement=0.8,
            new_entity_coverage=entities,
            source_diversity=0.8,
            predicate_coverage=predicate_coverage,
            bound_variable_coverage=bound_coverage,
            join_edge_coverage=join_coverage,
            extraction_consistency=consistency,
            row_count=int(entities > 0),
            remaining_plan_depth=depth,
            budget_remaining=2,
            budget_fraction=0.5,
            retrieval_count=5,
        ),
    )


def _examples() -> list[ActionPolicyExample]:
    examples: list[ActionPolicyExample] = []
    for index in range(12):
        mode = index % 4
        if mode == 0:
            prediction = _prediction(
                status="SUFFICIENT", probability=0.90, predicate_coverage=1.0,
                bound_coverage=1.0, join_coverage=1.0, entities=1.0,
                consistency=0.95, entropy=0.1, depth=0,
            )
            context = ActionPolicyContext(
                sufficiency=prediction, has_rows=True, answerable=True,
                retrieval_calls_used=1, retrieval_call_budget=3,
                max_binding_beam_width=1,
            )
            quality = {"ANSWER": 1.0, "STOP_SLOT": 0.95, "ABSTAIN": 0.0}
            oracle = "ANSWER"
        elif mode == 1:
            prediction = _prediction(
                status="PARTIAL", probability=0.45, predicate_coverage=0.5,
                bound_coverage=0.6, join_coverage=0.5, entities=0.5,
                consistency=0.55, entropy=0.8, depth=1,
            )
            context = ActionPolicyContext(
                sufficiency=prediction, has_rows=False, answerable=False,
                retrieval_calls_used=1, retrieval_call_budget=3,
                max_binding_beam_width=1,
            )
            quality = {"EXPAND_TOPK": 0.8, "REWRITE_QUERY": 0.7, "ABSTAIN": 0.0}
            oracle = "EXPAND_TOPK"
        elif mode == 2:
            prediction = _prediction(
                status="INSUFFICIENT", probability=0.12, predicate_coverage=0.1,
                bound_coverage=0.2, join_coverage=0.0, entities=0.0,
                consistency=0.0, entropy=0.9, depth=2,
            )
            context = ActionPolicyContext(
                sufficiency=prediction, has_rows=False, answerable=False,
                retrieval_calls_used=2, retrieval_call_budget=3,
                can_backtrack=True, query_rewrite_available=True,
                max_binding_beam_width=1,
            )
            quality = {"REWRITE_QUERY": 0.75, "BACKTRACK": 0.65, "ABSTAIN": 0.0}
            oracle = "REWRITE_QUERY"
        else:
            prediction = _prediction(
                status="PARTIAL", probability=0.38, predicate_coverage=0.8,
                bound_coverage=0.8, join_coverage=0.25, entities=0.5,
                consistency=0.65, entropy=0.6, depth=1,
            )
            context = ActionPolicyContext(
                sufficiency=prediction, has_rows=True, answerable=False,
                retrieval_calls_used=1, retrieval_call_budget=3,
                can_backtrack=True, binding_beam_width=1,
            )
            quality = {"BACKTRACK": 0.7, "EXPAND_BINDING_BEAM": 0.6, "EXPAND_TOPK": 0.4, "ABSTAIN": 0.0}
            oracle = "BACKTRACK"
        examples.append(ActionPolicyExample(
            example_id=f"policy-smoke-{index:02d}",
            context=context,
            action_quality=quality,
            baseline_action="ABSTAIN",
            oracle_action=oracle,
        ))
    return examples


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    examples = _examples()
    policy = PhysicalActionPolicy()
    reports = {
        name: evaluate_action_policy(examples, policy, policy_name=name).model_dump(mode="json")
        for name in ("utility", "rule", "fixed_topk", "legacy", "oracle")
    }
    decisions = []
    for example in examples:
        decision = policy.decide(example.context)
        decisions.append({
            "example_id": example.example_id,
            "oracle_action": example.oracle_action,
            "baseline_action": example.baseline_action,
            "chosen_action": decision.action,
            "selected": decision.selected.model_dump(mode="json"),
            "candidates": [candidate.model_dump(mode="json") for candidate in decision.candidates],
        })
    summary = {
        "version": "v61",
        "provider_calls": 0,
        "simulation_only": True,
        "example_count": len(examples),
        "reports": reports,
        "decisions": decisions,
    }
    if reports["oracle"]["mean_regret"] != 0.0:
        raise RuntimeError(f"oracle policy is not an upper bound: {summary}")
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "examples.jsonl").write_text(
        "".join(json.dumps(example.model_dump(mode="json"), ensure_ascii=False) + "\n" for example in examples),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
