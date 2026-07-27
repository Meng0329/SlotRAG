#!/usr/bin/env python3
"""Select and disjointly validate bounded top-k policies on development traces."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from slotrag.benchmarking.action_headroom import analyze_action_headroom
from slotrag.benchmarking.development import analyze_development_run
from slotrag.sufficiency import load_calibration_artifact


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_json_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_runs(specs: Sequence[Sequence[str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    examples: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for run_value, stage in specs:
        run_dir = Path(run_value)
        manifest = run_dir / "manifest.json"
        if not manifest.exists():
            raise FileNotFoundError(f"missing immutable run manifest: {manifest}")
        report = analyze_development_run(run_dir, stage=stage)
        examples.extend(report["examples"])
        sources.append({
            "run_dir": str(run_dir),
            "stage": stage,
            "manifest": str(manifest),
            "manifest_sha256": _sha256(manifest),
            "development_schema_version": report["schema_version"],
            "record_count": report["record_count"],
            "example_count": report["example_count"],
            "oracle_headroom": report["oracle_headroom"],
            "missing_source_count": report["missing_source_count"],
        })
    return examples, sources


def _without_examples(report: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in report.items() if key != "examples"}


def _write_json(path: Path, payload: object) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _policy_table(report: dict[str, Any]) -> list[str]:
    lines = [
        "| Policy | Expansions | TP/FP/FN | Precision | Recall | Mean calls | Proxy net utility |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, metrics in report["policies"].items():
        confusion = metrics["confusion"]
        lines.append(
            f"| {name} | {metrics['predicted_expansions']} | "
            f"{confusion['true_positive']}/{confusion['false_positive']}/{confusion['false_negative']} | "
            f"{metrics['precision']:.4f} | {metrics['recall']:.4f} | "
            f"{metrics['mean_retrieval_calls']:.4f} | {metrics['proxy_net_utility']:.6f} |"
        )
    return lines


def _report_markdown(
    development: dict[str, Any],
    validation: dict[str, Any],
    *,
    overlap_count: int,
) -> str:
    selected = development["selected_policy"]
    sufficient_dev = (
        development["strata"]["by_status"].get("SUFFICIENT", {})
        .get("recoverable_positive_count", 0)
    )
    sufficient_validation = (
        validation["strata"]["by_status"].get("SUFFICIENT", {})
        .get("recoverable_positive_count", 0)
    )
    lines = [
        "# v70 Bounded Top-k Action Headroom",
        "",
        "This is provider-free train/development analysis. Candidate-pool recovery is an optimistic",
        "retrieval upper bound and is not answer-quality evidence.",
        "",
        f"Frozen selected policy: `{selected}`. Development/validation question overlap: `{overlap_count}`.",
        f"Recoverable positives in SUFFICIENT states: development `{sufficient_dev}`, validation `{sufficient_validation}`.",
        "",
        "## Development selection",
        "",
        f"Examples/questions/positives: {development['example_count']}/{development['question_count']}/"
        f"{development['recoverable_positive_count']}.",
        "",
        *_policy_table(development),
        "",
        "## Disjoint validation",
        "",
        f"Examples/questions/positives: {validation['example_count']}/{validation['question_count']}/"
        f"{validation['recoverable_positive_count']}.",
        "",
        *_policy_table(validation),
        "",
        "## Interpretation boundary",
        "",
        "A true positive means unselected gold evidence existed in the recorded candidate pool. It does not",
        "guarantee extraction, join, generation, or final-answer improvement. Validation results were not used",
        "to change the frozen policy or call penalty.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--development-run",
        nargs=2,
        action="append",
        metavar=("RUN_DIR", "STAGE"),
        required=True,
    )
    parser.add_argument(
        "--validation-run",
        nargs=2,
        action="append",
        metavar=("RUN_DIR", "STAGE"),
        required=True,
    )
    parser.add_argument("--calibrator", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--retrieval-call-penalty", type=float, default=0.08)
    args = parser.parse_args()

    if args.output_dir.exists():
        raise FileExistsError(f"immutable output directory already exists: {args.output_dir}")
    development_examples, development_sources = _load_runs(args.development_run)
    validation_examples, validation_sources = _load_runs(args.validation_run)
    artifact, artifact_sha256 = load_calibration_artifact(args.calibrator)

    development = analyze_action_headroom(
        development_examples,
        calibration_artifact=artifact,
        role="development_selection",
        retrieval_call_penalty=args.retrieval_call_penalty,
    )
    selected_policy = str(development["selected_policy"])
    development_keys = {
        (str(row.get("dataset") or ""), str(row.get("question_id") or ""))
        for row in development_examples
    }
    validation_keys = {
        (str(row.get("dataset") or ""), str(row.get("question_id") or ""))
        for row in validation_examples
    }
    overlap = sorted(development_keys & validation_keys)
    if overlap:
        preview = ", ".join(f"{dataset}/{question}" for dataset, question in overlap[:10])
        raise ValueError(f"development and validation questions overlap: {preview}")
    validation = analyze_action_headroom(
        validation_examples,
        calibration_artifact=artifact,
        role="disjoint_validation",
        selected_policy=selected_policy,
        retrieval_call_penalty=args.retrieval_call_penalty,
    )

    created_at = datetime.now(timezone.utc).isoformat()
    selection = {
        "schema_version": 1,
        "created_at": created_at,
        "source_split": "train",
        "selected_policy": selected_policy,
        "selection_metric": "candidate-pool proxy net utility",
        "selection_tiebreak": [
            "proxy_net_utility",
            "precision",
            "recall",
            "lower_mean_retrieval_calls",
            "predeclared_policy_order",
        ],
        "retrieval_call_penalty": args.retrieval_call_penalty,
        "validation_used_for_selection": False,
        "oracle_excluded_from_selection": True,
        "development_policy_ranking": development["policy_ranking"],
        "development_selected_metrics": development["policies"][selected_policy],
        "development_question_fingerprint_sha256": _canonical_json_sha256(
            sorted(development_keys)
        ),
    }
    manifest = {
        "schema_version": 1,
        "created_at": created_at,
        "analysis": "bounded-topk-candidate-pool-headroom",
        "provider_calls": 0,
        "command": " ".join(sys.argv),
        "calibrator": str(args.calibrator),
        "calibrator_sha256": artifact_sha256,
        "retrieval_call_penalty": args.retrieval_call_penalty,
        "development_sources": development_sources,
        "validation_sources": validation_sources,
        "development_validation_overlap_count": len(overlap),
        "development_question_fingerprint_sha256": _canonical_json_sha256(
            sorted(development_keys)
        ),
        "validation_question_fingerprint_sha256": _canonical_json_sha256(
            sorted(validation_keys)
        ),
        "selected_policy": selected_policy,
        "candidate_pool_is_counterfactual_proxy": True,
    }

    args.output_dir.mkdir(parents=True, exist_ok=False)
    _write_json(args.output_dir / "manifest.json", manifest)
    _write_json(args.output_dir / "policy-selection.json", selection)
    _write_json(args.output_dir / "development-action-headroom.json", _without_examples(development))
    _write_json(args.output_dir / "validation-action-headroom.json", _without_examples(validation))
    _write_jsonl(args.output_dir / "development-action-examples.jsonl", development["examples"])
    _write_jsonl(args.output_dir / "validation-action-examples.jsonl", validation["examples"])
    with (args.output_dir / "REPORT.md").open("x", encoding="utf-8") as handle:
        handle.write(_report_markdown(development, validation, overlap_count=len(overlap)))

    print(json.dumps({
        "output_dir": str(args.output_dir),
        "selected_policy": selected_policy,
        "development_examples": development["example_count"],
        "validation_examples": validation["example_count"],
        "development_recoverable": development["recoverable_positive_count"],
        "validation_recoverable": validation["recoverable_positive_count"],
        "overlap_count": len(overlap),
        "provider_calls": 0,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
