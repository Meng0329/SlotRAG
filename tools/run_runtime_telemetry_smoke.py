"""Run provider-free smoke for runtime action and adaptive binding telemetry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from slotrag.action_policy import PhysicalActionPolicy
from slotrag.models import BindingRow, RunMetrics, SlotPlan
from slotrag.planner import AdaptiveExecutor
from slotrag.qo import compile_physical_plan, logical_plan_from_slot_plan


class SmokeMaterializer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.accessed_passage_ids: set[str] = set()
        self.accessed_document_ids: set[str] = set()
        self.last_evidence = []

    def materialize(self, slot, bindings):
        self.calls.append((slot.id, dict(bindings)))
        if slot.id == "S1":
            rows = [
                BindingRow(slot_id="S1", bindings={"person": "Ada"}, source_id="p-ada", source_span="Ada fact", confidence=0.52, retrieval_score=0.52),
                BindingRow(slot_id="S1", bindings={"person": "Grace"}, source_id="p-grace", source_span="Grace fact", confidence=0.50, retrieval_score=0.50),
                BindingRow(slot_id="S1", bindings={"person": "Lin"}, source_id="p-lin", source_span="Lin fact", confidence=0.49, retrieval_score=0.49),
            ]
        else:
            person = bindings["person"]
            rows = [BindingRow(
                slot_id="S2",
                bindings={"person": person, "company": {"Ada": "X", "Grace": "Y", "Lin": "Z"}[person]},
                source_id=f"p-{person.lower()}-company",
                source_span=f"{person} founded a company",
                confidence=0.8,
                retrieval_score=0.8,
            )]
        return rows, RunMetrics(documents_accessed=len(rows), passages_processed=len(rows))

    def materialize_many(self, slot, contexts):
        rows = []
        metrics = RunMetrics()
        for context in contexts:
            current, current_metrics = self.materialize(slot, context)
            rows.extend(current)
            metrics = metrics.model_copy(update={
                "documents_accessed": metrics.documents_accessed + current_metrics.documents_accessed,
                "passages_processed": metrics.passages_processed + current_metrics.passages_processed,
            })
        return rows, metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plan = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "Founder", "arguments": ["?person", "OpenAI"]},
            {"id": "S2", "predicate": "Founded", "arguments": ["?person", "?company"]},
        ],
        "joins": [["S1.person", "S2.person"]],
        "outputs": ["?person", "?company"],
    })
    physical = compile_physical_plan(logical_plan_from_slot_plan(plan)).model_copy(update={
        "slot_execution_order": ["S1", "S2"],
    })
    legacy_materializer = SmokeMaterializer()
    legacy = AdaptiveExecutor(
        legacy_materializer,
        max_binding_contexts=1,
        max_retrieval_calls=2,
    ).execute(plan, physical_plan=physical)
    adaptive_materializer = SmokeMaterializer()
    adaptive = AdaptiveExecutor(
        adaptive_materializer,
        max_binding_contexts=2,
        max_retrieval_calls=2,
        adaptive_binding_beam=True,
        action_policy=PhysicalActionPolicy(),
    ).execute(plan, physical_plan=physical)
    summary = {
        "version": "v62",
        "provider_calls": 0,
        "simulation_only": True,
        "physical_order": physical.slot_execution_order,
        "legacy": {
            "status": legacy.status,
            "rows": legacy.rows,
            "calls": legacy_materializer.calls,
            "metrics": legacy.metrics.model_dump(mode="json"),
        },
        "adaptive": {
            "status": adaptive.status,
            "rows": adaptive.rows,
            "calls": adaptive_materializer.calls,
            "metrics": adaptive.metrics.model_dump(mode="json"),
        },
    }
    if adaptive.status != "ok" or adaptive.metrics.binding_beam_decisions != 1:
        raise RuntimeError(f"runtime telemetry smoke failed: {summary}")
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "version": summary["version"],
        "provider_calls": summary["provider_calls"],
        "legacy_status": legacy.status,
        "adaptive_status": adaptive.status,
        "adaptive_rows": len(adaptive.rows),
        "beam_decisions": adaptive.metrics.binding_beam_decisions,
        "beam_widths": adaptive.metrics.binding_beam_widths,
        "candidates_considered": adaptive.metrics.binding_candidates_considered,
        "candidates_pruned": adaptive.metrics.binding_candidates_pruned,
        "actions": adaptive.metrics.physical_action_selected,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
