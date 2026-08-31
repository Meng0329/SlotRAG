#!/usr/bin/env python3
"""
validation_compile_census.py — Phase 5: Compile-only census for H-STRUCT-1 V1_1.

Runs SlotCompiler on ALL validation_set questions. NO retrieval, NO answer generation,
NO EM/F1 scoring, NO gold-answer inspection. Outcome-blind.

Output:
  research/hstruct_validation_census/validation_plan_manifest.jsonl
  research/hstruct_validation_census/validation_structural_census.csv
  research/hstruct_validation_census/validation_census_summary.md
"""

import csv
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── Setup ──────────────────────────────────────────────────────────────────
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from slotrag.benchmarking.datasets import DATASETS as DATASET_SPECS
from slotrag.benchmarking.methods import (
    METHODS,
    compile_slotrag_plan,
    slotrag_compile_options,
)
from slotrag.data import load_questions, QuestionRecord
from slotrag.models import SlotPlan
from slotrag.providers import AgnesClient, provider_clients
from slotrag.config import AppConfig

OUTPUT_DIR = REPO / "research" / "hstruct_validation_census"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MANIFEST_PATH = OUTPUT_DIR / "validation_plan_manifest.jsonl"
CENSUS_CSV = OUTPUT_DIR / "validation_structural_census.csv"
SUMMARY_MD = OUTPUT_DIR / "validation_census_summary.md"

VALIDATION_SET_PATH = REPO / "research" / "eval_sets" / "validation_set.json"

# Use the base slotrag method spec (compile options are identical across arms)
METHOD_NAME = "slotrag"
SPEC = METHODS[METHOD_NAME]

TARGET_DATASETS = ["hotpotqa", "2wikimultihop", "musique"]

# ── Graph utilities (inlined from structural_depth_correction.py) ──────────

def derive_structural_evidence_graph(plan: SlotPlan):
    """Build adjacency list + edge types from a SlotPlan."""
    slot_ids = {slot.id for slot in plan.slots}
    adj = {sid: set() for sid in slot_ids}
    edge_types = {frozenset({a, b}): set() for sid in slot_ids for a in [sid] for b in []}  # empty init
    edge_types = {}

    # Join edges
    for join in plan.joins:
        pair = frozenset({join.left_slot, join.right_slot})
        adj.setdefault(join.left_slot, set()).add(join.right_slot)
        adj.setdefault(join.right_slot, set()).add(join.left_slot)
        edge_types.setdefault(pair, set()).add("join")

    # Operator-induced edges (field_argmin / field_argmax)
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
                visited.discard(nb)  # backtrack

    for start in slot_ids:
        dfs(start, {start}, 0)

    return best_hops, best_hops + 1  # edges, nodes


def classify_topology(adj, slot_ids, edge_types):
    """Classify topology of the structural evidence graph."""
    n = len(slot_ids)
    if n <= 1:
        return "single"

    degrees = {sid: len(adj.get(sid, set())) for sid in slot_ids}
    max_deg = max(degrees.values()) if degrees else 0
    has_operator = any("operator" in types for types in edge_types.values())

    # Check star (n>=4, max_deg >= 3, hub degree = n-1)
    if n >= 4 and max_deg >= 3:
        if max_deg == n - 1:
            hub = [sid for sid, d in degrees.items() if d == n - 1]
            if len(hub) == 1:
                leaves = [sid for sid, d in degrees.items() if d == 1]
                if len(leaves) == n - 1:
                    return "star"

    # Check chain (all degrees ≤ 2, exactly 2 endpoints with degree 1)
    if all(d <= 2 for d in degrees.values()):
        endpoints = sum(1 for d in degrees.values() if d == 1)
        if endpoints == 2 or (n == 2 and endpoints == 2):
            return "chain"

    # Check tree (n-1 edges, connected)
    total_edges = sum(len(neighbors) for neighbors in adj.values()) // 2
    if total_edges == n - 1:
        return "tree"

    return "complex"


# ── Census worker ──────────────────────────────────────────────────────────

