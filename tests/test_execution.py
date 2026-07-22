import pytest
from pydantic import ValidationError

from slotrag.models import BindingRow, Passage, RelationalOperator, RetrievalResult, RunMetrics, Slot, SlotPlan
from slotrag.planner import AdaptiveExecutor, ExecutionOptions, SlotCompiler, SlotMaterializer, apply_operators, extraction_tool
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


class SequenceExtractionClient:
    def __init__(self, rows):
        self.rows = list(rows)

    def complete(self, *_args, **_kwargs):
        rows = self.rows.pop(0)
        return ChatResult(tool_calls=[ToolCall(name="emit_evidence_rows", arguments={"rows": rows})])

    @staticmethod
    def require_tool(result, name):
        return next(call.arguments for call in result.tool_calls if call.name == name)


class StaticRetriever:
    def __init__(self, passage):
        self.passage = passage

    def search(self, _query):
        return [RetrievalResult(passage=self.passage, score=1.0)]


def test_slot_variable_types_must_reference_exposed_variables():
    with pytest.raises(ValidationError, match="variable_types keys must be slot variables"):
        Slot(
            id="S1",
            predicate="EvidenceAnsweringQuestion",
            arguments=["?answer"],
            variable_types={"other": "boolean"},
        )


def test_boolean_variable_type_constrains_extraction_tool_domain():
    typed = extraction_tool(Slot(
        id="S1",
        predicate="EvidenceAnsweringQuestion",
        arguments=["?answer"],
        variable_types={"answer": "boolean"},
    ), typed_extraction_contracts=True)
    untyped = extraction_tool(Slot(
        id="S1",
        predicate="EvidenceAnsweringQuestion",
        arguments=["?answer"],
    ))

    typed_answer = typed["function"]["parameters"]["properties"]["rows"]["items"]["properties"]["answer"]
    untyped_answer = untyped["function"]["parameters"]["properties"]["rows"]["items"]["properties"]["answer"]

    assert typed_answer == {"type": "string", "enum": ["yes", "no", "unknown"]}
    assert untyped_answer == {"type": "string"}


class ComparisonMaterializer:
    def __init__(self):
        self.calls = []

    def materialize(self, slot, bindings):
        self.calls.append((slot.id, dict(bindings)))
        rows = {
            "S1": BindingRow(
                slot_id="S1",
                bindings={"d1": "Sidney Lumet"},
                source_id="Find Me Guilty#0",
                source_span="Find Me Guilty was directed by Sidney Lumet.",
                confidence=1,
            ),
            "S2": BindingRow(
                slot_id="S2",
                bindings={"d2": "Terry O. Morse"},
                source_id="Tear Gas Squad#0",
                source_span="Tear Gas Squad was directed by Terry O. Morse.",
                confidence=1,
            ),
            "S3": BindingRow(
                slot_id="S3",
                bindings={"d1": "Sidney Lumet", "bd1": "June 25, 1924"},
                source_id="Sidney Lumet#0",
                source_span="Sidney Lumet was born on June 25, 1924.",
                confidence=1,
            ),
            "S4": BindingRow(
                slot_id="S4",
                bindings={"d2": "Terry O. Morse", "bd2": "January 30, 1906"},
                source_id="Terry O. Morse#0",
                source_span="Terry O. Morse was born on January 30, 1906.",
                confidence=1,
            ),
        }
        return [rows[slot.id]], RunMetrics(documents_accessed=1, passages_processed=1)


def comparison_plan():
    return SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "DirectorOf", "arguments": ["Find Me Guilty", "?d1"]},
            {"id": "S2", "predicate": "DirectorOf", "arguments": ["Tear Gas Squad", "?d2"]},
            {"id": "S3", "predicate": "BirthDate", "arguments": ["?d1", "?bd1"]},
            {"id": "S4", "predicate": "BirthDate", "arguments": ["?d2", "?bd2"]},
        ],
        "joins": [["S1.d1", "S3.d1"], ["S2.d2", "S4.d2"]],
        "operators": [{
            "id": "O1",
            "kind": "field_argmin",
            "fields": ["bd1", "bd2"],
            "labels": ["Find Me Guilty", "Tear Gas Squad"],
            "output": "answer",
        }],
        "outputs": ["?answer"],
    })


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


