from types import SimpleNamespace

import pytest

from slotrag.benchmarking import methods
from slotrag.models import EvidenceRecord, ExecutionResult, Passage, QuestionRecord, RelationalOperator, RunMetrics, SlotPlan
from slotrag.providers import ChatResult
from slotrag.planner import apply_operators


def test_typed_relational_operators_execute_deterministically():
    rows = [{"name": "A", "score": "2"}, {"name": "B", "score": "5"}]
    operators = [RelationalOperator(id="max", kind="argmax", field="score")]
    assert apply_operators(rows, operators) == [{"name": "B", "score": "5"}]
    count = apply_operators(rows, [RelationalOperator(id="count", kind="count", output="n")])
    assert count == [{"n": "2"}]
    arithmetic = apply_operators(
        [{"rebounds": "6.4", "assists": "6.1"}],
        [RelationalOperator(id="difference", kind="arithmetic", fields=["?rebounds", "?assists"], operation="subtract", output="?difference")],
    )
    assert arithmetic == [{"difference": "0.3"}]


def test_plan_outputs_may_reference_typed_operator_output():
    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "Stats", "arguments": ["?x", "?y"]}],
        "joins": [],
        "operators": [{"id": "subtract", "kind": "arithmetic", "fields": ["x", "y"], "operation": "subtract", "output": "difference"}],
        "outputs": ["?difference"],
    })
    assert plan.operators[0].output == "difference"


def test_graphrag_counts_full_corpus_once(monkeypatch):
    question = QuestionRecord(
        id="q",
        question="alpha",
        passages=[
            Passage(id="p1", doc_id="d1", text="alpha beta"),
            Passage(id="p2", doc_id="d2", text="beta gamma"),
        ],
    )
    monkeypatch.setattr(methods, "_finalize", lambda _client, _dataset, _question, result: result)
    result = methods._run_graphrag("hotpotqa", question, object())
    assert result.metrics.documents_accessed == 2
    assert result.metrics.unique_documents_accessed == 2
    assert result.metrics.passages_processed == 2
    assert result.metrics.retrieval_calls == 1


def test_evidence_only_fallback_promotes_empty_result_to_answer():
    class Client:
        def complete(self, *_args, **_kwargs):
            return ChatResult(content="False")

    question = QuestionRecord(id="q", question="True?", answers=["False"])
    empty = ExecutionResult(
        status="empty",
        evidence=[EvidenceRecord(source_id="p", source_span="Evidence", slot_id="S1", bindings={})],
    )
    result = methods._finalize(Client(), "strategyqa", question, empty)
    assert result.status == "ok"
    assert result.answer == "False"
    assert result.metrics.evidence_only_fallbacks == 1
    assert result.metrics.generation_llm_calls == 1


def test_boolean_answer_prefers_explicit_extracted_binding():
    class Client:
        def complete(self, *_args, **_kwargs):
            return ChatResult(content="True")

    question = QuestionRecord(id="q", question="True?", answers=["False"])
    result = ExecutionResult(
        status="ok",
        rows=[{"answer": "No, the evidence contradicts the proposition."}],
        evidence=[EvidenceRecord(source_id="p", source_span="Evidence", slot_id="S1", bindings={})],
    )
    finalized = methods._finalize(Client(), "strategyqa", question, result)
    assert finalized.answer == "False"
    assert finalized.metrics.answer_reconciliations == 1


def test_no_operators_reports_unsupported_without_llm_calculation(monkeypatch):
    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "Value", "arguments": ["?x"]}],
        "joins": [],
        "operators": [{"id": "count", "kind": "count", "output": "n"}],
        "outputs": ["?n"],
    })

    class Compiler:
        def __init__(self, _client):
            pass

        def compile(self, _question, *, answer_kind, field_extremum_templates, polar_comparison_templates):
            assert field_extremum_templates is True
            assert polar_comparison_templates is True
            return plan, RunMetrics()

    class Executor:
        def __init__(self, *_args, **_kwargs):
            pass

        def execute(self, _plan, *, strategy):
            return ExecutionResult(
                rows=[{"x": "one"}],
                evidence=[EvidenceRecord(source_id="p1", source_span="one", slot_id="S1", bindings={"x": "one"})],
                order=["S1"],
            )

    class Client:
        def complete(self, *_args, **_kwargs):
            raise AssertionError("no-operators must not delegate the disabled operation to the LLM")

    monkeypatch.setattr(methods, "SlotCompiler", Compiler)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))
    result = methods._run_slotrag(
        methods.METHODS["slotrag-no-operators"],
        "drop",
        QuestionRecord(id="q", question="How many values?"),
        object(),
        Client(),
        config,
        seed=2027,
        max_steps=4,
        max_retrieval_calls=4,
    )
    assert result.status == "unsupported_operation"
    assert result.answer is None
    assert result.metrics.plan_slot_count == 1
    assert result.metrics.plan_operator_count == 1
    assert result.metrics.plan_complexity == 4
    assert result.metrics.steps_executed == 1


def test_slotrag_returns_single_unique_output_without_final_llm(monkeypatch):
    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "Partner", "arguments": ["Person", "?partner"]}],
        "joins": [],
        "outputs": ["?partner"],
    })

    class Compiler:
        def __init__(self, _client):
            pass

        def compile(self, _question, *, answer_kind, field_extremum_templates, polar_comparison_templates):
            assert field_extremum_templates is True
            assert polar_comparison_templates is True
            return plan, RunMetrics()

    class Executor:
        def __init__(self, *_args, **_kwargs):
            pass

        def execute(self, _plan, *, strategy):
            return ExecutionResult(
                rows=[{"partner": "Ernie Wise"}, {"partner": "Ernie Wise"}],
                evidence=[EvidenceRecord(source_id="p1", source_span="fact", slot_id="S1", bindings={"partner": "Ernie Wise"})],
                order=["S1"],
            )

    class Client:
        def complete(self, *_args, **_kwargs):
            raise AssertionError("a unique relational output must not be verbalized by another LLM call")

    monkeypatch.setattr(methods, "SlotCompiler", Compiler)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))
    result = methods._run_slotrag(
        methods.METHODS["slotrag"],
        "hotpotqa",
        QuestionRecord(id="q", question="Who was the partner?"),
        object(),
        Client(),
        config,
        seed=2027,
        max_steps=4,
        max_retrieval_calls=4,
    )
    assert result.answer == "Ernie Wise"
    assert result.metrics.deterministic_answers == 1


