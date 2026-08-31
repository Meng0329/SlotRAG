"""Structural Depth Correction + Offline Policy Replay (Phases 1-7).

Reads frozen sealed test items. NO LLM, NO retrieval.

Phase 1: Rename depth → structural_hops (edge count on longest simple path)
Phase 2: Exact longest-simple-path via DFS with path-local backtracking
Phase 3: Structural evidence graph includes operator-induced edges (tracked by edge_type)
Phase 4: Full denominator audit
Phase 5: Interaction test (paired permutation + GEE-like clustered regression)
Phase 6-7: Deterministic offline policy replay (P0-P2 + Candidates A/B/C)

Output:
  structural_per_question.csv
  denominator_audit.csv
  interaction_statistics.csv
  offline_policy_replay.csv
"""
import csv, json, glob, os, sys, hashlib, collections
import numpy as np
from collections import defaultdict

OUT = "/home/test/tkde_runs/tkde-sealed-test-q35"
RESEARCH = "/data/mzb/SlotRAG/research"
DEPTH_DIR = f"{RESEARCH}/depth_analysis"
os.makedirs(DEPTH_DIR, exist_ok=True)

DS = ["hotpotqa", "2wikimultihop", "musique"]
ARMS = ["slotrag-g7-static", "slotrag-g7-flat", "slotrag-g7-chain"]
ARM_SHORT = {"slotrag-g7-static": "static", "slotrag-g7-flat": "flat", "slotrag-g7-chain": "chain"}

# ═══════════════════════════════════════════════════════════════════
# PHASE 1-2: Structural graph construction + exact longest path
# ═══════════════════════════════════════════════════════════════════

def parse_join(j):
    """Parse a JoinSpec (dict or tuple/list) into (left_slot, right_slot)."""
    if isinstance(j, dict):
        return j.get("left_slot"), j.get("right_slot")
    elif isinstance(j, (list, tuple)):
        if len(j) == 2 and isinstance(j[0], str):
            return j[0], j[1]
        elif len(j) == 2 and isinstance(j[0], dict):
            return j[0].get("left_slot", j[0].get("left")), j[1].get("right_slot", j[1].get("right"))
    return None, None


def derive_structural_evidence_graph(plan):
    """Build the structural evidence graph from a compiled plan.

    Returns:
        adj: dict[slot_id -> set[slot_id]]  (undirected, all edge types merged)
        edge_types: dict[frozenset({s1,s2}) -> set[str]]  tracks which edge types connect each pair
        operator_edges: list of (s1, s2, operator_kind, fields)

    Edge types:
        "join"     — JoinSpec.left_slot ↔ right_slot
        "operator" — field_argmin/field_argmax references fields from both slots

    Non-structural operators (project, count, boolean, compare, intersect, filter,
    sort, arithmetic) do NOT create slot-to-slot edges. They consume slot outputs
    but don't establish retrieval dependency between slots.
    """
    slots = plan.get("slots", [])
    slot_ids = [s["id"] for s in slots]
    slot_fields = {s["id"]: {a[1:] for a in s.get("arguments", []) if a.startswith("?")} for s in slots}
    joins = plan.get("joins", [])
    operators = plan.get("operators", [])

    adj = defaultdict(set)
    edge_types = defaultdict(set)
    operator_edges = []

    # 1. Join edges
    for j in joins:
        l, r = parse_join(j)
        if l and r and l in slot_ids and r in slot_ids:
            adj[l].add(r)
            adj[r].add(l)
            edge_types[frozenset({l, r})].add("join")

    # 2. Operator-induced edges (field_argmin / field_argmax only)
    for op in operators:
        if op.get("kind") not in ("field_argmin", "field_argmax"):
            continue
        fields = op.get("fields", [])
        if not fields:
            continue
        op_slots = set()
        for f in fields:
            for sid, variables in slot_fields.items():
                if f in variables:
                    op_slots.add(sid)
        op_slots_list = sorted(op_slots)
        for i, s1 in enumerate(op_slots_list):
            for s2 in op_slots_list[i + 1:]:
                adj[s1].add(s2)
                adj[s2].add(s1)
                edge_types[frozenset({s1, s2})].add("operator")
                operator_edges.append((s1, s2, op.get("kind"), fields))

    return adj, edge_types, operator_edges


