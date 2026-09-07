# H-STRUCT-4 PRE-REGISTRATION — INDEPENDENT SHALLOW-GATE CONFIRMATION

> **Date**: 2026-09-07
> **Pre-Outcome Commit SHA**: e64ab9d6e978a3b41b88a2d38a0dca1cc47da22d
> **Status**: PRE-REGISTERED (execution BLOCKED — see §Feasibility)
> **RQ-STRUCT-4**: Under the same frozen matched-budget protocol, does applying the global budget-aware flat optimizer (uniform importance={}) to shallow compiled plans (structural_hops < 2) reduce answer quality relative to static physical execution?

---

## §1 Primary Estimand

ATE_shallow = E[EM_flat − EM_static | Shallow=1, Executable=1]

Tested via two-sided exact McNemar on discordant pairs: b (flat-only wins) vs c (static-only wins).

---

## §2 Hypothesis

**H-STRUCT-4A**: H₁: EM_flat < EM_static (one-directional claim, two-sided test).

Gate confirmed iff: ΔEM < 0 AND p < 0.05 AND 95% CI entirely < 0.

---

## §3 Candidate Pool

- **Primary pool**: V1.2 validation frozen census, structural_hops < 2, UNEXPOSED only.
- **Reserve pool**: Unexposed questions from validation census with frozen plan snapshots.
- **Forbidden**: questions already in H-STRUCT-1/2/3 confirmatory manifests; re-compilation of plans.

---

## §4 Prohibited Actions

- Modifying Policy A′ (P_gate_flat)
- Modifying the structural_hops definition
- Searching new thresholds, learned routers, new optimizers
- Modifying static/flat methods
- Re-running deep confirmatory samples
- Using exploratory outcomes to adjust samples or sample sizes
- Mid-run sample changes

---

## §5 Frozen Plan Requirement

SlotCompiler calls = 0 (no new plan compilation). Each candidate must have full frozen SlotPlan plan_json, plan_sha256, compiler_options, input_sha256, and structural_hops in a pre-frozen snapshot.

If frozen snapshot is missing, corrupt, or has hash mismatch → the question cannot enter the primary pool. Use the next pre-frozen reserve candidate. Re-compilation to fix is prohibited.

---

## §6 Arms

Only two arms: `slotrag-g7-static` and `slotrag-g7-flat`. Model: qwen3.5-9b. Budget: max_steps=8, max_retrieval_calls=8, max_llm_calls=96.

---

## §7 Sampling

Dataset-stratified proportional sampling from eligible census-shallow candidates. Seed = 2027. No 2Wiki enrichment.

---

## §8 Statistics

Primary: binomtest(b, n=b+c, p=0.5, two-sided). Report N, Static EM, Flat EM, ΔEM, b, c, discordant, exact p, odds ratio.

Paired bootstrap: `paired_bootstrap_vector` (iterations=10,000, seed=2027). No boot_comps[0] bug.

Dataset heterogeneity with Holm correction. Secondary: F1, cost (LLM/retrieval permutation p).

---

## §9 Power Analysis

From exploratory shallow trace (n=8,085): b=261, c=431, p10=0.0323, p01=0.0533, discordant rate=8.56%.

Required N @80% two-sided: 1,428. Required N @90% two-sided: 1,912. Census shallow pool: 6,133 (sufficient count).

---

## §Feasibility — BLOCKED

**V1.2 validation census stored only plan_hash (not plan_json) for the 6,133 census-shallow questions.** Only the 361 census-deep eligible questions received full SlotPlan frozen snapshots. Zero census-shallow questions have frozen SlotPlan plan_json anywhere in the repository.

Per §5, the primary candidate pool is **empty** (0 questions). Execution cannot proceed without violating the no-recompilation constraint.

This is documented in `H_STRUCT_4_EXPOSURE_AUDIT.md`. The spec conflict is structural: the V1.2 census snapshot infrastructure did not persist full plans for non-eligible (shallow) questions.
