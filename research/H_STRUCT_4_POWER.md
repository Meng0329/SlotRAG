# H-STRUCT-4 POWER ANALYSIS

> **Date**: 2026-09-07
> **Status**: Completed (exploratory-only; execution infeasible)
> **Inputs**: H-STRUCT-3 exploratory shallow trace (n=8,085)

---

## 1. Exploratory Discordant Counts

From `policy_replay_per_question.csv` (H-STRUCT-3), structural_hops < 2 subset:

| Parameter | Value |
|-----------|-------|
| n | 8,085 |
| b (flat-only wins, EM_flat=1 ∧ EM_static=0) | 261 |
| c (static-only wins, EM_static=1 ∧ EM_flat=0) | 431 |
| Discordant rate | 692 / 8,085 = 0.0856 |
| p10 = b/n | 0.0323 |
| p01 = c/n | 0.0533 |
| p_cond = p10 / (p10 + p01) | 0.3772 |
| ΔEM = (b − c)/n | −0.0210 |

---

## 2. Required N (Two-Sided McNemar, α = 0.05)

Method: Normal approximation with continuity correction (p_disc = 0.0856, p_cond = 0.3772).

| Target Power | N Required |
|-------------|-----------|
| 80% | **1,428** |
| 90% | **1,912** |

---

## 3. Practical Availability

- Census shallow pool (structural_hops < 2): **6,133 questions** — well above required N at both power levels.
- Frozen plan snapshots for shallow questions: **0** (see `H_STRUCT_4_EXPOSURE_AUDIT.md`).
- Available for execution after freeze: **0** (INFEASIBLE).

**Conclusion**: Power analysis is moot — the sample pool is large enough, but no questions have frozen SlotPlan snapshots required for execution under §5.

---

## 4. Sensitivity (Exploratory ±20%)

To assess robustness to discordant count uncertainty:

| b ± 20% | c ± 20% | ΔEM | N @80% two-sided |
|---------|---------|-----|-------------------|
| 209 (−20%) | 431 | −0.0274 | ~1,050 |
| 261 | 517 (+20%) | −0.0316 | ~890 |
| 261 | 345 (−20%) | −0.0104 | ~3,200 |

Even the worst-case (b −20%, c +20%) still only requires ~3,200 — well within the 6,133 census shallow pool. The blocker is infrastructure, not power.

---

## 5. H-STRUCT-1 Deep Comparison

For reference, H-STRUCT-1's deep power analysis (p10=0.2797, p01=0.2194, p_disc=0.4991):

| | Deep (H-STRUCT-1) | Shallow (H-STRUCT-4) |
|--|---|---|
| Discordant rate | 49.9% | 8.6% |
| Required N @80% two-sided | 1,061 | 1,428 |
| Population available | 350 (validation) | 6,133 (census) |
| Frozen plans available | 361 | 0 |

The shallow discordant rate is much lower (8.6% vs 49.9%), requiring slightly more questions per cell, but the pool is 17× larger. Frozen plan snapshots are the bottleneck.
