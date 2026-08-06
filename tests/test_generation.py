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


class ExtractThenSelectClient(CapturingClient):
    """Two-stage H-020 client: first complete() emits candidates, second emits selection."""

    def __init__(self, spans=None, selection="Hollywood"):
        self.calls = 0
        self.kwargs_by_call = []
        self.messages_by_call = []
        self.spans = spans if spans is not None else ["Hollywood", "George B. Seitz"]
        self.selection = selection

    def complete(self, messages, **kwargs):
        self.calls += 1
        self.kwargs_by_call.append(kwargs)
        self.messages_by_call.append(messages)
        if self.calls == 1:
            return ChatResult(
                tool_calls=[ToolCall(
                    name="emit_candidate_spans",
                    arguments={"spans": self.spans, "passage_ids": ["p1", "p2"]},
                )],
                finish_reason="tool_calls",
            )
        return ChatResult(
            tool_calls=[ToolCall(name="emit_selected_answer", arguments={"answer": self.selection})],
            finish_reason="tool_calls",
        )

    def require_tool(self, result, name):
        return next(call.arguments for call in result.tool_calls if call.name == name)


def test_extract_then_select_two_stage_contract_returns_selected_span():
    client = ExtractThenSelectClient(selection="Hollywood")
    result = ExecutionResult(
        rows=[{"subject": "Andy García"}],
        evidence=[
            EvidenceRecord(source_id="seitz", source_span="George B. Seitz was born in Hollywood", slot_id="S1", bindings={"subject": "Andy García"}),
        ],
    )
    answer, response = generate_answer_response(
        client,
        "Where was the director of the film born?",
        result,
        structured_output=True,
        extract_then_select=True,
    )

    assert answer == "Hollywood"
    assert client.calls == 2
    # Step 1 must force the candidate-spans tool, grounded in evidence by construction.
    step1 = client.kwargs_by_call[0]
    assert step1["tools"][0]["function"]["name"] == "emit_candidate_spans"
    assert step1["tool_choice"]["function"]["name"] == "emit_candidate_spans"
    # Step 2 must present the candidates back to the model before selecting.
    step2_messages = client.messages_by_call[1]
    assert "candidate answer spans" in step2_messages[-1]["content"]
    assert "Hollywood" in step2_messages[-1]["content"]
    assert client.kwargs_by_call[1]["tools"][0]["function"]["name"] == "emit_selected_answer"
    assert response.logical_calls == 2


def test_extract_then_select_falls_back_to_free_generation_when_no_candidates():
    class NoCandidatesThenAnswer(ExtractThenSelectClient):
        def complete(self, messages, **kwargs):
            self.calls += 1
            self.kwargs_by_call.append(kwargs)
            self.messages_by_call.append(messages)
            if self.calls == 1:
                return ChatResult(tool_calls=[ToolCall(name="emit_candidate_spans", arguments={"spans": [], "passage_ids": []})])
            return ChatResult(content="Tacoma, Washington")

    client = NoCandidatesThenAnswer()
    answer, response = generate_answer_response(
        client,
        "Where was the director born?",
        ExecutionResult(rows=[{"place": "Tacoma, Washington"}]),
        structured_output=True,
        extract_then_select=True,
    )

    # Fallback path must not raise and must produce an answer via free generation.
    assert answer == "Tacoma, Washington"
    assert client.calls == 2
    # Step 1 ran the candidate-spans contract; free generation reuses the final-answer tool.
    assert client.kwargs_by_call[0]["tools"][0]["function"]["name"] == "emit_candidate_spans"
    assert client.kwargs_by_call[1]["tools"][0]["function"]["name"] == "emit_final_answer"


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