def test_slot_compiler_rewrites_date_difference_predicate_to_typed_operator():
    plan_payload = {
        "slots": [
            {"id": "S1", "predicate": "BeganTerm", "arguments": ["?person", "?startDate"]},
            {"id": "S2", "predicate": "SworeAllegiance", "arguments": ["?person", "?endDate"]},
            {
                "id": "S3",
                "predicate": "DateDiffInMonths",
                "arguments": ["?startDate", "?endDate", "?months"],
            },
        ],
        "joins": [
            ["S1.person", "S2.person"],
            ["S1.startDate", "S3.startDate"],
            ["S2.endDate", "S3.endDate"],
        ],
        "outputs": ["?months"],
        "operators": [],
    }
    plan, metrics = SlotCompiler(FakeStructuredClient([plan_payload])).compile(
        "What is the difference in months between when he began his term and when Zaimis swore allegiance?",
        answer_kind="number",
    )

    assert [slot.id for slot in plan.slots] == ["S1", "S2"]
    assert [(join.left_slot, join.right_slot) for join in plan.joins] == [("S1", "S2")]
    assert len(plan.operators) == 1
    assert plan.operators[0].operation == "date_diff_months"
    assert plan.operators[0].fields == ["startDate", "endDate"]
    assert plan.operators[0].output == "months"
    assert metrics.operator_rewrites == 1


def test_slot_compiler_rewrites_grounded_birthdate_comparison_to_field_extremum():
    plan_payload = {
        "slots": [
            {"id": "S1", "predicate": "DirectorOf", "arguments": ["Find Me Guilty", "?d1"]},
            {"id": "S2", "predicate": "DirectorOf", "arguments": ["Tear Gas Squad", "?d2"]},
            {"id": "S3", "predicate": "BirthDate", "arguments": ["?d1", "?bd1"]},
            {"id": "S4", "predicate": "BirthDate", "arguments": ["?d2", "?bd2"]},
            {"id": "S5", "predicate": "Compare", "arguments": ["?bd1", "?bd2"]},
        ],
        "joins": [
            ["S1.d1", "S3.d1"],
            ["S2.d2", "S4.d2"],
            ["S3.bd1", "S5.bd1"],
            ["S4.bd2", "S5.bd2"],
        ],
        "outputs": ["?bd1", "?bd2"],
        "operators": [],
    }
    question = "Which film has the director who was born first, Find Me Guilty or Tear Gas Squad?"

    plan, metrics = SlotCompiler(FakeStructuredClient([plan_payload])).compile(
        question,
        field_extremum_templates=False,
    )

    assert [slot.id for slot in plan.slots] == ["S1", "S2", "S3", "S4"]
    assert [(join.left_slot, join.right_slot) for join in plan.joins] == [("S1", "S3"), ("S2", "S4")]
    assert plan.outputs == ["?answer"]
    assert len(plan.operators) == 1
    assert plan.operators[0].kind == "field_argmin"
    assert plan.operators[0].fields == ["bd1", "bd2"]
    assert plan.operators[0].labels == ["Find Me Guilty", "Tear Gas Squad"]
    assert plan.operators[0].output == "answer"
    assert metrics.operator_rewrites == 1


def test_typed_field_extremum_template_skips_llm_compilation():
    question = "Which film has the director who was born first, Find Me Guilty or Tear Gas Squad?"

    plan, metrics = SlotCompiler(FakeStructuredClient([])).compile(question)

    assert metrics.llm_calls == 0
    assert metrics.heuristic_plans == 1
    assert metrics.typed_plan_templates == 1
    assert metrics.field_extremum_templates == 1
    assert metrics.operator_rewrites == 0
    assert [slot.id for slot in plan.slots] == ["S1", "S2", "S3", "S4"]
    assert [slot.predicate for slot in plan.slots] == ["DirectorOf", "BirthDate", "DirectorOf", "BirthDate"]
    assert [slot.arguments for slot in plan.slots] == [
        ["Find Me Guilty", "?director1"],
        ["?director1", "?birthDate1"],
        ["Tear Gas Squad", "?director2"],
        ["?director2", "?birthDate2"],
    ]
    assert [
        (join.left_slot, join.left_field, join.right_slot, join.right_field)
        for join in plan.joins
    ] == [
        ("S1", "director1", "S2", "director1"),
        ("S3", "director2", "S4", "director2"),
    ]
    assert plan.outputs == ["?answer"]
    assert len(plan.operators) == 1
    assert plan.operators[0].kind == "field_argmin"
    assert plan.operators[0].fields == ["birthDate1", "birthDate2"]
    assert plan.operators[0].labels == ["Find Me Guilty", "Tear Gas Squad"]
    assert plan.operators[0].output == "answer"


