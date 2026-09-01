#!/usr/bin/env python3
"""
extract_validation_plans.py — Phase 5: Re-compile eligible validation questions and save plan_json

The validation census (validation_compile_census.py) computed SlotCompiler output
but only saved plan_hash to the manifest, not plan_json. The confirmatory runner
needs frozen plans for fairness (both arms use identical SlotPlan).

This script targets ONLY the 361 eligible questions (~10 min vs 3.4h full re-run).
It compiles each eligible question, saves plan_json, and appends to the manifest.

Usage:
    python tools/extract_validation_plans.py

Output:
    research/hstruct_validation_census/validation_plan_manifest_with_plans.jsonl
"""

import csv
import hashlib
import json
import time
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from slotrag.config import AppConfig
from slotrag.models import SlotPlan
from slotrag.providers import AgnesClient
from slotrag.benchmarking.datasets import DATASETS, adapt_record, iter_jsonl
from slotrag.planner import SlotCompiler

# ── Graph utilities (inlined from validation_compile_census.py) ──────────

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

OUTPUT_DIR = REPO / "research" / "hstruct_validation_census"
VALIDATION_SET = REPO / "research" / "eval_sets" / "validation_set.json"
CENSUS_CSV = OUTPUT_DIR / "validation_structural_census.csv"
MANIFEST_OUT = OUTPUT_DIR / "validation_plan_manifest_with_plans.jsonl"

SEED = 2027


def load_eligible_ids():
    """Load question_ids of eligible validation questions."""
    ids = set()
    with open(CENSUS_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["eligible"] == "True" or row["eligible"] == "1":
                ids.add(row["question_id"])
    return ids


def load_validation_ids():
    """Load validation set question IDs."""
    with open(VALIDATION_SET) as f:
        return json.load(f)


def load_validation_questions(dataset_name, target_ids):
    """Load specific validation questions from benchmark files, normalized via adapt_record."""
    spec = DATASETS[dataset_name]
    eval_path = REPO / "benchmark" / spec.evaluation_file
    questions = []
    for idx, rec in iter_jsonl(eval_path):
        if rec["id"] in target_ids:
            questions.append(adapt_record(spec, rec, idx, split="validation"))
    return questions


def compile_question(question, config, agnes_client):
    """Compile a question using SlotCompiler (firewall: compile only)."""
    compiler = SlotCompiler(client=agnes_client)
    plan, metrics = compiler.compile(question.question)
    plan_json = json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    plan_hash = hashlib.sha256(plan_json.encode()).hexdigest()[:16]
    return plan, plan_json, plan_hash


def main():
    import sys as _sys
    log = lambda msg: _sys.stderr.write(msg + "\n") or _sys.stderr.flush()

    log("=== Extract Validation Plans (Phase 5) ===")

    # Load eligible IDs
    eligible_ids = load_eligible_ids()
    log(f"Eligible validation questions: {len(eligible_ids)}")

    # Load validation IDs
    val_ids = load_validation_ids()
    log(f"Validation set IDs: {len(val_ids)}")

    # Organize by dataset
    by_dataset = {}
    for ds, ids in val_ids.items():
        overlap = [qid for qid in ids if qid in eligible_ids]
        by_dataset[ds] = overlap
        log(f"  {ds}: {len(overlap)} eligible")

    # Initialize shared infrastructure
    log("\n[Initializing services]")
    config = AppConfig.from_yaml(REPO / "configs/default.yaml")
    from slotrag.providers import AgnesClient
    agnes = AgnesClient(config.agnes)
    log("  AgnesClient created.")

    # Compile each eligible question — write results incrementally to JSONL
    t0 = time.time()
    total = len(eligible_ids)
    done = 0
    errors = 0
    log(f"\n[Compiling {total} eligible questions]")

    out_f = open(MANIFEST_OUT, "w")

    for ds in ["hotpotqa", "2wikimultihop", "musique"]:
        qids = by_dataset.get(ds, [])
        if not qids:
            continue

        questions = load_validation_questions(ds, set(qids))
        q_by_id = {q.id: q for q in questions}

        for qid in qids:
            done += 1
            q = q_by_id.get(qid)
            if q is None:
                log(f"  [{done}/{total}] {ds}/{qid} NOT FOUND")
                errors += 1
                continue

            try:
                plan, plan_json, plan_hash = compile_question(q, config, agnes)
                adj, edge_types, n_operator_edges = derive_structural_evidence_graph(plan)
                slot_ids = [s.id for s in plan.slots]
                structural_hops, structural_nodes = exact_longest_simple_path(adj, slot_ids)
                topology = classify_topology(adj, slot_ids, edge_types)

                rec = {
                    "dataset": ds,
                    "question_id": qid,
                    "plan_hash": plan_hash,
                    "plan_json": plan_json,
                    "n_slots": len(plan.slots),
                    "n_edges": len(plan.joins),
                    "n_operator_edges": n_operator_edges,
                    "structural_hops": structural_hops,
                    "structural_nodes": structural_nodes,
                    "topology": topology,
                    "eligible": True,
                    "error": None,
                }
                out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_f.flush()
                if done % 10 == 0 or done == total:
                    elapsed = time.time() - t0
                    rate = done / elapsed if elapsed > 0 else 0
                    eta = (total - done) / rate if rate > 0 else 0
                    log(f"  [{done}/{total}] {ds}/{qid} OK hops={structural_hops} | {elapsed:.0f}s elapsed ETA {eta:.0f}s")

            except Exception as e:
                import traceback
                errors += 1
                rec = {
                    "dataset": ds,
                    "question_id": qid,
                    "plan_hash": None,
                    "plan_json": None,
                    "n_slots": 0,
                    "n_edges": 0,
                    "n_operator_edges": 0,
                    "structural_hops": -1,
                    "structural_nodes": 0,
                    "topology": "error",
                    "eligible": False,
                    "error": str(e)[:200],
                }
                out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_f.flush()
                log(f"  [{done}/{total}] {ds}/{qid} ERROR: {e}")
                log(traceback.format_exc())

    out_f.close()
    elapsed = time.time() - t0
    n_ok = done - errors
    log(f"\n{'='*60}")
    log(f"Complete: {done} questions, {n_ok} OK, {errors} errors")
    log(f"Time: {elapsed:.0f}s ({elapsed/done:.1f}s/question)")
    log(f"Output: {MANIFEST_OUT}")
    log(f"\nNext: Run freeze_confirmatory_manifest.py to merge with train plans.")


if __name__ == "__main__":
    main()
