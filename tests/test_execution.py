from slotrag.models import BindingRow, RunMetrics, Slot, SlotPlan
from slotrag.planner import AdaptiveExecutor


class FakeMaterializer:
    def __init__(self):
        self.calls = []

    def materialize(self, slot, bindings):
        self.calls.append((slot.id, dict(bindings)))
        rows = {
            "S1": [BindingRow(slot_id="S1", bindings={"person": "Ada"}, source_id="p1", source_span="Ada founded X", confidence=1)],
            "S2": [BindingRow(slot_id="S2", bindings={"person": "Ada", "company": "X"}, source_id="p2", source_span="Ada founded X", confidence=1)],
        }[slot.id]
        return rows, RunMetrics(documents_accessed=1, passages_processed=1)


class MultiBindingMaterializer(FakeMaterializer):
    def materialize(self, slot, bindings):
        self.calls.append((slot.id, dict(bindings)))
        if slot.id == "S1":
            return [
                BindingRow(slot_id="S1", bindings={"person": "Ada"}, source_id="p1", source_span="Ada founded X", confidence=1),
                BindingRow(slot_id="S1", bindings={"person": "Grace"}, source_id="p3", source_span="Grace founded Y", confidence=1),
            ], RunMetrics(documents_accessed=2, passages_processed=2)
        person = bindings["person"]
        company = {"Ada": "X", "Grace": "Y"}[person]
        return [BindingRow(slot_id="S2", bindings={"person": person, "company": company}, source_id=f"{person}-p2", source_span=f"{person} founded {company}", confidence=1)], RunMetrics(documents_accessed=1, passages_processed=1)

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


def test_adaptive_executor_joins_and_propagates_bindings():
    materializer = FakeMaterializer()
    plan = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "Founder", "arguments": ["?person", "OpenAI"]},
            {"id": "S2", "predicate": "Founded", "arguments": ["?person", "?company"]},
        ],
        "joins": [["S1.person", "S2.person"]],
        "outputs": ["?person", "?company"],
    })
    result = AdaptiveExecutor(materializer).execute(plan)
    assert result.status == "ok"
    assert result.rows == [{"person": "Ada", "company": "X"}]
    assert result.order == ["S1", "S2"]
    assert materializer.calls[1][1] == {"person": "Ada"}


def test_executor_materializes_each_distinct_binding_context():
    materializer = MultiBindingMaterializer()
    plan = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "Founder", "arguments": ["?person", "OpenAI"]},
            {"id": "S2", "predicate": "Founded", "arguments": ["?person", "?company"]},
        ],
        "joins": [["S1.person", "S2.person"]],
        "outputs": ["?person", "?company"],
    })
    result = AdaptiveExecutor(materializer).execute(plan)
    assert result.rows == [{"person": "Ada", "company": "X"}, {"person": "Grace", "company": "Y"}]
    assert [call for call in materializer.calls if call[0] == "S2"] == [("S2", {"person": "Ada"}), ("S2", {"person": "Grace"})]