def exact_longest_simple_path(adj, slot_ids):
    """Exact longest simple path via DFS with path-local backtracking.

    Returns structural_hops (edge count) and structural_nodes (node count).
    visited set is LOCAL to each recursive path — not shared across starts.
    """
    if len(slot_ids) <= 1:
        return 0, len(slot_ids)  # 0 hops, 1 node

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

    return best_hops, best_hops + 1


def classify_topology(adj, slot_ids, edge_types):
    """Classify topology using the FULL structural graph (joins + operators).

    Returns:
        topology: str — 'single', 'chain', 'star', 'tree'
        join_topology: str — topology if only join edges considered
        operator_connects_components: bool — whether operators bridge join-disconnected components
        max_join_degree: int
        max_full_degree: int
        n_join_edges: int
        n_operator_edges: int
        operator_edge_pairs: list of (s1, s2)
    """
    n = len(slot_ids)
    if n <= 1:
        return "single", "single", False, 0, 0, 0, 0, []

    # Join-only adjacency
    adj_joins = defaultdict(set)
    for pair, types in edge_types.items():
        if "join" in types:
            s1, s2 = sorted(pair)
            adj_joins[s1].add(s2)
            adj_joins[s2].add(s1)

    # Join-only connectivity
    visited_j = set()
    stack = [slot_ids[0]]
    while stack:
        nd = stack.pop()
        if nd in visited_j:
            continue
        visited_j.add(nd)
        stack.extend(adj_joins.get(nd, set()) - visited_j)
    join_connected = len(visited_j) == n

    # Full connectivity
    visited_f = set()
    stack = [slot_ids[0]]
    while stack:
        nd = stack.pop()
        if nd in visited_f:
            continue
        visited_f.add(nd)
        stack.extend(adj.get(nd, set()) - visited_f)
    full_connected = len(visited_f) == n

    operator_connects = join_connected is False and full_connected is True

    # Degrees
    deg_joins = {s: len(adj_joins.get(s, set())) for s in slot_ids}
    deg_full = {s: len(adj.get(s, set())) for s in slot_ids}
    max_join_deg = max(deg_joins.values()) if deg_joins else 0
    max_full_deg = max(deg_full.values()) if deg_full else 0

    n_join = sum(len(v) for v in adj_joins.values()) // 2
    n_op = sum(1 for t in edge_types.values() if "operator" in t)
    op_pairs = [sorted(pair) for pair, types in edge_types.items() if "operator" in types]

    # Full topology (with operators)
    if not full_connected:
        topo_full = "disconnected"  # should not happen after Phase 3 finding
    elif max_full_deg == n - 1 and max_full_deg >= 3:
        non_hub_1 = sum(1 for d in deg_full.values() if d == 1)
        if non_hub_1 == n - 1:
            topo_full = "star"
        elif max_full_deg <= 2:
            topo_full = "chain"
        else:
            topo_full = "tree"
    elif max_full_deg <= 2:
        topo_full = "chain"
    else:
        topo_full = "tree"

    # Join-only topology
    if not join_connected:
        topo_join = "join_disconnected"
    elif max_join_deg == n - 1 and max_join_deg >= 3:
        non_hub_1 = sum(1 for d in deg_joins.values() if d == 1)
        if non_hub_1 == n - 1:
            topo_join = "star"
        else:
            topo_join = "tree"
    elif max_join_deg <= 2:
        topo_join = "chain"
    else:
        topo_join = "tree"

    return topo_full, topo_join, operator_connects, max_join_deg, max_full_deg, n_join, n_op, op_pairs


