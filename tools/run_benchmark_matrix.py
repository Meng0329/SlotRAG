#!/usr/bin/env python3
"""Run independent benchmark cells with a bounded process fan-out.

Each child keeps the existing per-question atomic persistence and provider
instrumentation. The matrix process only schedules disjoint dataset/method
cells, so high generation concurrency does not corrupt per-question deltas.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from slotrag.benchmarking.config import BenchmarkSuite
from slotrag.benchmarking.baselines import audit_baselines


def _safe_label(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in value)


def _run_cell(
    stage: str,
    suite: Path,
    output_dir: Path,
    dataset: str,
    method: str,
    log_dir: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    label = f"{_safe_label(dataset)}__{_safe_label(method)}"
    log_path = log_dir / f"{label}.log"
    command = [
        sys.executable,
        "-m",
        "slotrag.cli",
        "benchmark",
        "run",
        stage,
        "--suite",
        str(suite),
        "--output-dir",
        str(output_dir),
        "--dataset",
        dataset,
        "--method",
        method,
    ]
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(command, cwd=Path.cwd(), env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
    return {"dataset": dataset, "method": method, "returncode": completed.returncode, "log": str(log_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage")
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=64)
    parser.add_argument("--dataset", action="append", dest="datasets", help="Restrict to one or more configured datasets")
    parser.add_argument("--method", action="append", dest="methods", help="Restrict to one or more methods in the stage")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    suite = BenchmarkSuite.from_yaml(args.suite)
    stage = suite.stage(args.stage)
    datasets = args.datasets or suite.datasets
    methods = args.methods or stage.methods
    unknown_datasets = sorted(set(datasets) - set(suite.datasets))
    unknown_methods = sorted(set(methods) - set(stage.methods))
    if unknown_datasets:
        parser.error(f"datasets are not configured: {', '.join(unknown_datasets)}")
    if unknown_methods:
        parser.error(f"methods are not configured for {args.stage}: {', '.join(unknown_methods)}")
    jobs = [(dataset, method) for dataset in datasets for method in methods]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    log_dir = args.output_dir / "logs" / args.stage
    log_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    results: list[dict[str, Any]] = []
    safe_env = {
        key: value
        for key, value in env.items()
        if (key.startswith("SLOTRAG_") or key.startswith("QWEN36_"))
        and "KEY" not in key.upper()
        and "TOKEN" not in key.upper()
        and "SECRET" not in key.upper()
    }
    matrix_manifest = {
        "schema_version": 1,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "stage": args.stage,
        "suite": str(args.suite),
        "output_dir": str(args.output_dir),
        "workers": min(args.workers, len(jobs)),
        "datasets": datasets,
        "methods": methods,
        "jobs": [{"dataset": dataset, "method": method} for dataset, method in jobs],
        "safe_environment": safe_env,
        "command": [sys.executable, *sys.argv],
    }
    (args.output_dir / "matrix-manifest.json").write_text(
        json.dumps(matrix_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "command.txt").write_text(shlex.join([sys.executable, *sys.argv]) + "\n", encoding="utf-8")
    (args.output_dir / "baseline-audit.json").write_text(
        json.dumps(audit_baselines(Path.cwd(), suite.datasets), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with ThreadPoolExecutor(max_workers=min(args.workers, len(jobs))) as executor:
        futures = {
            executor.submit(_run_cell, args.stage, args.suite, args.output_dir, dataset, method, log_dir, env): (dataset, method)
            for dataset, method in jobs
        }
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: (item["dataset"], item["method"]))
    failed = [item for item in results if item["returncode"] != 0]
    print(json.dumps({"stage": args.stage, "workers": min(args.workers, len(jobs)), "jobs": len(jobs), "failed_jobs": failed, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
