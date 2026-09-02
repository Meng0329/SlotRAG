#!/usr/bin/env python3
"""
extract_validation_plans.py — V1.2: Recovery gate for validation frozen plans

Re-compiles the 361 census-eligible validation questions using the CORRECT
compile path: compile_slotrag_plan(SPEC, dataset, full_question_record, agnes_client).

This produces:
1. validation_plan_recovery_audit.csv — hash comparison with original census
2. Frozen plan snapshots in research/hstruct_frozen_validation/{dataset}/{question_id}.json

CRITICAL: Uses load_questions() from slotrag.data (same path as validation_compile_census.py)
and compile_slotrag_plan() with METHODS["slotrag"] SPEC.

Usage:
    python tools/extract_validation_plans.py
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
from slotrag.models import SlotPlan, RunMetrics
from slotrag.providers import AgnesClient, provider_clients
from slotrag.data import load_questions
from slotrag.benchmarking.datasets import DATASETS as DATASET_SPECS
from slotrag.benchmarking.methods import (
    METHODS,
    compile_slotrag_plan,
    slotrag_compile_options,
)

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


def _plan_sha256(plan: SlotPlan) -> str:
    """Deterministic plan hash (matches BenchmarkRunner)."""
    plan_json = json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(plan_json.encode()).hexdigest()


def _canonical_sha256(obj) -> str:
    """Canonical SHA256 for any JSON-serializable object."""
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


OUTPUT_DIR = REPO / "research" / "hstruct_validation_census"
FROZEN_DIR = REPO / "research" / "hstruct_frozen_validation"
VALIDATION_SET_PATH = REPO / "research" / "eval_sets" / "validation_set.json"
CENSUS_CSV = OUTPUT_DIR / "validation_structural_census.csv"
RECOVERY_AUDIT = OUTPUT_DIR / "validation_plan_recovery_audit.csv"
RECOVERY_MANIFEST = OUTPUT_DIR / "validation_plan_manifest_v12.jsonl"

METHOD_NAME = "slotrag"
SPEC = METHODS[METHOD_NAME]
TARGET_DATASETS = ["hotpotqa", "2wikimultihop", "musique"]


def main():
    import sys as _sys
    log = lambda msg: _sys.stderr.write(msg + "\n") or _sys.stderr.flush()

    log("=== Extract Validation Plans (V1.2 — CORRECT compile path) ===")
    log("RULES: No retrieval, no answer generation, no EM/F1, no gold-answer inspection.")
    log(f"Compile path: compile_slotrag_plan(METHODS['{METHOD_NAME}'], dataset, question, agnes)")
    log(f"SPEC fields: field_extremum={SPEC.field_extremum_templates}, "
        f"polar={SPEC.polar_comparison_templates}, runtime_compiler={SPEC.runtime_compiler}")
    log("")

    # Load census eligible
    census = {}
    with open(CENSUS_CSV) as f:
        for row in csv.DictReader(f):
            if row["eligible"] == "True":
                census[row["question_id"]] = {
                    "dataset": row["dataset"],
                    "plan_hash": row["plan_hash"],
                    "hops": int(row["structural_hops"]),
                    "topology": row["topology"],
                }
    log(f"Census eligible: {len(census)}")

    # Load validation IDs
    with open(VALIDATION_SET_PATH) as f:
        val_ids = json.load(f)
    log(f"Validation set IDs: {sum(len(v) for v in val_ids.values())}")

    # Load full QuestionRecords from benchmark files (same path as census)
    BENCHMARK_ROOT = REPO / "benchmark"
    ds_questions = {}
    for ds in TARGET_DATASETS:
        ds_spec = DATASET_SPECS[ds]
        jsonl_path = BENCHMARK_ROOT / ds_spec.evaluation_file
        if not jsonl_path.exists():
            log(f"  WARNING: {jsonl_path} not found, skipping {ds}")
            continue
        all_qs = load_questions(jsonl_path)
        # Filter to validation IDs
        target_ids = set(val_ids.get(ds, []))
        ds_questions[ds] = {q.id: q for q in all_qs if q.id in target_ids}
        log(f"  {ds}: loaded {len(all_qs)} total, {len(ds_questions[ds])} validation")

    # Initialize services
    log("\n[Initializing services]")
    config = AppConfig.from_yaml(REPO / "configs/default.yaml")
    agnes, embedding, reranker = provider_clients(config)
    log("  Services created.")

    # Compile each eligible question with CORRECT path
    log(f"\n[Compiling {len(census)} eligible questions with CORRECT path]")
    t0 = time.time()
    done = 0
    errors = 0
    hash_matches = 0
    hash_mismatches = 0
    hops_matches = 0
    hops_mismatches = 0

    FROZEN_DIR.mkdir(parents=True, exist_ok=True)
    audit_rows = []
    manifest_rows = []

    # Write recovery audit CSV header
    audit_f = open(RECOVERY_AUDIT, "w", newline="")
    audit_writer = csv.DictWriter(audit_f, fieldnames=[
        "dataset", "question_id",
        "census_plan_hash", "recovered_plan_hash", "hash_match",
        "census_hops", "recovered_hops", "hops_match",
        "census_topology", "recovered_topology", "topology_match",
        "recovery_mode", "compile_status", "error",
    ])
    audit_writer.writeheader()

    manifest_f = open(RECOVERY_MANIFEST, "w")

    for qid, census_info in census.items():
        ds = census_info["dataset"]
        done += 1

        question = ds_questions.get(ds, {}).get(qid)
        if question is None:
            errors += 1
            row = {
                "dataset": ds, "question_id": qid,
                "census_plan_hash": census_info["plan_hash"],
                "recovered_plan_hash": None, "hash_match": False,
                "census_hops": census_info["hops"],
                "recovered_hops": -1, "hops_match": False,
                "census_topology": census_info["topology"],
                "recovered_topology": "not_found",
                "topology_match": False,
                "recovery_mode": "unrecoverable",
                "compile_status": "question_not_found",
                "error": "question not found in benchmark file",
            }
            audit_writer.writerow(row)
            audit_f.flush()
            log(f"  [{done}/{len(census)}] {ds}/{qid} NOT FOUND")
            continue

        try:
            # CORRECT compile path — matches validation_compile_census.py
            plan, compiler_metrics = compile_slotrag_plan(SPEC, ds, question, agnes)

            # Compute structural properties
            slot_ids = [s.id for s in plan.slots]
            adj, edge_types, n_operator_edges = derive_structural_evidence_graph(plan)
            structural_hops, structural_nodes = exact_longest_simple_path(adj, slot_ids)
            topology = classify_topology(adj, set(slot_ids), edge_types)

            # Plan hashes
            plan_json = json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
            recovered_hash = hashlib.sha256(plan_json.encode()).hexdigest()[:16]
            census_hash = census_info["plan_hash"]
            hash_match = recovered_hash == census_hash
            hops_match = structural_hops == census_info["hops"]
            topology_match = topology == census_info["topology"]

            if hash_match:
                hash_matches += 1
                recovery_mode = "historical_exact"
            else:
                hash_mismatches += 1
                recovery_mode = "unrecoverable"
            if hops_match:
                hops_matches += 1
            else:
                hops_mismatches += 1

            # Build frozen snapshot (BenchmarkRunner-compatible format)
            compile_input = {
                "stage": "hstruct-v12-census",
                "dataset": ds,
                "question_id": qid,
                "question": question.question,
                "source_method": METHOD_NAME,
                "compiler_options": slotrag_compile_options(SPEC, ds, question),
            }
            input_sha256 = _canonical_sha256(compile_input)

            snapshot = {
                "schema_version": 1,
                "stage": "hstruct-v12-census",
                "dataset": ds,
                "question_id": qid,
                "source_method": METHOD_NAME,
                "input_sha256": input_sha256,
                "compiler_options": compile_input["compiler_options"],
                "attempt_index": 1,
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "wall_latency_ms": getattr(compiler_metrics, "compilation_latency_ms", 0),
                "provider_delta": {},
                "preparation_mode": "v12_census",
                "status": "ok",
                "error": None,
                "failure_category": "ok",
                "plan_sha256": _plan_sha256(plan),
                "plan": plan.model_dump(mode="json"),
                "compiler_metrics": compiler_metrics.model_dump(mode="json"),
                "structural_hops": structural_hops,
                "structural_nodes": structural_nodes,
                "topology": topology,
                "eligible": structural_hops >= 2,
            }

            # Save frozen snapshot
            snap_dir = FROZEN_DIR / ds
            snap_dir.mkdir(parents=True, exist_ok=True)
            snap_path = snap_dir / f"{qid}.json"
            with open(snap_path, "w") as f:
                json.dump(snapshot, f, indent=2, ensure_ascii=False)

            # Audit row
            audit_row = {
                "dataset": ds, "question_id": qid,
                "census_plan_hash": census_hash,
                "recovered_plan_hash": recovered_hash,
                "hash_match": hash_match,
                "census_hops": census_info["hops"],
                "recovered_hops": structural_hops,
                "hops_match": hops_match,
                "census_topology": census_info["topology"],
                "recovered_topology": topology,
                "topology_match": topology_match,
                "recovery_mode": recovery_mode,
                "compile_status": "ok",
                "error": None,
            }
            audit_writer.writerow(audit_row)
            audit_f.flush()

            # Manifest row (for downstream use)
            manifest_row = {
                "dataset": ds,
                "question_id": qid,
                "plan_hash": recovered_hash,
                "census_plan_hash": census_hash,
                "hash_match": hash_match,
                "plan_json": plan_json,
                "n_slots": len(plan.slots),
                "n_edges": len(plan.joins),
                "n_operator_edges": n_operator_edges,
                "structural_hops": structural_hops,
                "structural_nodes": structural_nodes,
                "topology": topology,
                "eligible": structural_hops >= 2,
                "error": None,
            }
            manifest_f.write(json.dumps(manifest_row, ensure_ascii=False) + "\n")
            manifest_f.flush()

            if done % 20 == 0 or done == len(census):
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                eta = (len(census) - done) / rate if rate > 0 else 0
                log(f"  [{done}/{len(census)}] {ds}/{qid} OK hops={structural_hops} "
                    f"hash_match={hash_match} | {elapsed:.0f}s ETA {eta:.0f}s")

        except Exception as e:
            import traceback
            errors += 1
            row = {
                "dataset": ds, "question_id": qid,
                "census_plan_hash": census_info["plan_hash"],
                "recovered_plan_hash": None, "hash_match": False,
                "census_hops": census_info["hops"],
                "recovered_hops": -1, "hops_match": False,
                "census_topology": census_info["topology"],
                "recovered_topology": "error",
                "topology_match": False,
                "recovery_mode": "unrecoverable",
                "compile_status": "error",
                "error": str(e)[:200],
            }
            audit_writer.writerow(row)
            audit_f.flush()
            log(f"  [{done}/{len(census)}] {ds}/{qid} ERROR: {e}")

    audit_f.close()
    manifest_f.close()
    elapsed = time.time() - t0

    log(f"\n{'='*60}")
    log(f"COMPLETE: {done} questions, {done - errors} OK, {errors} errors")
    log(f"Time: {elapsed:.0f}s ({elapsed/done:.1f}s/question)")
    log(f"HASH MATCH: {hash_matches}/{done - errors} exact, {hash_mismatches} mismatch")
    log(f"HOPS MATCH: {hops_matches}/{done - errors} exact, {hops_mismatches} mismatch")
    log(f"Recovery audit: {RECOVERY_AUDIT}")
    log(f"Frozen snapshots: {FROZEN_DIR}/")
    log(f"Manifest: {RECOVERY_MANIFEST}")

    # Summary
    if hash_matches == done - errors:
        log(f"\n*** CASE A: All {hash_matches} plans exact-recovered. V1.1 preserved. ***")
    else:
        log(f"\n*** CASE B: {hash_mismatches} plans unrecoverable. V1.2 REQUIRED. ***")
        log(f"    Original census plan hashes differ from re-compilation.")
        log(f"    V1.1 eligibility preserved for reference, V1.2 supersedes.")


if __name__ == "__main__":
    main()
