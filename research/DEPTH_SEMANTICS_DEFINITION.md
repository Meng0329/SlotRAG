# DEPENDENCY_DEPTH_DEFINITION.md — Formal Definition

> **⚠ EXPLORATORY MECHANISM DISCOVERY SET** — This document reports findings from exploratory analysis on 25,983 sealed items (hotpotqa/2wikimultihop/musique, test_set, 3-arm). Terminology corrected per STRUCTURAL_DEPTH_CORRECTION_REPORT.md. No confirmatory claims may be drawn from this analysis without an independent holdout.

> Phase 1 deliverable of the Depth-Stratified Mechanism Audit

## 1. Formal Definition

**dependency_depth(q)** = the longest directed path in the execution dependency DAG of question q's frozen logical plan.

### Operationally:

```
dependency_depth(q) = max(step) + 1   (from slot_traces)
```

where `slot_traces[i].step` is the 0-based execution order index — the position at which slot `i` was materialized during execution.

### Equivalently:

```
dependency_depth(q) = longest_path_in_join_undirected_graph(q.plan.slots, q.plan.joins)
```

Since the executor materializes slots greedily along join edges (any connected slot can be next), the undirected longest path equals the actual execution depth when all slots are materialized. When budget truncates execution, the trace step gives the depth of the materialized subgraph.

## 2. Why NOT n_slots

n_slots counts the total number of evidence slots in the plan. It does NOT measure how deep the dependency chain is:

| n_slots | dag_depth | Topology | Example |
|---------|-----------|----------|---------|
| 1 | 1 | single | "Who directed X?" |
| 2 | 2 | chain | "Who directed X's birthplace?" |
| 3 | 2 | chain | star: S1↔S2↔S3 but S1↔S3 also joined |
| 3 | 3 | chain | true linear: S1→S2→S3 |
| 4 | 2 | disconnected | 2Wiki star: 4 slots, 2-hop max |
| 4 | 4 | chain | true linear: S1→S2→S3→S4 |
| 7 | 5 | tree | mixed: some branching |

**Counterexample (2WikiMultiHopQA)**: 549 plans with n_slots=4 but dag_depth=2 — these are wide star plans where all 4 slots join on a common variable but the maximum hop chain is only 2 deep. Using n_slots≥3 as "deep" would incorrectly label these as deep.

## 3. Topology Classification

Plans are classified by their join graph structure:

- **single**: 1 slot (depth=1)
- **chain**: all nodes have degree ≤ 2, graph connected → linear dependency
- **star**: one hub node with degree > 2, others degree 1 → hub-and-spoke
- **tree**: connected, branching, not a star
- **disconnected**: graph has multiple components (2Wiki: 183 cases)

## 4. Chain Rule Formula

The chain-rule importance is: `tau(slot_i) = 2 * (idx + 1) - 1` where idx is the 0-based position in `logical.subgoals`.

- depth 1 (root): tau = 1
- depth 2: tau = 3
- depth 3: tau = 5
- depth 4: tau = 7

This formula assumes a linear chain topology. For star/tree plans, the "depth" of each slot is its position in the execution trace (which may differ from the topological depth).

## 5. Empirical Validation

On 30 hand-inspected plans (10 per dataset):
- Trace execution order always follows join connectivity (a slot is materialized only after a join partner has been materialized)
- JoinSpec.left_slot/right_slot direction is a convention set by the LLM compiler, NOT an enforced producer→consumer constraint (SlotPlan validation builds bidirectional adjacency)
- The trace step is the ground truth for execution depth

## 6. Measurement Properties

- **Invariant to JoinSpec.left/right convention**: Yes — uses trace order, not join direction
- **Invariant to join list permutation**: Yes — longest path in undirected graph is order-independent
- **Accounts for budget truncation**: Yes — trace step reflects materialized depth, not plan depth
- **Distinguishes chain from star**: Yes — a 4-slot star has dag_depth=2, not 4