def test_typed_field_extremum_template_supports_later_as_argmax():
    question = "Which film has the director who was born later, Alpha Film or Beta Film?"

    plan, metrics = SlotCompiler(FakeStructuredClient([])).compile(question)

    assert metrics.llm_calls == 0
    assert metrics.field_extremum_templates == 1
    assert plan.operators[0].kind == "field_argmax"
    assert plan.operators[0].labels == ["Alpha Film", "Beta Film"]


def test_field_extremum_template_compiles_and_executes_within_four_step_budget():
    question = "Which film has the director who was born first, Find Me Guilty or Tear Gas Squad?"
    plan, compiler_metrics = SlotCompiler(FakeStructuredClient([])).compile(question)

    class TemplateMaterializer:
        def __init__(self):
            self.calls = []

        def materialize(self, slot, bindings):
            self.calls.append((slot.id, dict(bindings)))
            rows = {
                "S1": BindingRow(
                    slot_id="S1",
                    bindings={"director1": "Sidney Lumet"},
                    source_id="Find Me Guilty#0",
                    source_span="Find Me Guilty was directed by Sidney Lumet.",
                    confidence=1,
                ),
                "S2": BindingRow(
                    slot_id="S2",
                    bindings={"director1": "Sidney Lumet", "birthDate1": "June 25, 1924"},
                    source_id="Sidney Lumet#0",
                    source_span="Sidney Lumet was born on June 25, 1924.",
                    confidence=1,
                ),
                "S3": BindingRow(
                    slot_id="S3",
                    bindings={"director2": "Terry O. Morse"},
                    source_id="Tear Gas Squad#0",
                    source_span="Tear Gas Squad was directed by Terry O. Morse.",
                    confidence=1,
                ),
                "S4": BindingRow(
                    slot_id="S4",
                    bindings={"director2": "Terry O. Morse", "birthDate2": "January 30, 1906"},
                    source_id="Terry O. Morse#0",
                    source_span="Terry O. Morse was born on January 30, 1906.",
                    confidence=1,
                ),
            }
            return [rows[slot.id]], RunMetrics(
                retrieval_calls=1,
                documents_accessed=1,
                passages_processed=1,
            )

    materializer = TemplateMaterializer()
    result = AdaptiveExecutor(
        materializer,
        max_replans=4,
        max_retrieval_calls=4,
    ).execute(plan)

    assert compiler_metrics.llm_calls == 0
    assert compiler_metrics.field_extremum_templates == 1
    assert result.status == "ok"
    assert result.rows == [{"answer": "Tear Gas Squad"}]
    assert result.order == ["S1", "S2", "S3", "S4"]
    assert materializer.calls == [
        ("S1", {}),
        ("S2", {"director1": "Sidney Lumet"}),
        ("S3", {}),
        ("S4", {"director2": "Terry O. Morse"}),
    ]
    assert result.metrics.retrieval_calls == 4
    assert result.metrics.operators_executed == 1


def test_polar_comparison_template_skips_llm_with_fallback_equivalent_plan():
    question = "Do Alpha Film and Beta Film share the same nationality?"

    plan, metrics = SlotCompiler(FakeStructuredClient([])).compile(question)

    assert metrics.llm_calls == 0
    assert metrics.heuristic_plans == 1
    assert metrics.polar_comparison_templates == 1
    assert metrics.plan_fallbacks == 0
    assert plan == SlotPlan(
        slots=[Slot(
            id="S1",
            predicate="EvidenceAnsweringQuestion",
            arguments=["?answer"],
            constraints={"question": question},
            variable_types={"answer": "boolean"},
            estimated_cardinality=5,
        )],
        outputs=["?answer"],
    )


@pytest.mark.parametrize(
    "question",
    [
        "Can you name both directors?",
        "Do you know which films have the same director?",
        "What films are from the same country?",
        "Are Alpha and Beta related?",
        "Are both Alpha and Beta from the same country",
    ],
)
def test_polar_comparison_template_rejects_non_whitelisted_boundaries(question):
    fallback_payload = {
        "slots": [{
            "id": "S1",
            "predicate": "EvidenceAnsweringQuestion",
            "arguments": ["?answer"],
            "constraints": {"question": question},
        }],
        "joins": [],
        "outputs": ["?answer"],
    }

    _, metrics = SlotCompiler(FakeStructuredClient([fallback_payload])).compile(question)

    assert metrics.llm_calls == 1
    assert metrics.polar_comparison_templates == 0


