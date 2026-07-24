"""Publication-readiness gate for benchmark runs.

The gate is deliberately stricter than the reporting code.  A run may be
useful for internal diagnostics while still being ineligible for a claim
against published baselines.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .adapted_protocol import validate_adapter_audit
from .record_audit import audit_run_records


_BASELINE_METHODS = {"hybrid", "ircot", "planrag", "react", "srag", "graphrag"}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _sample_count(output_dir: Path, stage: str, dataset: str, fallback: int) -> int:
    path = output_dir / "samples" / stage / f"{dataset}.jsonl"
    if not path.is_file():
        return fallback
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _expected_cells(
    output_dir: Path,
    stage: str,
    manifest: dict[str, Any],
    matrix: dict[str, Any] | None,
) -> tuple[dict[tuple[str, str], int], list[str]]:
    stage_config = ((manifest.get("suite") or {}).get("stages") or {}).get(stage) or {}
    fallback = int(stage_config.get("sample_size", 0) or 0)
    jobs = matrix.get("jobs") if isinstance(matrix, dict) else None
    if not isinstance(jobs, list):
        requests = [item for item in manifest.get("run_requests", []) if item.get("stage") == stage]
        jobs = [
            {"dataset": dataset, "method": method}
            for request in requests
            for dataset in request.get("datasets", [])
            for method in request.get("methods", [])
        ]
    cells: dict[tuple[str, str], int] = {}
    errors: list[str] = []
    random_seed_count = len((manifest.get("suite") or {}).get("random_seeds", [])) or 1
    for job in jobs:
        if not isinstance(job, dict):
            errors.append("matrix job is not an object")
            continue
        dataset = str(job.get("dataset") or "")
        method = str(job.get("method") or "")
        if not dataset or not method:
            errors.append("matrix job is missing dataset or method")
            continue
        expected = _sample_count(output_dir, stage, dataset, fallback)
        if method == "slotrag-random":
            expected *= random_seed_count
        key = (dataset, method)
        if key in cells:
            errors.append(f"duplicate matrix cell: {dataset}/{method}")
        cells[key] = expected
    return cells, errors


def _observed_cells(output_dir: Path, stage: str) -> tuple[Counter[tuple[str, str]], Counter[tuple[str, str]]]:
    root = output_dir / "items" / stage
    final: Counter[tuple[str, str]] = Counter()
    status: Counter[tuple[str, str]] = Counter()
    if not root.exists():
        return final, status
    for path in sorted(root.rglob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        dataset = str(record.get("dataset") or path.relative_to(root).parts[0])
        method = str(record.get("method_label") or record.get("method") or path.relative_to(root).parts[1])
        key = (dataset, method)
        final[key] += 1
        status[(dataset, method)] += int(record.get("result", {}).get("status") == "ok")
    return final, status


def audit_publication_readiness(
    output_dir: Path,
    stage: str,
    *,
    require_trace: bool = True,
    allow_diagnostic_adapters: bool = False,
    allow_adapted_protocol: bool = False,
) -> dict[str, Any]:
    """Return a machine-readable publication and diagnostic readiness report."""
    manifest = _read_json(output_dir / "manifest.json") or {}
    matrix = _read_json(output_dir / "matrix-manifest.json")
    adapter_audit = _read_json(output_dir / "adapter-audit.json")
    sample_audit = _read_json(output_dir / "sample-audit.json")
    record_audit = audit_run_records(output_dir, stage, require_trace=require_trace)
    expected_cells, matrix_errors = _expected_cells(output_dir, stage, manifest, matrix)
    observed_cells, ok_cells = _observed_cells(output_dir, stage)

    reasons: list[str] = []
    if not manifest:
        reasons.append("missing_or_invalid_manifest")
    if matrix is None:
        reasons.append("missing_or_invalid_matrix_manifest")
    if not record_audit["complete"]:
        reasons.append("record_audit_incomplete")
    if "smoke" in stage.casefold():
        reasons.append("smoke_stage_not_for_publication")
    if "ablation" in stage.casefold():
        if sample_audit is None:
            reasons.append("missing_or_invalid_sample_audit")
        elif int(sample_audit.get("all_overlap_count", -1)) != 0:
            reasons.append("ablation_sample_overlap")
    reasons.extend(matrix_errors)

    cell_report: list[dict[str, Any]] = []
    for key, expected in sorted(expected_cells.items()):
        observed = observed_cells.get(key, 0)
        ok = ok_cells.get(key, 0)
        cell_report.append({
            "dataset": key[0],
            "method": key[1],
            "expected": expected,
            "observed": observed,
            "ok": ok,
            "complete": observed == expected,
        })
        if observed != expected:
            reasons.append(f"cell_count_mismatch:{key[0]}/{key[1]}:{observed}!={expected}")
    extra_cells = sorted(set(observed_cells) - set(expected_cells))
    if extra_cells:
        reasons.append("unexpected_observed_cells:" + ",".join(f"{dataset}/{method}" for dataset, method in extra_cells))

    methods = {method for _, method in expected_cells}
    baseline_methods = sorted(method for method in methods if method.split("@", 1)[0] in _BASELINE_METHODS)
    validity = manifest.get("comparison_validity") or {}
    exact_upstream = bool(validity.get("exact_upstream_execution_verified"))
    adapted_errors: list[str] = []
    adapted_valid = False
    if baseline_methods and not exact_upstream:
        if allow_adapted_protocol:
            adapted_errors = validate_adapter_audit(adapter_audit, baseline_methods)
            adapted_valid = not adapted_errors
            if not adapted_valid:
                reasons.extend(f"adapted_protocol_invalid:{error}" for error in adapted_errors)
        else:
            reasons.append("upstream_baseline_execution_not_verified")

    analysis_blockers = {
        "record_audit_incomplete",
        "missing_or_invalid_manifest",
        "missing_or_invalid_matrix_manifest",
    }
    analysis_ready = not [reason for reason in reasons if reason in analysis_blockers or reason.startswith(("cell_count_mismatch:", "unexpected_observed_cells:", "duplicate matrix cell:"))]
    publication_ready = analysis_ready and "smoke_stage_not_for_publication" not in reasons and (
        exact_upstream or not baseline_methods or (allow_adapted_protocol and adapted_valid)
    )
    if analysis_ready and not publication_ready and (allow_diagnostic_adapters or "smoke" in stage.casefold()):
        status = "diagnostic_complete"
    elif publication_ready:
        status = "publication_ready_adapted_protocol" if adapted_valid else "publication_ready"
    else:
        status = "blocked"
    return {
        "schema_version": 1,
        "stage": stage,
        "output_dir": str(output_dir),
        "status": status,
        "analysis_ready": analysis_ready,
        "publication_ready": publication_ready,
        "publication_claim_allowed": publication_ready,
        "allow_diagnostic_adapters": allow_diagnostic_adapters,
        "allow_adapted_protocol": allow_adapted_protocol,
        "require_trace": require_trace,
        "record_audit": record_audit,
        "baseline_execution": {
            "methods": baseline_methods,
            "exact_upstream_execution_verified": exact_upstream,
            "comparison_validity": validity,
            "adapted_protocol_valid": adapted_valid,
            "adapted_protocol_errors": adapted_errors,
        },
        "adapter_audit": adapter_audit,
        "sample_audit": sample_audit,
        "publication_scope": "adapted_protocol_only" if adapted_valid else ("exact_upstream" if exact_upstream else None),
        "cells": cell_report,
        "extra_observed_cells": [{"dataset": dataset, "method": method} for dataset, method in extra_cells],
        "blocking_reasons": sorted(set(reasons)),
    }
