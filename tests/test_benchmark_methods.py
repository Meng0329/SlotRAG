from slotrag.benchmarking import methods
from slotrag.models import EvidenceRecord, ExecutionResult, Passage, QuestionRecord, RelationalOperator, SlotPlan
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
