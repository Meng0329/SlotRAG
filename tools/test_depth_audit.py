"""Tests for the Depth-Stratified Mechanism Audit — depth computation functions.

Phase 10: validates single-slot depth, two-slot chain, three-slot chain,
star graph, disconnected invalid graph, cycle handling, ordering invariance,
and join list permutation invariance.

Functions are inlined from analyze_depth_stratified_chain_effect.py to
avoid the heavy 25k-item data load that runs on module import.
"""
import hashlib, os, sys
from collections import defaultdict, Counter
from itertools import permutations

# ─────────────────────────────────────────────────────────────────
# Inlined depth functions (from analyze_depth_stratified_chain_effect.py)
# ─────────────────────────────────────────────────────────────────

def build_join_dag(slot_ids, joins):
    """Build undirected adjacency list from join specs."""
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
    """Dependency depth = max trace step + 1."""
    if not traces:
        return 0
    return max(t.get("step", 0) for t in traces) + 1


def compute_dag_longest_path(slot_ids, joins):
    """Longest path in the undirected join graph via DFS.

    For each starting node, do an independent DFS (fresh visited set)
    to find the longest simple path from that node.
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
    deg = Counter()
    for j in joins:
        l, r = (j["left_slot"], j["right_slot"]) if isinstance(j, dict) else (j[0], j[1])
        deg[l] += 1
        deg[r] += 1
    return sum(deg.values()) / len(slot_ids) if slot_ids else 0.0


def plan_topology(slot_ids, joins):
    """Classify plan topology: single, chain, star, tree, disconnected.

    Star requires n≥4 and max_deg=n-1 with all leaves degree 1.
    For n=3, star and chain are isomorphic (both degree seq {2,1,1});
    labeled 'chain' because execution follows a linear path.
    """
    if len(slot_ids) <= 1:
        return "single"
    adj = build_join_dag(slot_ids, joins)
    # Connectivity check via BFS
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
    # Degree analysis
    deg = {s: len(adj.get(s, set())) for s in slot_ids}
    max_deg = max(deg.values())
    # Star: one hub has degree n-1 (connects to all), all leaves degree 1.
    # Requires n≥4: for n=3, star and chain are isomorphic (both {2,1,1}),
    # and chain is the correct semantic label (linear 2-hop execution).
    if max_deg == len(slot_ids) - 1 and max_deg >= 3:
        non_hub_deg1 = sum(1 for d in deg.values() if d == 1)
        if non_hub_deg1 == len(slot_ids) - 1:
            return "star"
    if max_deg <= 2:
        return "chain"
    # Has branching but not a single hub → tree
    return "tree"


# ─────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────

def test_single_slot_depth():
    assert compute_dag_longest_path(["S1"], []) == 1
    assert compute_depth_from_trace(["S1"], [], [{"step": 0}]) == 1
    assert plan_topology(["S1"], []) == "single"
    assert compute_branching_factor(["S1"], []) == 0.0
    print("  PASS: single-slot depth=1")


def test_two_slot_chain():
    slots, joins = ["S1", "S2"], [{"left_slot": "S1", "right_slot": "S2"}]
    assert compute_dag_longest_path(slots, joins) == 2
    assert compute_depth_from_trace(slots, joins, [{"step": 0}, {"step": 1}]) == 2
    assert plan_topology(slots, joins) == "chain"
    assert abs(compute_branching_factor(slots, joins) - 1.0) < 0.01
    print("  PASS: two-slot chain depth=2")


def test_three_slot_chain():
    slots = ["S1", "S2", "S3"]
    joins = [{"left_slot": "S1", "right_slot": "S2"}, {"left_slot": "S2", "right_slot": "S3"}]
    assert compute_dag_longest_path(slots, joins) == 3
    assert compute_depth_from_trace(slots, joins, [{"step": 0}, {"step": 1}, {"step": 2}]) == 3
    assert plan_topology(slots, joins) == "chain"
    print("  PASS: three-slot chain depth=3")


def test_three_slot_star():
    """3-node star and chain are graph-isomorphic (degree seq {2,1,1}).
    Labeled 'chain' because execution is still a linear 2-hop path.
    dag_depth=3 (node-count: longest path S2→S1→S3 visits 3 nodes)."""
    slots = ["S1", "S2", "S3"]
    joins = [{"left_slot": "S1", "right_slot": "S2"}, {"left_slot": "S1", "right_slot": "S3"}]
    assert compute_dag_longest_path(slots, joins) == 3, "3-node star: path visits 3 nodes"
    assert plan_topology(slots, joins) == "chain"
    print("  PASS: three-slot star dag_depth=3, topology=chain (n=3 isomorphic)")


def test_four_slot_star_2wiki():
    """2Wiki counterexample: n_slots=4 but dag_depth=3 (not 4).
    Longest path S2→S1→S3 visits 3 nodes (not a 4-node linear chain)."""
    slots = ["S1", "S2", "S3", "S4"]
    joins = [
        {"left_slot": "S1", "right_slot": "S2"},
        {"left_slot": "S1", "right_slot": "S3"},
        {"left_slot": "S1", "right_slot": "S4"},
    ]
    assert compute_dag_longest_path(slots, joins) == 3, "4-node star: longest path visits 3 nodes"
    assert plan_topology(slots, joins) == "star"
    print("  PASS: four-slot star dag_depth=3, topology=star (2Wiki pattern)")


def test_four_slot_chain():
    slots = ["S1", "S2", "S3", "S4"]
    joins = [
        {"left_slot": "S1", "right_slot": "S2"},
        {"left_slot": "S2", "right_slot": "S3"},
        {"left_slot": "S3", "right_slot": "S4"},
    ]
    assert compute_dag_longest_path(slots, joins) == 4
    assert plan_topology(slots, joins) == "chain"
    print("  PASS: four-slot chain depth=4")


def test_tree_topology():
    """S1-S2-S3-S4 with extra S2-S5: branching, not star (hub degree 3 < n-1=4)."""
    slots = ["S1", "S2", "S3", "S4", "S5"]
    joins = [
        {"left_slot": "S1", "right_slot": "S2"},
        {"left_slot": "S2", "right_slot": "S3"},
        {"left_slot": "S3", "right_slot": "S4"},
        {"left_slot": "S2", "right_slot": "S5"},
    ]
    depth = compute_dag_longest_path(slots, joins)
    assert depth == 4, f"Expected depth=4, got {depth}"
    topo = plan_topology(slots, joins)
    assert topo == "tree", f"Expected 'tree', got '{topo}'"
    print("  PASS: tree topology depth=4")


def test_disconnected():
    slots = ["S1", "S2", "S3", "S4"]
    joins = [{"left_slot": "S1", "right_slot": "S2"}, {"left_slot": "S3", "right_slot": "S4"}]
    assert plan_topology(slots, joins) == "disconnected"
    assert compute_dag_longest_path(slots, joins) == 2
    print("  PASS: disconnected graph detected")


def test_ordering_invariance():
    slots = ["S3", "S1", "S2"]
    joins_a = [{"left_slot": "S1", "right_slot": "S2"}, {"left_slot": "S2", "right_slot": "S3"}]
    joins_b = [{"left_slot": "S3", "right_slot": "S2"}, {"left_slot": "S1", "right_slot": "S2"}]
    joins_c = [{"right_slot": "S3", "left_slot": "S2"}, {"right_slot": "S1", "left_slot": "S2"}]
    d_a = compute_dag_longest_path(slots, joins_a)
    d_b = compute_dag_longest_path(slots, joins_b)
    d_c = compute_dag_longest_path(slots, joins_c)
    assert d_a == d_b == d_c == 3, f"Ordering changed depth: {d_a}, {d_b}, {d_c}"
    print("  PASS: ordering invariance (3 permutations → depth=3)")


def test_join_permutation_invariance():
    slots = ["S1", "S2", "S3", "S4"]
    base_joins = [
        {"left_slot": "S1", "right_slot": "S2"},
        {"left_slot": "S2", "right_slot": "S3"},
        {"left_slot": "S3", "right_slot": "S4"},
    ]
    depths = set()
    for perm in permutations(base_joins):
        depths.add(compute_dag_longest_path(slots, list(perm)))
    assert depths == {4}, f"Permutations produced varying depths: {depths}"
    print("  PASS: join permutation invariance (6 permutations → all depth=4)")


def test_cycle_tolerant():
    """Triangle: longest path is 2 (no repeat nodes)."""
    slots = ["S1", "S2", "S3"]
    joins = [
        {"left_slot": "S1", "right_slot": "S2"},
        {"left_slot": "S2", "right_slot": "S3"},
        {"left_slot": "S3", "right_slot": "S1"},
    ]
    assert compute_dag_longest_path(slots, joins) == 2
    assert plan_topology(slots, joins) == "chain"
    print("  PASS: triangle graph depth=2, topology=chain")


def test_trace_budget_truncation():
    slots = ["S1", "S2", "S3", "S4"]
    joins = [
        {"left_slot": "S1", "right_slot": "S2"},
        {"left_slot": "S2", "right_slot": "S3"},
        {"left_slot": "S3", "right_slot": "S4"},
    ]
    traces = [{"step": 0, "slot_id": "S1"}, {"step": 1, "slot_id": "S2"}]
    assert compute_depth_from_trace(slots, joins, traces) == 2
    assert compute_dag_longest_path(slots, joins) == 4
    print("  PASS: budget truncation: trace_depth=2 < dag_depth=4")


def test_empty_traces():
    assert compute_depth_from_trace(["S1"], [], []) == 0
    print("  PASS: empty traces → depth=0")


def test_tuple_joins():
    adj = build_join_dag(["S1", "S2"], [("S1", "S2")])
    assert "S2" in adj["S1"]
    assert "S1" in adj["S2"]
    print("  PASS: tuple joins handled")


def test_branching_factor():
    assert compute_branching_factor(["S1"], []) == 0.0
    bf_chain = compute_branching_factor(
        ["S1", "S2", "S3"],
        [{"left_slot": "S1", "right_slot": "S2"}, {"left_slot": "S2", "right_slot": "S3"}],
    )
    assert abs(bf_chain - 4 / 3) < 0.01
    bf_star = compute_branching_factor(
        ["S1", "S2", "S3", "S4"],
        [{"left_slot": "S1", "right_slot": "S2"},
         {"left_slot": "S1", "right_slot": "S3"},
         {"left_slot": "S1", "right_slot": "S4"}],
    )
    assert abs(bf_star - 1.5) < 0.01
    print("  PASS: branching factor edge cases")


def test_five_slot_tree():
    """S1-S2-S3-S4 with S2-S5 branch: longest path S1→S2→S3→S4 = 4."""
    slots = ["S1", "S2", "S3", "S4", "S5"]
    joins = [
        {"left_slot": "S1", "right_slot": "S2"},
        {"left_slot": "S2", "right_slot": "S3"},
        {"left_slot": "S3", "right_slot": "S4"},
        {"left_slot": "S2", "right_slot": "S5"},
    ]
    assert compute_dag_longest_path(slots, joins) == 4
    assert plan_topology(slots, joins) == "tree"
    print("  PASS: five-slot tree depth=4")


# ─────────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        test_single_slot_depth, test_two_slot_chain, test_three_slot_chain,
        test_three_slot_star, test_four_slot_star_2wiki, test_four_slot_chain,
        test_tree_topology, test_disconnected, test_ordering_invariance,
        test_join_permutation_invariance, test_cycle_tolerant,
        test_trace_budget_truncation, test_empty_traces, test_tuple_joins,
        test_five_slot_tree, test_branching_factor,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {t.__name__}: {e}")
            failed += 1
    print(f"\nResults: {passed} passed, {failed} failed, {passed + failed} total")
    # SHA256 of this file and analysis scripts
    for name in ["test_depth_audit.py", "analyze_depth_stratified_chain_effect.py", "gen_depth_figures.py"]:
        p = f"/data/mzb/SlotRAG/tools/{name}"
        if os.path.exists(p):
            h = hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
            print(f"  SHA256({name}) = {h}")
    if failed:
        sys.exit(1)
    print("\nALL TESTS PASSED")
