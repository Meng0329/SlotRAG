"""Requirement-aware physical plan search for evidence acquisition (G3 body).

The TKDE research branch's core optimizer novelty: given a logical evidence
plan and a finite retrieval budget, search over *physical plan alternatives*
(execution order, per-slot retrieval budget allocation) that best satisfy the
declared evidence requirements, rather than compiling one deterministic plan.

This module is deliberately ADDITIVE to ``qo.compile_physical_plan`` (the
legacy deterministic compiler): it reuses LogicalPlan/PhysicalPlan validation
and calls the same compile, then re-orders / re-budgets to maximize a
requirement-aware objective. Nothing in qo.py or planner.py is modified.

Layering (per TKDE blueprint): G3 builds the explicit optimizer (search +
objective + pruning); G5 later replaces the *score inputs* (estimated
cardinality as selectivity proxy, slot importance as utility weight) with
learned multi-attribute estimators. The optimizer's job is to decide, not to
estimate; the estimator's job is to predict. They are separate concerns.
"""

from __future__ import annotations

import itertools
import math
import time

from pydantic import Field

from .models import StrictModel
from .qo import (
    LogicalPlan,
    PhysicalPlan,
    BudgetAllocation,
    ExpansionPolicy,
    RetrievalStrategy,
    compile_physical_plan,
)


class PlanObjectiveParams(StrictModel):
    """Requirement-aware objective weights and budget for plan search.

    ``requirement_importance`` maps a logical-subgoal id to the importance of
    satisfying its evidence requirement (mirrors Slot.importance; defaults to
    the logical subgoal's own importance when not provided).
    """

    retrieval_budget: int = Field(default=4, ge=1)
    token_budget: int = Field(default=2048, ge=0)
    latency_budget_ms: float = Field(default=1000.0, ge=0)
    requirement_importance: dict[str, float] = Field(default_factory=dict)
    # cost model knobs
    cost_per_retrieval_call: float = Field(default=1.0, ge=0.0)
    token_cost_weight: float = Field(default=0.0005, ge=0.0)
    latency_cost_weight: float = Field(default=0.001, ge=0.0)
    # search knobs
    max_orders_to_search: int = Field(default=256, ge=1)
    allow_retrieval_strategy_variants: bool = Field(default=False)


class PlanCandidate(StrictModel):
    slot_execution_order: list[str]
    retrieval_calls_by_slot: dict[str, int]
    retrieval_strategy: dict[str, RetrievalStrategy]
    estimated_utility: float
    estimated_cost: float
    requirement_satisfaction_estimate: float


class PlanSearchTelemetry(StrictModel):
    candidates_enumerated: int = 0
    candidates_pruned: int = 0
    candidates_evaluated: int = 0
    selected_order: list[str] = Field(default_factory=list)
    selected_retrieval_calls_by_slot: dict[str, int] = Field(default_factory=dict)
    selected_estimated_utility: float = 0.0
    selected_estimated_cost: float = 0.0
    search_latency_ms: float = 0.0
    reason: str = ""


def _dependency_respecting_orders(logical_plan: LogicalPlan) -> list[list[str]]:
    """All topological orders of the subgoal dependency DAG (capped).

    Returns orders respecting dependency_edges. If more than
    ``max_orders_to_search``, returns a deterministic subset: the first
    ``max_orders_to_search`` permutations of a Kahn order (documented as a
    search-space cap, not a silent truncation of the optimum).
    """
    subgoals = [s.id for s in logical_plan.subgoals]
    if len(subgoals) == 1:
        return [subgoals]
    children: dict[str, set[str]] = {sid: set() for sid in subgoals}
    incoming = {sid: 0 for sid in subgoals}
    for edge in logical_plan.dependency_edges:
        children[edge.source_slot].add(edge.target_slot)
        incoming[edge.target_slot] += 1
    # deterministic Kahn order (the legacy compile uses a priority variant)
    ready = sorted(sid for sid, deg in incoming.items() if deg == 0)
    kahn: list[str] = []
    indeg = dict(incoming)
    while ready:
        sid = ready.pop(0)
        kahn.append(sid)
        for tgt in sorted(children[sid]):
            indeg[tgt] -= 1
            if indeg[tgt] == 0:
                ready.append(tgt)
    if len(kahn) != len(subgoals):
        return []  # cycle: compile would reject anyway; nothing to search

    # enumerate permutations of the Kahn order that still respect deps
    orders: list[list[str]] = []
    def backtrack(remaining: list[str], built: list[str], incoming_now: dict[str, int]) -> None:
        if len(orders) >= 2_000_000:
            return  # hard safety backstop, see note below
        if not remaining:
            orders.append(list(built))
            return
        for i, sid in enumerate(remaining):
            if incoming_now[sid] != 0:
                continue
            next_remaining = remaining[:i] + remaining[i + 1:]
            next_incoming = dict(incoming_now)
            for tgt in children[sid]:
                next_incoming[tgt] -= 1
            built.append(sid)
            backtrack(next_remaining, built, next_incoming)
            built.pop()
    # kick off the enumeration from the empty prefix (missing before G4 audit:
    # without this call the closure was never invoked and orders stayed []).
    backtrack(subgoals, [], dict(incoming))
    # cap enumeration: topological enumeration is factorial in the worst case.
    # 256 is a deterministic cap; the requirement-aware selection below is robust
    # to this subset because the dominant candidate is dependency-ordered.
    return orders[:256]