def test_polar_comparison_template_can_be_disabled_for_ablation():
    question = "Are both Alpha and Beta from the same country?"
    fallback_payload = {
        "slots": [{
            "id": "S1",
            "predicate": "EvidenceAnsweringQuestion",
            "arguments": ["?answer"],
            "constraints": {"question": question},
        }],
        "joins": [],
        "outputs": ["?answer"],
    }

    _, metrics = SlotCompiler(FakeStructuredClient([fallback_payload])).compile(
        question,
        polar_comparison_templates=False,
    )

    assert metrics.llm_calls == 1
    assert metrics.polar_comparison_templates == 0


def test_explicit_boolean_route_is_not_counted_as_inferred_polar_comparison():
    plan, metrics = SlotCompiler(FakeStructuredClient([])).compile(
        "Are both Alpha and Beta from the same country?",
        answer_kind="boolean",
    )

    assert metrics.llm_calls == 0
    assert metrics.heuristic_plans == 1
    assert metrics.polar_comparison_templates == 0
    assert plan.slots[0].estimated_cardinality == 2


@pytest.mark.parametrize(
    ("noun", "extremum", "expected_kind"),
    [
        ("film", "earlier", "field_argmin"),
        ("film", "earliest", "field_argmin"),
        ("film", "latest", "field_argmax"),
        ("movie", "first", "field_argmin"),
    ],
)
def test_typed_field_extremum_template_supports_whitelisted_synonyms(noun, extremum, expected_kind):
    question = f"Which {noun} has the director who was born {extremum}, Alpha Film or Beta Film?"

    plan, metrics = SlotCompiler(FakeStructuredClient([])).compile(question)

    assert metrics.field_extremum_templates == 1
    assert plan.operators[0].kind == expected_kind


def test_typed_field_extremum_template_rejects_duplicate_candidates():
    question = "Which film has the director who was born first, Alpha Film or Alpha Film?"
    fallback_payload = {
        "slots": [{
            "id": "S1",
            "predicate": "EvidenceAnsweringQuestion",
            "arguments": ["?answer"],
            "constraints": {"question": question},
        }],
        "joins": [],
        "outputs": ["?answer"],
    }

    _, metrics = SlotCompiler(FakeStructuredClient([fallback_payload])).compile(question)

    assert metrics.llm_calls == 1
    assert metrics.typed_plan_templates == 0
    assert metrics.field_extremum_templates == 0


def test_typed_field_extremum_template_rejects_more_than_two_candidates():
    question = "Which film has the director who was born first, Alpha Film or Beta Film or Gamma Film?"
    fallback_payload = {
        "slots": [{
            "id": "S1",
            "predicate": "EvidenceAnsweringQuestion",
            "arguments": ["?answer"],
            "constraints": {"question": question},
        }],
        "joins": [],
        "outputs": ["?answer"],
    }

    _, metrics = SlotCompiler(FakeStructuredClient([fallback_payload])).compile(question)

    assert metrics.llm_calls == 1
    assert metrics.field_extremum_templates == 0


def test_field_extremum_template_can_be_disabled_for_ablation():
    question = "Which film has the director who was born first, Alpha Film or Beta Film?"
    fallback_payload = {
        "slots": [{
            "id": "S1",
            "predicate": "EvidenceAnsweringQuestion",
            "arguments": ["?answer"],
            "constraints": {"question": question},
        }],
        "joins": [],
        "outputs": ["?answer"],
    }

    _, metrics = SlotCompiler(FakeStructuredClient([fallback_payload])).compile(
        question,
        field_extremum_templates=False,
    )

    assert metrics.llm_calls == 1
    assert metrics.field_extremum_templates == 0


