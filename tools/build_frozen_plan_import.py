#!/usr/bin/env python3
"""Build validated frozen-plan imports from an existing SlotRAG run.

The source run must contain successful SlotRAG final records and the exact
sample JSONL used for that stage. The generated snapshots are suitable for a
compiler-compatible SlotRAG stage with ``frozen_plan_import_dir``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from slotrag.data import load_questions
from slotrag.models import RunMetrics, SlotPlan
from slotrag.benchmarking.methods import METHODS, slotrag_compile_options


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_id(value: str) -> str:
    prefix = "".join(char if char.isalnum() or char in "-_" else "_" for char in value)[:80]
    digest = hashlib.sha256(value.encode()).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _source_records(source_dir: Path, stage: str, dataset: str, method: str) -> dict[str, dict[str, Any]]:
    root = source_dir / "items" / stage / dataset / method
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("method") != method or record.get("dataset") != dataset:
            continue
        if not record.get("result", {}).get("plan"):
            continue
        question_id = str(record.get("question_id", ""))
        if question_id:
            records[question_id] = record
    return records


def _compiler_metrics(record: dict[str, Any]) -> dict[str, Any]:
    metrics = record.get("result", {}).get("metrics", {})
    return RunMetrics(
        compilation_llm_calls=int(metrics.get("compilation_llm_calls", 0)),
        compilation_prompt_tokens=int(metrics.get("compilation_prompt_tokens", 0)),
        compilation_completion_tokens=int(metrics.get("compilation_completion_tokens", 0)),
        compilation_latency_ms=float(metrics.get("compilation_latency_ms", 0.0)),
        plan_slot_count=int(metrics.get("plan_slot_count", 0)),
        plan_join_count=int(metrics.get("plan_join_count", 0)),
        plan_variable_count=int(metrics.get("plan_variable_count", 0)),
        plan_output_count=int(metrics.get("plan_output_count", 0)),
        plan_operator_count=int(metrics.get("plan_operator_count", 0)),
        plan_complexity=int(metrics.get("plan_complexity", 0)),
        structured_output_failures=int(metrics.get("structured_output_failures", 0)),
        structured_output_repairs=int(metrics.get("structured_output_repairs", 0)),
        plan_fallbacks=int(metrics.get("plan_fallbacks", 0)),
        heuristic_plans=int(metrics.get("heuristic_plans", 0)),
        typed_plan_templates=int(metrics.get("typed_plan_templates", 0)),
        field_extremum_templates=int(metrics.get("field_extremum_templates", 0)),
        polar_comparison_templates=int(metrics.get("polar_comparison_templates", 0)),
        direct_plan_templates=int(metrics.get("direct_plan_templates", 0)),
    ).model_dump(mode="json")


def build_import(
    source_dir: Path,
    source_stage: str,
    source_samples: Path,
    source_method: str,
    output_dir: Path,
) -> dict[str, Any]:
    if source_method not in METHODS or METHODS[source_method].family != "slotrag":
        raise ValueError(f"source method must be a SlotRAG-family method: {source_method}")
    output_dir.mkdir(parents=True, exist_ok=True)
    datasets = sorted(path.stem for path in source_samples.glob("*.jsonl"))
    summary: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_run": str(source_dir),
        "source_stage": source_stage,
        "source_method": source_method,
        "output_dir": str(output_dir),
        "datasets": {},
    }
    for dataset in datasets:
        questions = {question.id: question for question in load_questions(source_samples / f"{dataset}.jsonl")}
        records = _source_records(source_dir, source_stage, dataset, source_method)
        dataset_dir = output_dir / dataset
        dataset_dir.mkdir(parents=True, exist_ok=True)
        written = 0
        missing: list[str] = []
        for question_id, question in sorted(questions.items()):
            record = records.get(question_id)
            if record is None:
                missing.append(question_id)
                continue
            plan = SlotPlan.model_validate(record["result"]["plan"])
            compiler_options = slotrag_compile_options(METHODS[source_method], dataset, question)
            compile_input = {
                "stage": source_stage,
                "dataset": dataset,
                "question_id": question_id,
                "question": question.question,
                "source_method": source_method,
                "compiler_options": compiler_options,
            }
            snapshot = {
                "schema_version": 1,
                "stage": source_stage,
                "dataset": dataset,
                "question_id": question_id,
                "source_method": source_method,
                "input_sha256": _canonical_sha256(compile_input),
                "compiler_options": compiler_options,
                "attempt_index": int(record.get("attempt_index", 1)),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "wall_latency_ms": float(record.get("result", {}).get("metrics", {}).get("compilation_latency_ms", 0.0)),
                "provider_delta": record.get("provider_delta", {}),
                "preparation_mode": "imported_from_final_record",
                "source_result_status": record.get("result", {}).get("status"),
                "source_result_error": record.get("result", {}).get("error"),
                "status": "ok",
                "error": None,
                "failure_category": "ok",
                "plan_sha256": _canonical_sha256(plan.model_dump(mode="json")),
                "plan": plan.model_dump(mode="json"),
                "compiler_metrics": _compiler_metrics(record),
            }
            (dataset_dir / f"{_safe_id(question_id)}.json").write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            written += 1
        summary["datasets"][dataset] = {
            "question_count": len(questions),
            "source_record_count": len(records),
            "written": written,
            "missing": missing,
        }
    (output_dir / "import-audit.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-output-dir", type=Path, required=True)
    parser.add_argument("--source-stage", required=True)
    parser.add_argument("--source-samples", type=Path, required=True)
    parser.add_argument("--source-method", default="slotrag")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = build_import(
        args.source_output_dir,
        args.source_stage,
        args.source_samples,
        args.source_method,
        args.output_dir,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all(not value["missing"] for value in summary["datasets"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
