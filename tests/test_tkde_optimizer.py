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


def test_dependency_respecting_orders_respect_chain():
    orders = _dependency_respecting_orders(_chain_plan(3))
    for order in orders:
        assert order.index("s1") < order.index("s2") < order.index("s3")


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
