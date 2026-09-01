#!/usr/bin/env python3
"""
draw_train_supplement.py — Draw eligible questions from untouched train pool

Phase 3-4: Proper train filtering + deterministic sequential census

Filtering sources:
1. EXPOSED_SAMPLE_REGISTRY.csv — all contamination statuses
2. Development set — all 5 questions
3. Historical run items — none found (runs/ empty)

Exclusion criteria (ANY hit = exclude):
- TRAIN_EXPOSED
- CONTAMINATED
- EXPOSED_NOT_SCORED
- EXPOSED_VIA_ABLATION*
- UNKNOWN (split unknown, conservative)
- Development set IDs

Output: UNTOUCHED_TRAIN_POOL per dataset

Usage:
    python tools/draw_train_supplement.py --config configs/default.yaml

Next step after drawing: SlotCompiler census on drawn questions (Phase 4-5).
"""

import argparse
import csv
import json
import random
import sys
from pathlib import Path
from collections import defaultdict

# ---- Repo setup ----
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from slotrag.benchmarking.datasets import DATASETS, iter_jsonl

# ---- Paths ----
EXPOSURE_REGISTRY = REPO / "research" / "EXPOSED_SAMPLE_REGISTRY.csv"
DEVELOPMENT_SET = REPO / "research" / "eval_sets" / "development_set.json"
TRAIN_SUPPLEMENT_PATH = REPO / "research" / "hstruct_confirmatory" / "train_supplement_draw.jsonl"

# ---- Targets (frozen) ----
SUPPLEMENT_TARGETS = {
    "hotpotqa": 148,
    "2wikimultihop": 559,
    "musique": 37,
}

SEED = 2027

# All contamination statuses that require exclusion
EXCLUDED_STATUSES = {
    "TRAIN_EXPOSED",
    "CONTAMINATED",
    "EXPOSED_NOT_SCORED",
    "UNKNOWN",  # split unknown, conservative
}
# Also exclude any status containing "ABLATION"
EXCLUDE_PATTERN = "ABLATION"


