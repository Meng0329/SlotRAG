from slotrag.generation import generate_answer_response
from slotrag.models import EvidenceRecord, ExecutionResult, RunMetrics
from slotrag.providers import ChatResult, ToolCall


class CapturingClient:
    def complete(self, messages, **kwargs):
        self.messages = messages
        self.kwargs = kwargs
        return ChatResult(content="Tacoma, Washington")


class EmptyThenAnswerClient(CapturingClient):
    def __init__(self):
        self.calls = 0

    def complete(self, messages, **kwargs):
        self.calls += 1
        self.messages = messages
        self.kwargs = kwargs
        return ChatResult(content=None if self.calls == 1 else "42")


class ToolAnswerClient(CapturingClient):
    def complete(self, messages, **kwargs):
        self.messages = messages
        self.kwargs = kwargs
        return ChatResult(
            tool_calls=[ToolCall(name="emit_final_answer", arguments={"answer": "True"})],
            finish_reason="tool_calls",
        )

    def require_tool(self, result, name):
        return next(call.arguments for call in result.tool_calls if call.name == name)


def test_answer_prompt_keeps_all_slot_evidence_when_join_has_one_row():
    client = CapturingClient()
    result = ExecutionResult(
        rows=[{"director": "Howard Bretherton", "place": "Tacoma, Washington"}],
        evidence=[
            EvidenceRecord(source_id="film", source_span="Directed by Howard Bretherton", slot_id="S1", bindings={"director": "Howard Bretherton"}),
            EvidenceRecord(source_id="person", source_span="Born in Tacoma, Washington", slot_id="S2", bindings={"director": "Howard Bretherton", "place": "Tacoma, Washington"}),
        ],
    )
    answer, _ = generate_answer_response(client, "Where was the director born?", result)
    assert answer == "Tacoma, Washington"
    assert "film" in client.messages[1]["content"]
    assert "person" in client.messages[1]["content"]
    assert "Tacoma, Washington" in client.messages[1]["content"]


def test_answer_generation_retries_one_empty_response():
    client = EmptyThenAnswerClient()
    answer, _ = generate_answer_response(client, "Answer?", ExecutionResult(rows=[{"answer": "42"}]))
    assert answer == "42"
    assert client.calls == 2


def test_answer_generation_uses_structured_tool_and_disables_thinking():
    client = ToolAnswerClient()
    answer, _ = generate_answer_response(
        client,
        "Does the premise hold?",
        ExecutionResult(rows=[{"answer": "True"}]),
        answer_kind="boolean",
        structured_output=True,
    )

    assert answer == "True"
    assert client.kwargs["enable_thinking"] is False
    assert client.kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "emit_final_answer"},
    }
    assert client.kwargs["tools"][0]["function"]["name"] == "emit_final_answer"
    assert "If it is insufficient" not in client.messages[0]["content"]


def test_answer_generation_keeps_hidden_thinking_for_joined_answers():
    client = ToolAnswerClient()
    answer, _ = generate_answer_response(
        client,
        "Which answer follows from both facts?",
        ExecutionResult(
            rows=[{"answer": "True"}],
            metrics=RunMetrics(plan_slot_count=2, plan_join_count=1),
        ),
        answer_kind="short",
        structured_output=True,
        generation_thinking=True,
    )

    assert answer == "True"
    assert client.kwargs["enable_thinking"] is True
