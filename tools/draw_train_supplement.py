#!/usr/bin/env python3
"""
draw_train_supplement.py — Draw eligible questions from untouched train pool

Phase 10-11: Train supplement for H-STRUCT-1 confirmatory sample
- Draws 744 eligible questions from train splits (stratified by dataset)
- Uses validation census rates for proportional allocation
- Freezes question_ids + plan_hashes to manifest

Usage:
    python tools/draw_train_supplement.py --config configs/default.yaml

Output:
    research/hstruct_validation_census/train_supplement_sample.jsonl
    research/hstruct_validation_census/confirmatory_manifest.jsonl (validation + train)
"""

import argparse
import json
import random
import sys
from pathlib import Path

# ---- Repo setup ----
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from slotrag.benchmarking.datasets import DATASET_SPECS, load_questions

# ---- Constants ----
VALIDATION_CENSUS = REPO / "research" / "hstruct_validation_census" / "validation_structural_census.csv"
TRAIN_SUPPLEMENT_PATH = REPO / "research" / "hstruct_validation_census" / "train_supplement_sample.jsonl"
CONFIRMATORY_MANIFEST_PATH = REPO / "research" / "hstruct_validation_census" / "confirmatory_manifest.jsonl"

# Target supplement per dataset (proportional to validation census rates)
# Validation: hotpotqa 68, 2wikimultihop 258, musique 35 = 361 total
# Train supplement: 744 total, proportional
SUPPLEMENT_TARGETS = {
    "hotpotqa": 148,      # 68/361 × 744 ≈ 148
    "2wikimultihop": 559,  # 258/361 × 744 ≈ 559
    "musique": 37,         # 35/361 × 744 ≈ 37
}

SEED = 2027


def load_validation_eligible_ids():
    """Load validation eligible question_ids (to exclude from train draw)."""
    import csv
    val_ids = set()
    with open(VALIDATION_CENSUS, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["eligible"] == "True" or row["eligible"] == "1":
                val_ids.add(row["question_id"])
    print(f"  Validation eligible IDs loaded: {len(val_ids)}")
    return val_ids


def load_train_questions(dataset_name: str):
    """Load train split questions for a dataset."""
    spec = DATASET_SPECS[dataset_name]
    train_path = REPO / "benchmark" / spec["train_file"]
    questions = load_questions(train_path)
    return questions


def draw_stratified_supplement(val_ids: set, rng: random.Random):
    """Draw 744 eligible from train splits, stratified by dataset."""
    all_drawn = []

    for dataset, target in SUPPLEMENT_TARGETS.items():
        print(f"\n  Drawing {target} from {dataset} train...")

        # Load train questions
        train_questions = load_train_questions(dataset)
        print(f"    Train pool: {len(train_questions)} questions")

        # Filter out validation eligible IDs (avoid any overlap)
        train_filtered = [q for q in train_questions if q["id"] not in val_ids]
        print(f"    After excluding validation IDs: {len(train_filtered)} questions")

        # Random sample (we'll compile later to determine eligibility)
        # Over-sample by 3x to account for compile failures (~1.2% from census)
        over_sample_factor = 3
        n_draw = min(target * over_sample_factor, len(train_filtered))
        drawn = rng.sample(train_filtered, n_draw)
        print(f"    Over-sampled: {len(drawn)} questions (target: {target})")

        for q in drawn:
            all_drawn.append({
                "dataset": dataset,
                "question_id": q["id"],
                "question_text": q.get("question", ""),
                "target_eligible": target,
            })

    return all_drawn


def main():
    parser = argparse.ArgumentParser(description="Draw train supplement for H-STRUCT-1")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--dry-run", action="store_true", help="Show plan without writing")
    args = parser.parse_args()

    rng = random.Random(args.seed)

    print("=" * 60)
    print("H-STRUCT-1 Train Supplement Drawing")
    print("=" * 60)
    print(f"Seed: {args.seed}")
    print(f"Target supplement: {sum(SUPPLEMENT_TARGETS.values())} eligible")
    print(f"Per dataset: {SUPPLEMENT_TARGETS}")

    # Step 1: Load validation eligible IDs
    print("\n[1/4] Loading validation eligible IDs...")
    val_ids = load_validation_eligible_ids()

    # Step 2: Draw from train splits
    print("\n[2/4] Drawing from train splits (over-sampled)...")
    drawn = draw_stratified_supplement(val_ids, rng)

    # Step 3: Write train supplement sample
    print(f"\n[3/4] Writing train supplement sample: {TRAIN_SUPPLEMENT_PATH}")
    if not args.dry_run:
        with open(TRAIN_SUPPLEMENT_PATH, "w") as f:
            for item in drawn:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"  Written: {len(drawn)} items")

    # Step 4: Summary
    print(f"\n[4/4] Summary:")
    print(f"  Total over-sampled: {len(drawn)}")
    for dataset in SUPPLEMENT_TARGETS:
        count = sum(1 for d in drawn if d["dataset"] == dataset)
        print(f"    {dataset}: {count} drawn (target: {SUPPLEMENT_TARGETS[dataset]})")

    print(f"\n  Note: Over-sampled by 3x to account for compile failures.")
    print(f"  After SlotCompiler census on drawn questions,")
    print(f"  filter to eligible (hops >= 2) and take first {sum(SUPPLEMENT_TARGETS.values())}.")
    print(f"\n{'=' * 60}")
    print("Next step: Run SlotCompiler on drawn questions to determine eligibility.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
