from slotrag.generation import _majority_vote, generate_answer_response
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


class MajorityVoteClient(CapturingClient):
    """H-027 client that returns a rotation of candidate answers across N samples."""

    def __init__(self, answers, *, structured=False):
        self.calls = 0
        self.kwargs_by_call = []
        self.answers = answers
        self.structured = structured

    def complete(self, messages, **kwargs):
        self.calls += 1
        self.kwargs_by_call.append(kwargs)
        answer = self.answers[(self.calls - 1) % len(self.answers)]
        if self.structured:
            return ChatResult(
                tool_calls=[ToolCall(name="emit_final_answer", arguments={"answer": answer})],
                finish_reason="tool_calls",
            )
        return ChatResult(content=answer)

    def require_tool(self, result, name):
        return next(call.arguments for call in result.tool_calls if call.name == name)


def test_majority_vote_normalizes_and_returns_most_common_answer():
    # 3 votes for "George B. Seitz" (two case/punct variants), 2 for "Hollywood" —
    # normalization must collapse case/punctuation so the 2 real variants count as 3.
    candidates = ["George B. Seitz", "george b. seitz", "George B. Seitz", "Hollywood", "Hollywood"]
    assert _majority_vote(candidates) == "George B. Seitz"


def test_majority_vote_returns_none_when_all_empty():
    assert _majority_vote([]) is None
    assert _majority_vote(["", "  ", ""]) is None


def test_sample_majority_vote_collects_n_candidates_at_positive_temperature():
    client = MajorityVoteClient(
        ["George B. Seitz", "George B. Seitz", "Hollywood", "George B. Seitz", "Hollywood"],
        structured=True,
    )
    answer, response = generate_answer_response(
        client,
        "Where was the director of the film born?",
        ExecutionResult(
            rows=[{"director": "George B. Seitz"}],
            evidence=[
                EvidenceRecord(source_id="film", source_span="Directed by George B. Seitz", slot_id="S1", bindings={"director": "George B. Seitz"}),
            ],
        ),
        structured_output=True,
        sample_majority_vote=True,
        sample_n=5,
    )

    assert answer == "George B. Seitz"
    assert client.calls == 5
    # Every sample must run at temperature > 0 (the intervention) with the same
    # structured tool so candidates stay grounded.
    assert all(call["temperature"] == 0.7 for call in client.kwargs_by_call)
    assert all(call["tools"][0]["function"]["name"] == "emit_final_answer" for call in client.kwargs_by_call)
    # N samples share one combined response.
    assert response.logical_calls == 5
    assert response.usage.completion_tokens >= 0


def test_sample_majority_vote_falls_back_to_greedy_when_all_samples_empty():
    class AllEmptyClient(CapturingClient):
        def __init__(self):
            self.calls = 0

        def complete(self, messages, **kwargs):
            self.calls += 1
            # First 5 samples empty, then the greedy retry returns a real answer.
            return ChatResult(content="" if self.calls <= 5 else "Tacoma, Washington")

    client = AllEmptyClient()
    answer, _ = generate_answer_response(
        client,
        "Where was the director born?",
        ExecutionResult(rows=[{"place": "Tacoma, Washington"}]),
        sample_majority_vote=True,
        sample_n=5,
    )

    # H-027 must never lose an answer it could already produce (fallback to greedy).
    assert answer == "Tacoma, Washington"
    assert client.calls == 6  # 5 samples + first greedy attempt returns the real answer
