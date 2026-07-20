from slotrag.generation import generate_answer_response
from slotrag.models import EvidenceRecord, ExecutionResult
from slotrag.providers import ChatResult


class CapturingClient:
    def complete(self, messages, **_kwargs):
        self.messages = messages
        return ChatResult(content="Tacoma, Washington")


class EmptyThenAnswerClient(CapturingClient):
    def __init__(self):
        self.calls = 0

    def complete(self, messages, **_kwargs):
        self.calls += 1
        self.messages = messages
        return ChatResult(content=None if self.calls == 1 else "42")


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
