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
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from slotrag.benchmarking.config import BenchmarkSuite


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
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    suite = BenchmarkSuite.from_yaml(args.suite)
    stage = suite.stage(args.stage)
    jobs = [(dataset, method) for dataset in suite.datasets for method in stage.methods]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    log_dir = args.output_dir / "logs" / args.stage
    log_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    results: list[dict[str, Any]] = []
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
