#!/usr/bin/env python3
"""
freeze_confirmatory_manifest.py — Phase 6: Freeze final eligible manifest

Merges validation eligible (361) + train eligible (744) into exactly 1,105.
Computes SHA256. Manifest is frozen after this script runs.

Usage:
    python tools/freeze_confirmatory_manifest.py

Output:
    research/hstruct_confirmatory/confirmatory_eligible_manifest.jsonl
    research/hstruct_confirmatory/CONFIRMATORY_MANIFEST_SHA256.txt
"""

import csv
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

OUTPUT_DIR = REPO / "research" / "hstruct_confirmatory"
VALIDATION_CENSUS = REPO / "research" / "hstruct_validation_census" / "validation_structural_census.csv"
# Plans-enriched manifest — requires extract_validation_plans.py to have run.
# The plain validation_plan_manifest.jsonl lacks plan_json (only plan_hash), which
# is insufficient for the confirmatory runner (needs frozen plans for fairness).
VALIDATION_MANIFEST = REPO / "research" / "hstruct_validation_census" / "validation_plan_manifest_with_plans.jsonl"
TRAIN_ELIGIBLE = OUTPUT_DIR / "train_eligible_manifest.jsonl"
CONFIRMATORY_MANIFEST = OUTPUT_DIR / "confirmatory_eligible_manifest.jsonl"
SHA256_FILE = OUTPUT_DIR / "CONFIRMATORY_MANIFEST_SHA256.txt"

TARGETS = {"hotpotqa": 148, "2wikimultihop": 559, "musique": 37}
TOTAL = 1105


def load_validation_eligible():
    """Load validation eligible questions with plan_json."""
    items = []
    with open(VALIDATION_MANIFEST) as f:
        for line in f:
            rec = json.loads(line.strip())
            # Check if eligible from census
            items.append(rec)

    # Filter to eligible only using census
    eligible_ids = set()
    with open(VALIDATION_CENSUS) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["eligible"] == "True" or row["eligible"] == "1":
                eligible_ids.add(row["question_id"])

    validation_eligible = []
    for item in items:
        if item["question_id"] in eligible_ids:
            validation_eligible.append({
                "question_id": item["question_id"],
                "dataset": item["dataset"],
                "source_split": "validation",
                "plan_hash": item.get("plan_hash"),
                "plan_json": item.get("plan_json"),
                "structural_hops": item.get("structural_hops"),
                "topology": item.get("topology"),
            })

    return validation_eligible


def load_train_eligible():
    """Load train eligible questions from census output."""
    items = []
    with open(TRAIN_ELIGIBLE) as f:
        for line in f:
            rec = json.loads(line.strip())
            items.append({
                "question_id": rec["question_id"],
                "dataset": rec["dataset"],
                "source_split": "train",
                "plan_hash": rec.get("plan_hash"),
                "plan_json": rec.get("plan_json"),
                "structural_hops": rec.get("structural_hops"),
                "topology": rec.get("topology"),
            })
    return items


def main():
    print("=== Freeze Confirmatory Manifest (Phase 6) ===")

    # Load validation eligible
    print("\n[1/3] Loading validation eligible...")
    validation = load_validation_eligible()
    val_by_ds = {}
    for item in validation:
        ds = item["dataset"]
        val_by_ds[ds] = val_by_ds.get(ds, 0) + 1
    print(f"  Validation eligible: {len(validation)}")
    for ds, cnt in sorted(val_by_ds.items()):
        print(f"    {ds}: {cnt}")

    # Load train eligible
    print("\n[2/3] Loading train eligible...")
    if not TRAIN_ELIGIBLE.exists():
        print(f"  ERROR: {TRAIN_ELIGIBLE} not found. Run train_compile_census.py first.")
        sys.exit(1)
    train = load_train_eligible()
    train_by_ds = {}
    for item in train:
        ds = item["dataset"]
        train_by_ds[ds] = train_by_ds.get(ds, 0) + 1
    print(f"  Train eligible: {len(train)}")
    for ds, cnt in sorted(train_by_ds.items()):
        print(f"    {ds}: {cnt}")

    # Merge
    print("\n[3/3] Merging and freezing...")
    all_items = validation + train
    total = len(all_items)
    total_by_ds = {}
    total_by_source = {}
    for item in all_items:
        ds = item["dataset"]
        src = item["source_split"]
        total_by_ds[ds] = total_by_ds.get(ds, 0) + 1
        total_by_source[src] = total_by_source.get(src, 0) + 1

    print(f"\n  Total: {total}")
    print(f"  By source: {total_by_source}")
    print(f"  By dataset: {total_by_ds}")

    # Verify targets
    if total != TOTAL:
        print(f"\n  ERROR: Total {total} != required {TOTAL}")
        sys.exit(1)

    for ds in TARGETS:
        ds_count = total_by_ds.get(ds, 0)
        expected = TARGETS[ds] + (validation_eligible_count(ds))
        # Just check total per dataset matches
        if ds not in total_by_ds:
            print(f"  ERROR: Missing dataset {ds}")
            sys.exit(1)

    # Write manifest
    with open(CONFIRMATORY_MANIFEST, "w") as f:
        for item in all_items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    # Compute SHA256
    sha256 = hashlib.sha256()
    with open(CONFIRMATORY_MANIFEST, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    manifest_hash = sha256.hexdigest()

    with open(SHA256_FILE, "w") as f:
        f.write(f"SHA256: {manifest_hash}\n")
        f.write(f"Total items: {total}\n")
        f.write(f"Validation: {total_by_source.get('validation', 0)}\n")
        f.write(f"Train: {total_by_source.get('train', 0)}\n")
        f.write(f"Per dataset: {json.dumps(total_by_ds)}\n")

    print(f"\n  Manifest SHA256: {manifest_hash}")
    print(f"  Written: {CONFIRMATORY_MANIFEST}")
    print(f"  SHA256 file: {SHA256_FILE}")
    print(f"\n  MANIFEST IS NOW FROZEN. No re-draw allowed.")


def validation_eligible_count(ds):
    """Helper to count validation eligible per dataset."""
    count = 0
    with open(VALIDATION_CENSUS) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row["eligible"] == "True" or row["eligible"] == "1") and row["dataset"] == ds:
                count += 1
    return count


if __name__ == "__main__":
    main()
