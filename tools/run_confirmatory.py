#!/usr/bin/env python3
"""
run_confirmatory.py — Execute H-STRUCT-1 confirmatory static-vs-chain test

Phase 12-13: Natural-prevalence execution
- Eligible questions: both arms (static + chain)
- Non-eligible questions: static arm only
- All results scored with EM/F1

Usage:
    python tools/run_confirmatory.py --config configs/default.yaml --manifest research/hstruct_validation_census/confirmatory_manifest.jsonl

Requires:
    - confirmatory_manifest.jsonl (validation + train supplement, all eligible + non-eligible)
    - GO gates all PASS
    - Services running (Agnes/qwen3.5-9b generation, Qwen3-Embedding-0.6B, bge-reranker-v2-m3)
"""

import argparse
import json
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---- Repo setup ----
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from slotrag.config import AppConfig
from slotrag.benchmarking.methods import METHODS, MethodSpec
from slotrag.benchmarking.runner import BenchmarkRunner


# ---- Constants ----
SEED = 2027
BUDGET = {
    "max_steps": 8,
    "max_llm_calls": 96,
    "max_retrieval_calls": 8,
}


def load_manifest(manifest_path: Path):
    """Load confirmatory manifest (validation + train supplement)."""
    items = []
    with open(manifest_path, "r") as f:
        for line in f:
            items.append(json.loads(line.strip()))
    return items


def run_one_arm(app_config, dataset, question_id, arm, method_name, seed, output_dir):
    """Execute one arm for one question. Returns result dict."""
    spec = METHODS[method_name]

    runner = BenchmarkRunner(
        app_config=app_config,
        output_dir=output_dir,
        seed=seed,
    )

    result = runner.run_single(
        dataset=dataset,
        question_id=question_id,
        method=method_name,
        arm=arm,
        budget=BUDGET,
    )
    return result


def main():
    parser = argparse.ArgumentParser(description="Run H-STRUCT-1 confirmatory test")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--manifest", required=True, help="Path to confirmatory_manifest.jsonl")
    parser.add_argument("--output-dir", default=None, help="Output directory")
    parser.add_argument("--parallel", type=int, default=4, help="Parallel questions")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    args = parser.parse_args()

    # Load config
    app_config = AppConfig.from_yaml(REPO / args.config)

    # Load manifest
    manifest = load_manifest(Path(args.manifest))
    print(f"Loaded {len(manifest)} questions from manifest")

    # Separate eligible vs non-eligible
    eligible = [q for q in manifest if q.get("eligible", False)]
    non_eligible = [q for q in manifest if not q.get("eligible", False)]
    print(f"Eligible: {len(eligible)} (both arms)")
    print(f"Non-eligible: {len(non_eligible)} (static arm only)")

    # Summary
    print(f"\nExecution plan:")
    print(f"  Eligible × static arm: {len(eligible)}")
    print(f"  Eligible × chain arm: {len(eligible)}")
    print(f"  Non-eligible × static arm: {len(non_eligible)}")
    print(f"  Total executions: {len(eligible) * 2 + len(non_eligible)}")
    print(f"  Parallel: {args.parallel}")
    print(f"  Seed: {args.seed}")

    if args.dry_run:
        print("\n[DRY RUN] Would execute as above.")
        return

    # TODO: Implement actual execution using BenchmarkRunner
    # This is the skeleton — actual implementation depends on runner.py API
    print("\n[NOT IMPLEMENTED] Actual execution not yet implemented.")
    print("This script defines the execution plan. Implementation depends on")
    print("BenchmarkRunner.run_single() API and confirmed manifest format.")


if __name__ == "__main__":
    main()