def test_slot_compiler_does_not_rewrite_ambiguous_field_comparison():
    plan_payload = {
        "slots": [
            {"id": "S1", "predicate": "BirthDate", "arguments": ["Alice", "?bd1"]},
            {"id": "S2", "predicate": "BirthDate", "arguments": ["Bob", "?bd2"]},
            {"id": "S3", "predicate": "Compare", "arguments": ["?bd1", "?bd2"]},
        ],
        "joins": [["S1.bd1", "S3.bd1"], ["S2.bd2", "S3.bd2"]],
        "outputs": ["?bd1", "?bd2"],
    }

    plan, metrics = SlotCompiler(FakeStructuredClient([plan_payload])).compile(
        "Compare the birth dates of Alice and Bob."
    )

    assert [slot.id for slot in plan.slots] == ["S1", "S2", "S3"]
    assert plan.operators == []
    assert metrics.operator_rewrites == 0


def test_field_extremum_operator_selects_label_for_earliest_date():
    rows = apply_operators(
        [{"bd1": "June 25, 1924", "bd2": "January 30, 1906"}],
        [
            RelationalOperator(
                id="O1",
                kind="field_argmin",
                fields=["bd1", "bd2"],
                labels=["Find Me Guilty", "Tear Gas Squad"],
                output="answer",
            )
        ],
    )

    assert rows == [{"answer": "Tear Gas Squad"}]


def test_slot_compiler_rewrites_later_birthdate_comparison_to_field_argmax():
    plan_payload = {
        "slots": [
            {"id": "S1", "predicate": "BirthDate", "arguments": ["Alice", "?bd1"]},
            {"id": "S2", "predicate": "BirthDate", "arguments": ["Bob", "?bd2"]},
            {"id": "S3", "predicate": "DateCompare", "arguments": ["?bd1", "?bd2"]},
        ],
        "joins": [["S1.bd1", "S3.bd1"], ["S2.bd2", "S3.bd2"]],
        "outputs": ["?bd1", "?bd2"],
    }

    plan, metrics = SlotCompiler(FakeStructuredClient([plan_payload])).compile(
        "Who was born later, Alice or Bob?"
    )
    rows = apply_operators(
        [{"bd1": "2000-01-01", "bd2": "1990-01-01"}],
        plan.operators,
    )

    assert [slot.id for slot in plan.slots] == ["S1", "S2"]
    assert plan.operators[0].kind == "field_argmax"
    assert plan.operators[0].labels == ["Alice", "Bob"]
    assert rows == [{"answer": "Alice"}]
    assert metrics.operator_rewrites == 1


def test_field_extremum_operator_rejects_ties_and_mixed_types():
    operator = RelationalOperator(
        id="O1",
        kind="field_argmin",
        fields=["left", "right"],
        labels=["Left", "Right"],
        output="answer",
    )

    assert apply_operators([{"left": "1906-01-30", "right": "1906-01-30"}], [operator]) == []
    assert apply_operators([{"left": "1906-01-30", "right": "unknown"}], [operator]) == []


def test_executor_combines_only_branches_connected_by_field_operator():
    plan = comparison_plan()

    result = AdaptiveExecutor(ComparisonMaterializer(), max_replans=4).execute(plan)

    assert result.status == "ok"
    assert result.rows == [{"answer": "Tear Gas Squad"}]
    assert result.order == ["S1", "S3", "S2", "S4"]
    assert result.metrics.operators_executed == 1


def test_late_join_combines_branches_connected_by_field_operator():
    result = AdaptiveExecutor(
        ComparisonMaterializer(),
        max_replans=4,
        options=ExecutionOptions(incremental_join=False),
    ).execute(comparison_plan())

    assert result.status == "ok"
    assert result.rows == [{"answer": "Tear Gas Squad"}]
    assert result.metrics.operators_executed == 1


def test_plan_still_rejects_disconnected_slots_without_a_connecting_operator():
    with pytest.raises(ValidationError, match="slot join graph must be connected"):
        SlotPlan.model_validate({
            "slots": [
                {"id": "S1", "predicate": "LeftFact", "arguments": ["?left"]},
                {"id": "S2", "predicate": "RightFact", "arguments": ["?right"]},
            ],
            "joins": [],
            "operators": [],
            "outputs": ["?left"],
        })


def test_date_difference_operator_uses_calendar_month_boundaries():
    rows = apply_operators(
        [{"startDate": "18 September 1906", "endDate": "1906-12-02"}],
        [
            RelationalOperator(
                id="O1",
                kind="arithmetic",
                fields=["startDate", "endDate"],
                operation="date_diff_months",
                output="months",
            )
        ],
    )

    assert rows == [{"months": "3"}]