def test_slotrag_replays_frozen_plan_without_calling_compiler(monkeypatch):
    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "Partner", "arguments": ["Person", "?partner"]}],
        "joins": [],
        "outputs": ["?partner"],
    })

    class Compiler:
        def __init__(self, _client):
            raise AssertionError("frozen-plan replay must not construct the compiler")

    class Executor:
        def __init__(self, *_args, **_kwargs):
            pass

        def execute(self, replayed_plan, *, strategy):
            assert replayed_plan == plan
            return ExecutionResult(
                rows=[{"partner": "Ernie Wise"}],
                evidence=[EvidenceRecord(
                    source_id="p1",
                    source_span="fact",
                    slot_id="S1",
                    bindings={"partner": "Ernie Wise"},
                )],
                order=["S1"],
            )

    monkeypatch.setattr(methods, "SlotCompiler", Compiler)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))

    result = methods._run_slotrag(
        methods.METHODS["slotrag"],
        "hotpotqa",
        QuestionRecord(id="q", question="Who was the partner?"),
        object(),
        object(),
        config,
        seed=2027,
        max_steps=4,
        max_retrieval_calls=4,
        frozen_plan=plan,
    )

    assert result.answer == "Ernie Wise"
    assert result.plan == plan
    assert result.metrics.frozen_plan_replays == 1
    assert result.metrics.compilation_llm_calls == 0
    assert result.metrics.compilation_latency_ms == 0
    assert result.metrics.plan_slot_count == 1


def test_anchor_folding_candidate_derives_effective_plan_from_same_frozen_source(monkeypatch):
    raw_plan = SlotPlan.model_validate({
        "slots": [
            {
                "id": "S1",
                "predicate": "Person",
                "arguments": ["Baldwin De Redvers", "7Th Earl Of Devon", "?baldwin"],
            },
            {"id": "S2", "predicate": "MotherOf", "arguments": ["?mother", "?baldwin"]},
            {"id": "S3", "predicate": "MotherOf", "arguments": ["?grandmother", "?mother"]},
        ],
        "joins": [
            ["S1.baldwin", "S2.baldwin"],
            ["S2.mother", "S3.mother"],
        ],
        "outputs": ["?grandmother"],
    })
    executed_plans = []

    class Compiler:
        def __init__(self, _client):
            raise AssertionError("candidate must transform the frozen source rather than recompile")

    class Executor:
        def __init__(self, *_args, **_kwargs):
            pass

        def execute(self, plan, *, strategy):
            executed_plans.append(plan)
            return ExecutionResult(
                rows=[{"grandmother": "Isabel Marshal"}],
                evidence=[EvidenceRecord(
                    source_id="p1",
                    source_span="Isabel Marshal was the maternal grandmother.",
                    slot_id=plan.slots[-1].id,
                    bindings={"grandmother": "Isabel Marshal"},
                )],
                order=[slot.id for slot in plan.slots],
            )

    monkeypatch.setattr(methods, "SlotCompiler", Compiler)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))
    question = QuestionRecord(
        id="q",
        question="Who is Baldwin De Redvers, 7Th Earl Of Devon's maternal grandmother?",
    )

    base = methods._run_slotrag(
        methods.METHODS["slotrag"],
        "2wikimultihop",
        question,
        object(),
        object(),
        config,
        seed=2027,
        max_steps=4,
        max_retrieval_calls=4,
        frozen_plan=raw_plan,
    )
    candidate = methods._run_slotrag(
        methods.METHODS["slotrag-anchor-folding"],
        "2wikimultihop",
        question,
        object(),
        object(),
        config,
        seed=2027,
        max_steps=4,
        max_retrieval_calls=4,
        frozen_plan=raw_plan,
    )
    substitution = methods._run_slotrag(
        methods.METHODS["slotrag-anchor-substitution"],
        "2wikimultihop",
        question,
        object(),
        object(),
        config,
        seed=2027,
        max_steps=4,
        max_retrieval_calls=4,
        frozen_plan=raw_plan,
    )

    assert executed_plans[0] == raw_plan
    assert [slot.id for slot in executed_plans[1].slots] == ["S2", "S3"]
    assert executed_plans[2].slots[0].arguments == [
        "?mother",
        "Baldwin De Redvers, 7Th Earl Of Devon",
    ]
    assert base.metrics.grounded_entity_anchor_folds == 0
    assert candidate.metrics.grounded_entity_anchor_folds == 1
    assert substitution.metrics.grounded_entity_anchor_substitutions == 1
    assert base.metrics.plan_slot_count == 3
    assert candidate.metrics.plan_slot_count == 2
    assert candidate.metrics.plan_join_count == 1
    assert substitution.metrics.plan_slot_count == 2
    assert substitution.metrics.plan_join_count == 1
    assert substitution.metrics.plan_variable_count == 2
    assert candidate.answer == "Isabel Marshal"
    assert substitution.answer == "Isabel Marshal"