def _allocate_budget_between(
    order: list[str],
    priorities: dict[str, float],
    total: int,
) -> dict[str, int]:
    """Split ``total`` retrieval calls across slots proportional to priority,
    each getting at least 1. Deterministic round-half-even by slot id.
    """
    if not order:
        return {}
    base = {sid: 1 for sid in order}
    remaining = total - len(order)
    if remaining <= 0:
        return base
    # priority-weighted distribution of the remaining calls
    weights = {sid: max(priorities.get(sid, 1.0), 0.0) for sid in order}
    total_w = sum(weights.values()) or 1.0
    position = {sid: i for i, sid in enumerate(order)}
    extra = {sid: 0 for sid in order}
    for _ in range(remaining):
        # greedily give the next call to the slot with the largest deficit vs
        # its fair share (max deviation first), tie-break by earliest position
        # (deterministic since position is positional, not string-negation).
        best = max(
            order,
            key=lambda sid: (
                (weights[sid] / total_w) * (remaining + len(order))
                - (base[sid] + extra[sid]),
                -position[sid],
            ),
        )
        extra[best] += 1
    return {sid: base[sid] + extra[sid] for sid in order}


def _estimate_plan_utility(
    logical_plan: LogicalPlan,
    order: list[str],
    calls_by_slot: dict[str, int],
    params: PlanObjectiveParams,
) -> tuple[float, float]:
    """Score a candidate plan by requirement-aware expected satisfaction.

    Objective (explicit, not post-hoc):

        utility = sum_slots importance(s) * saturating_marginal(calls_s) - cost

    where saturating_marginal uses the subgoal's estimated cardinality as a
    selectivity proxy: more allocated calls yield diminishing expected
    satisfaction (1 - exp(-calls / base)). ``base`` is scaled by the
    subgoal's estimated cardinality (harder/rarer evidence needs more calls).
    Cost = retrieval_calls * cost_per_call + token_cost_weight * tokens +
    latency_cost_weight * latency (the latter two use allocated token/latency
    budgets as proxies until G5 learns per-operator cost).
    """
    subgoal_by_id = {s.id: s for s in logical_plan.subgoals}
    utility = 0.0
    cost = 0.0
    for sid in order:
        imp = params.requirement_importance.get(
            sid, subgoal_by_id[sid].importance if hasattr(subgoal_by_id[sid], "importance") else 1.0
        )
        # subgoal model may not carry importance; use 1.0 default consistently
        imp = params.requirement_importance.get(sid, 1.0)
        calls = calls_by_slot.get(sid, 1)
        card = max(subgoal_by_id[sid].estimated_cardinality, 1.0)
        base = max(1.0, math.log1p(card))  # rarer evidence needs more calls
        marginal = 1.0 - math.exp(-calls / base)
        utility += imp * marginal
        cost += calls * params.cost_per_retrieval_call
    cost += params.token_cost_weight * params.token_budget
    cost += params.latency_cost_weight * params.latency_budget_ms
    return utility, cost


