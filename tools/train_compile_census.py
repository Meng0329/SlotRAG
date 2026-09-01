#!/usr/bin/env python3
"""
train_compile_census.py — Deterministic sequential census for train supplement

Phase 4-5: Compile train questions one by one, accept if hops >= 2.
Stop when dataset target reached. If pool exhausted, STOP.

Firewall: SlotCompiler ONLY. No retrieval, no generation, no EM/F1, no gold answers.

Output:
  research/hstruct_confirmatory/train_compile_census.csv
  research/hstruct_confirmatory/train_eligible_manifest.jsonl
  research/hstruct_confirmatory/train_compile_failures.csv
"""

import csv
import hashlib
import json
import random
import sys
import time
from pathlib import Path

# ── Setup ──────────────────────────────────────────────────────────────────
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from slotrag.benchmarking.datasets import DATASETS, iter_jsonl
from slotrag.benchmarking.methods import (
    METHODS,
    compile_slotrag_plan,
)
from slotrag.models import SlotPlan
from slotrag.providers import provider_clients
from slotrag.config import AppConfig

# ── Paths ──────────────────────────────────────────────────────────────────
OUTPUT_DIR = REPO / "research" / "hstruct_confirmatory"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CENSUS_CSV = OUTPUT_DIR / "train_compile_census.csv"
ELIGIBLE_JSONL = OUTPUT_DIR / "train_eligible_manifest.jsonl"
FAILURES_CSV = OUTPUT_DIR / "train_compile_failures.csv"
DRAW_JSONL = REPO / "research" / "hstruct_confirmatory" / "train_supplement_draw.jsonl"

# ── Constants ──────────────────────────────────────────────────────────────
METHOD_NAME = "slotrag"
SPEC = METHODS[METHOD_NAME]

# Targets per dataset (frozen)
TARGETS = {
    "hotpotqa": 148,
    "2wikimultihop": 559,
    "musique": 37,
}

SEED = 2027

# ── Graph utilities (inlined from validation_compile_census.py) ────────────

def derive_structural_evidence_graph(plan: SlotPlan):
    """Build adjacency list + edge types from a SlotPlan."""
    slot_ids = {slot.id for slot in plan.slots}
    adj = {sid: set() for sid in slot_ids}
    edge_types = {}

    for join in plan.joins:
        pair = frozenset({join.left_slot, join.right_slot})
        adj.setdefault(join.left_slot, set()).add(join.right_slot)
        adj.setdefault(join.right_slot, set()).add(join.left_slot)
        edge_types.setdefault(pair, set()).add("join")

    slot_fields = {slot.id: slot.variables for slot in plan.slots}
    operator_edges = 0
    for op in plan.operators:
        if op.kind not in {"field_argmin", "field_argmax"}:
            continue
        sources = set()
        for field in op.fields:
            for sid, variables in slot_fields.items():
                if field in variables:
                    sources.add(sid)
        for left in sources:
            for right in sources:
                if left != right:
                    adj.setdefault(left, set()).add(right)
                    pair = frozenset({left, right})
                    edge_types.setdefault(pair, set()).add("operator")
                    operator_edges += 1

    return adj, edge_types, operator_edges


def exact_longest_simple_path(adj, slot_ids):
    """DFS with backtracking to find longest simple path (edge count)."""
    best_hops = 0

    def dfs(node, visited, depth):
        nonlocal best_hops
        best_hops = max(best_hops, depth)
        for nb in adj.get(node, set()):
            if nb not in visited:
                visited.add(nb)
                dfs(nb, visited, depth + 1)
                visited.discard(nb)

    for start in slot_ids:
        dfs(start, {start}, 0)

    return best_hops, best_hops + 1


