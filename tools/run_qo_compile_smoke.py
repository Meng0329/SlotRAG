#!/usr/bin/env python3
"""Run a provider-free LogicalPlan/PhysicalPlan compiler smoke."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from slotrag.models import JoinSpec, Slot, SlotPlan
from slotrag.qo import (
    LogicalPlan,
    LogicalSubgoal,
    LogicalVariable,
    PlanValidationError,
    compile_physical_plan,
    logical_plan_from_slot_plan,
)


def _valid_plan() -> SlotPlan:
    return SlotPlan(
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


def _invalid_plan() -> LogicalPlan:
    return LogicalPlan(
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


def run(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    logical = logical_plan_from_slot_plan(_valid_plan())
    physical = compile_physical_plan(logical, top_k=8, binding_beam_width=3)
    invalid_telemetry: dict[str, object]
    try:
        compile_physical_plan(_invalid_plan())
    except PlanValidationError as error:
        invalid_telemetry = error.telemetry.model_dump(mode="json")
    else:
        raise AssertionError("invalid smoke plan unexpectedly compiled")
    summary = {
        "schema_version": 1,
        "experiment": "slotrag-qo-compile-smoke-v58",
        "provider_calls": 0,
        "valid": {
            "logical_subgoals": [subgoal.model_dump(mode="json") for subgoal in logical.subgoals],
            "physical": physical.model_dump(mode="json"),
        },
        "invalid": {"telemetry": invalid_telemetry},
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("runs/slotrag-qo-compile-smoke-v58"),
    )
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
