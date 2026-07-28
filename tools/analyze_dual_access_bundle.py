#!/usr/bin/env python3
"""Audit a frozen two-path evidence bundle from immutable query-headroom traces."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


ACCESS_PATHS = ("slot", "question_plus_lexical_slot")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values))


def _mean(values: Sequence[int | float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def _summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    gains = sum(float(row["delta_recall"]) > 1e-12 for row in rows)
    losses = sum(float(row["delta_recall"]) < -1e-12 for row in rows)
    return {
        "question_count": len(rows),
        "baseline_mean_recall": _mean([float(row["baseline_recall"]) for row in rows]),
        "bundle_mean_recall": _mean([float(row["bundle_recall"]) for row in rows]),
        "absolute_recall_gain": _mean([float(row["delta_recall"]) for row in rows]),
        "relative_recall_gain": (
            _mean([float(row["delta_recall"]) for row in rows])
            / _mean([float(row["baseline_recall"]) for row in rows])
            if rows and _mean([float(row["baseline_recall"]) for row in rows])
            else 0.0
        ),
        "baseline_full_support_rate": _mean(
            [float(row["baseline_recall"] == 1.0) for row in rows]
        ),
        "bundle_full_support_rate": _mean(
            [float(row["bundle_recall"] == 1.0) for row in rows]
        ),
        "bundle_any_support_rate": _mean(
            [float(row["bundle_recall"] > 0.0) for row in rows]
        ),
        "gain_tie_loss": {
            "gain": gains,
            "tie": len(rows) - gains - losses,
            "loss": losses,
        },
    }


def analyze_records(
    materializations: Sequence[dict[str, Any]],
    question_strategy_records: Sequence[dict[str, Any]],
    *,
    per_path_top_k: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Compute question-level coverage without using answers or validation selection."""

    if per_path_top_k < 1:
        raise ValueError("per_path_top_k must be positive")
    materialization_rows: list[dict[str, Any]] = []
    retrieved_by_question: dict[tuple[str, str], set[str]] = defaultdict(set)
    materializations_by_question: dict[tuple[str, str], int] = defaultdict(int)
    for row in materializations:
        strategies = row.get("strategies") or {}
        missing = [name for name in ACCESS_PATHS if name not in strategies]
        if missing:
            raise ValueError(
                f"materialization {row.get('materialization_id')} lacks access paths: {missing}"
            )
        slot_ids = _unique(strategies[ACCESS_PATHS[0]].get("source_ids") or [])[
            :per_path_top_k
        ]
        question_ids = _unique(strategies[ACCESS_PATHS[1]].get("source_ids") or [])[
            :per_path_top_k
        ]
        union_ids = _unique([*slot_ids, *question_ids])
        overlap_ids = sorted(set(slot_ids).intersection(question_ids))
        key = (str(row["dataset"]), str(row["question_id"]))
        retrieved_by_question[key].update(union_ids)
        materializations_by_question[key] += 1
        materialization_rows.append({
            "materialization_id": str(row["materialization_id"]),
            "dataset": key[0],
            "question_id": key[1],
            "slot_id": str(row.get("slot_id") or ""),
            "access_paths": list(ACCESS_PATHS),
            "per_path_top_k": per_path_top_k,
            "slot_source_ids": slot_ids,
            "question_plus_lexical_slot_source_ids": question_ids,
            "union_source_ids": union_ids,
            "candidate_union_size": len(union_ids),
            "candidate_overlap_size": len(overlap_ids),
            "candidate_overlap_source_ids": overlap_ids,
            "logical_retrieval_calls": 2,
            "physical_sparse_batches": 1,
        })

    baselines = {
        (str(row["dataset"]), str(row["question_id"])): row
        for row in question_strategy_records
        if row.get("strategy") == "slot"
    }
    if not baselines:
        raise ValueError("question strategy records contain no slot baseline")
    if set(retrieved_by_question) != set(baselines):
        missing = sorted(set(baselines) - set(retrieved_by_question))
        extra = sorted(set(retrieved_by_question) - set(baselines))
        raise ValueError(f"question coverage mismatch; missing={missing[:3]}, extra={extra[:3]}")

    question_rows: list[dict[str, Any]] = []
    for key, baseline in sorted(baselines.items()):
        gold_ids = {str(value) for value in baseline.get("gold_ids") or []}
        if not gold_ids:
            raise ValueError(f"question {key} has no gold evidence")
        hits = gold_ids.intersection(retrieved_by_question[key])
        bundle_recall = len(hits) / len(gold_ids)
        baseline_recall = float(baseline["recall"])
        question_rows.append({
            "dataset": key[0],
            "question_id": key[1],
            "gold_ids": sorted(gold_ids),
            "bundle_retrieved_gold_ids": sorted(hits),
            "baseline_recall": baseline_recall,
            "bundle_recall": bundle_recall,
            "delta_recall": bundle_recall - baseline_recall,
            "full_support": bundle_recall == 1.0,
            "any_support": bundle_recall > 0.0,
            "materialization_count": materializations_by_question[key],
            "extra_logical_calls": materializations_by_question[key],
        })

    by_dataset: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in question_rows:
        by_dataset[str(row["dataset"])].append(row)
    report = {
        "protocol": "topk_slot_union_topk_question_plus_lexical_slot",
        "access_paths": list(ACCESS_PATHS),
        "per_path_top_k": per_path_top_k,
        "maximum_candidate_pool": 2 * per_path_top_k,
        "materialization_count": len(materialization_rows),
        "mean_candidate_union_size": _mean(
            [int(row["candidate_union_size"]) for row in materialization_rows]
        ),
        "mean_candidate_overlap_size": _mean(
            [int(row["candidate_overlap_size"]) for row in materialization_rows]
        ),
        "mean_extra_logical_calls_per_question": _mean(
            [int(row["extra_logical_calls"]) for row in question_rows]
        ),
        "logical_calls_per_materialization": 2,
        "physical_sparse_batches_per_materialization": 1,
        "overall": _summarize(question_rows),
        "by_dataset": {
            dataset: _summarize(rows) for dataset, rows in sorted(by_dataset.items())
        },
    }
    return materialization_rows, question_rows, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headroom-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--role", choices=("development_selection", "disjoint_validation"), required=True
    )
    parser.add_argument("--per-path-top-k", type=int, default=5)
    parser.add_argument("--frozen-spec", type=Path)
    args = parser.parse_args()

    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(f"immutable output directory is not empty: {args.output_dir}")
    if args.role == "disjoint_validation" and args.frozen_spec is None:
        raise ValueError("disjoint_validation requires --frozen-spec")
    source_manifest = _read_json(args.headroom_dir / "manifest.json")
    expected_source_role = args.role
    if source_manifest.get("role") != expected_source_role:
        raise ValueError(
            f"source role mismatch: expected {expected_source_role}, "
            f"got {source_manifest.get('role')}"
        )

    frozen_spec_sha256 = None
    if args.frozen_spec is not None:
        frozen_spec = _read_json(args.frozen_spec)
        frozen_spec_sha256 = _sha256(args.frozen_spec)
        if tuple(frozen_spec.get("access_paths") or ()) != ACCESS_PATHS:
            raise ValueError("frozen access paths do not match the registered dual bundle")
        frozen_top_k = int(frozen_spec.get("per_path_top_k") or 0)
        if args.per_path_top_k != frozen_top_k:
            raise ValueError(
                f"validation top-k {args.per_path_top_k} differs from frozen top-k {frozen_top_k}"
            )

    materializations = _read_jsonl(args.headroom_dir / "materialization-strategies.jsonl")
    question_strategies = _read_jsonl(
        args.headroom_dir / "question-strategy-records.jsonl"
    )
    materialization_rows, question_rows, report = analyze_records(
        materializations,
        question_strategies,
        per_path_top_k=args.per_path_top_k,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(args.output_dir / "materialization-records.jsonl", materialization_rows)
    _write_jsonl(args.output_dir / "question-records.jsonl", question_rows)
    _write_json(args.output_dir / "report.json", report)
    spec = {
        "schema_version": 1,
        "access_path_policy": "dual_bundle",
        "access_paths": list(ACCESS_PATHS),
        "per_path_top_k": args.per_path_top_k,
        "maximum_candidate_pool": 2 * args.per_path_top_k,
        "candidate_selection": "deduplicated_union",
        "validation_used_for_selection": False,
    }
    _write_json(args.output_dir / "bundle-spec.json", spec)
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "role": args.role,
        "provider_calls": 0,
        "source_headroom_dir": str(args.headroom_dir),
        "source_manifest_sha256": _sha256(args.headroom_dir / "manifest.json"),
        "frozen_spec_sha256": frozen_spec_sha256,
        "question_count": len(question_rows),
        "materialization_count": len(materialization_rows),
        "artifacts": {},
    }
    for name in (
        "materialization-records.jsonl",
        "question-records.jsonl",
        "report.json",
        "bundle-spec.json",
    ):
        manifest["artifacts"][name] = _sha256(args.output_dir / name)
    _write_json(args.output_dir / "manifest.json", manifest)
    print(json.dumps({
        "output_dir": str(args.output_dir),
        "role": args.role,
        "provider_calls": 0,
        "report": report,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
