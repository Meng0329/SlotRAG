from slotrag.models import BindingRow, Passage, RetrievalResult, RunMetrics, Slot, SlotPlan
from slotrag.planner import AdaptiveExecutor, SlotCompiler, SlotMaterializer
from slotrag.providers import ChatResult, ToolCall, Usage


class FakeMaterializer:
    def __init__(self):
        self.calls = []

    def materialize(self, slot, bindings):
        self.calls.append((slot.id, dict(bindings)))
        rows = {
            "S1": [BindingRow(slot_id="S1", bindings={"person": "Ada"}, source_id="p1", source_span="Ada founded X", confidence=1)],
            "S2": [BindingRow(slot_id="S2", bindings={"person": "Ada", "company": "X"}, source_id="p2", source_span="Ada founded X", confidence=1)],
        }[slot.id]
        return rows, RunMetrics(documents_accessed=1, passages_processed=1, extraction_llm_calls=1)


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


class FakeStructuredClient:
    def __init__(self, arguments):
        self.arguments = list(arguments)

    def complete(self, *_args, **_kwargs):
        arguments = self.arguments.pop(0)
        return ChatResult(
            request_id=f"r{len(self.arguments)}",
            tool_calls=[ToolCall(name="emit_slot_plan", arguments=arguments)],
            usage=Usage(prompt_tokens=2, completion_tokens=1),
        )

    @staticmethod
    def require_tool(result, name):
        return next(call.arguments for call in result.tool_calls if call.name == name)


class FakeExtractionClient:
    def complete(self, *_args, **_kwargs):
        return ChatResult(tool_calls=[ToolCall(name="emit_evidence_rows", arguments={"rows": [{"wrong": "value"}]})])

    @staticmethod
    def require_tool(result, name):
        return next(call.arguments for call in result.tool_calls if call.name == name)


class FakeRetriever:
    def search(self, _query):
        return [RetrievalResult(passage=Passage(id="p", text="Fact"), score=1.0)]


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
    assert result.metrics.extraction_llm_calls == 2


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


def test_executor_prunes_binding_fanout_to_runtime_budget():
    materializer = MultiBindingMaterializer()
    plan = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "Founder", "arguments": ["?person", "OpenAI"]},
            {"id": "S2", "predicate": "Founded", "arguments": ["?person", "?company"]},
        ],
        "joins": [["S1.person", "S2.person"]],
        "outputs": ["?person", "?company"],
    })
    result = AdaptiveExecutor(materializer, max_binding_contexts=1, max_retrieval_calls=2).execute(plan)
    assert result.rows == [{"person": "Ada", "company": "X"}]
    assert result.metrics.binding_contexts_pruned == 1


def test_slot_compiler_repairs_invalid_plan_once():
    invalid = {"slots": [{"id": "S1", "predicate": "Fact", "arguments": ["constant"]}], "joins": [], "outputs": ["?answer"]}
    valid = {"slots": [{"id": "S1", "predicate": "Fact", "arguments": ["?answer"]}], "joins": [], "outputs": ["?answer"]}
    plan, metrics = SlotCompiler(FakeStructuredClient([invalid, valid])).compile("What?")
    assert plan.outputs == ["?answer"]
    assert metrics.llm_calls == 2
    assert metrics.compilation_llm_calls == 2
    assert metrics.structured_output_failures == 1
    assert metrics.structured_output_repairs == 1
    assert metrics.plan_fallbacks == 0


def test_slot_compiler_repairs_unambiguous_join_key_locally():
    invalid_join = {
        "slots": [
            {"id": "S1", "predicate": "DirectedBy", "arguments": ["Film", "?director"]},
            {"id": "S2", "predicate": "BornIn", "arguments": ["?director", "?place"]},
        ],
        "joins": [{"left_slot": "S1", "left_field": "person", "right_slot": "S2", "right_field": "person"}],
        "outputs": ["?place"],
    }
    plan, metrics = SlotCompiler(FakeStructuredClient([invalid_join])).compile("Where was the director of Film born?")
    assert plan.joins[0].left_field == "director"
    assert plan.joins[0].right_field == "director"
    assert metrics.llm_calls == 1
    assert metrics.compilation_llm_calls == 1
    assert metrics.structured_output_failures == 1
    assert metrics.structured_output_repairs == 1
    assert metrics.local_plan_repairs == 1


def test_slot_compiler_uses_heuristic_plan_for_boolean_question():
    plan, metrics = SlotCompiler(FakeStructuredClient([])).compile(
        "Would Hannah Nixon be proud of Richard Nixon?", answer_kind="boolean"
    )
    assert plan.slots[0].predicate == "EvidenceAnsweringQuestion"
    assert plan.outputs == ["?answer"]
    assert metrics.heuristic_plans == 1
    assert metrics.llm_calls == 0


def test_slot_compiler_falls_back_after_three_invalid_plans():
    invalid = {"slots": [], "joins": [], "outputs": []}
    plan, metrics = SlotCompiler(FakeStructuredClient([invalid, invalid, invalid])).compile("What?")
    assert plan.slots[0].predicate == "EvidenceAnsweringQuestion"
    assert metrics.plan_fallbacks == 1
    assert metrics.llm_calls == 3


def test_slot_compiler_repairs_ungrounded_parametric_constant():
    leaked = {"slots": [{"id": "S1", "predicate": "Wrote", "arguments": ["Hidden Person", "?answer"]}], "joins": [], "outputs": ["?answer"]}
    grounded = {"slots": [{"id": "S1", "predicate": "SubjectOf", "arguments": ["Morecambe", "?answer"]}], "joins": [], "outputs": ["?answer"]}
    plan, metrics = SlotCompiler(FakeStructuredClient([leaked, grounded])).compile("Who is the subject of Morecambe?")
    assert plan.slots[0].arguments == ["Morecambe", "?answer"]
    assert metrics.structured_output_failures == 1


def test_slot_compiler_eliminates_redundant_grounded_anchor_slot():
    plan_payload = {
        "slots": [
            {"id": "S0", "predicate": "Person", "arguments": ["Michael Jordan", "?player"]},
            {"id": "S1", "predicate": "Rebounds", "arguments": ["?player", "?rebounds"]},
            {"id": "S2", "predicate": "Assists", "arguments": ["?player", "?assists"]},
        ],
        "joins": [
            ["S0.player", "S1.player"],
            ["S0.player", "S2.player"],
        ],
        "operators": [{"id": "O1", "kind": "arithmetic", "fields": ["rebounds", "assists"], "operation": "subtract", "output": "difference"}],
        "outputs": ["?difference"],
    }
    plan, _ = SlotCompiler(FakeStructuredClient([plan_payload])).compile(
        "How many more rebounds than assists did Michael Jordan average per game?"
    )
    assert [slot.id for slot in plan.slots] == ["S1", "S2"]
    assert all(slot.constraints["player"] == "Michael Jordan" for slot in plan.slots)
    assert [(join.left_slot, join.right_slot) for join in plan.joins] == [("S1", "S2")]


def test_materializer_counts_and_skips_repeated_invalid_extractions():
    materializer = SlotMaterializer(FakeExtractionClient(), FakeRetriever())
    rows, metrics = materializer.materialize(
        Slot(id="S1", predicate="Fact", arguments=["?answer"]),
        {},
    )
    assert rows == []
    assert metrics.llm_calls == 2
    assert metrics.extraction_llm_calls == 2
    assert metrics.structured_output_failures == 2
    assert metrics.structured_output_repairs == 1
    assert materializer.accessed_passage_ids == {"p"}
    assert [item.source_id for item in materializer.last_evidence] == ["p"]
