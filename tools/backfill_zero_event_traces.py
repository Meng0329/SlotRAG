#!/usr/bin/env python3
"""Backfill auditable empty traces for attempts with no provider events."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _attempt_count(delta: Any) -> int:
    if not isinstance(delta, dict):
        return 0
    return sum(
        int(value.get("attempts", 0) or 0)
        for name, value in delta.items()
        if name != "attempts" and isinstance(value, dict)
    )


def _trace_info(trace_path: Path, output_dir: Path) -> dict[str, Any]:
    data = trace_path.read_bytes()
    return {
        "enabled": True,
        "event_count": sum(1 for line in data.splitlines() if line.strip()),
        "path": str(trace_path.relative_to(output_dir)),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def backfill(output_dir: Path, stage: str) -> dict[str, Any]:
    items_root = output_dir / "items" / stage
    if not items_root.is_dir():
        raise SystemExit(f"missing items directory: {items_root}")

    changed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item_path in sorted(items_root.rglob("*.json")):
        record = json.loads(item_path.read_text(encoding="utf-8"))
        trace = record.get("provider_trace") or {}
        if trace.get("enabled") is True:
            continue
        result = record.get("result") or {}
        provider_delta = record.get("provider_delta")
        index_delta = record.get("index_provider_delta")
        if result.get("status") != "budget_exceeded" or _attempt_count(provider_delta) or _attempt_count(index_delta):
            skipped.append({"path": str(item_path.relative_to(output_dir)), "reason": "not_zero_event_budget_timeout"})
            continue

        relative = item_path.relative_to(items_root)
        dataset, method_label, question_file = relative.parts
        question_id = question_file.rsplit(".", 1)[0]
        attempt_index = int(record.get("attempt_index", 1) or 1)
        trace_path = (
            output_dir
            / "traces"
            / stage
            / dataset
            / method_label
            / question_id
            / f"attempt-{attempt_index:04d}.jsonl"
        )
        if trace_path.exists() and trace_path.read_bytes():
            raise SystemExit(f"refusing to overwrite non-empty trace: {trace_path}")
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.touch(exist_ok=True)
        trace_info = _trace_info(trace_path, output_dir)
        record["provider_trace"] = trace_info
        _atomic_json(item_path, record)

        attempt_path = (
            output_dir
            / "attempts"
            / stage
            / dataset
            / method_label
            / question_id
            / f"attempt-{attempt_index:04d}.json"
        )
        if not attempt_path.is_file():
            raise SystemExit(f"missing matching attempt record: {attempt_path}")
        attempt_record = json.loads(attempt_path.read_text(encoding="utf-8"))
        attempt_record["provider_trace"] = trace_info
        _atomic_json(attempt_path, attempt_record)
        changed.append({
            "item": str(item_path.relative_to(output_dir)),
            "trace": trace_info,
            "status": result.get("status"),
            "error": result.get("error"),
        })

    report = {
        "schema_version": 1,
        "stage": stage,
        "policy": "empty_trace_only_for_budget_timeout_with_zero_provider_attempts",
        "changed_count": len(changed),
        "skipped_count": len(skipped),
        "changed": changed,
        "skipped": skipped,
    }
    _atomic_json(output_dir / "zero-event-trace-backfill.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--stage", required=True)
    args = parser.parse_args()
    print(json.dumps(backfill(args.output_dir, args.stage), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