def test_typed_month_difference_template_skips_llm_compilation_and_executes():
    question = "How many months after he began his term did Zaimis swear allegiance to the new constitution?"
    plan, compiler_metrics = SlotCompiler(FakeStructuredClient([])).compile(
        question,
        answer_kind="number",
        document_count=1,
    )

    assert compiler_metrics.llm_calls == 0
    assert compiler_metrics.heuristic_plans == 1
    assert compiler_metrics.typed_plan_templates == 1
    assert len(plan.slots) == 1
    assert plan.slots[0].predicate == "MonthDifferenceDates"
    assert plan.slots[0].arguments == ["?startDate", "?endDate"]
    assert plan.operators[0].operation == "date_diff_months"

    materializer = SlotMaterializer(
        SequenceExtractionClient(
            [[{
                "startDate": "18 September 1906",
                "endDate": "2 December 1906",
                "source_id": "drop_11251#0",
            }]]
        ),
        StaticRetriever(
            Passage(
                id="drop_11251#0",
                doc_id="drop_11251",
                text="Zaimis began his term on 18 September 1906 and swore allegiance on 2 December 1906.",
            )
        ),
    )
    result = AdaptiveExecutor(materializer).execute(plan)

    assert result.status == "ok"
    assert result.rows == [{"months": "3"}]
    assert result.metrics.extraction_llm_calls == 1
    assert result.metrics.operators_executed == 1


def test_typed_month_difference_template_does_not_match_other_numeric_relations():
    questions = [
        "How many months before the oath did the term begin?",
        "How many days after the term began was the oath sworn?",
        "How many years after the term began was the oath sworn?",
        "After the election, how many months did the term last?",
    ]
    for question in questions:
        payload = {
            "slots": [{
                "id": "S1",
                "predicate": "EvidenceAnsweringQuestion",
                "arguments": ["?answer"],
                "constraints": {"question": question},
            }],
            "joins": [],
            "outputs": ["?answer"],
        }

        _, metrics = SlotCompiler(FakeStructuredClient([payload])).compile(question, answer_kind="number")

        assert metrics.llm_calls == 1
        assert metrics.typed_plan_templates == 0


def test_single_document_compilation_uses_direct_evidence_plan():
    question = "Which player caught the first touchdown pass?"

    plan, metrics = SlotCompiler(FakeStructuredClient([])).compile(
        question,
        answer_kind="number",
        document_count=1,
    )

    assert metrics.llm_calls == 0
    assert metrics.heuristic_plans == 1
    assert metrics.direct_plan_templates == 1
    assert plan.slots[0].predicate == "EvidenceAnsweringQuestion"
    assert plan.slots[0].arguments == ["?answer"]
    assert plan.slots[0].constraints == {"question": question}
    assert plan.outputs == ["?answer"]
    assert plan.operators == []


def test_multi_document_compilation_does_not_use_direct_evidence_plan():
    question = "Which player caught the first touchdown pass?"
    payload = {
        "slots": [{
            "id": "S1",
            "predicate": "EvidenceAnsweringQuestion",
            "arguments": ["?answer"],
            "constraints": {"question": question},
        }],
        "joins": [],
        "outputs": ["?answer"],
    }

    _, metrics = SlotCompiler(FakeStructuredClient([payload])).compile(
        question,
        answer_kind="number",
        document_count=2,
    )

    assert metrics.llm_calls == 1
    assert metrics.direct_plan_templates == 0


def test_materializer_rejects_propagated_binding_not_grounded_in_source():
    invalid_row = {
        "person": "Rogério Martins",
        "series": "Holy Avenger",
        "source_id": "Erica Awano#0",
    }
    materializer = SlotMaterializer(
        SequenceExtractionClient([[invalid_row], [invalid_row]]),
        StaticRetriever(
            Passage(
                id="Erica Awano#0",
                doc_id="Erica Awano",
                text="Erica Awano is a comics artist who worked on Holy Avenger.",
            )
        ),
    )

    rows, metrics = materializer.materialize(
        Slot(id="S2", predicate="CreatedComicBookSeries", arguments=["?person", "?series"]),
        {"person": "Rogério Martins"},
    )

    assert rows == []
    assert metrics.grounding_rejections == 2
    assert metrics.structured_output_failures == 2


