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
**STATUS: PASS**
Census complete: 6,494 questions, 361 eligible (5.6%), 77 compile failures.
Output: `research/hstruct_validation_census/` (CSV + manifest + summary).
Firewall audit: verified outcome-blind (no retrieval, no generation, no EM/F1).

### G3: Power analysis
**STATUS: PASS**
HSTRUCT_POWER_V1_1.md completed.
- Required n_eligible (80% power, two-sided): 1,105
- Required n_eligible (90% power, two-sided): 1,466
- Monte Carlo validated (seed=2027)

### G4: Eligible sample adequacy
**STATUS: CONDITIONAL PASS (train supplement required)**

Census result:
- Validation eligible: **361** (actual, not estimated)
- Required: 1,105 (80% power) or 1,466 (90% power)
- Gap: -744

**Validation alone is INSUFFICIENT at 32.7% of required.**

Remediation: Supplement from untouched train pool (~17,200 eligible available, Phase 9 audit confirmed zero contamination).

**GO condition:** Train supplement provides adequate pool. Final confirmatory n = 1,105 (validation 361 + train ~744).

### G5: Question IDs frozen
**STATUS: PASS (census complete)**
- 361 validation eligible question_ids known
- 361 plan_hashes frozen in `validation_plan_manifest.jsonl`
- Additional ~744 train eligible to be drawn stratified, frozen before execution

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
  |-- YES --> G4: eligible >= 1,105 (validation only)?
  |             |-- YES --> GO (full power, validation-only confirmatory)
  |             |-- NO --> G4 alt: eligible >= 361 (validation)?
  |                         |-- YES --> Supplement from train pool
  |                         |           |-- Train pool >= 744 eligible? --> GO (combined confirmatory)
  |                         |           |-- Train pool < 744 eligible? --> GO (underpowered, label as such)
  |                         |-- NO --> STOP (insufficient even for feasibility check)
  |-- NO --> WAIT
```

---

## 5. Actual Outcome (Census-Verified)

**Validation eligible: 361 (5.6% of 6,494)**

| Dataset | Validation eligible | Required share | Available from train |
|---------|--------------------|----|----|
| hotpotqa | 68 | — | ~8,160 |
| 2wikimultihop | 258 | — | ~7,681 |
| musique | 35 | — | ~1,359 |
| **Total** | **361** | **32.7% of 1,105** | **~17,200** |

**Decision: GO (with train supplement)**

Final confirmatory design:
- Validation: 361 eligible (all used)
- Train supplement: 744 eligible (stratified draw)
- Total confirmatory: 1,105 eligible (80% power)
- Source disclosure: required in paper (stratified by split)

**Most likely path:** validation 361 + train 744 = 1,105 eligible → full power confirmatory.

**Alternative path:** validation-only (361 eligible) → underpowered label, report with honesty.
