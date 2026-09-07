# TKDE_BASELINE_GAP_AUDIT.md — Baseline Classification for TKDE Paper v4

> **Date**: 2026-09-07
> **Scope**: All baselines mentioned in paper/ and research/
> **Purpose**: Per spec §29, classify every baseline into 4 categories

---

## Baseline Classification

### Category A: Published, Formally Compared (with matched budget)

| Baseline | Citation | Dataset | Comparison Type | Budget Matched? | Status |
|----------|----------|---------|-----------------|-----------------|--------|
| Static Allocation (SlotRAG internal) | own system | hotpotqa/2wiki/musique | Direct (flat vs static) | Yes (B=8) | COMPARABLE — reported in paper §7 |

### Category B: Adapted as Method Variants (same system, different configuration)

| Baseline | Citation | Description | Status |
|----------|----------|-------------|--------|
| Flat (budget-aware uniform) | own variant | Even reallocation under Σa_s ≤ B | Variant arm, not external baseline |
| Chain (dependency-weighted) | own variant | Importance τ = 2(i+1) - 1 | Variant arm, ablation in paper §7.3 |
| Policy A' (structure-gated) | own variant | Flat if hops≥2 ∧ F=0, else static | Final system variant |

### Category C: Prior Work Referenced but NOT Compared

| Baseline | Citation | Reason Not Compared | Where Discussed |
|----------|----------|---------------------|-----------------|
| Adaptive-RAG | Jeong et al. 2024, arXiv:2403.14403 | Different decision point (query-level routing vs plan-level allocation); no shared benchmark protocol | Related work §2.1 |
| PlanRAG | Liu et al. 2026, arXiv:2607.00508 | Different decision point (tree construction vs execution allocation); no matched-budget protocol available | Related work §2.2 |
| PyRAG | Sun et al. 2026, arXiv:2605.12975 | Program composition is upstream of execution; SlotRAG addresses downstream allocation | Related work §2.2 |
| DynaKRAG | Zhou et al. 2026, arXiv:2607.06507 | Learned evidence control; SlotRAG is non-parametric/structural | Related work §2.2 |
| PAGE-RAG | Deng et al. 2026, arXiv:2608.29753 | Candidate-level promotion under fixed budgets; different abstraction level | Related work §2.3 |
| Know Before You Fetch | Dong et al. 2026, arXiv:2606.29959 | Retrieval-budget calibration; different decision point | Related work §2.3 |
| IRCoT | Trivedi et al. 2023 ACL | Iterative retrieval; no compiled evidence plan | Related work §2.4 |
| ReAct | Yao et al. 2023 ICLR | Agentic loop; no pre-committed plan | Related work §2.4 |
| GraphRAG | Edge et al. 2024 | Knowledge-graph retrieval; different approach | Related work §2.4 |

### Category D: Mentioned but Unverifiable (cannot cite)

| Baseline | Status | Action |
|----------|--------|--------|
| RAG-on-a-Diet (Chen et al. 2024) | NOT FOUND on arXiv despite exhaustive search; no DOI; no proceedings listing | Dropped from bibliography; discussed as concept class in related work §2.3 |

---

## Justification for No External Baseline Comparison

The paper is a **systems paper** (TKDE, not NeurIPS/ICML), focused on a **downstream execution mechanism** within an existing multi-hop RAG system. The experimental design compares:

1. **Internal system variants** (static/flat/chain/gated) under the **same model, same retrieval index, same budget, same datasets**
2. This isolates the contribution of the execution mechanism from confounds of model quality, retrieval quality, or dataset difficulty

External baseline comparison would require:
- Shared retrieval index + reranker + generation model
- Matched budget protocol (same B, same step/call limits)
- Published execution traces with budget-exhaustion events

None of the referenced systems publish execution traces at this granularity, and their protocols differ in model, budget, and evaluation metrics. A fair comparison would require reimplementing each system under the SlotRAG protocol — this is explicitly out of scope per the frozen protocol (no new experiments beyond the H-STRUCT series).

The paper is transparent about this: §8 (Threats) explicitly states that external baseline comparison under matched conditions is an open requirement, and the related work §2 explicitly differentiates decision points rather than claiming superiority.