def test_materializer_accepts_propagated_binding_grounded_by_document_title():
    row = {
        "person": "Erica Awano",
        "series": "Holy Avenger",
        "source_id": "Erica Awano#0",
    }
    materializer = SlotMaterializer(
        SequenceExtractionClient([[row]]),
        StaticRetriever(
            Passage(
                id="Erica Awano#0",
                doc_id="Erica Awano",
                text="She is the artist of Holy Avenger.",
            )
        ),
    )

    rows, metrics = materializer.materialize(
        Slot(id="S2", predicate="CreatedComicBookSeries", arguments=["?person", "?series"]),
        {"person": "Erica Awano"},
    )

    assert [item.bindings for item in rows] == [{"person": "Erica Awano", "series": "Holy Avenger"}]
    assert metrics.grounding_rejections == 0


def test_typed_boolean_materializer_emits_canonical_supported_rows():
    materializer = SlotMaterializer(
        SequenceExtractionClient([[{"answer": "no", "source_id": "p"}]]),
        StaticRetriever(Passage(id="p", doc_id="d", text="Alpha and Beta are from different countries.")),
        typed_extraction_contracts=True,
    )

    rows, metrics = materializer.materialize(
        Slot(
            id="S1",
            predicate="EvidenceAnsweringQuestion",
            arguments=["?answer"],
            constraints={"question": "Are Alpha and Beta from the same country?"},
            variable_types={"answer": "boolean"},
        ),
        {},
    )

    assert [row.bindings for row in rows] == [{"answer": "no"}]
    assert metrics.typed_extraction_contracts == 1
    assert metrics.typed_extraction_answers == 1
    assert metrics.typed_extraction_abstentions == 0


@pytest.mark.parametrize(
    "extracted_rows",
    [
        [],
        [{"answer": "unknown", "source_id": "p"}],
        [
            {"answer": "yes", "source_id": "p"},
            {"answer": "no", "source_id": "p"},
        ],
    ],
)
def test_typed_boolean_materializer_abstains_on_empty_unknown_or_conflict(extracted_rows):
    materializer = SlotMaterializer(
        SequenceExtractionClient([extracted_rows]),
        StaticRetriever(Passage(id="p", doc_id="d", text="Partial evidence.")),
        typed_extraction_contracts=True,
    )

    rows, metrics = materializer.materialize(
        Slot(
            id="S1",
            predicate="EvidenceAnsweringQuestion",
            arguments=["?answer"],
            variable_types={"answer": "boolean"},
        ),
        {},
    )

    assert rows == []
    assert metrics.llm_calls == 1
    assert metrics.typed_extraction_contracts == 1
    assert metrics.typed_extraction_answers == 0
    assert metrics.typed_extraction_abstentions == 1
    assert metrics.structured_output_failures == 0


def test_typed_boolean_materializer_repairs_invalid_value_then_abstains():
    materializer = SlotMaterializer(
        SequenceExtractionClient([
            [{"answer": "maybe", "source_id": "p"}],
            [{"answer": "unknown", "source_id": "p"}],
        ]),
        StaticRetriever(Passage(id="p", doc_id="d", text="Partial evidence.")),
        typed_extraction_contracts=True,
    )

    rows, metrics = materializer.materialize(
        Slot(
            id="S1",
            predicate="EvidenceAnsweringQuestion",
            arguments=["?answer"],
            variable_types={"answer": "boolean"},
        ),
        {},
    )

    assert rows == []
    assert metrics.llm_calls == 2
    assert metrics.structured_output_failures == 1
    assert metrics.structured_output_repairs == 1
    assert metrics.typed_extraction_abstentions == 1


def test_typed_extraction_is_disabled_by_default_and_keeps_free_text_rows():
    materializer = SlotMaterializer(
        SequenceExtractionClient([[{"answer": "No, Alpha differs from Beta.", "source_id": "p"}]]),
        StaticRetriever(Passage(id="p", doc_id="d", text="Alpha differs from Beta.")),
    )

    rows, metrics = materializer.materialize(
        Slot(
            id="S1",
            predicate="EvidenceAnsweringQuestion",
            arguments=["?answer"],
            variable_types={"answer": "boolean"},
        ),
        {},
    )

    assert [row.bindings for row in rows] == [{"answer": "No, Alpha differs from Beta."}]
    assert metrics.typed_extraction_contracts == 0
    assert metrics.typed_extraction_answers == 0
    assert metrics.typed_extraction_abstentions == 0


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
