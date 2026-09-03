import sys
sys.path.insert(0, 'src')
sys.path.insert(0, '.')
from slotrag.models import Slot, SlotPlan, JoinSpec, BindingRow, RunMetrics
from slotrag.planner import AdaptiveExecutor
from slotrag.qo import compile_physical_plan, logical_plan_from_slot_plan

# Star topology: S3 joins S1 and S2
plan = SlotPlan(
    slots=[
        Slot(id="S1", predicate="Expensive Source", arguments=["?x"], estimated_cardinality=10, estimated_cost=2),
        Slot(id="S2", predicate="Cheap Source", arguments=["?y"], estimated_cardinality=1, estimated_cost=1),
        Slot(id="S3", predicate="Join Target", arguments=["?x", "?y", "?answer"], estimated_cardinality=1, estimated_cost=1),
    ],
    joins=[
        JoinSpec(left_slot="S1", left_field="x", right_slot="S3", right_field="x"),
        JoinSpec(left_slot="S2", left_field="y", right_slot="S3", right_field="y"),
    ],
    outputs=["?answer"],
)

class Stub:
    def materialize(self, slot, bindings, *, retrieval_strategy='hybrid'):
        return [BindingRow(slot_id=slot.id, bindings={v: f"val_{v}" for v in slot.variables}, source_id="src", source_span="", confidence=1)], RunMetrics()
    def accessed_document_ids(self):
        return set()
    def accessed_passage_ids(self):
        return set()

logical = logical_plan_from_slot_plan(plan)
pp = compile_physical_plan(logical)
print("physical order:", pp.slot_execution_order)

ex = AdaptiveExecutor(Stub(), max_steps=3)
res = ex.execute(plan, physical_plan=pp)
print("status:", res.status)
print("error:", repr(res.error))
print("order:", res.order)