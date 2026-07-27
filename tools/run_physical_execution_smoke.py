"""Run a provider-free smoke for PhysicalPlan order application."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from slotrag.models import BindingRow, RunMetrics, SlotPlan
from slotrag.planner import AdaptiveExecutor
from slotrag.qo import compile_physical_plan, logical_plan_from_slot_plan


class SmokeMaterializer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.accessed_document_ids: set[str] = set()
        self.accessed_passage_ids: set[str] = set()
        self.last_evidence: list[Any] = []

    def materialize(self, slot: Any, bindings: dict[str, str]) -> tuple[list[BindingRow], RunMetrics]:
        self.calls.append((slot.id, dict(bindings)))
        self.accessed_document_ids.add(slot.id)
        self.accessed_passage_ids.add(f"{slot.id}:p1")
        if slot.id == "S1":
            rows = [BindingRow(
                slot_id="S1",
                bindings={"person": "Ada"},
                source_id="S1:p1",
                source_span="Ada founded OpenAI.",
                confidence=1.0,
            )]
        else:
            rows = [BindingRow(
                slot_id="S2",
                bindings={"person": "Ada", "company": "OpenAI"},
                source_id="S2:p1",
                source_span="Ada founded OpenAI.",
                confidence=1.0,
            )]
        return rows, RunMetrics(documents_accessed=1, passages_processed=1)


def _plan() -> SlotPlan:
    return SlotPlan.model_validate({
        "slots": [
            {
                "id": "S1",
                "predicate": "Founder",
                "arguments": ["?person", "OpenAI"],
                "importance": 100,
                "estimated_cardinality": 10,
                "estimated_cost": 2,
            },
            {
                "id": "S2",
                "predicate": "Founded",
                "arguments": ["?person", "?company"],
                "estimated_cardinality": 1,
                "estimated_cost": 1,
            },
        ],
        "joins": [["S1.person", "S2.person"]],
        "outputs": ["?person", "?company"],
    })


def _result_summary(result: Any) -> dict[str, Any]:
    return {
        "status": result.status,
        "order": result.order,
        "error": result.error,
        "physical_plan_applied": result.metrics.physical_plan_applied,
        "physical_plan_order_mismatches": result.metrics.physical_plan_order_mismatches,
        "physical_plan_order": result.metrics.physical_plan_order,
        "retrieval_calls": result.metrics.retrieval_calls,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    plan = _plan()
    legacy_materializer = SmokeMaterializer()
    legacy = AdaptiveExecutor(legacy_materializer, max_retrieval_calls=4).execute(plan)
    physical_plan = compile_physical_plan(logical_plan_from_slot_plan(plan))
    physical_materializer = SmokeMaterializer()
    physical = AdaptiveExecutor(physical_materializer, max_retrieval_calls=4).execute(
        plan,
        physical_plan=physical_plan,
    )
    invalid_plan = physical_plan.model_copy(update={"slot_execution_order": ["S1", "S1"]})
    rejected = AdaptiveExecutor(SmokeMaterializer(), max_retrieval_calls=4).execute(
        plan,
        physical_plan=invalid_plan,
    )

    summary = {
        "version": "v59",
        "provider_calls": 0,
        "plan": {
            "logical_slots": [slot.id for slot in plan.slots],
            "compiled_order": physical_plan.slot_execution_order,
            "validation_status": physical_plan.telemetry.validation_status,
            "validation_errors": physical_plan.telemetry.validation_errors,
            "validation_warnings": physical_plan.telemetry.validation_warnings,
        },
        "legacy": _result_summary(legacy),
        "physical": _result_summary(physical),
        "rejected_mismatch": _result_summary(rejected),
        "calls": {
            "legacy": legacy_materializer.calls,
            "physical": physical_materializer.calls,
        },
    }
    if legacy.status != "ok" or physical.status != "ok":
        raise RuntimeError(f"physical execution smoke failed: {summary}")
    if legacy.order == physical.order:
        raise RuntimeError(f"smoke did not exercise a distinct order: {summary}")
    if rejected.status != "failed" or rejected.metrics.physical_plan_order_mismatches != 1:
        raise RuntimeError(f"mismatch rejection failed: {summary}")

    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