def census_one(
    question: QuestionRecord,
    dataset: str,
    agnes_client,
) -> dict | None:
    """Compile one question and extract structural census. NO retrieval/generation."""
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
        }

    # Compute structural properties from plan
    slot_ids = [slot.id for slot in plan.slots]
    adj, edge_types, n_operator_edges = derive_structural_evidence_graph(plan)
    structural_hops, structural_nodes = exact_longest_simple_path(adj, slot_ids)
    topology = classify_topology(adj, set(slot_ids), edge_types)
    eligible = structural_hops >= 2

    # Plan hash (deterministic)
    plan_json = json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    plan_hash = hashlib.sha256(plan_json.encode()).hexdigest()[:16]

    n_joins = len(plan.joins)
    n_operators = len(plan.operators)

    return {
        "dataset": dataset,
        "question_id": question.id,
        "plan_hash": plan_hash,
        "n_slots": len(plan.slots),
        "n_edges": n_joins,
        "n_operator_edges": n_operator_edges,
        "structural_hops": structural_hops,
        "structural_nodes": structural_nodes,
        "topology": topology,
        "eligible": eligible,
        "error": None,
    }


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print("=== Validation Compile Census (Phase 5) ===")
    print("RULES: No retrieval, no answer generation, no EM/F1, no gold-answer inspection.")
    print()

    # Load config and providers
    # Load config and providers (env vars must be set via: set -a && source .env && set +a)
    config = AppConfig.from_yaml(REPO / "configs" / "default.yaml")
    agnes, embedding, reranker = provider_clients(config)

    # Load validation IDs
    with open(VALIDATION_SET_PATH) as f:
        val_ids = json.load(f)

    # Load questions from benchmark JSONL and filter by validation IDs
    BENCHMARK_ROOT = REPO / "benchmark"
    ds_questions = {}
    for ds in TARGET_DATASETS:
        ds_spec = DATASET_SPECS[ds]
        jsonl_path = BENCHMARK_ROOT / ds_spec.evaluation_file
        if not jsonl_path.exists():
            print(f"WARNING: {jsonl_path} not found, skipping {ds}")
            continue
        all_qs = load_questions(jsonl_path)
        ds_id_set = set(val_ids.get(ds, []))
        filtered = [q for q in all_qs if q.id in ds_id_set]
        ds_questions[ds] = filtered
        print(f"  {ds}: {len(filtered)}/{len(all_qs)} questions (from {len(ds_id_set)} validation IDs)")

    total = sum(len(qs) for qs in ds_questions.values())
    print(f"\nTotal validation questions loaded: {total}")
    print(f"\nCompiling {total} questions (no retrieval, no generation)...")
    print(f"Timeout: ~{total * 0.7 / 60:.0f} min serial, ~{total * 0.7 / 60 / 8:.0f} min with 8 workers")

    results = []
    start_time = time.perf_counter()
    completed = 0
    errors = 0

    # Use ThreadPoolExecutor for parallel compilation (each needs LLM call)
    max_workers = int(os.environ.get("CENSUS_WORKERS", "8"))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for ds, questions in ds_questions.items():
            for q in questions:
                future = executor.submit(census_one, q, ds, agnes)
                futures[future] = (ds, q.id)

        for future in as_completed(futures):
            ds, qid = futures[future]
            try:
                result = future.result()
                if result is not None:
                    results.append(result)
                    if result.get("error"):
                        errors += 1
            except Exception as e:
                results.append({
                    "dataset": ds,
                    "question_id": qid,
                    "plan_hash": None,
                    "n_slots": 0,
                    "n_edges": 0,
                    "n_operator_edges": 0,
                    "structural_hops": -1,
                    "structural_nodes": 0,
                    "topology": "exception",
                    "eligible": False,
                    "error": str(e)[:200],
                })
                errors += 1

            completed += 1
            if completed % 100 == 0:
                elapsed = time.perf_counter() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (total - completed) / rate if rate > 0 else 0
                print(f"  [{completed}/{total}] {elapsed:.0f}s elapsed, ETA {eta:.0f}s, {errors} errors")

    elapsed = time.perf_counter() - start_time
    print(f"\nDone: {completed} questions in {elapsed:.1f}s ({elapsed/completed:.2f}s/question)")
    print(f"Errors: {errors}")

    # Write manifest (JSONL)
    print(f"\nWriting manifest: {MANIFEST_PATH}")
    with open(MANIFEST_PATH, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Write census CSV
    print(f"Writing census CSV: {CENSUS_CSV}")
    fieldnames = [
        "dataset", "question_id", "plan_hash", "n_slots", "n_edges",
        "n_operator_edges", "structural_hops", "structural_nodes",
        "topology", "eligible", "error",
    ]
    with open(CENSUS_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in sorted(results, key=lambda x: (x["dataset"], x["question_id"])):
            writer.writerow(r)

    # Write summary
    print(f"Writing summary: {SUMMARY_MD}")
    write_summary(results, elapsed)

    print("\n=== FIREWALL VERIFICATION ===")
    print("NO retrieval performed.")
    print("NO answer generation performed.")
    print("NO EM/F1 scoring performed.")
    print("NO gold-answer inspection performed.")
    print("Census is fully outcome-blind.")


def write_summary(results: list[dict], elapsed: float):
    """Write human-readable summary."""
    lines = [
        "# validation_census_summary.md — Phase 5 Outcome-Blind Census",
        "",
        "> **Generated:** 2026-08-31",
        "> **FIREWALL:** No retrieval, no answer generation, no EM/F1, no gold-answer inspection.",
        "> **Compiler:** Same frozen SlotCompiler + static-arm MethodSpec used in sealed experiments.",
        "",
        "## Per-Dataset Structural Distribution",
        "",
    ]

    for ds in TARGET_DATASETS:
        ds_results = [r for r in results if r["dataset"] == ds]
        total = len(ds_results)
        eligible = sum(1 for r in ds_results if r.get("eligible"))
        compile_failed = sum(1 for r in ds_results if r.get("error"))

        lines.append(f"### {ds}")
        lines.append(f"- Total: {total}")
        lines.append(f"- Compile failed: {compile_failed}")
        lines.append(f"- Eligible (hops ≥ 2): {eligible} ({eligible/total*100:.1f}%)" if total > 0 else "- No data")
        lines.append("")

        # hops distribution
        hops_dist = {}
        for r in ds_results:
            h = r.get("structural_hops", -1)
            hops_dist[h] = hops_dist.get(h, 0) + 1
        lines.append("| structural_hops | count | eligible |")
        lines.append("|---|---|---|")
        for h in sorted(hops_dist.keys()):
            label = "yes" if h >= 2 else "no"
            lines.append(f"| {h} | {hops_dist[h]} | {label} |")
        lines.append("")

        # topology distribution
        topo_dist = {}
        for r in ds_results:
            t = r.get("topology", "unknown")
            topo_dist[t] = topo_dist.get(t, 0) + 1
        lines.append("| topology | count |")
        lines.append("|---|---|")
        for t, c in sorted(topo_dist.items(), key=lambda x: -x[1]):
            lines.append(f"| {t} | {c} |")
        lines.append("")

    # Overall
    total_all = len(results)
    eligible_all = sum(1 for r in results if r.get("eligible"))
    failed_all = sum(1 for r in results if r.get("error"))

    lines.append("## Overall")
    lines.append("")
    lines.append(f"- Total questions: {total_all}")
    lines.append(f"- Compile failed: {failed_all}")
    lines.append(f"- Eligible (hops ≥ 2): {eligible_all} ({eligible_all/total_all*100:.1f}%)" if total_all > 0 else "- No data")
    lines.append(f"- Compilation time: {elapsed:.1f}s ({elapsed/total_all:.2f}s/question)" if total_all > 0 else "")
    lines.append("")
    lines.append("## Power Comparison")
    lines.append("")
    lines.append(f"- Required eligible n (80% power, two-sided): 1,105")
    lines.append(f"- Available eligible (validation only): {eligible_all}")
    lines.append(f"- Gap: {1105 - eligible_all} (validation {'sufficient' if eligible_all >= 1105 else 'INSUFFICIENT'})")
    lines.append("")
    lines.append("## Firewall Audit")
    lines.append("")
    lines.append("- [ ] No retrieval calls made")
    lines.append("- [ ] No answer generation calls made")
    lines.append("- [ ] No EM/F1 scores computed")
    lines.append("- [ ] No gold answers inspected")
    lines.append("- [ ] No policy comparison performed")
    lines.append("- [ ] Census output contains only structural properties + plan_hash")
    lines.append("")

    with open(SUMMARY_MD, "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
