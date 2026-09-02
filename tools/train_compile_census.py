#!/usr/bin/env python3
"""
train_compile_census.py — V1.2: Deterministic sequential census for train supplement

V1.2 FIX: Uses full QuestionRecord from load_questions() (same path as validation census).
No MinimalQR. Passages, metadata, gold_evidence all present.

compile_slotrag_plan(METHODS["slotrag"], dataset, full_question_record, agnes_client)
compiler_options match real execution path exactly.

Output:
  research/hstruct_confirmatory/train_compile_census_v12.csv
  research/hstruct_confirmatory/train_eligible_manifest_v12.jsonl
  research/hstruct_confirmatory/train_compile_failures_v12.csv
  research/hstruct_frozen_train/{dataset}/{question_id}.json  (frozen snapshots)
"""

import csv
import hashlib
import json
import random
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from slotrag.data import load_questions
from slotrag.benchmarking.datasets import DATASETS as DATASET_SPECS
from slotrag.benchmarking.methods import (
    METHODS,
    compile_slotrag_plan,
    slotrag_compile_options,
)
from slotrag.models import SlotPlan, RunMetrics
from slotrag.providers import provider_clients
from slotrag.config import AppConfig

OUTPUT_DIR = REPO / "research" / "hstruct_confirmatory"
FROZEN_DIR = REPO / "research" / "hstruct_frozen_train"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
FROZEN_DIR.mkdir(parents=True, exist_ok=True)

CENSUS_CSV = OUTPUT_DIR / "train_compile_census_v12.csv"
ELIGIBLE_JSONL = OUTPUT_DIR / "train_eligible_manifest_v12.jsonl"
FAILURES_CSV = OUTPUT_DIR / "train_compile_failures_v12.csv"

METHOD_NAME = "slotrag"
SPEC = METHODS[METHOD_NAME]

TARGETS = {
    "hotpotqa": 148,
    "2wikimultihop": 559,
    "musique": 37,
}

SEED = 2027


def _plan_sha256(plan: SlotPlan) -> str:
    plan_json = json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(plan_json.encode()).hexdigest()


def _canonical_sha256(obj) -> str:
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def derive_structural_evidence_graph(plan: SlotPlan):
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