def classify_topology(adj, slot_ids, edge_types):
    """Classify topology of the structural evidence graph."""
    n = len(slot_ids)
    if n <= 1:
        return "single"

    degrees = {sid: len(adj.get(sid, set())) for sid in slot_ids}
    max_deg = max(degrees.values()) if degrees else 0

    if n >= 4 and max_deg >= 3:
        if max_deg == n - 1:
            hub = [sid for sid, d in degrees.items() if d == n - 1]
            if len(hub) == 1:
                leaves = [sid for sid, d in degrees.items() if d == 1]
                if len(leaves) == n - 1:
                    return "star"

    if all(d <= 2 for d in degrees.values()):
        endpoints = sum(1 for d in degrees.values() if d == 1)
        if endpoints == 2 or (n == 2 and endpoints == 2):
            return "chain"

    total_edges = sum(len(neighbors) for neighbors in adj.values()) // 2
    if total_edges == n - 1:
        return "tree"

    return "complex"


# ── Census worker ──────────────────────────────────────────────────────────

def compile_one(dataset, question_id, question_text, agnes_client):
    """Compile one question and extract structural properties. FIREWALL: compile only."""

    # Create a minimal QuestionRecord-like object
    class MinimalQR:
        def __init__(self, qid, text, ds):
            self.id = qid
            self.question = text
            self.dataset = ds
            self.answers = ""
            self.passages = []
            self.type = ""

    q = MinimalQR(question_id, question_text, dataset)

    try:
        plan, metrics = compile_slotrag_plan(SPEC, dataset, q, agnes_client)
    except Exception as e:
        return {
            "dataset": dataset,
            "question_id": question_id,
            "plan_hash": None,
            "n_slots": 0,
            "n_edges": 0,
            "n_operator_edges": 0,
            "structural_hops": -1,
            "structural_nodes": 0,
            "topology": "compile_failed",
            "eligible": False,
            "error": str(e)[:200],
        }

    slot_ids = [slot.id for slot in plan.slots]
    adj, edge_types, n_operator_edges = derive_structural_evidence_graph(plan)
    structural_hops, structural_nodes = exact_longest_simple_path(adj, slot_ids)
    topology = classify_topology(adj, set(slot_ids), edge_types)
    eligible = structural_hops >= 2

    plan_json = json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    plan_hash = hashlib.sha256(plan_json.encode()).hexdigest()[:16]

    return {
        "dataset": dataset,
        "question_id": question_id,
        "plan_hash": plan_hash,
        "plan_json": plan_json,
        "n_slots": len(plan.slots),
        "n_edges": len(plan.joins),
        "n_operator_edges": n_operator_edges,
        "structural_hops": structural_hops,
        "structural_nodes": structural_nodes,
        "topology": topology,
        "eligible": eligible,
        "error": None,
    }


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print("=== Train Compile Census (Phase 4-5) ===")
    print("FIREWALL: SlotCompiler ONLY. No retrieval, no generation, no EM/F1.")
    print(f"Targets: {TARGETS}")
    print(f"Seed: {SEED}")
    print()

    # Load config and providers
    config = AppConfig.from_yaml(REPO / "configs" / "default.yaml")
    agnes, embedding, reranker = provider_clients(config)

    # Load drawn questions
    drawn = []
    with open(DRAW_JSONL) as f:
        for line in f:
            drawn.append(json.loads(line.strip()))

    # Group by dataset
    by_dataset = {}
    for item in drawn:
        ds = item["dataset"]
        by_dataset.setdefault(ds, []).append(item)

    # Deterministic shuffle per dataset
    for ds in by_dataset:
        rng = random.Random(SEED)
        rng.shuffle(by_dataset[ds])

    # Census state
    all_results = []
    eligible_by_ds = {ds: [] for ds in TARGETS}
    failures_by_ds = {ds: [] for ds in TARGETS}
    compiled_by_ds = {ds: 0 for ds in TARGETS}
    start_time = time.time()

    # Open CSV writer
    csv_fields = [
        "dataset", "question_id", "plan_hash", "n_slots", "n_edges",
        "n_operator_edges", "structural_hops", "structural_nodes",
        "topology", "eligible", "error",
    ]

    with open(CENSUS_CSV, "w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=csv_fields)
        writer.writeheader()

        for dataset in ["hotpotqa", "2wikimultihop", "musique"]:
            if dataset not in by_dataset:
                continue

            target = TARGETS[dataset]
            questions = by_dataset[dataset]
            print(f"\n--- {dataset}: target={target} eligible, pool={len(questions)} ---")

            for i, item in enumerate(questions):
                # Check if target reached
                if len(eligible_by_ds[dataset]) >= target:
                    print(f"  TARGET REACHED: {len(eligible_by_ds[dataset])}/{target}")
                    break

                qid = item["question_id"]
                qtext = item.get("question_text", "")

                # Compile
                result = compile_one(dataset, qid, qtext, agnes)
                compiled_by_ds[dataset] += 1

                # Write to census CSV (without plan_json)
                csv_row = {k: result[k] for k in csv_fields}
                writer.writerow(csv_row)
                csvfile.flush()

                if result["error"]:
                    failures_by_ds[dataset].append(result)
                    status = f"FAIL({result['error'][:50]})"
                elif result["eligible"]:
                    eligible_by_ds[dataset].append(result)
                    status = f"ELIGIBLE(hops={result['structural_hops']})"
                else:
                    status = f"not_eligible(hops={result['structural_hops']})"

                # Progress
                elapsed = time.time() - start_time
                total_compiled = sum(compiled_by_ds.values())
                total_eligible = sum(len(v) for v in eligible_by_ds.values())
                print(f"  [{total_compiled}] {dataset}/{qid[:12]}... {status} "
                      f"| eligible={total_eligible}/{sum(TARGETS.values())} "
                      f"| {elapsed:.0f}s")

            print(f"  {dataset} done: {len(eligible_by_ds[dataset])}/{target} eligible, "
                  f"{compiled_by_ds[dataset]} compiled, "
                  f"{len(failures_by_ds[dataset])} failures")

    # Write eligible manifest JSONL
    with open(ELIGIBLE_JSONL, "w") as f:
        for ds in ["hotpotqa", "2wikimultihop", "musique"]:
            for result in eligible_by_ds[ds]:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")

    # Write failures CSV
    with open(FAILURES_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields)
        writer.writeheader()
        for ds in ["hotpotqa", "2wikimultihop", "musique"]:
            for result in failures_by_ds[ds]:
                writer.writerow({k: result[k] for k in csv_fields})

    # Summary
    elapsed = time.time() - start_time
    total_compiled = sum(compiled_by_ds.values())
    total_eligible = sum(len(v) for v in eligible_by_ds.values())
    total_failures = sum(len(v) for v in failures_by_ds.values())

    print(f"\n{'='*60}")
    print(f"CENSUS COMPLETE")
    print(f"{'='*60}")
    print(f"Time: {elapsed:.0f}s ({elapsed/total_compiled:.1f}s/question)")
    print(f"Total compiled: {total_compiled}")
    print(f"Total eligible: {total_eligible}/{sum(TARGETS.values())}")
    print(f"Total failures: {total_failures}")
    for ds in ["hotpotqa", "2wikimultihop", "musique"]:
        print(f"  {ds}: {len(eligible_by_ds[ds])}/{TARGETS[ds]} eligible, "
              f"{compiled_by_ds[ds]} compiled, {len(failures_by_ds[ds])} failures")

    # Check if all targets met
    all_met = all(len(eligible_by_ds[ds]) >= TARGETS[ds] for ds in TARGETS)
    if all_met:
        print(f"\nALL TARGETS MET. Eligible manifest ready.")
    else:
        print(f"\nWARNING: Not all targets met!")
        for ds in TARGETS:
            if len(eligible_by_ds[ds]) < TARGETS[ds]:
                print(f"  {ds}: {len(eligible_by_ds[ds])}/{TARGETS[ds]} — SHORT")

    print(f"\nOutput:")
    print(f"  Census CSV: {CENSUS_CSV}")
    print(f"  Eligible manifest: {ELIGIBLE_JSONL}")
    print(f"  Failures CSV: {FAILURES_CSV}")


if __name__ == "__main__":
    main()
