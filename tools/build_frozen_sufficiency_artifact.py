#!/usr/bin/env python3
"""Build a runner calibration artifact from fit-only selected candidates."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from slotrag.benchmarking.sufficiency_validation import (
    build_frozen_runtime_artifact,
    write_immutable_validation_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-artifact", type=Path, action="append", required=True)
    parser.add_argument("--retrieval-protocol", choices=("local_context", "global_corpus"), required=True)
    parser.add_argument("--retrieval-backend", choices=("bm25", "hybrid"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = build_frozen_runtime_artifact(
        selection_artifact_paths=args.selection_artifact,
        retrieval_protocol=args.retrieval_protocol,
        retrieval_backend=args.retrieval_backend,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    write_immutable_validation_report(args.output, report)
    print(json.dumps({
        "output": str(args.output),
        "schema_version": report["schema_version"],
        "retrieval_protocol": report["retrieval_protocol"],
        "retrieval_backend": report["retrieval_backend"],
        "training_manifest_sha256": report["training_manifest_sha256"],
        "datasets": report["example_counts"],
        "selected_candidates": {
            dataset: values["selected_candidate"]
            for dataset, values in report["reports"].items()
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