def load_exposed_ids():
    """Load all exposed question IDs from EXPOSED_SAMPLE_REGISTRY.csv."""
    exposed = defaultdict(set)  # dataset -> set of question_ids
    status_counts = defaultdict(lambda: defaultdict(int))

    with open(EXPOSURE_REGISTRY, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dataset = row["dataset"]
            qid = row["sample_id"]
            status = row["contamination_status"]

            # Exclude if status matches any excluded category
            if status in EXCLUDED_STATUSES or EXCLUDE_PATTERN in status:
                exposed[dataset].add(qid)
                status_counts[dataset][status] += 1

    return exposed, status_counts


def load_development_ids():
    """Load development set question IDs."""
    with open(DEVELOPMENT_SET, "r") as f:
        dev = json.load(f)

    dev_ids = defaultdict(set)
    if isinstance(dev, list):
        for q in dev:
            if isinstance(q, dict):
                ds = q.get("dataset", "unknown")
                qid = q.get("id", q.get("question_id", ""))
                if qid:
                    dev_ids[ds].add(qid)
    return dev_ids


def load_train_questions(dataset_name):
    """Load train split questions for a dataset."""
    spec = DATASETS[dataset_name]
    train_path = REPO / "benchmark" / spec.train_file
    questions = []
    for idx, rec in iter_jsonl(train_path):
        questions.append({"id": rec["id"], "question": rec.get("question", ""), "record": rec})
    return questions


def build_untouched_pool(dataset, train_questions, exposed_ids, dev_ids):
    """Build untouched train pool for a dataset."""
    exposed_for_ds = exposed_ids.get(dataset, set())
    dev_for_ds = dev_ids.get(dataset, set())

    all_excluded = exposed_for_ds | dev_for_ds

    untouched = [q for q in train_questions if q["id"] not in all_excluded]
    return untouched, len(exposed_for_ds), len(dev_for_ds)


def draw_stratified_supplement(exposed_ids, dev_ids, rng, seed):
    """Draw full shuffled pools from train splits with proper filtering.

    Returns the FULL shuffled untouched pool per dataset (not just target).
    The compile census script iterates through and stops at target.
    """
    all_pools = {}

    for dataset, target in SUPPLEMENT_TARGETS.items():
        print(f"\n{'='*50}")
        print(f"Dataset: {dataset}")
        print(f"{'='*50}")

        # Load raw train questions
        train_questions = load_train_questions(dataset)
        raw_count = len(train_questions)
        print(f"  Raw train pool: {raw_count}")

        # Build untouched pool
        untouched, n_exposed, n_dev = build_untouched_pool(
            dataset, train_questions, exposed_ids, dev_ids
        )
        print(f"  Exposed removed: {n_exposed}")
        print(f"  Dev removed: {n_dev}")
        print(f"  Untouched pool: {len(untouched)}")
        print(f"  Target eligible: {target}")

        if len(untouched) < target:
            print(f"  WARNING: Untouched pool ({len(untouched)}) < target ({target})")
            print(f"  Will draw all available questions")

        # Deterministic shuffle with seed=2027
        rng.shuffle(untouched)

        # Output FULL shuffled pool (compile census stops at target)
        all_pools[dataset] = untouched
        print(f"  Shuffled pool: {len(untouched)} (full pool for sequential census)")

    return all_pools


def main():
    parser = argparse.ArgumentParser(description="Draw train supplement for H-STRUCT-1")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--dry-run", action="store_true", help="Show plan without writing")
    args = parser.parse_args()

    rng = random.Random(args.seed)

    print("=" * 60)
    print("H-STRUCT-1 Train Supplement Drawing (Corrected)")
    print("=" * 60)
    print(f"Seed: {args.seed}")
    print(f"Target supplement: {sum(SUPPLEMENT_TARGETS.values())} eligible")
    print(f"Per dataset: {SUPPLEMENT_TARGETS}")

    # Step 1: Load exposure registry
    print("\n[1/3] Loading exposure registry...")
    exposed_ids, status_counts = load_exposed_ids()
    total_exposed = sum(len(v) for v in exposed_ids.values())
    print(f"  Total exposed IDs: {total_exposed}")
    for ds in sorted(status_counts.keys()):
        print(f"  {ds}:")
        for status, count in sorted(status_counts[ds].items()):
            print(f"    {status}: {count}")

    # Step 2: Load development set IDs
    print("\n[2/3] Loading development set IDs...")
    dev_ids = load_development_ids()
    total_dev = sum(len(v) for v in dev_ids.values())
    print(f"  Development set IDs: {total_dev}")

    # Step 3: Draw from train splits
    print("\n[3/3] Building shuffled pools from train splits...")
    all_pools = draw_stratified_supplement(exposed_ids, dev_ids, rng, args.seed)

    # Write output — full shuffled pools per dataset
    if not args.dry_run:
        TRAIN_SUPPLEMENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TRAIN_SUPPLEMENT_PATH, "w") as f:
            for dataset in ["hotpotqa", "2wikimultihop", "musique"]:
                pool = all_pools.get(dataset, [])
                for item in pool:
                    f.write(json.dumps({
                        "dataset": dataset,
                        "question_id": item["id"],
                        "question_text": item.get("question", ""),
                    }, ensure_ascii=False) + "\n")
        total_written = sum(len(v) for v in all_pools.values())
        print(f"\nWritten: {TRAIN_SUPPLEMENT_PATH}")
        print(f"Total pool: {total_written}")

    # Summary
    print(f"\n{'='*60}")
    print("Summary")
    print(f"{'='*60}")
    for dataset in SUPPLEMENT_TARGETS:
        pool_size = len(all_pools.get(dataset, []))
        print(f"  {dataset}: pool={pool_size} (target={SUPPLEMENT_TARGETS[dataset]} eligible)")
    total_pool = sum(len(v) for v in all_pools.values())
    print(f"  Total pool: {total_pool}")

    print(f"\nNext step: Run train_compile_census.py to compile questions sequentially.")
    print(f"  The census iterates through each shuffled pool and accepts")
    print(f"  questions with structural_hops >= 2 until target is reached.")


if __name__ == "__main__":
    main()
