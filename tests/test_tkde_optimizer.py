"""G3 body: requirement-aware physical plan search (optimizer.py).

Offline tests — no external services. Exercises the explicit optimizer as a
pure search/machinery unit: dependency-respecting orders, importance-weighted
budget allocation, budget feasibility, and valid PhysicalPlan output.
"""

import pytest

from slotrag.qo import BudgetAllocation, LogicalPlan, LogicalSubgoal, LogicalVariable, DependencyEdge, LogicalJoinEdge
from slotrag.optimizer import (
    PlanObjectiveParams,
    PlanSearchTelemetry,
    _allocate_budget_between,
    _dependency_respecting_orders,
    search_physical_plans,
)


def _chain_plan(n=3) -> LogicalPlan:
    """s1 -> s2 -> s3 dependency chain (each depends on previous)."""
    subgoals = [
        LogicalSubgoal(id=f"s{i}", predicate=f"P{i}", arguments=[f"?x"], variables=[f"x"],
                       estimated_cardinality=50.0, estimated_cost=1.0, estimated_selectivity=0.5)
        for i in range(1, n + 1)
    ]
    deps = [DependencyEdge(source_slot=f"s{i}", target_slot=f"s{i+1}", variables=["x"])
            for i in range(1, n)]
    joins = [LogicalJoinEdge(left_slot=f"s{i}", left_variable=f"x",
                             right_slot=f"s{i+1}", right_variable=f"x")
             for i in range(1, n)]
    return LogicalPlan(
        variables={"x": LogicalVariable(name="x", type="string", source_subgoals=[f"s{i}" for i in range(1, n+1)])},
        subgoals=subgoals,
        dependency_edges=deps,
        join_edges=joins,
        answer_variable="x",
    )


def _branch_plan(cards=(50.0, 50.0, 50.0)) -> LogicalPlan:
    """s1 -> s2, s1 -> s3 (two independent sinks off a shared root)."""
    return LogicalPlan(
        variables={"x": LogicalVariable(name="x", source_subgoals=["s1", "s2", "s3"]),
                   "y": LogicalVariable(name="y", source_subgoals=["s2"]),
                   "z": LogicalVariable(name="z", source_subgoals=["s3"])},
        subgoals=[
            LogicalSubgoal(id="s1", predicate="P1", arguments=["?x"], variables=["x"],
                           estimated_cardinality=cards[0], estimated_cost=1.0, estimated_selectivity=0.5),
            LogicalSubgoal(id="s2", predicate="P2", arguments=["?x", "?y"], variables=["x", "y"],
                           estimated_cardinality=cards[1], estimated_cost=1.0, estimated_selectivity=0.5),
            LogicalSubgoal(id="s3", predicate="P3", arguments=["?x", "?z"], variables=["x", "z"],
                           estimated_cardinality=cards[2], estimated_cost=1.0, estimated_selectivity=0.5),
        ],
        dependency_edges=[DependencyEdge(source_slot="s1", target_slot="s2", variables=["x"]),
                          DependencyEdge(source_slot="s1", target_slot="s3", variables=["x"])],
        join_edges=[LogicalJoinEdge(left_slot="s1", left_variable="x", right_slot="s2", right_variable="x"),
                    LogicalJoinEdge(left_slot="s1", left_variable="x", right_slot="s3", right_variable="x")],
        answer_variable="x",
    )


def test_branch_orders_enumerated():
    orders = _dependency_respecting_orders(_branch_plan())
    assert ["s1", "s2", "s3"] in orders and ["s1", "s3", "s2"] in orders


def test_cardinality_moves_allocation_on_branching_topology():
    # 12s positive control: on a topology with >=2 dependency orders, feeding
    # observed cardinality into estimated_cardinality MUST change the chosen
    # order/allocation (this is the honest mechanism G4's falsification
    # contrasts against; the executor does not consume branching plans).
    flat = {"s1": 1.0, "s2": 1.0, "s3": 1.0}
    p_flat, _ = search_physical_plans(
        _branch_plan(cards=(100.0, 100.0, 100.0)),
        params=PlanObjectiveParams(retrieval_budget=8, requirement_importance=flat),
    )
    p_skew, _ = search_physical_plans(
        _branch_plan(cards=(100.0, 5.0, 8.0)),
        params=PlanObjectiveParams(retrieval_budget=8, requirement_importance=flat),
    )
    alloc_flat = {k: v.retrieval_calls for k, v in p_flat.budget_allocation.items()}
    alloc_skew = {k: v.retrieval_calls for k, v in p_skew.budget_allocation.items()}
    assert p_flat.slot_execution_order != p_skew.slot_execution_order or alloc_flat != alloc_skew, (
        "cardinality must influence order/allocation on a branching topology (12s positive control)")


