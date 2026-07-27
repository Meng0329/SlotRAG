#!/usr/bin/env python3
"""Evaluate frozen sufficiency selections on a disjoint validation trace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from slotrag.benchmarking.sufficiency_validation import (
    evaluate_frozen_sufficiency,
    write_immutable_validation_report,
)


def _bootstrap_count(value: str) -> int:
    count = int(value)
    if count < 100:
        raise argparse.ArgumentTypeError("bootstrap iterations must be at least 100")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--examples", type=Path, required=True, help="Validation examples JSONL")
    parser.add_argument(
        "--selection-artifact",
        type=Path,
        action="append",
        required=True,
        help="One frozen feature-ablation artifact per dataset; repeat the option.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-iterations", type=_bootstrap_count, default=10_000)
    parser.add_argument("--seed", type=int, default=2027)
    args = parser.parse_args()

    report = evaluate_frozen_sufficiency(
        examples_path=args.examples,
        selection_artifact_paths=args.selection_artifact,
        bootstrap_iterations=args.bootstrap_iterations,
        seed=args.seed,
    )
    write_immutable_validation_report(args.output, report)
    compact = {
        "output": str(args.output),
        "examples_sha256": report["examples_sha256"],
        "provider_calls": report["provider_calls"],
        "validation_used_for_selection": report["validation_used_for_selection"],
        "datasets": {
            dataset: {
                "selected_candidate": values["selected_candidate"],
                "comparator_candidate": values["comparator_candidate"],
                "validation_example_count": values["validation_example_count"],
                "validation_question_overlap_count": values["validation_question_overlap_count"],
                "selected_brier": values["selected_metrics"]["brier_score"],
                "comparator_brier": values["comparator_metrics"]["brier_score"],
                "paired_brier_delta": values["paired_brier_delta"],
            }
            for dataset, values in report["datasets"].items()
        },
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