def test_role_projected_substitution_routes_anchor_metadata_to_materializer(monkeypatch):
    raw_plan = SlotPlan.model_validate({
        "slots": [
            {
                "id": "S1",
                "predicate": "Person",
                "arguments": ["Baldwin De Redvers", "7Th Earl Of Devon", "?baldwin"],
            },
            {"id": "S2", "predicate": "MotherOf", "arguments": ["?mother", "?baldwin"]},
            {"id": "S3", "predicate": "MotherOf", "arguments": ["?grandmother", "?mother"]},
        ],
        "joins": [
            ["S1.baldwin", "S2.baldwin"],
            ["S2.mother", "S3.mother"],
        ],
        "outputs": ["?grandmother"],
    })
    materializer_options = []

    class Materializer:
        accessed_document_ids = set()
        accessed_passage_ids = set()

        def __init__(self, *_args, **kwargs):
            materializer_options.append(kwargs)

    class Executor:
        def __init__(self, _materializer, *_args, **_kwargs):
            pass

        def execute(self, plan, *, strategy):
            return ExecutionResult(
                rows=[{"grandmother": "Isabel Marshal"}],
                evidence=[EvidenceRecord(
                    source_id="Amice de Clare#0",
                    source_span="Amice de Clare was the daughter of Isabel Marshal.",
                    slot_id="S3",
                    bindings={"grandmother": "Isabel Marshal"},
                )],
                order=[slot.id for slot in plan.slots],
            )

    monkeypatch.setattr(methods, "SlotMaterializer", Materializer)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))

    result = methods._run_slotrag(
        methods.METHODS["slotrag-role-projected-substitution"],
        "2wikimultihop",
        QuestionRecord(
            id="q",
            question="Who is Baldwin De Redvers, 7Th Earl Of Devon's maternal grandmother?",
        ),
        object(),
        object(),
        config,
        seed=2027,
        max_steps=4,
        max_retrieval_calls=4,
        frozen_plan=raw_plan,
    )

    assert materializer_options == [{
        "max_passages": 5,
        "typed_extraction_contracts": False,
        "role_projected_extraction": True,
        "protected_anchor_values": {"Baldwin De Redvers, 7Th Earl Of Devon"},
    }]
    assert result.metrics.grounded_entity_anchor_substitutions == 1
    assert result.answer == "Isabel Marshal"


def test_role_projected_substitution_is_inert_without_a_safe_anchor(monkeypatch):
    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "Answer", "arguments": ["?answer"]}],
        "outputs": ["?answer"],
    })
    materializer_options = []

    class Materializer:
        accessed_document_ids = set()
        accessed_passage_ids = set()

        def __init__(self, *_args, **kwargs):
            materializer_options.append(kwargs)

    class Executor:
        def __init__(self, _materializer, *_args, **_kwargs):
            pass

        def execute(self, effective, *, strategy):
            assert effective == plan
            return ExecutionResult(
                rows=[{"answer": "Alpha"}],
                evidence=[EvidenceRecord(
                    source_id="p",
                    source_span="Alpha",
                    slot_id="S1",
                    bindings={"answer": "Alpha"},
                )],
                order=["S1"],
            )

    monkeypatch.setattr(methods, "SlotMaterializer", Materializer)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))

    result = methods._run_slotrag(
        methods.METHODS["slotrag-role-projected-substitution"],
        "2wikimultihop",
        QuestionRecord(id="q", question="What is the answer?"),
        object(),
        object(),
        config,
        seed=2027,
        max_steps=4,
        max_retrieval_calls=4,
        frozen_plan=plan,
    )

    assert materializer_options == [{
        "max_passages": 5,
        "typed_extraction_contracts": False,
    }]
    assert result.metrics.grounded_entity_anchor_substitutions == 0


def test_grounded_role_projection_routes_direct_anchor_without_changing_plan(monkeypatch):
    plan = SlotPlan.model_validate({
        "slots": [
            {
                "id": "S1",
                "predicate": "MotherOf",
                "arguments": ["Baldwin De Redvers, 7Th Earl Of Devon", "?mother"],
            },
            {"id": "S2", "predicate": "MotherOf", "arguments": ["?mother", "?grandmother"]},
        ],
        "joins": [["S1.mother", "S2.mother"]],
        "outputs": ["?grandmother"],
    })
    materializer_options = []

    class Materializer:
        accessed_document_ids = set()
        accessed_passage_ids = set()

        def __init__(self, *_args, **kwargs):
            materializer_options.append(kwargs)

    class Executor:
        def __init__(self, _materializer, *_args, **_kwargs):
            pass

        def execute(self, effective, *, strategy):
            assert effective == plan
            return ExecutionResult(
                rows=[{"grandmother": "Isabel Marshal"}],
                evidence=[EvidenceRecord(
                    source_id="Amice de Clare#0",
                    source_span="Amice de Clare was the daughter of Isabel Marshal.",
                    slot_id="S2",
                    bindings={"grandmother": "Isabel Marshal"},
                )],
                order=["S1", "S2"],
            )

    monkeypatch.setattr(methods, "SlotMaterializer", Materializer)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))

    result = methods._run_slotrag(
        methods.METHODS["slotrag-grounded-role-projection"],
        "2wikimultihop",
        QuestionRecord(
            id="q",
            question="Who is Baldwin De Redvers, 7Th Earl Of Devon's maternal grandmother?",
        ),
        object(),
        object(),
        config,
        seed=2027,
        max_steps=4,
        max_retrieval_calls=4,
        frozen_plan=plan,
    )

    assert materializer_options == [{
        "max_passages": 5,
        "typed_extraction_contracts": False,
        "role_projected_extraction": True,
        "protected_anchor_values": {"Baldwin De Redvers, 7Th Earl Of Devon"},
    }]
    assert result.plan == plan
    assert result.metrics.grounded_entity_anchor_substitutions == 0
    assert result.metrics.direct_grounded_anchor_projections == 1
    assert result.answer == "Isabel Marshal"