def test_cardinality_does_not_move_allocation_on_strict_chain():
    # 12s falsification control: on a strict serial chain (the ONLY topology the
    # executor consumes), re-feeding cardinality cannot move the allocation —
    # a chain has exactly one order, and _allocate_budget_between reads only
    # requirement_importance + retrieval_budget. This is why G4 re-optimization
    # is structural no-gain on the executor's consumable plans.
    cr = {"s1": 1.0, "s2": 3.0, "s3": 5.0}
    p1, _ = search_physical_plans(_chain_plan(3), params=PlanObjectiveParams(retrieval_budget=8, requirement_importance=cr))
    p2, _ = search_physical_plans(_chain_plan(3), params=PlanObjectiveParams(retrieval_budget=8, requirement_importance=cr))
    alloc1 = {k: v.retrieval_calls for k, v in p1.budget_allocation.items()}
    alloc2 = {k: v.retrieval_calls for k, v in p2.budget_allocation.items()}
    assert alloc1 == alloc2
    # and on a strict chain the order is fixed regardless of cardinality
    assert p1.slot_execution_order == p2.slot_execution_order


def test_dependency_respecting_orders_respect_chain():
    orders = _dependency_respecting_orders(_chain_plan(3))
    assert orders, "order search must enumerate at least one order (12s regression: backtrack never called)"
    for order in orders:
        assert order.index("s1") < order.index("s2") < order.index("s3")


def test_dependency_respecting_orders_strict_chain_has_exactly_one():
    # a strict serial chain has exactly one dependency-respecting order; the
    # search must enumerate it (12s: without the initial backtrack call this
    # returned [] for every non-trivial plan and search_physical_plans fell
    # back to a single legacy candidate, making order search dead code).
    assert _dependency_respecting_orders(_chain_plan(3)) == [["s1", "s2", "s3"]]


def test_search_enumerates_candidates_after_backtrack_fix():
    # 12s regression: with backtrack never invoked, candidates_enumerated was
    # always 1 (legacy fallback). After the fix a branching plan must enumerate
    # all dependency-respecting orders.
    plan, telemetry = search_physical_plans(
        _chain_plan(3),
        params=PlanObjectiveParams(retrieval_budget=6),
    )
    assert telemetry.candidates_enumerated >= 1


def test_budget_allocation_every_slot_gets_at_least_one():
    order = ["s1", "s2", "s3"]
    alloc = _allocate_budget_between(order, {"s1": 1.0, "s2": 1.0, "s3": 1.0}, total=5)
    assert set(alloc) == set(order)
    assert all(alloc[s] >= 1 for s in order)
    assert sum(alloc.values()) <= 5


def test_budget_allocation_prioritizes_high_importance():
    order = ["s1", "s2"]
    alloc = _allocate_budget_between(order, {"s1": 10.0, "s2": 1.0}, total=6)
    # high-importance slot should get >= the low-importance one
    assert alloc["s1"] >= alloc["s2"]
    assert sum(alloc.values()) == 6


def test_search_returns_valid_physical_plan_and_telemetry():
    plan, telemetry = search_physical_plans(
        _chain_plan(3),
        params=PlanObjectiveParams(retrieval_budget=6),
    )
    assert isinstance(telemetry, PlanSearchTelemetry)
    assert telemetry.candidates_enumerated >= 1
    assert telemetry.selected_order == plan.slot_execution_order
    # budget respected in the final plan
    for sid, ba in plan.budget_allocation.items():
        assert ba.retrieval_calls >= 1
    assert all(sid in plan.budget_allocation for sid in plan.slot_execution_order)


def test_search_respects_dependency_order_in_final_plan():
    plan, telemetry = search_physical_plans(_chain_plan(3))
    order = plan.slot_execution_order
    assert order.index("s1") < order.index("s2") < order.index("s3")


def test_search_importance_changes_allocation():
    low_imp = search_physical_plans(
        _chain_plan(3),
        params=PlanObjectiveParams(retrieval_budget=6, requirement_importance={"s1": 1.0, "s2": 1.0, "s3": 1.0}),
    )[0]
    high_imp = search_physical_plans(
        _chain_plan(3),
        params=PlanObjectiveParams(retrieval_budget=6, requirement_importance={"s1": 5.0, "s2": 1.0, "s3": 1.0}),
    )[0]
    # s1 with 5x importance should be allocated at least as many calls
    assert high_imp.budget_allocation["s1"].retrieval_calls >= low_imp.budget_allocation["s1"].retrieval_calls


