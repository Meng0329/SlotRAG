#!/usr/bin/env python3
"""Validate train_eligible_manifest_v12.jsonl — reject plans that fail
compile_physical_plan or search_physical_plans, then pull replacements from
the surplus eligible pool (same dataset, shuffle order, frozen snapshots)."""

import json, random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from slotrag.models import SlotPlan
from slotrag.qo import compile_physical_plan, logical_plan_from_slot_plan, PlanValidationError
from slotrag.optimizer import search_physical_plans, PlanObjectiveParams

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "research" / "hstruct_confirmatory" / "train_eligible_manifest_v12.jsonl"
FROZEN = REPO / "research" / "hstruct_frozen_train"
CSV = REPO / "research" / "hstruct_confirmatory" / "train_compile_census_v12.csv"
SEED = 2027
TARGETS = {"hotpotqa": 148, "2wikimultihop": 559, "musique": 37}


def plan_passes(plan: SlotPlan) -> bool:
    logical = logical_plan_from_slot_plan(plan)
    try:
        compile_physical_plan(logical, top_k=8)
    except PlanValidationError:
        return False
    try:
        sp, _ = search_physical_plans(logical, params=PlanObjectiveParams(retrieval_budget=8))
        if sp.telemetry.validation_status != "valid":
            return False
    except Exception:
        return False
    return True


def main():
    manifest = [json.loads(l) for l in open(MANIFEST)]
    print(f"loaded {len(manifest)} manifest items")

    # Identify failures
    failures = []
    ok = []
    for m in manifest:
        plan = SlotPlan.model_validate_json(m['plan_json'])
        if plan_passes(plan):
            ok.append(m)
        else:
            failures.append(m)

    print(f"validated: {len(ok)} pass, {len(failures)} fail")
    if not failures:
        print("no repairs needed")
        return

    # Group failures by dataset
    fail_by_ds = {}
    for m in failures:
        fail_by_ds.setdefault(m['dataset'], []).append(m)
    for ds, items in fail_by_ds.items():
        print(f"  {ds}: {len(items)} failures")

    # Build pool of all eligible questions from census CSV (non-error, eligible)
    import csv
    eligible_pool: dict[str, list[tuple[str, str]]] = {}
    with open(CSV) as f:
        for row in csv.DictReader(f):
            if row['eligible'] != 'True' or row['error']:
                continue
            eligible_pool.setdefault(row['dataset'], []).append(row['question_id'])

    # Deterministic shuffle order
    rng = random.Random(SEED)
    for ds in eligible_pool:
        rng.shuffle(eligible_pool[ds])

    # Track already-in-manifest question_ids per dataset
    in_manifest = {m['dataset']: set() for m in ok}
    for m in ok:
        in_manifest[m['dataset']].add(m['question_id'])

    # Pull replacements from surplus per dataset
    replacements_needed = {ds: len(items) for ds, items in fail_by_ds.items()}
    added = 0
    for ds in sorted(replacements_needed):
        needed = replacements_needed[ds]
        pulled = 0
        for qid in eligible_pool.get(ds, []):
            if pulled >= needed:
                break
            if qid in in_manifest[ds]:
                continue
            snap = FROZEN / ds / f"{qid}.json"
            if not snap.exists():
                continue
            snap_data = json.load(open(snap))
            plan = SlotPlan.model_validate_json(
                json.dumps(snap_data['plan'], sort_keys=True, separators=(',', ':'))
            )
            if plan_passes(plan):
                new_item = {
                    "dataset": ds,
                    "question_id": qid,
                    "source_split": "train",
                    "plan_json": json.dumps(snap_data['plan'], sort_keys=True, separators=(',', ':')),
                }
                ok.append(new_item)
                in_manifest[ds].add(qid)
                pulled += 1
                added += 1
            else:
                continue
        shortfall = needed - pulled
        if shortfall > 0:
            print(f"  WARNING: {ds}: {shortfall} replacements not found (pool exhausted)")
        else:
            print(f"  {ds}: {pulled} replacements found")

    # Rebuild manifest per dataset in shuffle order, cap at target
    final = []
    for ds in ["hotpotqa", "2wikimultihop", "musique"]:
        ds_items = [m for m in ok if m['dataset'] == ds]
        # Sort in shuffle order
        order = {qid: i for i, qid in enumerate(eligible_pool.get(ds, []))}
        ds_items.sort(key=lambda m: order.get(m['question_id'], 999999))
        final.extend(ds_items[:TARGETS[ds]])

    print(f"\nfinal manifest: {len(final)} items")
    for ds in ["hotpotqa", "2wikimultihop", "musique"]:
        n = sum(1 for m in final if m['dataset'] == ds)
        print(f"  {ds}: {n}/{TARGETS[ds]}")

    with open(MANIFEST, "w") as f:
        for item in final:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"\nwrote {MANIFEST}")


if __name__ == "__main__":
    main()
