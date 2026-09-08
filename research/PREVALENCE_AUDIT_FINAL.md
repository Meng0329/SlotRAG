# PREVALENCE_AUDIT_FINAL.md — Unified Prevalence Figure

> **Date**: 2026-09-08
> **Status**: RESOLVED — all paper instances unified

---

## Resolution

**Final value**: 5.39%

**Derivation**: 350 / 6,494 = 0.05389... ≈ 5.39%

**Definition**: The fraction of validation-set questions (N = 6,494) for which the V1.2 frozen census produced executable deep plans that were confirmed under matched budget B = 8.

## Census Numbers

| Quantity | Value | Denominator |
|----------|-------|-------------|
| Deep-eligible (hops ≥ 2, valid plan) | 361 | 6,494 |
| Deep-executable (confirmed under B=8) | 350 | 6,494 |
| Shallow (hops < 2) | 6,133 | 6,494 |

- 361/6,494 = 5.56% — the eligible census stratum (used for census description only)
- 350/6,494 = 5.39% — the confirmatory-executed stratum (used everywhere in the paper)

## Why 5.39% (not 5.56%)

The population-level ATE is computed over the confirmatory stratum (350 plans), not the full census (361 plans). The 11 plans excluded from confirmation are ineligible for ATE computation. Using the census 361 would overstate the treated fraction. The paper uses 5.39% (350/6,494) as the single prevalence figure.

## ATE Formula Consistency

ATE_pop(A') = 0.054 × 0.0771 = +0.00416

Where 0.054 ≈ 350/6,494 = 5.39%. The formula is internally consistent.

## History of Errors

1. Original threats.tex: "approximately 5.4% (361/6,494)" — WRONG: 361/6494 = 5.56%
2. Original results.tex: "approximately 5.39% (361 eligible / 6,494)" — WRONG: numerator mismatch
3. Commit 7618c80: partially fixed (5.6% for 361/6,494, 5.4% for 350/6,494)
4. This revision: unified to 5.39% everywhere

## Files Updated

- `paper/sections/threats.tex:17` — "approximately 5.39% (350 / 6,494)"
- `paper/sections/analysis.tex:17` — "5.39% of the validation natural workload"
- `paper/sections/analysis.tex:26` — "constitutes 5.39% of the natural workload"
- `paper/sections/results.tex:128` — "constitutes 5.39% of the validation natural workload (350 / 6,494)"