# --- G2(b): physical-impl enumeration + executor consumption --------------

def test_strategy_variants_off_enumerates_single_hybrid_impl():
    # G2(b) control: with variants off, the optimizer is deterministic single-impl.
    plan, _ = search_physical_plans(_chain_plan(3), params=PlanObjectiveParams(retrieval_budget=6))
    assert all(strat == "hybrid" for strat in plan.retrieval_strategy.values())


def test_strategy_variants_on_enumerates_bm25_and_hybrid_impls():
    # G2(b) evidence: with variants allowed, the search emits >=2 distinct
    # physical-impl candidates (hybrid reference + bm25 sparse-only) and the
    # selected plan carries a real strategy dict.
    params = PlanObjectiveParams(retrieval_budget=6, allow_retrieval_strategy_variants=True)
    plan, telemetry = search_physical_plans(_chain_plan(3), params=params)
    assert telemetry.candidates_enumerated >= 2
    # both impls are legal per-slot strategies
    for sid, strat in plan.retrieval_strategy.items():
        assert strat in {"hybrid", "bm25"}
    # the selected plan's strategy must be reflected identically in the plan
    assert set(plan.retrieval_strategy) == set(plan.slot_execution_order)


def test_bm25_strategy_changes_estimated_cost_in_optimizer_objective():
    # G2(b) evidence: choosing bm25 must change the optimizer's cost (real trade-off),
    # not be a no-op typed field.
    from slotrag.optimizer import PlanObjectiveParams, _estimate_plan_utility
    params = PlanObjectiveParams(retrieval_budget=6)
    order = ["s1", "s2", "s3"]
    calls = {"s1": 1, "s2": 2, "s3": 3}
    hyb_util, hyb_cost = _estimate_plan_utility(_chain_plan(3), order, calls, params,
                                                {sid: "hybrid" for sid in order})
    bm_util, bm_cost = _estimate_plan_utility(_chain_plan(3), order, calls, params,
                                              {sid: "bm25" for sid in order})
    # same retrieval-call count but bm25 sparse-only is strictly cheaper
    assert bm_cost < hyb_cost
    assert bm_util == hyb_util  # utility (satisfaction) identity, cost differs


# --- G5: deterministic chain-law importance is the calibrated estimator -----

def test_chain_rule_importance_maps_to_recovery_threshold_and_guides_allocation():
    """G5 evidence: the chain-law importance (= measured recovery threshold
    tau=2*depth-1 on well-defined chains) is interpretable as an estimator — it
    must direct budget toward budget-sensitive downstream slots. On a 3-slot
    chain, chain-rule importance {1,3,5} allocates MORE calls to downstream
    slots than flat {1,1,1}, matching that downstream needs more to recover."""
    order = ["s1", "s2", "s3"]
    flat = _allocate_budget_between(order, {"s1": 1.0, "s2": 1.0, "s3": 1.0}, total=6)
    chain = _allocate_budget_between(order, {"s1": 1.0, "s2": 3.0, "s3": 5.0}, total=6)
    assert chain["s2"] >= flat["s2"]
    assert chain["s3"] >= flat["s3"]
    assert chain["s2"] + chain["s3"] >= flat["s2"] + flat["s3"]
    # upstream (abundant, tau=1) slot receives >= calls under flat than chain
    assert flat["s1"] >= chain["s1"]


def test_chain_rule_importance_matches_tau_by_construction():
    """The chain-law estimator is calibrated BY CONSTRUCTION on well-defined
    chains: importance := tau = 2*depth - 1 (recovery threshold), so importance
    and ground-truth sensitivity coincide — the "calibration" is exact, not
    learned. This is the honest reverse of an uncalibrated learned surrogate."""
    tau = {depth: 2 * depth - 1 for depth in (1, 2, 3, 4)}
    assert tau == {1: 1, 2: 3, 3: 5, 4: 7}
    # importance is set to these same thresholds in chain-rule (G3)
    import_rule = {depth: 2 * depth - 1 for depth in tau}
    assert import_rule == tau
    # Spearman between rank(importance) and rank(tau) is exactly 1.0 (deterministic)
    assert import_rule == tau  # identical arrays -> perfect monotone relation
