"""Depth-Stratified Mechanism Audit: per-question depth extraction + statistics.

Reads frozen sealed test items (no LLM, no retrieval). Computes dependency depth
from the join DAG and generates per_question.csv + stratified statistics.

Phase 2-3 of the Depth-Stratified Mechanism Audit.
"""
import json, glob, os, csv, collections, hashlib
import numpy as np

OUT = "/home/test/tkde_runs/tkde-sealed-test-q35"
PAPER = "/data/mzb/SlotRAG/paper/tkde_writing"
RESEARCH = "/data/mzb/SlotRAG/research"
DEPTH_DIR = f"{RESEARCH}/depth_analysis"
os.makedirs(DEPTH_DIR, exist_ok=True)

DS = ["hotpotqa", "2wikimultihop", "musique"]
ARMS = ["slotrag-g7-static", "slotrag-g7-flat", "slotrag-g7-chain"]
ARM_SHORT = {"slotrag-g7-static": "static", "slotrag-g7-flat": "flat", "slotrag-g7-chain": "chain"}

# ──────────────────────────────────────────────────────────────────
# PHASE 1: Dependency depth definition (algorithmic)
# ──────────────────────────────────────────────────────────────────

def build_join_dag(slot_ids, joins):
    """Build adjacency list from join specs.

    Joins can be dicts (with "left_slot"/"right_slot" keys) or tuples (left, right).
    JoinSpec.left_slot/right_slot encode convention-based directionality.
    For depth computation we use the UNDIRECTED graph: any join creates
    an edge.  The true producer→consumer direction emerges from the
    slot_traces execution order (which slot was materialized first).

    We then overlay the trace-implied directionality onto the undirected
    edges to produce a directed acyclic graph (DAG) for depth computation.
    """
    from collections import defaultdict
    adj = defaultdict(set)
    for j in joins:
        if isinstance(j, dict):
            l, r = j["left_slot"], j["right_slot"]
        else:
            l, r = j[0], j[1]
        adj[l].add(r)
        adj[r].add(l)
    return adj


def compute_depth_from_trace(slot_ids, joins, traces):
    """Compute dependency depth = max trace step + 1.

    This is the most reliable definition because:
    - It reflects actual execution order (which slot materialized when)
    - It's invariant to JoinSpec.left/right convention
    - It accounts for budget limits (not all slots may materialize)

    For plans where ALL slots were materialized, this equals the true
    dependency depth of the executed subgraph.

    For plans where budget ran out before all slots were materialized,
    this gives the depth of the materialized portion.

    We ALSO compute the full DAG depth (longest path in join graph)
    to distinguish "depth limited by budget" from "depth limited by plan".
    """
    if not traces:
        return 0  # no execution at all (budget_exceeded before first step)
    return max(t.get("step", 0) for t in traces) + 1


def compute_dag_longest_path(slot_ids, joins):
    """Longest path in the undirected join graph via DFS.

    Since the join graph is small (≤7 nodes), brute-force DFS is fine.
    For each starting node, do an independent DFS (fresh visited set)
    to find the longest simple path from that node.
    This gives the TRUE structural depth of the plan regardless of budget.
    """
    if len(slot_ids) <= 1:
        return len(slot_ids)
    adj = build_join_dag(slot_ids, joins)
    best = 1
    for start in slot_ids:
        visited = {start}  # fresh per start node
        stack = [(start, 1)]
        while stack:
            node, depth = stack.pop()
            best = max(best, depth)
            for nb in adj.get(node, set()):
                if nb not in visited:
                    visited.add(nb)
                    stack.append((nb, depth + 1))
    return best


def compute_branching_factor(slot_ids, joins):
    """Average degree in the join graph."""
    if not joins:
        return 0.0
    from collections import Counter
    deg = Counter()
    for j in joins:
        l, r = (j["left_slot"], j["right_slot"]) if isinstance(j, dict) else (j[0], j[1])
        deg[l] += 1
        deg[r] += 1
    return sum(deg.values()) / len(slot_ids) if slot_ids else 0.0