def test_grounded_binding_guard_routes_known_binding_protection(monkeypatch):
    plan = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "namesakeOf", "arguments": ["Johar Town", "?movement"]},
            {"id": "S2", "predicate": "alsoKnownAs", "arguments": ["?movement", "?otherMovement"]},
        ],
        "joins": [["S1.movement", "S2.movement"]],
        "outputs": ["?otherMovement"],
    })
    materializer_options = []

    class Materializer:
        accessed_document_ids = set()
        accessed_passage_ids = set()

        def __init__(self, *_args, **kwargs):
            materializer_options.append(kwargs)

    class Executor:
        def __init__(self, _materializer, *_args, **_kwargs):
            pass

        def execute(self, effective, *, strategy):
            assert effective == plan
            return ExecutionResult(rows=[{"otherMovement": "Khilafat Movement"}], order=["S1", "S2"])

    monkeypatch.setattr(methods, "SlotMaterializer", Materializer)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))

    result = methods._run_slotrag(
        methods.METHODS["slotrag-grounded-binding-guard"],
        "hotpotqa",
        QuestionRecord(
            id="q",
            question="What was the movement the namesake of Johar Town known as besides the Pakistan Movement?",
        ),
        object(),
        object(),
        config,
        seed=2027,
        max_steps=4,
        max_retrieval_calls=4,
        frozen_plan=plan,
    )

    assert materializer_options == [{
        "max_passages": 5,
        "typed_extraction_contracts": False,
        "role_projected_extraction": True,
        "protected_anchor_values": {"Johar Town"},
        "protect_known_binding_values": True,
    }]
    assert result.answer == "Khilafat Movement"


def test_lean_grounded_role_projection_routes_phase_controls_only_when_triggered(monkeypatch):
    plan = SlotPlan.model_validate({
        "slots": [
            {
                "id": "S1",
                "predicate": "MotherOf",
                "arguments": ["Baldwin De Redvers, 7Th Earl Of Devon", "?mother"],
            },
            {"id": "S2", "predicate": "MotherOf", "arguments": ["?mother", "?grandmother"]},
        ],
        "joins": [["S1.mother", "S2.mother"]],
        "outputs": ["?grandmother"],
    })
    materializer_options = []

    class Materializer:
        accessed_document_ids = set()
        accessed_passage_ids = set()

        def __init__(self, *_args, **kwargs):
            materializer_options.append(kwargs)

    class Executor:
        def __init__(self, _materializer, *_args, **_kwargs):
            pass

        def execute(self, effective, *, strategy):
            assert effective == plan
            return ExecutionResult(
                rows=[{"grandmother": "Isabel Marshal"}],
                order=["S1", "S2"],
            )

    monkeypatch.setattr(methods, "SlotMaterializer", Materializer)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))

    result = methods._run_slotrag(
        methods.METHODS["slotrag-lean-grounded-role-projection"],
        "2wikimultihop",
        QuestionRecord(
            id="q",
            question="Who is Baldwin De Redvers, 7Th Earl Of Devon's maternal grandmother?",
        ),
        object(),
        object(),
        config,
        seed=2027,
        max_steps=4,
        max_retrieval_calls=4,
        frozen_plan=plan,
    )

    assert materializer_options == [{
        "max_passages": 5,
        "typed_extraction_contracts": False,
        "role_projected_extraction": True,
        "protected_anchor_values": {"Baldwin De Redvers, 7Th Earl Of Devon"},
        "extraction_enable_thinking": False,
        "bound_role_signatures": True,
    }]
    assert result.metrics.direct_grounded_anchor_projections == 1


def test_grounded_role_type_filter_routes_only_inside_direct_anchor_scope(monkeypatch):
    triggered_plan = SlotPlan.model_validate({
        "slots": [
            {
                "id": "S1",
                "predicate": "MotherOf",
                "arguments": ["Baldwin De Redvers, 7Th Earl Of Devon", "?mother"],
            },
            {"id": "S2", "predicate": "MotherOf", "arguments": ["?mother", "?grandmother"]},
        ],
        "joins": [["S1.mother", "S2.mother"]],
        "outputs": ["?grandmother"],
    })
    inert_plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "Answer", "arguments": ["?answer"]}],
        "outputs": ["?answer"],
    })
    materializer_options = []

    class Materializer:
        accessed_document_ids = set()
        accessed_passage_ids = set()

        def __init__(self, *_args, **kwargs):
            materializer_options.append(kwargs)

    class Executor:
        def __init__(self, _materializer, *_args, **_kwargs):
            pass

        def execute(self, effective, *, strategy):
            output = effective.outputs[0].lstrip("?")
            return ExecutionResult(rows=[{output: "Isabel Marshal"}], order=[slot.id for slot in effective.slots])

    monkeypatch.setattr(methods, "SlotMaterializer", Materializer)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))
    spec = methods.METHODS["slotrag-grounded-role-type-filter"]

    triggered = methods._run_slotrag(
        spec,
        "2wikimultihop",
        QuestionRecord(
            id="triggered",
            question="Who is Baldwin De Redvers, 7Th Earl Of Devon's maternal grandmother?",
        ),
        object(),
        object(),
        config,
        seed=2027,
        max_steps=4,
        max_retrieval_calls=4,
        frozen_plan=triggered_plan,
    )
    inert = methods._run_slotrag(
        spec,
        "2wikimultihop",
        QuestionRecord(id="inert", question="Is this answer supported?"),
        object(),
        object(),
        config,
        seed=2027,
        max_steps=4,
        max_retrieval_calls=4,
        frozen_plan=inert_plan,
    )

    assert materializer_options == [
        {
            "max_passages": 5,
            "typed_extraction_contracts": False,
            "role_projected_extraction": True,
            "protected_anchor_values": {"Baldwin De Redvers, 7Th Earl Of Devon"},
            "semantic_role_type_filter": True,
        },
        {
            "max_passages": 5,
            "typed_extraction_contracts": False,
        },
    ]
    assert triggered.metrics.direct_grounded_anchor_projections == 1
    assert inert.metrics.direct_grounded_anchor_projections == 0


