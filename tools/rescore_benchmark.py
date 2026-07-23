#!/usr/bin/env python3
"""Re-score an existing benchmark run without making provider calls.

The source run is never edited.  The destination contains the same immutable
records and a new score payload produced by the current answer-span parser.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from slotrag.benchmarking.metrics import score_record
from slotrag.models import ExecutionResult, QuestionRecord


def _rescore_record(record: dict) -> dict:
    result = ExecutionResult.model_validate(record.get("result") or {})
    answers = record.get("answers") or []
    if not isinstance(answers, list):
        answers = [str(answers)]
    old_scores = record.get("scores") or {}
    question = QuestionRecord(
        id=str(record.get("question_id") or "unknown"),
        question="",
        answers=[str(value) for value in answers],
        metadata={"evidence_available": old_scores.get("evidence_metric_status") == "computed"},
    )
    scores = score_record(str(record.get("dataset") or ""), question, result)
    # The source item contains the authoritative retrieval/evidence audit. It
    # is not reconstructible from a compact item record, so carry those fields
    # forward unchanged while replacing answer metrics.
    for key, value in old_scores.items():
        if key.startswith("evidence_") or key in {
            "retrieved_evidence_count",
            "retrieved_document_count",
            "evidence_text_chars",
        }:
            scores[key] = value
    record["scores"] = scores
    return record


def _copy_run(source: Path, destination: Path) -> None:
    if destination.exists():
        raise SystemExit(f"destination already exists: {destination}")
    destination.mkdir(parents=True)
    for name in ("manifest.json", "dataset-audit.json", "samples", "items", "attempts", "plans", "plan_attempts"):
        source_path = source / name
        if not source_path.exists():
            continue
        target_path = destination / name
        if source_path.is_dir():
            shutil.copytree(source_path, target_path)
        else:
            shutil.copy2(source_path, target_path)


def _rescore_tree(destination: Path, stage: str) -> int:
    count = 0
    for root_name in ("items", "attempts"):
        root = destination / root_name / stage
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            path.write_text(json.dumps(_rescore_record(record), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--stage", required=True)
    args = parser.parse_args()
    if not (args.source / "items" / args.stage).exists():
        parser.error(f"source stage does not exist: {args.source / 'items' / args.stage}")
    _copy_run(args.source, args.destination)
    count = _rescore_tree(args.destination, args.stage)
    manifest_path = args.destination / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["rescore"] = {
            "source_run": str(args.source),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "answer_extraction": "final_tag_or_think_suffix_v2",
            "provider_calls": 0,
            "records_rescored": count,
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"source": str(args.source), "destination": str(args.destination), "stage": args.stage, "records_rescored": count}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