# ═══════════════════════════════════════════════════════════════════
# PHASE 0+4: Load all items + denominator audit
# ═══════════════════════════════════════════════════════════════════

print("Loading all sealed items...")
records = {}
denom_raw = collections.Counter()
denom_plan_valid = collections.Counter()
denom_depth_valid = collections.Counter()
denom_metric_valid = collections.Counter()
excluded = []

for ds in DS:
    for arm in ARMS:
        d = f"{OUT}/items/g7-sealed/{ds}/{arm}"
        if not os.path.isdir(d):
            continue
        for fp in sorted(glob.glob(f"{d}/*.json")):
            j = json.load(open(fp))
            qid = j.get("question_id")
            result = j.get("result") or {}
            plan = result.get("plan") or {}
            metrics = result.get("metrics") or {}
            scores = j.get("scores") or {}
            traces = result.get("slot_traces") or []
            status = result.get("status", "unknown")

            denom_raw[(ds, arm)] += 1

            slots = plan.get("slots", [])
            joins = plan.get("joins", [])
            slot_ids = [s["id"] for s in slots]

            if not slot_ids:
                excluded.append((ds, arm, qid, "no_slots"))
                continue

            # Derive structural evidence graph
            adj, edge_types, op_edges = derive_structural_evidence_graph(plan)
            structural_hops, structural_nodes = exact_longest_simple_path(adj, slot_ids)
            (topo_full, topo_join, op_connects,
             max_join_deg, max_full_deg, n_join, n_op, op_pairs) = classify_topology(adj, slot_ids, edge_types)

            denom_plan_valid[(ds, arm)] += 1

            trace_depth = max((t.get("step", 0) for t in traces), default=-1) + 1 if traces else 0
            if structural_hops < 0:
                excluded.append((ds, arm, qid, "invalid_structural_hops"))
                continue

            denom_depth_valid[(ds, arm)] += 1

            em = scores.get("em")
            f1 = scores.get("f1")
            if em is None:
                excluded.append((ds, arm, qid, "no_em_score"))
                continue

            denom_metric_valid[(ds, arm)] += 1

            # Branching factor
            deg_count = defaultdict(int)
            for pair in edge_types:
                for s in pair:
                    deg_count[s] += 1
            bf = sum(deg_count.values()) / len(slot_ids) if slot_ids else 0.0

            records[(ds, arm, qid)] = {
                "dataset": ds, "arm": ARM_SHORT[arm], "question_id": qid,
                "n_slots": len(slot_ids), "n_joins": n_join, "n_operator_edges": n_op,
                "structural_hops": structural_hops, "structural_nodes": structural_nodes,
                "trace_depth": trace_depth,
                "branching_factor": round(bf, 3),
                "topology_full": topo_full, "topology_join": topo_join,
                "operator_connects_components": 1 if op_connects else 0,
                "max_join_degree": max_join_deg, "max_full_degree": max_full_deg,
                "em": em, "f1": f1,
                "retrieval_calls": metrics.get("retrieval_calls"),
                "llm_calls": metrics.get("llm_calls"),
                "documents_accessed": metrics.get("documents_accessed"),
                "latency_ms": metrics.get("latency_ms"),
                "budget_exceeded": 1 if status == "budget_exceeded" else 0,
                "status": status,
            }

print(f"  Loaded {len(records)} records")

# ═══════════════════════════════════════════════════════════════════
# PHASE 4: Write denominator audit
# ═══════════════════════════════════════════════════════════════════