def test_anchor_window_projection_routes_only_inside_direct_anchor_scope(monkeypatch):
    plan = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "DirectorOf", "arguments": ["Her Wild Oat", "?director"]},
            {"id": "S2", "predicate": "CountryOfOrigin", "arguments": ["?director", "?country"]},
        ],
        "joins": [["S1.director", "S2.director"]],
        "outputs": ["?country"],
    })
    materializer_options = []

    class Materializer:
        accessed_document_ids = set()
        accessed_passage_ids = set()

        def __init__(self, *_args, **kwargs):
            materializer_options.append(kwargs)

    class Executor:
        def __init__(self, _materializer, *_args, **_kwargs):
            pass

        def execute(self, effective, *, strategy):
            return ExecutionResult(rows=[{"country": "American"}], order=[slot.id for slot in effective.slots])

    monkeypatch.setattr(methods, "SlotMaterializer", Materializer)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))

    result = methods._run_slotrag(
        methods.METHODS["slotrag-anchor-window-projection"],
        "2wikimultihop",
        QuestionRecord(id="q", question="Which country the director of film Her Wild Oat is from?"),
        object(),
        object(),
        config,
        seed=2027,
        max_steps=4,
        max_retrieval_calls=4,
        frozen_plan=plan,
    )

    assert materializer_options == [{
        "max_passages": 5,
        "typed_extraction_contracts": False,
        "role_projected_extraction": True,
        "protected_anchor_values": {"Her Wild Oat"},
        "anchor_centered_extraction": True,
    }]
    assert result.answer == "American"


def test_normalized_anchor_window_projection_enables_predicate_family_mapping(monkeypatch):
    plan = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "PerformerOf", "arguments": ["Lift Him Up That's All", "?performer"]},
            {"id": "S2", "predicate": "FromCountry", "arguments": ["?performer", "?country"]},
        ],
        "joins": [["S1.performer", "S2.performer"]],
        "outputs": ["?country"],
    })
    materializer_options = []

    class Materializer:
        accessed_document_ids = set()
        accessed_passage_ids = set()

        def __init__(self, *_args, **kwargs):
            materializer_options.append(kwargs)

    class Executor:
        def __init__(self, _materializer, *_args, **_kwargs):
            pass

        def execute(self, effective, *, strategy):
            return ExecutionResult(rows=[{"country": "American"}], order=[slot.id for slot in effective.slots])

    monkeypatch.setattr(methods, "SlotMaterializer", Materializer)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))

    result = methods._run_slotrag(
        methods.METHODS["slotrag-normalized-anchor-window-projection"],
        "2wikimultihop",
        QuestionRecord(
            id="q",
            question="Which country is the performer of Lift Him Up That's All from?",
        ),
        object(),
        object(),
        config,
        seed=2028,
        max_steps=4,
        max_retrieval_calls=4,
        frozen_plan=plan,
    )

    assert materializer_options == [{
        "max_passages": 5,
        "typed_extraction_contracts": False,
        "role_projected_extraction": True,
        "protected_anchor_values": {"Lift Him Up That's All"},
        "anchor_centered_extraction": True,
        "normalize_anchor_window_predicates": True,
    }]
    assert result.answer == "American"


def test_context_normalized_anchor_window_projection_protects_query_title(monkeypatch):
    plan = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "DirectorOf", "arguments": ["?director"]},
            {"id": "S2", "predicate": "HasNationality", "arguments": ["?director", "?nationality"]},
        ],
        "joins": [["S1.director", "S2.director"]],
        "outputs": ["?nationality"],
    })
    materializer_options = []

    class Materializer:
        accessed_document_ids = set()
        accessed_passage_ids = set()

        def __init__(self, *_args, **kwargs):
            materializer_options.append(kwargs)

    class Executor:
        def __init__(self, _materializer, *_args, **_kwargs):
            pass

        def execute(self, effective, *, strategy):
            return ExecutionResult(rows=[{"nationality": "American"}], order=[slot.id for slot in effective.slots])

    monkeypatch.setattr(methods, "SlotMaterializer", Materializer)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))

    result = methods._run_slotrag(
        methods.METHODS["slotrag-context-normalized-anchor-window-projection"],
        "2wikimultihop",
        QuestionRecord(id="q", question="What nationality is the director of film Claire (1924 Film)?"),
        object(),
        object(),
        config,
        seed=2029,
        max_steps=4,
        max_retrieval_calls=4,
        frozen_plan=plan,
    )

    assert materializer_options == [{
        "max_passages": 5,
        "typed_extraction_contracts": False,
        "role_projected_extraction": True,
        "protected_anchor_values": {"Claire (1924 Film)"},
        "anchor_centered_extraction": True,
        "normalize_anchor_window_predicates": True,
    }]
    assert result.metrics.query_grounded_anchor_contexts == 1


def test_repaired_context_anchor_window_routes_plan_and_surface_repairs(monkeypatch):
    plan = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "DirectorOf", "arguments": ["?director"]},
            {"id": "S2", "predicate": "HasNationality", "arguments": ["?director", "?nationality"]},
        ],
        "joins": [["S1.director", "S2.director"]],
        "outputs": ["?nationality"],
    })
    materializer_options = []

    class Materializer:
        accessed_document_ids = set()
        accessed_passage_ids = set()

        def __init__(self, *_args, **kwargs):
            materializer_options.append(kwargs)

    class Executor:
        def __init__(self, _materializer, *_args, **_kwargs):
            pass

        def execute(self, effective, *, strategy):
            return ExecutionResult(rows=[{"nationality": "Danish"}], order=[slot.id for slot in effective.slots])

    monkeypatch.setattr(methods, "SlotMaterializer", Materializer)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))

    result = methods._run_slotrag(
        methods.METHODS["slotrag-repaired-context-anchor-window-projection"],
        "2wikimultihop",
        QuestionRecord(id="q", question="What nationality is the director of film Claire (1924 Film)?"),
        object(),
        object(),
        config,
        seed=2030,
        max_steps=4,
        max_retrieval_calls=4,
        frozen_plan=plan,
    )

    assert result.plan.slots[0].arguments == ["?director", "Claire (1924 Film)"]
    assert result.metrics.query_anchor_plan_repairs == 1
    assert materializer_options == [{
        "max_passages": 5,
        "typed_extraction_contracts": False,
        "role_projected_extraction": True,
        "protected_anchor_values": {"Claire (1924 Film)"},
        "anchor_centered_extraction": True,
        "normalize_anchor_window_predicates": True,
        "evidence_surface_grounding_repair": True,
    }]


