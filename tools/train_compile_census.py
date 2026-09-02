#!/usr/bin/env python3
"""
train_compile_census.py — V1.3: PARALLEL census for train supplement

V1.3: ThreadPoolExecutor parallel compilation (~16 workers).
Resume support: skips questions already in existing CSV.
Thread-safe: Lock-protected CSV writes + counters.

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
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
MAX_WORKERS = 16


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


def load_processed_ids(csv_path: Path) -> set:
    """Load already-processed (dataset, question_id) pairs from existing CSV.

    Only rows WITHOUT an error count as processed — an error row means the
    compile failed and must be retried on resume (otherwise a batch launched
    without env would mark every question as done-with-0-eligible)."""
    processed = set()
    if not csv_path.exists():
        return processed
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("error"):
                continue
            processed.add((row["dataset"], row["question_id"]))
    return processed


def main():
    print("=== Train Compile Census (V1.3 — PARALLEL, 16 workers) ===")
    print("FIREWALL: SlotCompiler ONLY. No retrieval, no generation, no EM/F1.")
    print(f"Compile path: compile_slotrag_plan(METHODS['{METHOD_NAME}'], dataset, full_question_record, agnes)")
    print(f"Targets: {TARGETS}")
    print(f"Seed: {SEED}")
    print(f"Workers: {MAX_WORKERS}")
    print()

    config = AppConfig.from_yaml(REPO / "configs" / "default.yaml")

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

    # Resume: skip already-processed questions
    processed = load_processed_ids(CENSUS_CSV)
    if processed:
        print(f"  RESUME: {len(processed)} questions already processed, skipping them")

    csv_fields = [
        "dataset", "question_id", "plan_hash", "n_slots", "n_edges",
        "n_operator_edges", "structural_hops", "structural_nodes",
        "topology", "eligible", "error",
    ]

    # Build work queue per dataset: (dataset, question_id, question) for
    # unprocessed questions, ordered by deterministic shuffle.  Only enqueue
    # until the dataset's eligible target is projected to be reached; a
    # sliding in-flight window (see execution below) enforces the hard stop.
    eligible_done = {ds: sum(1 for (d, _) in processed if d == ds) for ds in TARGETS}
    work = []
    for dataset in ["hotpotqa", "2wikimultihop", "musique"]:
        if dataset not in ds_questions:
            continue
        target = TARGETS[dataset]
        questions = ds_questions[dataset]
        print(f"--- {dataset}: target={target} eligible, pool={len(questions)}, "
              f"already_eligible={eligible_done[dataset]}, already_processed="
              f"{sum(1 for (ds, _) in processed if ds == dataset)} ---")
        for qid, question in questions.items():
            if (dataset, qid) in processed:
                continue
            work.append((dataset, qid, question))

    total_work = len(work)
    total_all = sum(len(q) for q in ds_questions.values())
    print(f"\n  Total questions: {total_all}, already processed: {len(processed)}, "
          f"remaining: {total_work}")
    print(f"  Estimated time: ~{total_work * 14 / MAX_WORKERS / 60:.0f} min "
          f"(vs ~{total_work * 14 / 60:.0f} min serial)")
    print()

    # Create agnes client (file-based rate limiters are thread-safe)
    agnes, embedding, reranker = provider_clients(config)

    # Thread-safe state
    csv_lock = threading.Lock()
    counter_lock = threading.Lock()
    eligible_by_ds = {ds: [] for ds in TARGETS}
    failures_by_ds = {ds: [] for ds in TARGETS}
    compiled_count = 0
    eligible_count = 0
    error_count = 0
    start_time = time.time()

    # Append to existing CSV (or create new)
    csv_file = open(CENSUS_CSV, "a", newline="")
    writer = csv.DictWriter(csv_file, fieldnames=csv_fields)
    if not processed:
        writer.writeheader()
        csv_file.flush()

    def do_one(item):
        dataset, qid, question = item
        result, snapshot, compile_input = compile_one(dataset, question, agnes)

        # Thread-safe CSV write
        with csv_lock:
            csv_row = {k: result[k] for k in csv_fields}
            writer.writerow(csv_row)
            csv_file.flush()

        # Thread-safe snapshot save (if eligible)
        if snapshot and result["eligible"]:
            snap_dir = FROZEN_DIR / dataset
            snap_dir.mkdir(parents=True, exist_ok=True)
            snap_path = snap_dir / f"{qid}.json"
            with open(snap_path, "w") as f:
                json.dump(snapshot, f, indent=2, ensure_ascii=False)

        return result

    # Execute in parallel with a sliding in-flight window.  Preserve the
    # serial "stop when target reached" semantics: once a dataset reaches its
    # eligible target (counting already-completed eligible from resume), no
    # further items of that dataset are submitted.
    dataset_target_left = {ds: max(0, TARGETS[ds] - eligible_done[ds]) for ds in TARGETS}

    def dataset_done(item_ds: str) -> bool:
        return dataset_target_left[item_ds] <= 0

    # Drop datasets already at/above their resume-eligible target from work,
    # and memorize a stable mapping for futures -> items.
    work = [item for item in work if not dataset_done(item[0])]
    futures_map: dict = {}
    work_iter = iter(work)
    submitted = 0

    def maybe_fill(pool, in_flight):
        nonlocal submitted
        # submit up to the window, skipping items whose dataset target is met
        while len(in_flight) < MAX_WORKERS * 2:
            try:
                item = next(work_iter)
            except StopIteration:
                break
            if dataset_done(item[0]):
                continue
            submitted += 1
            future = pool.submit(do_one, item)
            futures_map[future] = item
            in_flight.add(future)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        in_flight: set = set()
        maybe_fill(pool, in_flight)
        i = 0
        while in_flight:
            snapshot = tuple(in_flight)
            for future in as_completed(snapshot):
                in_flight.discard(future)
                item = futures_map.get(future)
                try:
                    result = future.result()
                except Exception as e:
                    print(f"  FATAL: {item[0]}/{item[1] if item else '?'} {e}")
                    with counter_lock:
                        error_count += 1
                    i += 1
                    maybe_fill(pool, in_flight)
                    continue

                with counter_lock:
                    compiled_count += 1
                    if result["error"]:
                        error_count += 1
                        with csv_lock:
                            failures_by_ds[result["dataset"]].append(result)
                    elif result["eligible"]:
                        eligible_count += 1
                        with csv_lock:
                            eligible_by_ds[result["dataset"]].append(result)
                        ds = result["dataset"]
                        if dataset_target_left[ds] > 0:
                            dataset_target_left[ds] -= 1
                            if dataset_target_left[ds] == 0:
                                print(f"  TARGET REACHED: {ds} "
                                      f"(eligible+resume={sum(len(v) for v in eligible_by_ds.values()) + sum(v for v in eligible_done.values())})")

                i += 1
                total_done = len(processed) + compiled_count
                if i % 100 == 0 or i == len(work):
                    elapsed = time.time() - start_time
                    rate = compiled_count / elapsed if elapsed > 0 else 0
                    eta = (max(len(work) - submitted, 0) + len(in_flight)) / rate if rate > 0 else 0
                    print(f"  [{total_done}/{len(work)+len(processed)}] compiled={compiled_count} "
                          f"eligible={eligible_count} errors={error_count} "
                          f"| {elapsed:.0f}s elapsed, ETA {eta:.0f}s "
                          f"| {rate:.1f} q/s")
                maybe_fill(pool, in_flight)

    csv_file.close()

    # Build eligible manifest deterministically from the census CSV.  The
    # manifest must reflect the FIRST `target` eligible questions per dataset
    # in the deterministic shuffle order (completion order in the parallel
    # run is not shuffle order, so it cannot be used).  Rebuilt fresh from
    # the CSV on every resume so the manifest never duplicates rows.
    csv_rows: dict[tuple[str, str], dict] = {}
    with open(CENSUS_CSV) as f:
        for row in csv.DictReader(f):
            csv_rows[(row["dataset"], row["question_id"])] = row

    selected: list[dict] = []
    missing_plan = 0
    for ds in ["hotpotqa", "2wikimultihop", "musique"]:
        if ds not in ds_questions:
            continue
        target = TARGETS[ds]
        count = 0
        for qid, question in ds_questions[ds].items():
            if count >= target:
                break
            row = csv_rows.get((ds, qid))
            if row is None or row["eligible"] != "True":
                continue
            snap_path = FROZEN_DIR / ds / f"{qid}.json"
            if not snap_path.exists():
                missing_plan += 1
                continue
            snap = json.load(open(snap_path))
            plan = snap["plan"]
            selected.append({
                "dataset": ds,
                "question_id": qid,
                "source_split": "train",
                "plan_json": json.dumps(plan, sort_keys=True, separators=(",", ":")),
            })
            count += 1

    with open(ELIGIBLE_JSONL, "w") as f:
        for item in selected:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    # Write failures fresh from the CSV (all compile_failed rows)
    with open(FAILURES_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=csv_fields)
        w.writeheader()
        seen_fail: set[tuple[str, str]] = set()
        for (ds, qid), row in csv_rows.items():
            if row["error"] and (ds, qid) not in seen_fail:
                seen_fail.add((ds, qid))
                w.writerow({k: row.get(k, "") for k in csv_fields})

    if missing_plan:
        print(f"  WARNING: {missing_plan} eligible rows missing frozen snapshots")

    elapsed = time.time() - start_time
    total_compiled = len(processed) + compiled_count
    total_eligible = eligible_count  # from this run only; need to recount from CSV
    # Recount all eligible from CSV
    all_eligible = 0
    for ds in TARGETS:
        with open(CENSUS_CSV) as f:
            reader = csv.DictReader(f)
            ds_eligible = sum(1 for row in reader if row["dataset"] == ds and row["eligible"] == "True")
            all_eligible += ds_eligible

    print(f"\n{'='*60}")
    print(f"V1.3 TRAIN CENSUS COMPLETE (PARALLEL)")
    print(f"{'='*60}")
    print(f"Time: {elapsed:.0f}s ({elapsed/max(compiled_count,1):.1f}s/question)")
    print(f"Total compiled: {total_compiled}")
    print(f"Total eligible: {all_eligible}/{sum(TARGETS.values())}")
    for ds in ["hotpotqa", "2wikimultihop", "musique"]:
        with open(CENSUS_CSV) as f:
            reader = csv.DictReader(f)
            ds_eligible = sum(1 for row in reader if row["dataset"] == ds and row["eligible"] == "True")
        print(f"  {ds}: {ds_eligible}/{TARGETS[ds]} eligible")

    all_met = all(
        sum(1 for row in csv.DictReader(open(CENSUS_CSV))
            if row["dataset"] == ds and row["eligible"] == "True") >= TARGETS[ds]
        for ds in TARGETS
    )
    if all_met:
        print(f"\nALL TARGETS MET.")
    else:
        print(f"\nWARNING: Not all targets met!")
        for ds in TARGETS:
            with open(CENSUS_CSV) as f:
                reader = csv.DictReader(f)
                ds_eligible = sum(1 for row in reader if row["dataset"] == ds and row["eligible"] == "True")
            if ds_eligible < TARGETS[ds]:
                print(f"  {ds}: {ds_eligible}/{TARGETS[ds]} — SHORT")

    print(f"\nOutputs:")
    print(f"  Census CSV: {CENSUS_CSV}")
    print(f"  Eligible manifest: {ELIGIBLE_JSONL}")
    print(f"  Frozen snapshots: {FROZEN_DIR}/")


if __name__ == "__main__":
    main()