def compile_one(dataset, question, agnes_client):
    """Compile one question with FULL QuestionRecord. FIREWALL: compile only."""
    try:
        plan, metrics = compile_slotrag_plan(SPEC, dataset, question, agnes_client)
    except Exception as e:
        return {
            "dataset": dataset,
            "question_id": question.id,
            "plan_hash": None,
            "n_slots": 0,
            "n_edges": 0,
            "n_operator_edges": 0,
            "structural_hops": -1,
            "structural_nodes": 0,
            "topology": "compile_failed",
            "eligible": False,
            "error": str(e)[:200],
        }, None, None

    slot_ids = [slot.id for slot in plan.slots]
    adj, edge_types, n_operator_edges = derive_structural_evidence_graph(plan)
    structural_hops, structural_nodes = exact_longest_simple_path(adj, slot_ids)
    topology = classify_topology(adj, set(slot_ids), edge_types)
    eligible = structural_hops >= 2

    plan_json = json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    plan_hash = hashlib.sha256(plan_json.encode()).hexdigest()[:16]

    # Build frozen snapshot
    compile_input = {
        "stage": "hstruct-v12-train-census",
        "dataset": dataset,
        "question_id": question.id,
        "question": question.question,
        "source_method": METHOD_NAME,
        "compiler_options": slotrag_compile_options(SPEC, dataset, question),
    }
    input_sha256 = _canonical_sha256(compile_input)

    snapshot = {
        "schema_version": 1,
        "stage": "hstruct-v12-train-census",
        "dataset": dataset,
        "question_id": question.id,
        "source_method": METHOD_NAME,
        "input_sha256": input_sha256,
        "compiler_options": compile_input["compiler_options"],
        "attempt_index": 1,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "wall_latency_ms": getattr(metrics, "compilation_latency_ms", 0),
        "provider_delta": {},
        "preparation_mode": "v12_train_census",
        "status": "ok",
        "error": None,
        "failure_category": "ok",
        "plan_sha256": _plan_sha256(plan),
        "plan": plan.model_dump(mode="json"),
        "compiler_metrics": metrics.model_dump(mode="json"),
        "structural_hops": structural_hops,
        "structural_nodes": structural_nodes,
        "topology": topology,
        "eligible": eligible,
    }

    result = {
        "dataset": dataset,
        "question_id": question.id,
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

    return result, snapshot, compile_input


def main():
    print("=== Train Compile Census (V1.2 — FULL QuestionRecord) ===")
    print("FIREWALL: SlotCompiler ONLY. No retrieval, no generation, no EM/F1.")
    print(f"Compile path: compile_slotrag_plan(METHODS['{METHOD_NAME}'], dataset, full_question_record, agnes)")
    print(f"Targets: {TARGETS}")
    print(f"Seed: {SEED}")
    print()

    config = AppConfig.from_yaml(REPO / "configs" / "default.yaml")
    agnes, embedding, reranker = provider_clients(config)

    # Load full QuestionRecords from train benchmark files
    BENCHMARK_ROOT = REPO / "benchmark"
    ds_questions = {}
    for ds in ["hotpotqa", "2wikimultihop", "musique"]:
        ds_spec = DATASET_SPECS[ds]
        train_path = BENCHMARK_ROOT / ds_spec.train_file
        if not train_path.exists():
            print(f"  WARNING: {train_path} not found, skipping {ds}")
            continue
        all_qs = load_questions(train_path)
        ds_questions[ds] = {q.id: q for q in all_qs}
        print(f"  {ds}: loaded {len(all_qs)} full QuestionRecords from train file")

    print()

    # Deterministic shuffle per dataset
    rng = random.Random(SEED)
    for ds in ds_questions:
        ids = list(ds_questions[ds].keys())
        rng.shuffle(ids)
        ds_questions[ds] = {qid: ds_questions[ds][qid] for qid in ids}

    csv_fields = [
        "dataset", "question_id", "plan_hash", "n_slots", "n_edges",
        "n_operator_edges", "structural_hops", "structural_nodes",
        "topology", "eligible", "error",
    ]

    eligible_by_ds = {ds: [] for ds in TARGETS}
    failures_by_ds = {ds: [] for ds in TARGETS}
    compiled_by_ds = {ds: 0 for ds in TARGETS}
    start_time = time.time()

    with open(CENSUS_CSV, "w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=csv_fields)
        writer.writeheader()

        for dataset in ["hotpotqa", "2wikimultihop", "musique"]:
            if dataset not in ds_questions:
                continue

            target = TARGETS[dataset]
            questions = ds_questions[dataset]
            print(f"\n--- {dataset}: target={target} eligible, pool={len(questions)} ---")

            for i, (qid, question) in enumerate(questions.items()):
                if len(eligible_by_ds[dataset]) >= target:
                    print(f"  TARGET REACHED: {len(eligible_by_ds[dataset])}/{target}")
                    break

                result, snapshot, compile_input = compile_one(dataset, question, agnes)
                compiled_by_ds[dataset] += 1

                csv_row = {k: result[k] for k in csv_fields}
                writer.writerow(csv_row)
                csvfile.flush()

                if result["error"]:
                    failures_by_ds[dataset].append(result)
                    status = f"FAIL({result['error'][:50]})"
                elif result["eligible"]:
                    eligible_by_ds[dataset].append(result)
                    # Save frozen snapshot
                    snap_dir = FROZEN_DIR / dataset
                    snap_dir.mkdir(parents=True, exist_ok=True)
                    snap_path = snap_dir / f"{qid}.json"
                    with open(snap_path, "w") as f:
                        json.dump(snapshot, f, indent=2, ensure_ascii=False)
                    status = f"ELIGIBLE(hops={result['structural_hops']})"
                else:
                    status = f"not_eligible(hops={result['structural_hops']})"

                elapsed = time.time() - start_time
                total_compiled = sum(compiled_by_ds.values())
                total_eligible = sum(len(v) for v in eligible_by_ds.values())
                if total_compiled % 20 == 0 or total_compiled <= 3:
                    print(f"  [{total_compiled}] {dataset}/{qid[:12]}... {status} "
                          f"| eligible={total_eligible}/{sum(TARGETS.values())} "
                          f"| {elapsed:.0f}s")

            print(f"  {dataset} done: {len(eligible_by_ds[dataset])}/{target} eligible, "
                  f"{compiled_by_ds[dataset]} compiled, "
                  f"{len(failures_by_ds[dataset])} failures")

    # Write eligible manifest
    with open(ELIGIBLE_JSONL, "w") as f:
        for ds in ["hotpotqa", "2wikimultihop", "musique"]:
            for result in eligible_by_ds[ds]:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")

    # Write failures
    with open(FAILURES_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields)
        writer.writeheader()
        for ds in ["hotpotqa", "2wikimultihop", "musique"]:
            for result in failures_by_ds[ds]:
                writer.writerow({k: result[k] for k in csv_fields})

    elapsed = time.time() - start_time
    total_compiled = sum(compiled_by_ds.values())
    total_eligible = sum(len(v) for v in eligible_by_ds.values())

    print(f"\n{'='*60}")
    print(f"V1.2 TRAIN CENSUS COMPLETE")
    print(f"{'='*60}")
    print(f"Time: {elapsed:.0f}s ({elapsed/max(total_compiled,1):.1f}s/question)")
    print(f"Total compiled: {total_compiled}")
    print(f"Total eligible: {total_eligible}/{sum(TARGETS.values())}")
    for ds in ["hotpotqa", "2wikimultihop", "musique"]:
        print(f"  {ds}: {len(eligible_by_ds[ds])}/{TARGETS[ds]} eligible")

    all_met = all(len(eligible_by_ds[ds]) >= TARGETS[ds] for ds in TARGETS)
    if all_met:
        print(f"\nALL TARGETS MET.")
    else:
        print(f"\nWARNING: Not all targets met!")
        for ds in TARGETS:
            if len(eligible_by_ds[ds]) < TARGETS[ds]:
                print(f"  {ds}: {len(eligible_by_ds[ds])}/{TARGETS[ds]} — SHORT")

    print(f"\nOutputs:")
    print(f"  Census CSV: {CENSUS_CSV}")
    print(f"  Eligible manifest: {ELIGIBLE_JSONL}")
    print(f"  Frozen snapshots: {FROZEN_DIR}/")


if __name__ == "__main__":
    main()