def test_repaired_context_anchor_window_ablation_matrix():
    base = methods.METHODS["slotrag-context-normalized-anchor-window-projection"]
    plan_only = methods.METHODS["slotrag-plan-repaired-context-anchor-window-projection"]
    surface_only = methods.METHODS["slotrag-surface-repaired-context-anchor-window-projection"]
    combined = methods.METHODS["slotrag-repaired-context-anchor-window-projection"]

    assert (base.query_anchor_plan_repair, base.evidence_surface_grounding_repair) == (False, False)
    assert (plan_only.query_anchor_plan_repair, plan_only.evidence_surface_grounding_repair) == (True, False)
    assert (surface_only.query_anchor_plan_repair, surface_only.evidence_surface_grounding_repair) == (False, True)
    assert (combined.query_anchor_plan_repair, combined.evidence_surface_grounding_repair) == (True, True)


def test_grounded_role_projection_prefers_substitution_activation(monkeypatch):
    plan = SlotPlan.model_validate({
        "slots": [
            {
                "id": "S1",
                "predicate": "Person",
                "arguments": ["Baldwin De Redvers", "7Th Earl Of Devon", "?baldwin"],
            },
            {"id": "S2", "predicate": "MotherOf", "arguments": ["?mother", "?baldwin"]},
            {"id": "S3", "predicate": "MotherOf", "arguments": ["?grandmother", "?mother"]},
        ],
        "joins": [
            ["S1.baldwin", "S2.baldwin"],
            ["S2.mother", "S3.mother"],
        ],
        "outputs": ["?grandmother"],
    })

    class Materializer:
        accessed_document_ids = set()
        accessed_passage_ids = set()

        def __init__(self, *_args, **_kwargs):
            pass

    class Executor:
        def __init__(self, _materializer, *_args, **_kwargs):
            pass

        def execute(self, effective, *, strategy):
            assert len(effective.slots) == 2
            return ExecutionResult(
                rows=[{"grandmother": "Isabel Marshal"}],
                evidence=[EvidenceRecord(
                    source_id="Amice de Clare#0",
                    source_span="Amice de Clare was the daughter of Isabel Marshal.",
                    slot_id="S3",
                    bindings={"grandmother": "Isabel Marshal"},
                )],
                order=["S2", "S3"],
            )

    monkeypatch.setattr(methods, "SlotMaterializer", Materializer)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    monkeypatch.setattr(
        methods,
        "direct_grounded_relation_anchor_values",
        lambda *_args: (_ for _ in ()).throw(AssertionError("direct scan must not run")),
    )
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))

    result = methods._run_slotrag(
        methods.METHODS["slotrag-grounded-role-projection"],
        "2wikimultihop",
        QuestionRecord(
            id="q",
            question="Who is Baldwin De Redvers, 7Th Earl Of Devon's maternal grandmother?",
        ),
        object(),
        object(),
        config,
        seed=2027,
        max_steps=4,
        max_retrieval_calls=4,
        frozen_plan=plan,
    )

    assert result.metrics.grounded_entity_anchor_substitutions == 1
    assert result.metrics.direct_grounded_anchor_projections == 0


def test_slotrag_routes_one_document_topology_and_no_direct_ablation_disables_it(monkeypatch):
    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "Answer", "arguments": ["?answer"]}],
        "joins": [],
        "outputs": ["?answer"],
    })
    observed_document_counts = []

    class Compiler:
        def __init__(self, _client):
            pass

        def compile(
            self,
            _question,
            *,
            answer_kind,
            field_extremum_templates,
            polar_comparison_templates,
            document_count=None,
        ):
            assert field_extremum_templates is True
            assert polar_comparison_templates is True
            observed_document_counts.append(document_count)
            return plan, RunMetrics()

    class Executor:
        def __init__(self, *_args, **_kwargs):
            pass

        def execute(self, _plan, *, strategy):
            return ExecutionResult(
                rows=[{"answer": "Anthony Gonzalez"}],
                evidence=[EvidenceRecord(
                    source_id="p1",
                    source_span="Anthony Gonzalez caught the pass.",
                    slot_id="S1",
                    bindings={"answer": "Anthony Gonzalez"},
                )],
                order=["S1"],
            )

    monkeypatch.setattr(methods, "SlotCompiler", Compiler)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))
    question = QuestionRecord(
        id="q",
        question="Who caught the pass?",
        passages=[
            Passage(id="p1", doc_id="game", text="First chunk."),
            Passage(id="p2", doc_id="game", text="Second chunk."),
        ],
    )

    for method in ("slotrag", "slotrag-no-direct"):
        result = methods._run_slotrag(
            methods.METHODS[method],
            "drop",
            question,
            object(),
            object(),
            config,
            seed=2027,
            max_steps=4,
            max_retrieval_calls=4,
        )
        assert result.answer == "Anthony Gonzalez"

    assert observed_document_counts == [1, None]


def test_direct_answer_projection_strips_only_redundant_numeric_explanation():
    verbose = "families (20,154 families compared to 74,563 people)"
    result = ExecutionResult(
        rows=[
            {"answer": verbose},
            {"answer": "Mercury (planet)"},
            {"answer": "Washington (Washington state)"},
        ],
        evidence=[EvidenceRecord(
            source_id="p1",
            source_span="20,154 families compared to 74,563 people.",
            slot_id="S1",
            bindings={"answer": verbose},
        )],
        metrics=RunMetrics(direct_plan_templates=1),
    )

    normalized = methods._normalize_direct_answer_rows(result)

    assert normalized.rows == [
        {"answer": "families"},
        {"answer": "Mercury (planet)"},
        {"answer": "Washington (Washington state)"},
    ]
    assert normalized.evidence[0].bindings["answer"] == verbose
    assert normalized.metrics.answer_span_normalizations == 1

    non_direct = result.model_copy(update={"metrics": RunMetrics()})
    assert methods._normalize_direct_answer_rows(non_direct).rows[0]["answer"] == verbose


