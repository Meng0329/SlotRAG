#!/usr/bin/env python3
"""Build enriched development examples and a frozen sufficiency calibrator."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from slotrag.benchmarking.development import analyze_development_run, calibrate_development_report


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--holdout-fraction", type=float, default=0.2)
    parser.add_argument("--minimum-examples", type=int, default=20)
    args = parser.parse_args()

    manifest_path = args.run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"missing immutable run manifest: {manifest_path}")
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    report = analyze_development_run(args.run_dir, stage=args.stage)
    _write_json(args.output_dir / "development-analysis.json", {
        key: value for key, value in report.items() if key != "examples"
    })
    _write_jsonl(args.output_dir / "sufficiency-examples.jsonl", report["examples"])

    artifact, calibration = calibrate_development_report(
        report,
        training_manifest_sha256=manifest_sha256,
        created_at=datetime.now(timezone.utc).isoformat(),
        holdout_fraction=args.holdout_fraction,
        minimum_examples=args.minimum_examples,
    )
    _write_json(args.output_dir / "sufficiency-calibrator.json", artifact.model_dump(mode="json"))
    _write_json(args.output_dir / "calibration-report.json", calibration)
    print(json.dumps({
        "run_dir": str(args.run_dir),
        "stage": args.stage,
        "record_count": report["record_count"],
        "example_count": report["example_count"],
        "supervision_counts": report["supervision_counts"],
        "label_counts": report["label_counts"],
        "missing_source_count": report["missing_source_count"],
        "oracle_headroom": report["oracle_headroom"],
        "calibration_datasets": calibration["datasets"],
        "artifact": str(args.output_dir / "sufficiency-calibrator.json"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
