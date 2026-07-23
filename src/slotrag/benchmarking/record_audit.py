"""Read-only completeness checks for an experiment run directory."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _trace_ok(output_dir: Path, info: Any) -> tuple[bool, str | None]:
    if not isinstance(info, dict) or not info.get("enabled"):
        return False, "disabled"
    relative = info.get("path")
    if not isinstance(relative, str) or not relative:
        return False, "missing_path"
    path = output_dir / relative
    if not path.is_file():
        return False, "missing_file"
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != info.get("sha256"):
        return False, "sha256_mismatch"
    event_count = sum(1 for line in data.splitlines() if line.strip())
    if event_count != info.get("event_count"):
        return False, "event_count_mismatch"
    return True, None


def audit_run_records(output_dir: Path, stage: str, *, require_trace: bool = False) -> dict[str, Any]:
    """Audit final/attempt/trace consistency without changing any files."""
    items_root = output_dir / "items" / stage
    attempts_root = output_dir / "attempts" / stage
    records = sorted(items_root.rglob("*.json")) if items_root.exists() else []
    missing_attempt_count = 0
    non_contiguous_attempt_count = 0
    missing_trace_count = 0
    trace_error_counts: dict[str, int] = {}
    final_keys: set[str] = set()
    for item_path in records:
        record = _json(item_path)
        key = str(item_path.relative_to(items_root))
        if key in final_keys:
            non_contiguous_attempt_count += 1
        final_keys.add(key)
        if record is None:
            missing_attempt_count += 1
            continue
        attempt_dir = attempts_root / item_path.parent.relative_to(items_root) / item_path.stem
        attempt_paths = sorted(attempt_dir.glob("attempt-*.json")) if attempt_dir.exists() else []
        indices = [int(path.stem.rsplit("-", 1)[-1]) for path in attempt_paths if path.stem.rsplit("-", 1)[-1].isdigit()]
        expected_index = int(record.get("attempt_index", 0) or 0)
        if not attempt_paths or expected_index not in indices or sorted(indices) != list(range(1, len(indices) + 1)):
            missing_attempt_count += 1
        if require_trace:
            ok, reason = _trace_ok(output_dir, record.get("provider_trace"))
            if not ok:
                missing_trace_count += 1
                trace_error_counts[reason or "invalid"] = trace_error_counts.get(reason or "invalid", 0) + 1
    missing_manifest = [
        name
        for name in ("manifest.json", "matrix-manifest.json", "baseline-audit.json", "adapter-audit.json", "command.txt")
        if not (output_dir / name).is_file()
    ]
    complete = bool(records) and not missing_attempt_count and not missing_trace_count and not missing_manifest
    return {
        "schema_version": 1,
        "stage": stage,
        "complete": complete,
        "require_trace": require_trace,
        "final_count": len(records),
        "missing_attempt_count": missing_attempt_count,
        "non_contiguous_attempt_count": non_contiguous_attempt_count,
        "missing_trace_count": missing_trace_count,
        "trace_error_counts": trace_error_counts,
        "missing_manifest": missing_manifest,
    }