def test_deterministic_output_rejects_serialized_structures():
    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "Answer", "arguments": ["?answer"]}],
        "joins": [],
        "outputs": ["?answer"],
    })
    result = ExecutionResult(rows=[{"answer": "{'country': 'Canada', 'period': '1960s-1990s'}"}])

    assert methods._deterministic_output("hotpotqa", plan, result) is None


def test_run_method_normalizes_answer_leading_polar_response_at_shared_outlet(monkeypatch):
    original = ExecutionResult(
        answer="No, the two directors have different nationalities.",
        rows=[{"answer": "No, the two directors have different nationalities."}],
        evidence=[EvidenceRecord(
            source_id="p1",
            source_span="The directors have different nationalities.",
            slot_id="hybrid",
            bindings={},
        )],
        metrics=RunMetrics(llm_calls=1, prompt_tokens=10, completion_tokens=5),
    )
    monkeypatch.setattr(methods, "_run_hybrid", lambda *_args: original)

    result = methods.run_method(
        "hybrid",
        dataset="2wikimultihop",
        question=QuestionRecord(id="q", question="Do the directors share the same nationality?"),
        retriever=object(),
        client=object(),
        config=object(),
        seed=2027,
    )

    assert result.answer == "no"
    assert result.rows == original.rows
    assert result.evidence == original.evidence
    assert result.metrics.llm_calls == 1
    assert result.metrics.prompt_tokens == 10
    assert result.metrics.completion_tokens == 5
    assert result.metrics.polar_answer_normalizations == 1


def test_run_method_does_not_normalize_auxiliary_led_non_question(monkeypatch):
    original = ExecutionResult(answer="No, this is explanatory prose.")
    monkeypatch.setattr(methods, "_run_hybrid", lambda *_args: original)

    result = methods.run_method(
        "hybrid",
        dataset="2wikimultihop",
        question=QuestionRecord(id="q", question="Do not reduce this answer to one token."),
        retriever=object(),
        client=object(),
        config=object(),
        seed=2027,
    )

    assert result.answer == original.answer
    assert result.metrics.polar_answer_normalizations == 0


def test_run_method_does_not_count_already_canonical_polar_answer(monkeypatch):
    original = ExecutionResult(answer="no")
    monkeypatch.setattr(methods, "_run_hybrid", lambda *_args: original)

    result = methods.run_method(
        "hybrid",
        dataset="2wikimultihop",
        question=QuestionRecord(id="q", question="Do the directors share a nationality?"),
        retriever=object(),
        client=object(),
        config=object(),
        seed=2027,
    )

    assert result.answer == "no"
    assert result.metrics.polar_answer_normalizations == 0


def test_no_extremum_template_ablation_only_disables_compiler_entry(monkeypatch):
    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "Answer", "arguments": ["?answer"]}],
        "joins": [],
        "outputs": ["?answer"],
    })
    observed = []

    class Compiler:
        def __init__(self, _client):
            pass

        def compile(self, _question, **kwargs):
            observed.append(kwargs["field_extremum_templates"])
            return plan, RunMetrics()

    class Executor:
        def __init__(self, *_args, **_kwargs):
            pass

        def execute(self, _plan, *, strategy):
            return ExecutionResult(
                rows=[{"answer": "Alpha"}],
                evidence=[EvidenceRecord(source_id="p", source_span="Alpha", slot_id="S1", bindings={"answer": "Alpha"})],
            )

    monkeypatch.setattr(methods, "SlotCompiler", Compiler)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))
    question = QuestionRecord(id="q", question="Which answer?")

    for method in ("slotrag", "slotrag-no-extremum-template"):
        result = methods._run_slotrag(
            methods.METHODS[method],
            "2wikimultihop",
            question,
            object(),
            object(),
            config,
            seed=2027,
            max_steps=4,
            max_retrieval_calls=4,
        )
        assert result.answer == "Alpha"
        assert methods.METHODS[method].options.typed_operators is True

    assert observed == [True, False]


def test_no_polar_template_ablation_only_disables_compiler_entry(monkeypatch):
    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "Answer", "arguments": ["?answer"]}],
        "joins": [],
        "outputs": ["?answer"],
    })
    observed = []

    class Compiler:
        def __init__(self, _client):
            pass

        def compile(self, _question, **kwargs):
            observed.append(kwargs["polar_comparison_templates"])
            return plan, RunMetrics()

    class Executor:
        def __init__(self, *_args, **_kwargs):
            pass

        def execute(self, _plan, *, strategy):
            return ExecutionResult(
                rows=[{"answer": "no"}],
                evidence=[EvidenceRecord(source_id="p", source_span="no", slot_id="S1", bindings={"answer": "no"})],
            )

    monkeypatch.setattr(methods, "SlotCompiler", Compiler)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))
    question = QuestionRecord(id="q", question="Are both facts the same?")

    for method in ("slotrag", "slotrag-no-polar-template"):
        result = methods._run_slotrag(
            methods.METHODS[method],
            "2wikimultihop",
            question,
            object(),
            object(),
            config,
            seed=2027,
            max_steps=4,
            max_retrieval_calls=4,
        )
        assert result.answer == "no"
        assert methods.METHODS[method].options.typed_operators is True
        assert methods.METHODS[method].field_extremum_templates is True

    assert observed == [True, False]