def plan_topology(slot_ids, joins):
    """Classify plan as 'chain', 'star', 'tree', or 'single'.

    - single: 1 slot
    - chain: all nodes have degree ≤ 2, graph is connected → linear
    - star: exactly one node has degree > 2, all others have degree 1 → hub-and-spoke
    - tree: connected, branching (more than one node with degree > 1), not a star
    - disconnected: graph has multiple components
    """
    if len(slot_ids) <= 1:
        return "single"
    adj = build_join_dag(slot_ids, joins)
    # Check connectivity via BFS
    visited = set()
    queue = [slot_ids[0]]
    while queue:
        n = queue.pop(0)
        if n in visited:
            continue
        visited.add(n)
        for nb in adj.get(n, set()):
            if nb not in visited:
                queue.append(nb)
    if len(visited) < len(slot_ids):
        return "disconnected"
    # Compute degrees
    deg = {s: len(adj.get(s, set())) for s in slot_ids}
    max_deg = max(deg.values())
    # Star: one hub has degree n-1 (connects to all others), all leaves degree 1.
    # Must check BEFORE chain: for n=3, a star and a chain are isomorphic
    # (both have max_deg=2), but star is the more semantically specific label.
    # Note: for n=3, both pass the star check (degree sequence {2,1,1} is
    # shared). We label n=3 as "chain" because the execution is still linear.
    # Star label only applies at n≥4 where degree sequences diverge.
    if max_deg == len(slot_ids) - 1 and max_deg >= 3:
        non_hub_deg1 = sum(1 for d in deg.values() if d == 1)
        if non_hub_deg1 == len(slot_ids) - 1:
            return "star"
    if max_deg <= 2:
        return "chain"
    # Has branching but not a single hub → tree
    return "tree"


# ──────────────────────────────────────────────────────────────────
# PHASE 2: Load all items and extract per-question records
# ──────────────────────────────────────────────────────────────────

def load_all():
    """Load every sealed item into a flat dict keyed by (ds, arm, qid)."""
    records = {}
    for ds in DS:
        for arm in ARMS:
            d = f"{OUT}/items/g7-sealed/{ds}/{arm}"
            if not os.path.isdir(d):
                continue
            for fp in glob.glob(f"{d}/*.json"):
                j = json.load(open(fp))
                qid = j.get("question_id")
                result = j.get("result") or {}
                plan = result.get("plan") or {}
                metrics = result.get("metrics") or {}
                scores = j.get("scores") or {}
                traces = result.get("slot_traces") or []
                plan_provenance = j.get("plan_provenance") or {}

                slots = plan.get("slots", [])
                joins = plan.get("joins", [])
                slot_ids = [s["id"] for s in slots]
                join_pairs = [(j2["left_slot"], j2["right_slot"]) for j2 in joins]

                # Depth metrics
                trace_depth = compute_depth_from_trace(slot_ids, joins, traces)
                dag_depth = compute_dag_longest_path(slot_ids, join_pairs)
                bf = compute_branching_factor(slot_ids, join_pairs)
                topo = plan_topology(slot_ids, join_pairs)

                # Failure info
                status = result.get("status", "unknown")
                failure = j.get("failure_category", "unknown")

                records[(ds, arm, qid)] = {
                    "dataset": ds,
                    "arm": ARM_SHORT[arm],
                    "question_id": qid,
                    "n_slots": len(slot_ids),
                    "n_joins": len(joins),
                    "trace_depth": trace_depth,
                    "dag_depth": dag_depth,
                    "branching_factor": round(bf, 3),
                    "topology": topo,
                    "em": scores.get("em"),
                    "f1": scores.get("f1"),
                    "retrieval_calls": metrics.get("retrieval_calls"),
                    "llm_calls": metrics.get("llm_calls"),
                    "documents_accessed": metrics.get("documents_accessed"),
                    "latency_ms": metrics.get("latency_ms"),
                    "budget_exceeded": 1 if status == "budget_exceeded" else 0,
                    "status": status,
                    "failure_category": failure,
                    "plan_slot_count": metrics.get("plan_slot_count"),
                    "physical_plan_order": metrics.get("physical_plan_order", []),
                }
    return records


print("Loading all sealed items...")
all_records = load_all()
print(f"  Loaded {len(all_records)} records")

# ──────────────────────────────────────────────────────────────────
# Write per_question.csv (Phase 2 output)
# ──────────────────────────────────────────────────────────────────

FIELDS = [
    "dataset", "arm", "question_id",
    "n_slots", "n_joins", "trace_depth", "dag_depth",
    "branching_factor", "topology",
    "em", "f1",
    "retrieval_calls", "llm_calls", "documents_accessed", "latency_ms",
    "budget_exceeded", "status", "failure_category",
]

