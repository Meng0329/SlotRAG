# H-STRUCT-4 INTERACTION SYNTHESIS — Treatment × Structural-Regime

> **Date**: 2026-09-07
> **Status**: NOT COMPUTABLE — execution infeasible (primary pool empty)

---

## 1. Why No Interaction Contrast Exists

Spec §16 mandates: IF CASE A (GATE CONFIRMED, CI entirely < 0), build the Treatment×Structural-Regime interaction table with a bootstrap CI on the contrast. H-STRUCT-4's execution is **INFEASIBLE** (see `H_STRUCT_4_FINAL_REPORT.md`), so CASE A is never reached. No shallow-side flat-vs-static pairs exist, so the contrast

    interaction = ATE_deep(flat − static) − ATE_shallow(flat − static)

cannot be estimated from confirmatory data.

---

## 2. What Is Known (For a Future Census-and-Freeze Phase)

The two regime-level estimates available today:

| Regime | Source | flat − static ΔEM | Confidence |
|--------|--------|-------------------|------------|
| Deep (hops ≥ 2) | H-STRUCT-1/2 confirmatory validation n=350 (+ H-STRUCT-2 flat arm) | **+0.0771** | CI [+0.0486, +0.1086]; exact McNemar p=1.4e-06 |
| Shallow (hops < 2) | H-STRUCT-3 exploratory trace n=8,085 | **−0.0210** | CI [−0.0273, −0.0146]; p<0.001 |

The sign-flip between regimes (deep positive, shallow negative) is the qualitative basis of the gate. A confirmatory interaction contrast would require:

1. A V1.3 census that persists full `plan_json` for shallow questions (infrastructure gap identified in H-STRUCT-4).
2. A new freeze phase for the shallow pool.
3. Execution of a fresh, unexposed shallow sample under matched-budget B=8.

N(P) required: 1,428 @80% two-sided (power analysis in `H_STRUCT_4_POWER.md`).

---

## 3. Recorded Statement

> "The structural-depth gate is supported by the sign-flip in treatment effects between the deep regime (flat > static, confirmatory) and the shallow regime (flat < static, exploratory). A confirmatory interaction contrast could not be produced because the V1.2 frozen census lacks plan snapshots for shallow questions, leaving the primary pool empty under the no-recompilation constraint."