import json

from slotrag.benchmarking.datasets import DatasetSpec, adapt_record, load_sample
from slotrag.data import load_questions, normalize_jsonl


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def test_dataset_adapter_maps_hotpot_titles_to_passage_ids():
    spec = DatasetSpec("toy", "train.jsonl", "dev.jsonl", "f1", lambda record: record["type"], "hotpot_titles")
    question = adapt_record(
        spec,
        {
            "id": "q1",
            "question": "Who?",
            "answers": "Ada",
            "passages": [{"id": "Ada#0", "doc_id": "Ada", "text": "Ada wrote it."}],
            "gold_evidence": {"title": ["Ada"], "sent_id": [0]},
            "type": "bridge",
        },
        0,
        split="train",
    )
    assert question.answers == ["Ada"]
    assert question.gold_evidence == ["Ada#0"]
    assert question.metadata["stratum"] == "bridge"


def test_stratified_sample_is_deterministic_and_round_trips_metadata(tmp_path):
    records = [
        {
            "id": f"q{index}",
            "question": f"Question {index}?",
            "answers": [str(index)],
            "passages": [{"id": f"p{index}", "text": "Evidence"}],
            "group": "a" if index < 6 else "b",
        }
        for index in range(10)
    ]
    _write_jsonl(tmp_path / "toy.jsonl", records)
    spec = DatasetSpec("toy", "toy.jsonl", "toy.jsonl", "f1", lambda record: record["group"])
    first = load_sample(spec, tmp_path, split="train", size=4, seed=7)
    second = load_sample(spec, tmp_path, split="train", size=4, seed=7)
    assert [item.id for item in first] == [item.id for item in second]
    assert {item.metadata["stratum"] for item in first} == {"a", "b"}

    sample_path = normalize_jsonl(first, tmp_path / "sample.jsonl")
    reloaded = load_questions(sample_path)
    assert [item.metadata["stratum"] for item in reloaded] == [item.metadata["stratum"] for item in first]

