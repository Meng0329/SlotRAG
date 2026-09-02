from slotrag.models import JoinSpec, Slot, SlotPlan
import pytest

from slotrag.qo import (
    LogicalPlan,
    LogicalSubgoal,
    LogicalVariable,
    PlanValidationError,
    compile_physical_plan,
    logical_plan_from_slot_plan,
)


def test_logical_plan_compiles_to_physical_plan_with_validation_telemetry():
    logical = logical_plan_from_slot_plan(
        SlotPlan(
            slots=[
                Slot(
                    id="S1",
                    predicate="Born In",
                    arguments=["?person", "?place"],
                    variable_types={"person": "string", "place": "string"},
                    estimated_cardinality=10,
                    estimated_cost=2,
                ),
                Slot(
                    id="S2",
                    predicate="Located-In",
                    arguments=["?place", "?country"],
                    variable_types={"place": "string", "country": "string"},
                    estimated_cardinality=4,
                    estimated_cost=1,
                ),
            ],
            joins=[JoinSpec(left_slot="S1", left_field="place", right_slot="S2", right_field="place")],
            outputs=["?country"],
        )
    )

    physical = compile_physical_plan(
        logical,
        top_k=8,
        reranker_enabled=True,
        binding_beam_width=3,
    )

    assert [subgoal.predicate for subgoal in physical.logical_plan.subgoals] == ["born_in", "located_in"]
    assert physical.slot_execution_order == ["S1", "S2"]
    assert physical.top_k == {"S1": 8, "S2": 8}
    assert physical.reranker_usage == {"S1": True, "S2": True}
    assert physical.binding_beam_width == {"S1": 3, "S2": 3}
    assert {slot_id: budget.retrieval_calls for slot_id, budget in physical.budget_allocation.items()} == {
        "S1": 6,
        "S2": 6,
    }
    assert physical.telemetry.validation_status == "valid"
    assert physical.telemetry.validation_errors == []
    assert physical.telemetry.canonicalized_predicates == 2


def test_invalid_logical_plan_exposes_all_compile_errors_in_telemetry():
    logical = LogicalPlan(
        variables={
            "x": LogicalVariable(name="x", source_subgoals=["S1"]),
            "y": LogicalVariable(name="y", source_subgoals=["S2"]),
        },
        subgoals=[
            LogicalSubgoal(id="S1", predicate="p", arguments=["?x"], variables=["x"], estimated_cardinality=0),
            LogicalSubgoal(id="S2", predicate="q", arguments=["?y"], variables=["y"], estimated_cost=-1),
        ],
        dependency_edges=[
            {"source_slot": "S1", "target_slot": "S2"},
            {"source_slot": "S2", "target_slot": "S1"},
        ],
        answer_variable="answer",
    )

    with pytest.raises(PlanValidationError) as raised:
        compile_physical_plan(logical)

    telemetry = raised.value.telemetry
    assert telemetry.validation_status == "invalid"
    assert any(error.startswith("INVALID_CARDINALITY") for error in telemetry.validation_errors)
    assert any(error.startswith("INVALID_COST") for error in telemetry.validation_errors)
    assert "JOIN_GRAPH_DISCONNECTED" in telemetry.validation_errors
    assert any(error.startswith("ANSWER_UNREACHABLE") for error in telemetry.validation_errors)
    assert any(error.startswith("DEPENDENCY_CYCLE") for error in telemetry.validation_errors)
    assert telemetry.detected_cycles == ["S1", "S2"]


def test_physical_plan_cost_orders_ready_slots_without_violating_dependencies():
    logical = logical_plan_from_slot_plan(
        SlotPlan(
            slots=[
                Slot(
                    id="S1",
                    predicate="Expensive Source",
                    arguments=["?x"],
                    estimated_cardinality=10,
                    estimated_cost=2,
                ),
                Slot(
                    id="S2",
                    predicate="Cheap Source",
                    arguments=["?y"],
                    estimated_cardinality=1,
                    estimated_cost=1,
                ),
                Slot(
                    id="S3",
                    predicate="Join Target",
                    arguments=["?x", "?y", "?answer"],
                    estimated_cardinality=1,
                    estimated_cost=1,
                ),
            ],
            joins=[
                JoinSpec(left_slot="S1", left_field="x", right_slot="S3", right_field="x"),
                JoinSpec(left_slot="S2", left_field="y", right_slot="S3", right_field="y"),
            ],
            outputs=["?answer"],
        )
    )

    physical = compile_physical_plan(logical)

    # Order must be materializer-join-adjacent: every slot after the first has
    # a join-neighbor already in the prefix (S3 joins S1 and S2, so S3 must
    # come before both leaves-or-after-one — the executable order is a frontier
    # expansion that keeps S3 between/before its join partners).
    order = physical.slot_execution_order
    join_adj: dict[str, set[str]] = {s: set() for s in order}
    for j in logical.join_edges:
        join_adj[j.left_slot].add(j.right_slot)
        join_adj[j.right_slot].add(j.left_slot)
    visited: set[str] = set()
    for sid in order:
        assert not visited or (visited & join_adj[sid]), f"slot {sid} has no join path at position {len(visited)}"
        visited.add(sid)
    # deterministic: cost-ordered leaves first then their shared join target
    assert order[0] == "S2"