print("\n--- DENOMINATOR AUDIT ---")
denom_rows = []
for ds in DS:
    for arm_full, arm_short in ARM_SHORT.items():
        denom_rows.append({
            "dataset": ds, "arm": arm_short,
            "raw": denom_raw.get((ds, arm_full), 0),
            "plan_valid": denom_plan_valid.get((ds, arm_full), 0),
            "depth_valid": denom_depth_valid.get((ds, arm_full), 0),
            "metric_valid": denom_metric_valid.get((ds, arm_full), 0),
            "analysis_final": sum(1 for (dds, a, _) in records if dds == ds and a == arm_short),
        })
    # Paired count
    paired = sum(1 for qid in set(q for (dds, _, q) in records if dds == ds)
                 if all((ds, arm, qid) in records for arm in ARM_SHORT.values()))
    denom_rows.append({"dataset": ds, "arm": "THREE_ARM_PAIRED", "raw": paired,
                       "plan_valid": paired, "depth_valid": paired, "metric_valid": paired, "analysis_final": paired})

# Exclusions
for ds, arm, qid, reason in excluded:
    denom_rows.append({"dataset": ds, "arm": f"EXCLUDED:{reason}", "raw": 1,
                       "plan_valid": 0, "depth_valid": 0, "metric_valid": 0, "analysis_final": 0})

denom_path = f"{DEPTH_DIR}/denominator_audit.csv"
with open(denom_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["dataset", "arm", "raw", "plan_valid", "depth_valid", "metric_valid", "analysis_final"])
    w.writeheader()
    w.writerows(denom_rows)
print(f"  Wrote {denom_path}")

# ═══════════════════════════════════════════════════════════════════
# Write structural_per_question.csv
# ═══════════════════════════════════════════════════════════════════

FIELDS = [
    "dataset", "arm", "question_id",
    "n_slots", "n_joins", "n_operator_edges",
    "structural_hops", "structural_nodes", "trace_depth",
    "branching_factor", "topology_full", "topology_join",
    "operator_connects_components", "max_join_degree", "max_full_degree",
    "em", "f1", "retrieval_calls", "llm_calls", "documents_accessed", "latency_ms",
    "budget_exceeded", "status",
]

