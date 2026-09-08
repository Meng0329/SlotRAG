# FINAL_CLAIM_AUDIT.md — Overclaiming Scan

> **Date**: 2026-09-08
> **Scope**: Every factual claim in the paper, checked against experimental evidence. Red = overclaim; Yellow = fragile; Green = supported.

---

## Abstract Claims

| # | Claim | Location | Verdict | Fix |
|---|-------|----------|---------|-----|
| A1 | "every observed budget exhaustion violated global allocation feasibility (recall 1.0)" | abstract L35-36 | ✅ GREEN | — |
| A2 | "many infeasible plans terminated without exhausting the budget (precision 0.533)" | abstract L37-38 | ✅ GREEN | — |
| A3 | "improves answer quality by 7.7 EM points ... p < 10^{-6}, exact McNemar" | abstract L39-41 | ✅ GREEN | Exact p=1.4e-6; 10^{-6} is valid upper bound |
| A4 | "eliminates all 146 observed budget-exhaustion events" | abstract L41 | ✅ GREEN | — |
| A5 | "uniform budget-aware optimizer outperforms a dependency-weighted variant ... EM difference +0.009, p = 0.743" | abstract L43-44 | 🟡 YELLOW | +0.009 is rounded from +0.0086; "outperforms" is directional language for a non-significant result. Soften to "matches" or "is not significantly different from" |
| A6 | "applying the budget-aware optimizer to structurally shallow plans can reduce answer quality (-0.021 EM, p < 0.001)" | abstract L46-47 | 🟡 YELLOW | Correct but not qualified as exploratory in the abstract — should add "(exploratory)" |
| A7 | "The gate's independent confirmation on shallow matched-budget executions was pre-registered but could not be executed" | abstract L48-49 | ✅ GREEN | Honest disclosure |
| A8 | "a mechanism for regime-sensitive physical planning whose confirmatory benefit is established on the deep plans where it was designed to operate" | abstract L52 | ✅ GREEN | Correct scoping |

## Introduction Claims

| # | Claim | Location | Verdict | Fix |
|---|-------|----------|---------|-----|
| I1 | "structurally deep plans (where evidence requirements involve three or more slots joined through intermediate bindings)" | intro L7 | 🟡 YELLOW | Deep = hops ≥ 2, not necessarily "three or more slots" — a 2-slot plan with a join AND operator could be hops=2. Simplify to "structurally deep plans (hops ≥ 2)" |
| I2 | "budget-aware allocation improves answer quality by 7.7 EM points and eliminates all budget-exhaustion events" | intro L7 | ✅ GREEN | Confirmatory, paired, B=8 |
| I3 | "the same optimizer can reduce answer quality by 2.1 EM points (p < 0.001 in exploratory analysis)" | intro L7 | 🟡 YELLOW | Correct but "in exploratory analysis" qualifier present — OK. The p-value is from the exploratory trace, not matched B=8. Should note budget regime differs |
| I4 | "many infeasible plans completed without exhausting the budget (precision 0.533)" | intro L15 | ✅ GREEN | — |
| I5 | "Confirmatory experiments on deep executable plans show the planner improves answer quality" | intro L17 (C3) | ✅ GREEN | Correct for the planner (flat vs static on deep); the gate component of C3 is NOT confirmatory |
| I6 | "Large-scale exploratory replay provides evidence that retaining static execution outside the deep regime is justified" | intro L17 (C3) | ✅ GREEN | Correctly labeled exploratory |

## Results Claims

| # | Claim | Location | Verdict | Fix |
|---|-------|----------|---------|-----|
| R1 | "146 of 350 plans experience budget exhaustion (41.7%)" | results L20 | ✅ GREEN | 146/350 = 0.4171 ✓ |
| R2 | "precision = 146 / 274 = 0.533" | results L20 | ✅ GREEN | 146/274 = 0.5328 ✓ |
| R3 | "The flat planner improves EM by 7.71 points ... discordant pairs: b=30, c=3" | results L42 | ✅ GREEN | b=30 (flat wins), c=3 (static wins). McNemar correct |
| R4 | "reduces budget-exhaustion events from 146 to 0" | results L44 | ✅ GREEN | By construction Σa_s ≤ B |
| R5 | "chain law yields ΔEM = +0.0086 (p = 0.743, 95% CI includes zero)" | results L65 | ✅ GREEN | — |
| R6 | "Flat allocation reduces EM by 2.10 points on shallow plans (p < 0.001)" | results L93 | 🟡 YELLOW | Exploratory trace, permissive budget — should note this differs from matched B=8 |
| R7 | "the deep-eligible stratum constitutes approximately 5.39% of the validation natural workload (361 eligible / 6,494 total)" | results L128 | 🔴 RED | **5.39% = 350/6494, not 361/6494. 361/6494 = 5.56%.** Numerator mismatch with percentage. ATE uses 0.054 = 350/6494 — correct for confirmatory, but label is wrong |
| R8 | "ATE_pop(A') = 0.054 × 0.0771 = +0.00416 EM/question" | results L130 | 🟡 YELLOW | 0.054 ≈ 350/6494 = 5.39%. The formula is correct if the fraction represents the confirmatory-stratum prevalence, but the preceding sentence attributes it to "361 eligible". Fix: label as 350/6494 |

