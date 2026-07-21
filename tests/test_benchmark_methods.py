from types import SimpleNamespace

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

        def compile(self, _question, *, answer_kind):
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

        def compile(self, _question, *, answer_kind):
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

        def compile(self, _question, *, answer_kind, document_count=None):
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
