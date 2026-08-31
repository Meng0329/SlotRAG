#!/usr/bin/env python3
"""Read-only analysis: extract plan structures from sealed test items."""

import json
import hashlib
import glob
import os
from collections import defaultdict
import statistics

BASE = "/home/test/tkde_runs/tkde-sealed-test-q35/items/g7-sealed"
OUT_DIR = "/data/mzb/SlotRAG/research/depth_analysis"
OUT_FILE = os.path.join(OUT_DIR, "all_plans.jsonl")

DATASETS = ["hotpotqa", "2wikimultihop", "musique"]
ARMS = ["slotrag-g7-static", "slotrag-g7-flat", "slotrag-g7-chain"]


def plan_hash(plan):
    """Deterministic hash of plan content for dedup."""
    h = hashlib.sha256()
    h.update(json.dumps(plan.get("slots", []), sort_keys=True).encode())
    h.update(json.dumps(plan.get("joins", []), sort_keys=True).encode())
    h.update(json.dumps(plan.get("outputs", []), sort_keys=True).encode())
    h.update(json.dumps(plan.get("operators", []), sort_keys=True).encode())
    return h.hexdigest()[:16]


def extract_record(dataset, arm, filepath):
    with open(filepath) as f:
        raw = json.load(f)

    qid = raw.get("question_id", os.path.basename(filepath).replace(".json", ""))
    result = raw.get("result") or {}
    plan = result.get("plan") or {}
    metrics = result.get("metrics") or {}
    traces = result.get("slot_traces") or []

    # Plan elements
    slots = plan.get("slots", [])
    joins = plan.get("joins", [])
    operators = plan.get("operators", [])
    outputs = plan.get("outputs", [])

    # Metrics
    n_slots = metrics.get("plan_slot_count", len(slots))
    n_joins = metrics.get("plan_join_count", len(joins))
    plan_variable_count = metrics.get("plan_variable_count", 0)
    plan_complexity = metrics.get("plan_complexity", 0)
    physical_plan_order = metrics.get("physical_plan_order", [])
    physical_action_executions = metrics.get("physical_action_executions", 0)

    # Trace
    trace_steps = len(traces)
    trace_slot_order = [t.get("slot_id", f"step_{t.get('step', i)}") for i, t in enumerate(traces)]

    return {
        "dataset": dataset,
        "arm": arm,
        "question_id": qid,
        "file": os.path.basename(filepath),
        "n_slots": n_slots,
        "n_joins": n_joins,
        "plan_variable_count": plan_variable_count,
        "plan_complexity": plan_complexity,
        "physical_plan_order": physical_plan_order,
        "physical_action_executions": physical_action_executions,
        "slots": slots,
        "joins": joins,
        "operators": operators,
        "outputs": outputs,
        "trace_steps": trace_steps,
        "trace_slot_order": trace_slot_order,
        "_plan_hash": plan_hash(plan),
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    records = []
    errors = 0
    for dataset in DATASETS:
        for arm in ARMS:
            pattern = os.path.join(BASE, dataset, arm, "*.json")
            files = sorted(glob.glob(pattern))
            for fp in files:
                try:
                    rec = extract_record(dataset, arm, fp)
                    records.append(rec)
                except Exception as e:
                    errors += 1
                    print(f"  ERROR {fp}: {e}")

    print(f"\nLoaded {len(records)} items ({errors} errors)\n")

    # Write JSONL (strip internal _plan_hash)
    with open(OUT_FILE, "w") as f:
        for rec in records:
            out = {k: v for k, v in rec.items() if k != "_plan_hash"}
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
    print(f"Wrote {OUT_FILE}\n")

    # ---- Summary statistics ----

    # Per dataset x arm
    print("=" * 80)
    print("SUMMARY: Per dataset x arm")
    print("=" * 80)
    key_fields = ["n_slots", "n_joins"]
    for ds in DATASETS:
        print(f"\n--- {ds} ---")
        for arm in ARMS:
            subset = [r for r in records if r["dataset"] == ds and r["arm"] == arm]
            qids = set(r["question_id"] for r in subset)
            print(f"  {arm}: {len(subset)} items, {len(qids)} unique qids")
            for field in key_fields:
                vals = [r[field] for r in subset]
                if vals:
                    print(f"    {field}: min={min(vals)} max={max(vals)} "
                          f"mean={statistics.mean(vals):.2f} median={statistics.median(vals)} "
                          f"stdev={statistics.stdev(vals):.2f}" if len(vals) > 1 else
                          f"    {field}: {vals[0]}")
                else:
                    print(f"    {field}: (empty)")

    # Unique plans per dataset
    print("\n" + "=" * 80)
    print("UNIQUE PLANS BY DATASET (content hash)")
    print("=" * 80)
    for ds in DATASETS:
        hashes = set()
        for r in records:
            if r["dataset"] == ds:
                hashes.add(r["_plan_hash"])
        total = sum(1 for r in records if r["dataset"] == ds)
        print(f"  {ds}: {len(hashes)} unique plans across {total} items")

    # Unique plans per dataset x arm
    print("\nUNIQUE PLANS BY DATASET x ARM:")
    for ds in DATASETS:
        for arm in ARMS:
            hashes = set()
            for r in records:
                if r["dataset"] == ds and r["arm"] == arm:
                    hashes.add(r["_plan_hash"])
            total = sum(1 for r in records if r["dataset"] == ds and r["arm"] == arm)
            print(f"  {ds}/{arm}: {len(hashes)} unique plans / {total} items")

    # Sample items with n_slots >= 3
    print("\n" + "=" * 80)
    print("SAMPLE: 5 items with n_slots >= 3 (full plan structure)")
    print("=" * 80)
    candidates = [r for r in records if r["n_slots"] >= 3]
    import random
    random.seed(42)
    sampled = random.sample(candidates, min(5, len(candidates)))
    for i, rec in enumerate(sampled, 1):
        print(f"\n--- Sample {i}: {rec['dataset']}/{rec['arm']} qid={rec['question_id']} ---")
        print(f"  n_slots={rec['n_slots']} n_joins={rec['n_joins']} "
              f"complexity={rec['plan_complexity']} variables={rec['plan_variable_count']}")
        print(f"  physical_plan_order: {rec['physical_plan_order']}")
        print(f"  Slots:")
        for s in rec["slots"]:
            print(f"    {s['id']}: predicate={s['predicate']} args={s.get('arguments', [])} "
                  f"vtypes={s.get('variable_types', {})}")
        print(f"  Joins:")
        for j in rec["joins"]:
            print(f"    {j.get('left_slot')}.{j.get('left_field')} <-> "
                  f"{j.get('right_slot')}.{j.get('right_field')}")
        print(f"  Outputs: {rec['outputs']}")
        print(f"  Operators: {rec['operators']}")
        print(f"  Trace ({rec['trace_steps']} steps): {' -> '.join(rec['trace_slot_order'])}")


if __name__ == "__main__":
    main()