## Analysis Claims

| # | Claim | Location | Verdict | Fix |
|---|-------|----------|---------|-----|
| D1 | "41.7% of static executions exhaust the budget" | analysis L2 | ✅ GREEN | 146/350 = 41.7% ✓ |
| D2 | "The flat planner eliminates these events entirely by design" | analysis L2 | ✅ GREEN | Σa_s ≤ B by construction |
| D3 | "the harm is concentrated on 2WikiMultiHop (ΔEM = -0.045 on hops-0 questions)" | analysis L5 | 🟡 YELLOW | Post-hoc subgroup, not pre-registered; should add "exploratory" qualifier |
| D4 | "The dependency-weighted allocator is more expensive conceptually" | analysis L8 | 🟡 YELLOW | "more expensive conceptually" is vague; both are O(n). Rephrase to "more complex to define" or similar |
| D5 | "There are no learned parameters, no reinforcement-learning loops" | analysis L11 | ✅ GREEN | — |
| D6 | "The population-level ATE of +0.004 EM/question reflects this low prevalence" | analysis L20 | 🟡 YELLOW | Says "5.4%" → should be "5.4%" (350/6494 = 5.39% ≈ 5.4% — this is approximately correct for the confirmatory stratum) |

## Threats Claims

| # | Claim | Location | Verdict | Fix |
|---|-------|----------|---------|-----|
| T1 | "approximately 5.4% (361 / 6,494)" | threats L17 | 🔴 RED | **361/6494 = 5.56%, not 5.4%.** This is a factual error. Fix to "approximately 5.6% (361 / 6,494)" or change numerator to 350 for the confirmatory stratum |
| T2 | "361 plans as deep and 6,133 as shallow" | threats L8 | ✅ GREEN | 361+6133=6494 ✓ |
| T3 | "V1.2 frozen census did not persist full SlotPlan payloads for shallow questions" | threats L20 | ✅ GREEN | Factually accurate |

## Conclusion Claims

| # | Claim | Location | Verdict | Fix |
|---|-------|----------|---------|-----|
| C1 | "improves answer quality by 7.7 EM points and eliminates all 146 budget-exhaustion events" | conclusion L7 | ✅ GREEN | — |
| C2 | "a dependency-sensitive importance law is ablated" | conclusion L9 | ✅ GREEN | — |
| C3 | "The independent shallow-regime confirmation was pre-registered but could not be executed" | conclusion L11 | ✅ GREEN | — |

---

## Summary of Overclaiming Findings

### 🔴 RED (must fix)

1. **Prevalence arithmetic inconsistency** (results.tex:128, threats.tex:17): 361/6494 = 5.56%, not 5.4% or 5.39%. Three different numbers used for the same or related quantities with no consistent numerator.

### 🟡 YELLOW (should fix)

2. **A5** (abstract): "outperforms" for non-significant p=0.743 result — soften to "matches"
3. **A6** (abstract): shallow harm not labeled exploratory
4. **I1** (intro): "three or more slots" does not exactly match hops ≥ 2 definition
5. **I3** (intro): shallow harm p-value from permissive budget, not B=8
6. **R6** (results): shallow harm from permissive budget should note budget regime difference
7. **R8** (results): ATE fraction label inconsistent with formula
8. **D3** (analysis): 2Wiki sub-group finding not pre-registered
9. **D4** (analysis): "more expensive conceptually" is imprecise
10. **D6** (analysis): "5.4%" consistent with 350/6494 ≈ 5.39% but should use exact figure

### ✅ GREEN (no fix needed)

All other claims are supported by the reported evidence.