pq_path = f"{DEPTH_DIR}/structural_per_question.csv"
with open(pq_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader()
    for key in sorted(records.keys()):
        row = {k: records[key].get(k) for k in FIELDS}
        w.writerow(row)
print(f"  Wrote {pq_path} ({len(records)} rows)")

# ═══════════════════════════════════════════════════════════════════
# PHASE 5: Interaction test
# ═══════════════════════════════════════════════════════════════════

print("\n--- INTERACTION TEST ---")

# Build question-level paired treatment table
by_q = defaultdict(dict)
for r in records.values():
    by_q[(r["dataset"], r["question_id"])][r["arm"]] = r

# Compute chain-static and chain-flat deltas
interaction_rows = []
for (ds, qid), arms in sorted(by_q.items()):
    c = arms.get("chain")
    s = arms.get("static")
    fl = arms.get("flat")
    if not c or not s:
        continue
    structural_hops = c.get("structural_hops", 0)
    topology = c.get("topology_full", "unknown")
    ce, se = c.get("em"), s.get("em")
    fe = fl.get("em") if fl else None
    if ce is None or se is None:
        continue
    chain_static_em = ce - se
    chain_flat_em = (ce - fe) if fe is not None else None
    interaction_rows.append({
        "dataset": ds, "question_id": qid,
        "structural_hops": structural_hops, "topology": topology,
        "chain_em": ce, "static_em": se, "flat_em": fe,
        "chain_minus_static_em": chain_static_em,
        "chain_minus_flat_em": chain_flat_em,
    })

print(f"  Paired treatment rows: {len(interaction_rows)}")

# ── A. Dataset-stratified paired permutation interaction ──
# Test: deep chain-like regime vs shallow regime, chain-static effect
# Permutation within dataset, shuffling treatment assignment

def permutation_interaction_test(rows, deep_condition, n_perms=10000, seed=2027):
    """Paired permutation test for interaction between depth regime and treatment effect.

    H0: treatment effect is the same in deep and shallow regimes.
    Test statistic: mean(chain_static in deep) - mean(chain_static in shallow).
    """
    rng = np.random.RandomState(seed)
    deep_effects = np.array([r["chain_minus_static_em"] for r in rows if deep_condition(r)])
    shallow_effects = np.array([r["chain_minus_static_em"] for r in rows if not deep_condition(r)])

    if len(deep_effects) < 5 or len(shallow_effects) < 5:
        return None

    observed = np.mean(deep_effects) - np.mean(shallow_effects)

    # Permutation: for each question, randomly assign to deep or shallow
    # keeping group sizes fixed
    all_effects = np.concatenate([deep_effects, shallow_effects])
    n_deep = len(deep_effects)
    count = 0
    for _ in range(n_perms):
        perm = rng.permutation(all_effects)
        perm_deep = perm[:n_deep]
        perm_shallow = perm[n_deep:]
        perm_stat = np.mean(perm_deep) - np.mean(perm_shallow)
        if perm_stat >= observed:
            count += 1
    p_value = count / n_perms
    return {
        "observed_diff": round(observed, 4),
        "deep_n": len(deep_effects),
        "deep_mean": round(np.mean(deep_effects), 4),
        "shallow_n": len(shallow_effects),
        "shallow_mean": round(np.mean(shallow_effects), 4),
        "permutation_p": round(p_value, 5),
        "n_perms": n_perms,
    }

# Depth threshold: structural_hops >= 2 means "deep" (3+ nodes)
# This is the natural cutoff from the exploratory discovery
TAU_DEPTH = 2

interaction_stats = []
for ds in DS + ["pooled"]:
    ds_rows = [r for r in interaction_rows if r["dataset"] == ds] if ds != "pooled" else interaction_rows
    if not ds_rows:
        continue

    # Depth interaction
    result = permutation_interaction_test(
        ds_rows,
        deep_condition=lambda r: r["structural_hops"] >= TAU_DEPTH,
        n_perms=10000,
    )
    if result:
        result["dataset"] = ds
        result["test"] = "depth_interaction"
        result["tau"] = TAU_DEPTH
        interaction_stats.append(result)

    # Topology interaction: chain-like vs non-chain
    result_topo = permutation_interaction_test(
        ds_rows,
        deep_condition=lambda r: r["topology"] in ("chain",),
        n_perms=10000,
    )
    if result_topo:
        result_topo["dataset"] = ds
        result_topo["test"] = "topology_interaction"
        result_topo["tau"] = "chain"
        interaction_stats.append(result_topo)

# ── B. Clustered regression (OLS with question_id cluster SE) ──

# correct = f(policy, hops, topology, dataset, policy:hops, policy:topology)
# Using chain-static difference as outcome
from numpy.linalg import lstsq

def clustered_regression(rows):
    """Simple OLS with cluster-robust SE by dataset.

    Model: chain_minus_static_em ~ hops + is_chain_topo
    (Pooled across datasets, clustered by dataset)
    """
    y = np.array([r["chain_minus_static_em"] for r in rows])
    X_cols = []
    for r in rows:
        X_cols.append([
            1,  # intercept
            r["structural_hops"],
            1 if r["topology"] == "chain" else 0,
        ])
    X = np.array(X_cols)
    # OLS
    beta, residuals, rank, sv = lstsq(X, y, rcond=None)
    # Residuals
    y_hat = X @ beta
    e = y - y_hat
    n, k = X.shape

    # Cluster-robust SE (3 clusters = 3 datasets)
    clusters = defaultdict(lambda: {"Xe": np.zeros(k), "n": 0})
    for i, r in enumerate(rows):
        ds = r["dataset"]
        clusters[ds]["Xe"] += X[i] * e[i]
        clusters[ds]["n"] += 1

    bread = np.linalg.inv(X.T @ X)
    meat = np.zeros((k, k))
    N = len(rows)
    for c in clusters.values():
        meat += np.outer(c["Xe"], c["Xe"])
    # HC1: multiply by N/(N-k) and G/(G-1) where G=3 clusters
    G = len(clusters)
    meat *= (N / (N - k)) * (G / (G - 1))
    V = bread @ meat @ bread
    se = np.sqrt(np.diag(V))
    z = beta / se
    p = 2 * (1 - np.abs(np.clip(z / 2, -1, 1)))  # approx

    return {
        "intercept": round(beta[0], 4), "intercept_se": round(se[0], 4),
        "hops_coef": round(beta[1], 4), "hops_se": round(se[1], 4),
        "chain_topo_coef": round(beta[2], 4), "chain_topo_se": round(se[2], 4),
        "n": n, "r_squared": round(1 - np.sum(e**2) / np.sum((y - np.mean(y))**2), 4),
    }

reg_result = clustered_regression(interaction_rows)
print(f"  Clustered regression: hops coef={reg_result['hops_coef']:.4f} (SE={reg_result['hops_se']:.4f}), "
      f"chain_topo coef={reg_result['chain_topo_coef']:.4f} (SE={reg_result['chain_topo_se']:.4f}), "
      f"R²={reg_result['r_squared']:.4f}")

# Write interaction statistics
ix_path = f"{DEPTH_DIR}/interaction_statistics.csv"
all_fields = ["dataset", "test", "tau", "observed_diff", "deep_n", "deep_mean",
              "shallow_n", "shallow_mean", "permutation_p", "n_perms",
              "intercept", "intercept_se", "hops_coef", "hops_se",
              "chain_topo_coef", "chain_topo_se", "n", "r_squared"]
with open(ix_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=all_fields, extrasaction="ignore")
    w.writeheader()
    for row in interaction_stats:
        w.writerow(row)
    w.writerow({"dataset": "pooled", "test": "clustered_ols", **reg_result})
print(f"  Wrote {ix_path}")

# ═══════════════════════════════════════════════════════════════════
# PHASE 6-7: Offline Policy Replay
# ═══════════════════════════════════════════════════════════════════

print("\n--- OFFLINE POLICY REPLAY ---")

# Build per-question record indexed by (dataset, question_id, arm)
# For each question, we know what static/flat/chain would produce.

def compute_policy_metrics(policy_name, by_q, ds_filter=None):
    """Compute metrics for a deterministic policy that selects arm per question."""
    results_by_ds = defaultdict(lambda: {"em": [], "f1": [], "retr": [], "llm": [], "budget_ex": [], "n": 0})

    for (ds, qid), arms in by_q.items():
        if ds_filter and ds != ds_filter:
            continue

        # Policy selects an arm
        selected_arm = policy_name(arms, ds, qid)
        if selected_arm is None:
            continue

        r = arms.get(selected_arm)
        if not r or r.get("em") is None:
            continue

        results_by_ds[ds]["em"].append(r["em"])
        results_by_ds[ds]["f1"].append(r["f1"] or 0)
        results_by_ds[ds]["retr"].append(r.get("retrieval_calls") or 0)
        results_by_ds[ds]["llm"].append(r.get("llm_calls") or 0)
        results_by_ds[ds]["budget_ex"].append(r.get("budget_exceeded") or 0)
        results_by_ds[ds]["n"] += 1

    return dict(results_by_ds)


# Define policies
TAU = 2  # structural_hops >= 2 → deep

def policy_p0(arms, ds, qid):
    """P0: static always"""
    return "static"

def policy_p1(arms, ds, qid):
    """P1: flat always"""
    return "flat"

def policy_p2(arms, ds, qid):
    """P2: chain always"""
    return "chain"

def policy_a(arms, ds, qid):
    """Candidate A: depth only — chain if structural_hops >= tau, else static"""
    chain = arms.get("chain")
    if chain and chain.get("structural_hops", 0) >= TAU:
        return "chain"
    return "static"

def policy_b(arms, ds, qid):
    """Candidate B: depth × topology — chain if hops >= tau AND topology is chain-like"""
    chain = arms.get("chain")
    if (chain and chain.get("structural_hops", 0) >= TAU
            and chain.get("topology_full") in ("chain",)):
        return "chain"
    return "static"

def policy_c(arms, ds, qid):
    """Candidate C (exploratory): depth × topology (chain OR tree)"""
    chain = arms.get("chain")
    if (chain and chain.get("structural_hops", 0) >= TAU
            and chain.get("topology_full") in ("chain", "tree")):
        return "chain"
    return "static"

policies = [
    ("P0_static", policy_p0),
    ("P1_flat", policy_p1),
    ("P2_chain", policy_p2),
    ("A_depth_only", policy_a),
    ("B_depth_x_topo", policy_b),
    ("C_depth_x_topo_tree", policy_c),
]

replay_rows = []
for pname, pfunc in policies:
    metrics_by_ds = compute_policy_metrics(pfunc, by_q)
    for ds in DS:
        m = metrics_by_ds.get(ds, {"em": [], "f1": [], "retr": [], "llm": [], "budget_ex": [], "n": 0})
        n = m["n"]
        if n == 0:
            continue
        replay_rows.append({
            "policy": pname, "dataset": ds, "scope": "dataset",
            "n": n,
            "em": round(np.mean(m["em"]), 4),
            "f1": round(np.mean(m["f1"]), 4),
            "retr_calls": round(np.mean(m["retr"]), 3),
            "llm_calls": round(np.mean(m["llm"]), 3),
            "budget_ex_rate": round(np.mean(m["budget_ex"]), 4),
        })

    # Pooled (micro)
    all_em, all_f1, all_retr, all_llm, all_bex = [], [], [], [], []
    for ds in DS:
        m = metrics_by_ds.get(ds, {})
        all_em.extend(m.get("em", []))
        all_f1.extend(m.get("f1", []))
        all_retr.extend(m.get("retr", []))
        all_llm.extend(m.get("llm", []))
        all_bex.extend(m.get("budget_ex", []))
    if all_em:
        replay_rows.append({
            "policy": pname, "dataset": "pooled_micro", "scope": "micro",
            "n": len(all_em),
            "em": round(np.mean(all_em), 4),
            "f1": round(np.mean(all_f1), 4),
            "retr_calls": round(np.mean(all_retr), 3),
            "llm_calls": round(np.mean(all_llm), 3),
            "budget_ex_rate": round(np.mean(all_bex), 4),
        })

    # Pooled (macro = avg of per-dataset means)
    ds_em = [metrics_by_ds.get(ds, {}).get("em", [0]) for ds in DS]
    ds_f1 = [metrics_by_ds.get(ds, {}).get("f1", [0]) for ds in DS]
    ds_llm = [metrics_by_ds.get(ds, {}).get("llm", [0]) for ds in DS]
    ds_retr = [metrics_by_ds.get(ds, {}).get("retr", [0]) for ds in DS]
    ds_bex = [metrics_by_ds.get(ds, {}).get("budget_ex", [0]) for ds in DS]
    replay_rows.append({
        "policy": pname, "dataset": "pooled_macro", "scope": "macro",
        "n": sum(len(e) for e in ds_em),
        "em": round(np.mean([np.mean(e) if len(e) else 0 for e in ds_em]), 4),
        "f1": round(np.mean([np.mean(e) if len(e) else 0 for e in ds_f1]), 4),
        "retr_calls": round(np.mean([np.mean(e) if len(e) else 0 for e in ds_retr]), 3),
        "llm_calls": round(np.mean([np.mean(e) if len(e) else 0 for e in ds_llm]), 3),
        "budget_ex_rate": round(np.mean([np.mean(e) if len(e) else 0 for e in ds_bex]), 4),
    })

    # Leave-one-stratum-out: exclude HotpotQA structural_hops>=4
    if pname in ("B_depth_x_topo", "P0_static", "P2_chain", "A_depth_only"):
        # Filter: exclude questions where structural_hops >= 4 (any arm, since plan is shared)
        filtered_by_q = {}
        for (ds, qid), arms in by_q.items():
            # Get structural_hops from any arm (plan is same)
            any_arm = next(iter(arms.values()), None)
            if any_arm and any_arm.get("structural_hops", 0) >= 4 and ds == "hotpotqa":
                continue
            filtered_by_q[(ds, qid)] = arms
        m_loso = compute_policy_metrics(pfunc, filtered_by_q)
        # Micro
        all_loso = []
        for ds in DS:
            all_loso.extend(m_loso.get(ds, {}).get("em", []))
        if all_loso:
            replay_rows.append({
                "policy": pname, "dataset": "LOSA_hotpot_hops4+", "scope": "losa_micro",
                "n": len(all_loso),
                "em": round(np.mean(all_loso), 4),
                "f1": 0, "retr_calls": 0, "llm_calls": 0, "budget_ex_rate": 0,
            })
        # Macro
        ds_em_loso = [m_loso.get(ds, {}).get("em", [0]) for ds in DS]
        replay_rows.append({
            "policy": pname, "dataset": "LOSA_hotpot_hops4+", "scope": "losa_macro",
            "n": sum(len(e) for e in ds_em_loso),
            "em": round(np.mean([np.mean(e) if len(e) else 0 for e in ds_em_loso]), 4),
            "f1": 0, "retr_calls": 0, "llm_calls": 0, "budget_ex_rate": 0,
        })

replay_path = f"{DEPTH_DIR}/offline_policy_replay.csv"
if replay_rows:
    with open(replay_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(replay_rows[0].keys()))
        w.writeheader()
        w.writerows(replay_rows)
    print(f"  Wrote {replay_path}")

# Print summary
print("\n  POLICY COMPARISON (macro EM):")
for r in replay_rows:
    if r["scope"] == "macro":
        print(f"    {r['policy']:20s}  EM={r['em']:.4f}  F1={r['f1']:.4f}  LLM={r['llm_calls']:.1f}  budget={r['budget_ex_rate']:.1%}  n={r['n']}")

print("\n  PER-DATASET COMPARISON (B_depth_x_topo vs static):")
b_rows = {r["dataset"]: r for r in replay_rows if r["policy"] == "B_depth_x_topo" and r["scope"] == "dataset"}
s_rows = {r["dataset"]: r for r in replay_rows if r["policy"] == "P0_static" and r["scope"] == "dataset"}
for ds in DS:
    b = b_rows.get(ds, {})
    s = s_rows.get(ds, {})
    delta = (b.get("em", 0) - s.get("em", 0)) if b and s else 0
    print(f"    {ds:15s}  B={b.get('em',0):.4f}  static={s.get('em',0):.4f}  Δ={delta:+.4f}")

print("\n  LOSA (exclude HotpotQA hops>=4):")
for r in replay_rows:
    if r["scope"] == "losa_macro":
        print(f"    {r['policy']:20s}  macro_EM={r['em']:.4f}  n={r['n']}")

# ═══════════════════════════════════════════════════════════════════
# Topology distribution summary
# ═══════════════════════════════════════════════════════════════════

print("\n--- TOPOLOGY DISTRIBUTION (full graph, with operators) ---")
topo_counts = collections.Counter()
op_connects_counts = collections.Counter()
for r in records.values():
    topo_counts[(r["dataset"], r["topology_full"])] += 1
    if r["operator_connects_components"]:
        op_connects_counts[r["dataset"]] += 1
for ds in DS:
    print(f"\n  {ds}:")
    for topo in sorted(set(t for (d, t) in topo_counts if d == ds)):
        print(f"    {topo:>20s}: {topo_counts[(ds, topo)]:>6d}")
    print(f"    operator_connects: {op_connects_counts.get(ds, 0)}")

print("\n--- DONE ---")

# SHA256
for p in [pq_path, denom_path, ix_path, replay_path]:
    if os.path.exists(p):
        h = hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
        print(f"  SHA256({os.path.basename(p)}) = {h}")
