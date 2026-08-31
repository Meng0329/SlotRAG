# HSTRUCT_GO_CRITERION.md — Phase 15 GO/STOP Decision Framework

> **Date:** 2026-08-31
> **Purpose:** Define the GO criterion for initiating confirmatory answer execution

---

## 1. GO Gates

All 6 gates must be satisfied BEFORE confirmatory answer execution begins.

| Gate | Condition | Status |
|------|-----------|--------|
| G1 | H_STRUCT_1_PRE_REGISTRATION_V1_1.md frozen | DONE |
| G2 | Validation compile census complete, outcome-blind | IN PROGRESS |
| G3 | Exact power analysis completed | DONE |
| G4 | Eligible sample >= required n OR explicitly labeled "underpowered" | PENDING (after G2) |
| G5 | All question_ids and plan_hashes frozen | PENDING (after G2) |
| G6 | Execution commands, budget, seed, model frozen | DONE (in V1.1) |

---

## 2. Current Assessment

### G1: Pre-registration frozen
**STATUS: PASS**
H_STRUCT_1_PRE_REGISTRATION_V1_1.md is written and frozen at timestamp 2026-08-31.

### G2: Census outcome-blind
**STATUS: IN PROGRESS**
Census running (PID 1134266). Expected completion ~2h.

### G3: Power analysis
**STATUS: PASS**
HSTRUCT_POWER_V1_1.md completed.
- Required n_eligible (80% power, two-sided): 1,105
- Required n_eligible (90% power, two-sided): 1,466
- Monte Carlo validated (seed=2027)

### G4: Eligible sample adequacy
**STATUS: PENDING** (depends on G2)

Expected from census:
- Validation eligible: ~409 (from exploratory prevalence rates)
- Required: 1,105 (80% power) or 1,466 (90% power)

If validation provides ~409: **underpowered at 80% target**

Remediation options:
1. Supplement from untouched train pool (17,200 eligible available)
2. Label as "underpowered confirmatory study" and report honestly

V1.1 allows option 2.

### G5: Question IDs frozen
**STATUS: PENDING** (depends on G2)

After census completes:
- All validation question_ids are known
- All plan_hashes are known
- These become the frozen confirmatory set

### G6: Execution frozen
**STATUS: PASS**
- Generator: qwen3.5-9b
- Budget: max_steps=8, max_llm_calls=96, max_retrieval_calls=8
- Policy: A (chain if hops >= 2, else static)
- tau: 2
- Seed: 2027
- Method: slotrag (base)

---

## 3. STOP Conditions

Execution must NOT proceed if any of the following are true:

1. Census reveals answer generation or EM scoring occurred
2. Census reveals retrieval was performed
3. Any validation question_id was previously used in a non-census context
4. The census is incomplete (partial results only)
5. The pre-registration was modified after census completion

---

## 4. Post-GO Decision Tree

```
G2 complete?
  |-- YES --> G4: eligible >= 1,105?
  |             |-- YES --> GO (full power confirmatory)
  |             |-- NO --> G4 alt: eligible >= 600?
  |                         |-- YES --> GO (underpowered, label as such)
  |                         |-- NO --> STOP (insufficient even for feasibility check)
  |-- NO --> WAIT
```

---

## 5. Expected Outcome

Based on exploratory eligible rates (6.3%):
- Validation eligible: ~409
- Gap to 80% power: -696
- Available from train: ~17,200

**Most likely path:** validation ~409 is below threshold, supplement from train pool to reach ~1,105.

**Alternative path:** label as underpowered confirmatory study (V1.1 allows this).

Either path requires:
1. Census completion (G2)
2. Source disclosure in the paper
3. Stratified analysis by source split
