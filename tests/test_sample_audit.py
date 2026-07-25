import json

from slotrag.benchmarking.datasets import DatasetSpec, adapt_record
from slotrag.benchmarking.sample_audit import audit_existing_samples
from slotrag.data import normalize_jsonl


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def _record(question_id):
    return {
        "id": question_id,
        "question": f"Question {question_id}?",
        "answers": [question_id],
        "passages": [{"id": f"p-{question_id}", "text": "Evidence"}],
        "group": "a",
    }


def test_existing_sample_audit_validates_source_membership_and_metadata(tmp_path):
    spec = DatasetSpec("toy", "train.jsonl", "evaluation.jsonl", "f1", lambda record: record["group"])
    source_records = [_record("q1"), _record("q2"), _record("q3")]
    _write_jsonl(tmp_path / "benchmark" / "train.jsonl", source_records)
    sample = [adapt_record(spec, source_records[index], index, split="train") for index in (0, 2)]
    normalize_jsonl(sample, tmp_path / "samples" / "toy.jsonl")

    report = audit_existing_samples(
        benchmark_root=tmp_path / "benchmark",
        dataset_specs={"toy": spec},
        datasets=["toy"],
        split="train",
        expected_size=2,
        seed=7,
        sample_dir=tmp_path / "samples",
    )

    assert report["valid"] is True
    assert report["all_overlap_count"] == 0
    assert report["all_missing_from_source_count"] == 0
    assert report["all_duplicate_count"] == 0
    assert report["all_metadata_mismatch_count"] == 0
    assert report["datasets"]["toy"]["selected_ids"] == ["q1", "q3"]
    assert report["datasets"]["toy"]["sample_sha256"]
    assert report["datasets"]["toy"]["source_sha256"]


def test_existing_sample_audit_rejects_unknown_duplicate_and_excluded_ids(tmp_path):
    spec = DatasetSpec("toy", "train.jsonl", "evaluation.jsonl", "f1", lambda record: record["group"])
    source_records = [_record("q1"), _record("q2")]
    _write_jsonl(tmp_path / "benchmark" / "train.jsonl", source_records)
    bad = adapt_record(spec, _record("missing"), 0, split="evaluation")
    normalize_jsonl([bad, bad], tmp_path / "samples" / "toy.jsonl")
    normalize_jsonl([bad], tmp_path / "excluded" / "prior" / "toy.jsonl")

    report = audit_existing_samples(
        benchmark_root=tmp_path / "benchmark",
        dataset_specs={"toy": spec},
        datasets=["toy"],
        split="train",
        expected_size=2,
        seed=7,
        sample_dir=tmp_path / "samples",
        excluded_sample_dirs=[tmp_path / "excluded"],
    )

    assert report["valid"] is False
    assert report["all_overlap_count"] == 1
    assert report["all_missing_from_source_count"] == 1
    assert report["all_duplicate_count"] == 1
    assert report["all_metadata_mismatch_count"] == 1
    assert report["datasets"]["toy"]["overlap_ids"] == ["missing"]