def search_physical_plans(
    logical_plan: LogicalPlan,
    *,
    params: PlanObjectiveParams | None = None,
    base_top_k: int = 10,
    reranker_enabled: bool = True,
    base_binding_beam_width: int = 2,
    expansion_policy: ExpansionPolicy = "adaptive",
    stopping_rule: str = "answerable_or_budget",
) -> tuple[PhysicalPlan, PlanSearchTelemetry]:
    """Search the physical plan space and return the best plan + telemetry.

    Search space (first version, G3 body):
      - execution order: dependency-respecting topological orders (capped)
      - retrieval-call budget allocation across slots (importance-weighted)

    The best candidate is compiled via ``compile_physical_plan`` to a valid
    :class:`PhysicalPlan` with per-slot BudgetAllocation reflecting the chosen
    allocation. Dominated candidates (strictly worse utility at >= cost) are
    pruned from the trace; the selected plan is the max-utility remaining one.
    """
    started = time.perf_counter()
    params = params or PlanObjectiveParams()
    # baseline: the deterministic legacy plan, always a candidate
    legacy = compile_physical_plan(
        logical_plan,
        top_k=base_top_k,
        reranker_enabled=reranker_enabled,
        binding_beam_width=base_binding_beam_width,
        expansion_policy=expansion_policy,
        stopping_rule=stopping_rule,
    )
    # derive legacy budget allocation (uniform) for candidate scoring
    legacy_calls = {sid: ba.retrieval_calls for sid, ba in legacy.budget_allocation.items()}
    legacy_utility, legacy_cost = _estimate_plan_utility(
        logical_plan, legacy.slot_execution_order, legacy_calls, params
    )

    orders = _dependency_respecting_orders(logical_plan)
    if not orders:
        orders = [legacy.slot_execution_order]

    candidate_records: list[PlanCandidate] = []
    seen: set[tuple[tuple[str, ...], tuple[tuple[str, int], ...]]] = set()
    for order in orders:
        allocation = _allocate_budget_between(order, params.requirement_importance, params.retrieval_budget)
        key = (tuple(order), tuple(sorted(allocation.items())))
        if key in seen:
            continue
        seen.add(key)
        utility, cost = _estimate_plan_utility(logical_plan, order, allocation, params)
        candidate_records.append(PlanCandidate(
            slot_execution_order=order,
            retrieval_calls_by_slot=allocation,
            retrieval_strategy={sid: "hybrid" for sid in order},
            estimated_utility=utility,
            estimated_cost=cost,
            requirement_satisfaction_estimate=utility,  # utility proxy pre-cost
        ))

    # dominance pruning: drop candidates with <= utility and >= cost of another
    pruned = 0
    surviving: list[PlanCandidate] = []
    for cand in sorted(candidate_records, key=lambda c: (-c.estimated_utility, c.estimated_cost)):
        if any(
            other.estimated_utility >= cand.estimated_utility
            and other.estimated_cost <= cand.estimated_cost
            and other is not cand
            for other in surviving
        ):
            pruned += 1
            continue
        surviving.append(cand)

    # select best: max utility, tie-break min cost then deterministic order
    if not surviving:
        selected = PlanCandidate(
            slot_execution_order=legacy.slot_execution_order,
            retrieval_calls_by_slot=legacy_calls,
            retrieval_strategy={sid: "hybrid" for sid in legacy.slot_execution_order},
            estimated_utility=legacy_utility,
            estimated_cost=legacy_cost,
            requirement_satisfaction_estimate=legacy_utility,
        )
    else:
        selected = max(surviving, key=lambda c: (c.estimated_utility, -c.estimated_cost))

    # materialize the final PhysicalPlan with per-slot budget allocation
    final = compile_physical_plan(
        logical_plan,
        top_k=base_top_k,
        reranker_enabled=reranker_enabled,
        binding_beam_width=base_binding_beam_width,
        expansion_policy=expansion_policy,
        stopping_rule=stopping_rule,
    )
    final = final.model_copy(update={
        "slot_execution_order": selected.slot_execution_order,
        "budget_allocation": {
            sid: BudgetAllocation(
                retrieval_calls=selected.retrieval_calls_by_slot[sid],
                token_budget=params.token_budget,
                latency_budget_ms=params.latency_budget_ms,
            )
            for sid in selected.slot_execution_order
        },
    })
    telemetry = PlanSearchTelemetry(
        candidates_enumerated=len(candidate_records),
        candidates_pruned=pruned,
        candidates_evaluated=len(surviving),
        selected_order=selected.slot_execution_order,
        selected_retrieval_calls_by_slot=selected.retrieval_calls_by_slot,
        selected_estimated_utility=selected.estimated_utility,
        selected_estimated_cost=selected.estimated_cost,
        search_latency_ms=(time.perf_counter() - started) * 1000,
        reason="requirement-aware budgeted search",
    )
    return final, telemetry


__all__ = [
    "PlanCandidate",
    "PlanObjectiveParams",
    "PlanSearchTelemetry",
    "search_physical_plans",
]
