"""Create an immutable compact audit for a SlotRAG 2x2 runtime run."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from slotrag.benchmarking.action_runtime_analysis import analyze_runtime_records
from slotrag.benchmarking.statistics import load_records
from slotrag.benchmarking.sufficiency_validation import write_immutable_validation_report


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", default="slotrag")
    args = parser.parse_args()

    records = load_records(args.run_dir, args.stage)
    report = analyze_runtime_records(records, reference_method=args.reference)
    report.update({
        "run_dir": str(args.run_dir),
        "stage": args.stage,
        "provider_calls": 0,
        "analysis_only": True,
    })
    record_audit_path = args.run_dir / "record-audit.json"
    if record_audit_path.exists():
        record_audit = json.loads(record_audit_path.read_text(encoding="utf-8"))
        report["record_audit"] = {
            "path": str(record_audit_path),
            "sha256": _sha256(record_audit_path),
            "complete": bool(record_audit.get("complete")),
            "final_count": record_audit.get("final_count"),
            "missing_attempt_count": record_audit.get("missing_attempt_count"),
            "missing_trace_count": record_audit.get("missing_trace_count"),
        }
    write_immutable_validation_report(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