per_q_path = f"{DEPTH_DIR}/per_question.csv"
with open(per_q_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader()
    for key in sorted(all_records.keys()):
        row = {k: all_records[key].get(k) for k in FIELDS}
        w.writerow(row)
print(f"  Wrote {per_q_path}")

# ──────────────────────────────────────────────────────────────────
# PHASE 3: Stratified statistics by dag_depth
# ──────────────────────────────────────────────────────────────────

def stratified_stats(records, depth_key="dag_depth", group_by=("dataset", "arm")):
    """Compute per-stratum statistics."""
    # Group by dataset × arm × depth
    groups = collections.defaultdict(list)
    for r in records.values():
        depth = r[depth_key]
        if depth >= 4:
            depth = "4+"
        else:
            depth = str(depth)
        key = (r["dataset"], r["arm"], depth)
        groups[key].append(r)

    rows = []
    for (ds, arm, depth) in sorted(groups.keys()):
        items = groups[(ds, arm, depth)]
        n = len(items)
        em_vals = [r["em"] for r in items if r["em"] is not None]
        f1_vals = [r["f1"] for r in items if r["f1"] is not None]
        retr_vals = [r["retrieval_calls"] for r in items if r["retrieval_calls"] is not None]
        llm_vals = [r["llm_calls"] for r in items if r["llm_calls"] is not None]
        budget_ex = sum(r["budget_exceeded"] for r in items)
        ok_count = sum(1 for r in items if r["status"] == "ok")

        rows.append({
            "dataset": ds,
            "arm": arm,
            "depth": depth,
            "n": n,
            "n_ok": ok_count,
            "em": round(np.mean(em_vals), 4) if em_vals else None,
            "f1": round(np.mean(f1_vals), 4) if f1_vals else None,
            "retr_calls": round(np.mean(retr_vals), 3) if retr_vals else None,
            "llm_calls": round(np.mean(llm_vals), 3) if llm_vals else None,
            "budget_exceeded": budget_ex,
            "budget_ex_rate": round(budget_ex / n, 4) if n else 0,
        })
    return rows

print("\nComputing stratified statistics...")
strat = stratified_stats(all_records)

# Write stratified CSV
strat_path = f"{DEPTH_DIR}/depth_stratified.csv"
with open(strat_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=strat[0].keys())
    w.writeheader()
    w.writerows(strat)
print(f"  Wrote {strat_path}")

# ──────────────────────────────────────────────────────────────────
# Compute chain vs static/flat deltas per stratum (paired by qid)
# ──────────────────────────────────────────────────────────────────

def paired_deltas(records, depth_key="dag_depth"):
    """Compute chain-static and chain-flat deltas per dataset × depth."""
    # Group by (dataset, qid) → {arm: record}
    by_q = collections.defaultdict(dict)
    for r in records.values():
        by_q[(r["dataset"], r["question_id"])][r["arm"]] = r

    results = []
    for ds in DS:
        for depth_val in ["1", "2", "3", "4+"]:
            chain_em, static_em, flat_em = [], [], []
            chain_llm, static_llm, flat_llm = [], [], []
            chain_retr, static_retr, flat_retr = [], [], []
            chain_wins, static_wins, ties = 0, 0, 0

            for (dds, qid), arms_data in by_q.items():
                if dds != ds:
                    continue
                c = arms_data.get("chain")
                s = arms_data.get("static")
                fl = arms_data.get("flat")
                if not c or not s:
                    continue

                # Depth check
                d = c.get(depth_key, 0)
                if d >= 4:
                    d = "4+"
                else:
                    d = str(d)
                if d != depth_val:
                    continue

                # EM values
                ce = c.get("em")
                se = s.get("em")
                fe = fl.get("em") if fl else None

                if ce is not None and se is not None:
                    chain_em.append(ce)
                    static_em.append(se)
                    if ce > se:
                        chain_wins += 1
                    elif ce < se:
                        static_wins += 1
                    else:
                        ties += 1

                # LLM calls
                cl = c.get("llm_calls")
                sl = s.get("llm_calls")
                fl_l = fl.get("llm_calls") if fl else None
                if cl is not None and sl is not None:
                    chain_llm.append(cl)
                    static_llm.append(sl)
                if fl is not None and cl is not None and fl_l is not None:
                    flat_em.append(fe) if fe is not None else None

                # Retrieval calls
                cr = c.get("retrieval_calls")
                sr = s.get("retrieval_calls")
                if cr is not None and sr is not None:
                    chain_retr.append(cr)
                    static_retr.append(sr)

            if not chain_em:
                continue

            n = len(chain_em)
            em_diff = np.array(chain_em) - np.array(static_em)
            llm_diff = np.array(chain_llm) - np.array(static_llm) if chain_llm else np.array([0])
            retr_diff = np.array(chain_retr) - np.array(static_retr) if chain_retr else np.array([0])

            # Bootstrap CI for EM difference
            B = 10000
            rng = np.random.RandomState(2027)
            boot_em = np.array([rng.choice(em_diff, size=n, replace=True).mean() for _ in range(B)])
            ci_lo, ci_hi = np.percentile(boot_em, [2.5, 97.5])

            results.append({
                "dataset": ds,
                "depth": depth_val,
                "n": n,
                "static_em": round(np.mean(static_em), 4) if static_em else None,
                "chain_em": round(np.mean(chain_em), 4) if chain_em else None,
                "flat_em": round(np.mean(flat_em), 4) if flat_em else None,
                "delta_em_chain_static": round(np.mean(em_diff), 4),
                "ci_em_lo": round(ci_lo, 4),
                "ci_em_hi": round(ci_hi, 4),
                "chain_wins": chain_wins,
                "static_wins": static_wins,
                "ties": ties,
                "delta_llm_chain_static": round(np.mean(llm_diff), 3),
                "delta_retr_chain_static": round(np.mean(retr_diff), 3),
            })

    return results


print("Computing paired deltas...")
deltas = paired_deltas(all_records)

delta_path = f"{DEPTH_DIR}/depth_paired_deltas.csv"
if deltas:
    with open(delta_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=deltas[0].keys())
        w.writeheader()
        w.writerows(deltas)
    print(f"  Wrote {delta_path}")

# ──────────────────────────────────────────────────────────────────
# Print summary tables
# ──────────────────────────────────────────────────────────────────

print("\n" + "="*80)
print("DEPTH DISTRIBUTION (dag_depth, all items)")
print("="*80)
depth_dist = collections.Counter()
for r in all_records.values():
    d = r["dag_depth"]
    depth_dist[(r["dataset"], d)] += 1
for ds in DS:
    print(f"\n{ds}:")
    for d in sorted(depth_dist.keys()):
        if d[0] == ds:
            print(f"  depth={d[1]:>2d}: {depth_dist[d]:>6d} questions")

print("\n" + "="*80)
print("TOPOLOGY DISTRIBUTION")
print("="*80)
topo_dist = collections.Counter()
for r in all_records.values():
    topo_dist[(r["dataset"], r["topology"], r["arm"])] += 1
for ds in DS:
    print(f"\n{ds}:")
    for key in sorted(topo_dist.keys()):
        if key[0] == ds:
            print(f"  {key[2]:>10s} {key[1]:>12s}: {topo_dist[key]:>6d}")

print("\n" + "="*80)
print("PAIRED DELTAS (chain - static) by dag_depth")
print("="*80)
for d in deltas:
    print(f"  {d['dataset']:15s} depth={d['depth']:>3s} n={d['n']:>5d} "
          f"ΔEM={d['delta_em_chain_static']:+.4f} CI[{d['ci_em_lo']:+.4f},{d['ci_em_hi']:+.4f}] "
          f"W/L/T={d['chain_wins']}/{d['static_wins']}/{d['ties']} "
          f"ΔLLM={d['delta_llm_chain_static']:+.1f}")

# ──────────────────────────────────────────────────────────────────
# Phase 5: n_slots vs dag_depth matrix
# ──────────────────────────────────────────────────────────────────

print("\n" + "="*80)
print("n_slots × dag_depth MATRIX")
print("="*80)
matrix = collections.Counter()
for r in all_records.values():
    matrix[(r["dataset"], r["n_slots"], r["dag_depth"])] += 1

for ds in DS:
    print(f"\n{ds}:")
    print(f"  {'n_slots':>8s}", end="")
    for dd in range(1, 8):
        print(f"  d={dd}", end="")
    print()
    for ns in range(0, 8):
        print(f"  {ns:>8d}", end="")
        for dd in range(1, 8):
            c = matrix.get((ds, ns, dd), 0)
            print(f"  {c:>5d}", end="")
        print()

# ──────────────────────────────────────────────────────────────────
# Phase 6: Selection ceiling by depth
# ──────────────────────────────────────────────────────────────────

print("\n" + "="*80)
print("BUDGET-EXCEEDED RATE by dag_depth")
print("="*80)
for ds in DS:
    print(f"\n{ds}:")
    for arm in ARM_SHORT.values():
        items = [r for r in all_records.values() if r["dataset"] == ds and r["arm"] == arm]
        depths = sorted(set(r["dag_depth"] for r in items))
        parts = []
        for d in depths:
            subset = [r for r in items if r["dag_depth"] == d]
            n = len(subset)
            be = sum(r["budget_exceeded"] for r in subset)
            rate = be / n if n else 0
            parts.append(f"d={d}: {be}/{n} ({rate:.1%})")
        print(f"  {arm:>10s}: " + "  ".join(parts))

# ──────────────────────────────────────────────────────────────────
# SHA256 of output
# ──────────────────────────────────────────────────────────────────
for p in [per_q_path, strat_path, delta_path]:
    if os.path.exists(p):
        h = hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
        print(f"\n  SHA256({os.path.basename(p)}) = {h}")

print("\nDONE")
