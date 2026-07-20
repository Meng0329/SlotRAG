import json

from slotrag.data import chunk_passage, load_questions, normalize_jsonl
from slotrag.models import Passage, QuestionRecord


def test_load_questions_supports_jsonl(tmp_path):
    path = tmp_path / "questions.jsonl"
    path.write_text(json.dumps({"id": "q1", "question": "Who?", "passages": [{"id": "p1", "text": "A fact."}], "answers": ["A"]}) + "\n", encoding="utf-8")
    questions = load_questions(path)
    assert questions[0].id == "q1"
    assert questions[0].passages[0].id == "p1"


def test_normalize_jsonl_round_trip(tmp_path):
    destination = normalize_jsonl([QuestionRecord(id="q", question="What?", passages=[Passage(id="p", text="Fact")])], tmp_path / "out.jsonl")
    assert load_questions(destination)[0].question == "What?"


def test_chunk_passage_preserves_parent_provenance():
    passage = Passage(id="p", doc_id="d", text="one two three four five six")
    chunks = chunk_passage(passage, chunk_tokens=4, overlap=1)
    assert len(chunks) == 2
    assert chunks[1].metadata["parent_passage_id"] == "p"
