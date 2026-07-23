import hashlib
import json

from slotrag.benchmarking.record_audit import audit_run_records


def _write_record(root, *, trace: bool):
    item_dir = root / "items" / "test" / "hotpotqa" / "hybrid"
    attempt_dir = root / "attempts" / "test" / "hotpotqa" / "hybrid" / "q1"
    item_dir.mkdir(parents=True)
    attempt_dir.mkdir(parents=True)
    record = {"attempt_index": 1, "result": {"status": "ok"}}
    if trace:
        trace_path = root / "traces" / "test" / "hotpotqa" / "hybrid" / "q1" / "attempt-0001.jsonl"
        trace_path.parent.mkdir(parents=True)
        trace_path.write_text('{"schema_version":1}\n', encoding="utf-8")
        record["provider_trace"] = {
            "enabled": True,
            "event_count": 1,
            "path": str(trace_path.relative_to(root)),
            "sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        }
    (item_dir / "q1.json").write_text(json.dumps(record), encoding="utf-8")
    (attempt_dir / "attempt-0001.json").write_text(json.dumps(record), encoding="utf-8")
    (root / "manifest.json").write_text("{}", encoding="utf-8")
    (root / "matrix-manifest.json").write_text("{}", encoding="utf-8")
    (root / "baseline-audit.json").write_text("{}", encoding="utf-8")
    (root / "adapter-audit.json").write_text("{}", encoding="utf-8")
    (root / "command.txt").write_text("test\n", encoding="utf-8")


def test_audit_accepts_complete_trace_record(tmp_path):
    _write_record(tmp_path, trace=True)
    report = audit_run_records(tmp_path, "test", require_trace=True)
    assert report["complete"] is True
    assert report["final_count"] == 1
    assert report["missing_trace_count"] == 0


def test_audit_rejects_missing_trace_when_required(tmp_path):
    _write_record(tmp_path, trace=False)
    report = audit_run_records(tmp_path, "test", require_trace=True)
    assert report["complete"] is False
    assert report["missing_trace_count"] == 1
