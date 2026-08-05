import json

from slotrag.benchmarking.datasets import DATASETS, DatasetSpec, adapt_record, load_all_questions, load_sample
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


def test_strategyqa_facts_kept_for_local_context_and_excluded_for_shared_index():
    # local_context (default): facts are the question's own supporting context
    strategy = adapt_record(
        DATASETS["strategyqa"],
        {
            "id": "sq1",
            "question": "Is alpha true?",
            "answers": ["True"],
            "passages": [{"id": "fact_0#0", "doc_id": "fact_0", "text": "Alpha is true."}],
            "type": "strategy",
        },
        0,
        split="train",
    )
    assert [p.id for p in strategy.passages] == ["fact_0#0"]
    assert strategy.metadata["available_evidence"] is True
    assert strategy.metadata["evidence_protocol"] == "gold_facts_only"
    assert strategy.metadata["protocol_warning"] == "strategyqa_facts_are_not_shared_corpus"

    # shared index (exclude_facts=True): facts are not a shared corpus
    shared = adapt_record(
        DATASETS["strategyqa"],
        {
            "id": "sq1",
            "question": "Is alpha true?",
            "answers": ["True"],
            "passages": [{"id": "fact_0#0", "doc_id": "fact_0", "text": "Alpha is true."}],
            "type": "strategy",
        },
        0,
        split="train",
        exclude_facts=True,
    )
    assert shared.passages == []
    assert shared.metadata["available_evidence"] is False
    assert shared.metadata["evidence_protocol"] == "gold_facts_only"
    assert shared.metadata["protocol_warning"] == "strategyqa_facts_are_not_shared_corpus"

    drop = adapt_record(
        DATASETS["drop"],
        {
            "id": "drop1",
            "question": "List the names.",
            "answers": ["Alpha"],
            "passages": [{"id": "p1", "text": "Alpha."}],
            "operation_type": "listing",
            "operation_type_source": "official",
        },
        0,
        split="train",
    )
    assert drop.metadata["stratum"] == "listing"
    assert drop.metadata["stratum_source"] == "official"


def test_load_all_questions_reads_the_complete_split(tmp_path):
    path = tmp_path / "toy.jsonl"
    _write_jsonl(path, [
        {"id": "q1", "question": "One?", "answers": ["1"], "passages": [{"id": "p1", "text": "One."}], "group": "a"},
        {"id": "q2", "question": "Two?", "answers": ["2"], "passages": [{"id": "p2", "text": "Two."}], "group": "b"},
    ])
    spec = DatasetSpec("toy", "toy.jsonl", "toy.jsonl", "f1", lambda record: record["group"])
    questions = load_all_questions(spec, tmp_path, split="train")
    assert [question.id for question in questions] == ["q1", "q2"]
