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
    assert physical.slot_execution_order == ["S2", "S1"]
    assert physical.top_k == {"S1": 8, "S2": 8}
    assert physical.reranker_usage == {"S1": True, "S2": True}
    assert physical.binding_beam_width == {"S1": 3, "S2": 3}
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
    assert telemetry.detected_cycles == ["S1", "S2"]