def test_slotrag_uses_explicit_polar_row_consensus_without_final_llm(monkeypatch):
    question = QuestionRecord(id="q", question="Do Alpha and Beta share the same nationality?")
    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "EvidenceAnsweringQuestion", "arguments": ["?answer"]}],
        "joins": [],
        "outputs": ["?answer"],
    })
    rows = [
        {"answer": "No, Alpha is French."},
        {"answer": "No, Beta is German."},
    ]
    evidence = [EvidenceRecord(source_id="p", source_span="facts", slot_id="S1", bindings={})]

    class Compiler:
        def __init__(self, _client):
            pass

        def compile(self, _question, **_kwargs):
            return plan, RunMetrics()

    class Executor:
        def __init__(self, *_args, **_kwargs):
            pass

        def execute(self, _plan, *, strategy):
            return ExecutionResult(rows=rows, evidence=evidence, order=["S1"])

    class Client:
        def complete(self, *_args, **_kwargs):
            raise AssertionError("explicit polar consensus must not call the final generator")

    monkeypatch.setattr(methods, "SlotCompiler", Compiler)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))

    result = methods._run_slotrag(
        methods.METHODS["slotrag"],
        "2wikimultihop",
        question,
        object(),
        Client(),
        config,
        seed=2027,
        max_steps=4,
        max_retrieval_calls=4,
    )
    normalized = methods._normalize_polar_answer(question.question, result)

    assert result.answer == "No"
    assert result.rows == rows
    assert result.evidence == evidence
    assert result.metrics.deterministic_answers == 1
    assert result.metrics.polar_row_consensus == 1
    assert normalized.answer == "no"
    assert normalized.metrics.polar_row_consensus == 1
    assert normalized.metrics.polar_answer_normalizations == 1


@pytest.mark.parametrize(
    ("question", "values"),
    [
        ("Do Alpha and Beta match?", ["No, Alpha differs.", "Yes, Beta matches."]),
        ("Do Alpha and Beta match?", ["No, Alpha differs.", "Beta is German."]),
        ("Do Alpha and Beta match?", ["No", "No"]),
        ("Which facts match?", ["No, Alpha differs.", "No, Beta differs."]),
    ],
)
def test_polar_row_consensus_rejects_conflict_missing_token_unique_and_nonpolar(question, values):
    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "EvidenceAnsweringQuestion", "arguments": ["?answer"]}],
        "joins": [],
        "outputs": ["?answer"],
    })
    result = ExecutionResult(rows=[{"answer": value} for value in values])

    assert methods._polar_row_consensus(question, plan, result) is None


def test_no_polar_consensus_ablation_only_disables_projection(monkeypatch):
    question = QuestionRecord(id="q", question="Do Alpha and Beta share the same nationality?")
    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "EvidenceAnsweringQuestion", "arguments": ["?answer"]}],
        "joins": [],
        "outputs": ["?answer"],
    })

    class Compiler:
        def __init__(self, _client):
            pass

        def compile(self, _question, **_kwargs):
            return plan, RunMetrics()

    class Executor:
        def __init__(self, *_args, **_kwargs):
            pass

        def execute(self, _plan, *, strategy):
            return ExecutionResult(
                rows=[{"answer": "No, Alpha is French."}, {"answer": "No, Beta is German."}],
                evidence=[EvidenceRecord(source_id="p", source_span="facts", slot_id="S1", bindings={})],
                order=["S1"],
            )

    finalized = []

    def finalize(_client, _dataset, _question, result):
        finalized.append(result)
        return result.model_copy(update={"answer": "generated"})

    monkeypatch.setattr(methods, "SlotCompiler", Compiler)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    monkeypatch.setattr(methods, "_finalize", finalize)
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))

    results = []
    for method in ("slotrag", "slotrag-no-polar-consensus"):
        results.append(methods._run_slotrag(
            methods.METHODS[method],
            "2wikimultihop",
            question,
            object(),
            object(),
            config,
            seed=2027,
            max_steps=4,
            max_retrieval_calls=4,
        ))

    assert [result.answer for result in results] == ["No", "generated"]
    assert [result.metrics.polar_row_consensus for result in results] == [1, 0]
    assert len(finalized) == 1
    assert methods.METHODS["slotrag-no-polar-consensus"].options.typed_operators is True
    assert methods.METHODS["slotrag-no-polar-consensus"].field_extremum_templates is True
    assert methods.METHODS["slotrag-no-polar-consensus"].polar_comparison_templates is True


def test_typed_extraction_candidate_only_enables_materializer_contract(monkeypatch):
    question = QuestionRecord(id="q", question="Are Alpha and Beta from the same country?")
    plan = SlotPlan.model_validate({
        "slots": [{
            "id": "S1",
            "predicate": "EvidenceAnsweringQuestion",
            "arguments": ["?answer"],
            "variable_types": {"answer": "boolean"},
        }],
        "joins": [],
        "outputs": ["?answer"],
    })
    observed = []

    class Compiler:
        def __init__(self, _client):
            pass

        def compile(self, _question, **_kwargs):
            return plan, RunMetrics(polar_comparison_templates=1)

    class Materializer:
        def __init__(self, *_args, typed_extraction_contracts, **_kwargs):
            observed.append(typed_extraction_contracts)
            self.accessed_document_ids = set()
            self.accessed_passage_ids = set()

    class Executor:
        def __init__(self, *_args, **_kwargs):
            pass

        def execute(self, _plan, *, strategy):
            return ExecutionResult(
                rows=[{"answer": "no"}],
                evidence=[EvidenceRecord(source_id="p", source_span="fact", slot_id="S1", bindings={})],
                order=["S1"],
            )

    monkeypatch.setattr(methods, "SlotCompiler", Compiler)
    monkeypatch.setattr(methods, "SlotMaterializer", Materializer)
    monkeypatch.setattr(methods, "AdaptiveExecutor", Executor)
    config = SimpleNamespace(execution=SimpleNamespace(
        materialization_top_k=5,
        default_slot_cost=1.0,
        unbound_argument_cost=2.0,
        max_replans=4,
        max_binding_contexts=2,
    ))

    results = []
    for method in ("slotrag", "slotrag-typed-extraction"):
        results.append(methods._run_slotrag(
            methods.METHODS[method],
            "2wikimultihop",
            question,
            object(),
            object(),
            config,
            seed=2027,
            max_steps=4,
            max_retrieval_calls=4,
        ))

    assert [result.answer for result in results] == ["no", "no"]
    assert observed == [False, True]
    assert methods.METHODS["slotrag-typed-extraction"].options.typed_operators is True
    assert methods.METHODS["slotrag-typed-extraction"].field_extremum_templates is True
    assert methods.METHODS["slotrag-typed-extraction"].polar_comparison_templates is True
    assert methods.METHODS["slotrag-typed-extraction"].polar_row_consensus is True
