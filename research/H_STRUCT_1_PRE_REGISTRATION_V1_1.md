# H_STRUCT_1_PRE_REGISTRATION_V1_1.md — Confirmatory Depth-Adaptive Policy Test

> **Protocol version:** 1.1
> **Date:** 2026-08-31
> **Status:** FROZEN (no validation answer outcomes observed as of this timestamp)
> **Supersedes:** H_STRUCT_1_PRE_REGISTRATION.md (v1.0, power-analysis correction)
> **Amendment reason:** V1.0 power analysis (n=600 total) was based on total sample size rather than eligible-stratum sample size. Recomputed power shows n_eligible=1,105 required for 80% power. V1.0 contained conflicting claims ("adequate power" in §7.2 vs "underpowered" in §7.4). V1.1 resolves this with correct treatment-domain formalization.

---

## 0. Amendment Log

| Field | Value |
|-------|-------|
| Amendment timestamp | 2026-08-31 |
| Amendment reason | Power analysis correction: required n is eligible-stratum size, not total sample |
| Validation outcomes observed | NO — zero validation answers have been generated |
| Policy A changed | NO — frozen at: chain if structural_hops ≥ 2, else static |
| tau changed | NO — frozen at 2 |
| Candidate changed | NO — frozen at A (not B or C) |
| Only changed | Sampling design, statistical framework, estimand formalization |

---

## 1. Treatment Domain Formalization

### 1.1 Eligibility

```
Eligible(q) = 1[structural_hops(q) >= 2]
```

Policy A and static differ **only** when `Eligible(q) = 1`.

For `Eligible(q) = 0`: `Policy_A(q) == Static(q)` **by construction** (both use static arm).

Therefore: `Δ(q) = Y_A(q) - Y_static(q) = 0` for all `Eligible(q) = 0`.

### 1.2 Two Estimands

**Estimand 1 — Eligible-Stratum Treatment Effect (ATE_eligible):**

```
ATE_eligible = E[Y_A - Y_static | Eligible = 1]
```

This is the **primary estimand**. It measures the effect of chain allocation among questions whose compiled plans have structural depth ≥ 2.

**Estimand 2 — Natural-Prevalence Policy Effect (ATE_population):**

```
ATE_population = P(Eligible = 1) × ATE_eligible
```

Since `Δ(q) = 0` for all non-eligible questions, the population effect is simply the eligible effect weighted by eligibility prevalence.

### 1.3 Why Two Estimands?

ATE_eligible answers: "Does chain help when it matters?" (the scientific question)
ATE_population answers: "What is the expected benefit of deploying Policy A on the full test set?" (the engineering question)

The paper must report both.

---

## 2. Policy Definition (Frozen)

```
Policy A (depth_only):
    if structural_hops(plan) >= 2:
        arm = "chain"
    else:
        arm = "static"

structural_hops(plan):
    G = build_structural_evidence_graph(plan)  # joins + field_argmin/field_argmax
    return exact_longest_simple_path(G)         # DFS with backtracking, edge count
```

**Frozen parameters:**

| Parameter | Value | Frozen since |
|-----------|-------|-------------|
| tau | 2 | Exploratory discovery |
| Policy | A (depth_only) | Selected by exploratory offline replay |
| Graph edges | joins + field_argmin/field_argmax | STRUCTURAL_DEPTH_CORRECTION_REPORT |
| Longest path | exact DFS with backtracking, edge count | Phase 2 correction |
| Generator | qwen3.5-9b | TKDE protocol |
| Budget | max_steps=8, max_llm_calls=96, max_retrieval_calls=8 | Frozen protocol |

**Prohibited modifications (locked by this pre-registration):**

- tau (not re-estimated from validation)
- topology condition (Candidate B/C rejected)
- fallback arm (static is frozen)
- chain importance threshold
- retrieval budget
- generator model
- prompts
- physical allocation internals

---

## 3. Hypotheses

### 3.1 H-STRUCT-1A (Primary — Eligible-Stratum)

**H0:** `ATE_eligible ≤ 0` (chain does not improve EM among eligible questions)
**H1:** `ATE_eligible > 0` (chain improves EM among eligible questions)

**Statistical test:** McNemar exact test on paired binary outcomes (correct/incorrect) for eligible questions only.

**Significance:** α = 0.05, two-sided. One-sided p-value also reported for reference.

**Decision:**

| Outcome | Condition | Verdict |
|---------|-----------|---------|
| CONFIRMED | Two-sided p < 0.05 AND point estimate ΔEM > 0 | H-STRUCT-1A supported |
| TENTATIVE | 0.05 ≤ p < 0.10 AND ΔEM > 0 | Insufficient evidence, larger holdout needed |
| REFUTED | p ≥ 0.10 OR ΔEM ≤ 0 | H-STRUCT-1A rejected |

### 3.2 H-STRUCT-1B (Secondary — Natural-Prevalence)

**Computed, not tested.** Uses the eligibility prevalence from the compile census:

```
ATE_population = p_eligible × ATE_eligible
```

Reported with stratified bootstrap 95% CI (10,000 resamples).

---

## 4. Sample Size and Power

### 4.1 Power Basis

Power is computed over **eligible questions only** (not total sample).

From exploratory data (n_eligible = 547):
- b = 153 (static wrong, chain right)
- c = 120 (static right, chain wrong)
- p10 = 0.2797, p01 = 0.2194
- Discordant rate = 0.499

### 4.2 Required Eligible Sample Size

| Target | Test | Required n_eligible |
|--------|------|-------------------|
| 80% power | McNemar two-sided, α=0.05 | **1,105** |
| 90% power | McNemar two-sided, α=0.05 | **1,466** |

### 4.3 Validation Set Eligible Inventory

Expected eligible per dataset (at exploratory prevalence):

| Dataset | validation_set | Eligible rate | Expected eligible |
|---------|---------------|---------------|-------------------|
| hotpotqa | 2,146 | 9.1% | ~194 |
| 2wikimultihop | 3,698 | 4.6% | ~171 |
| musique | 650 | 6.9% | ~44 |
| **Total** | **6,494** | **6.3%** | **~409** |

### 4.4 Gap Analysis

| | Required (80%) | Required (90%) | Validation available |
|---|---|---|---|
| n_eligible | 1,105 | 1,466 | ~409 |
| Gap | -696 | -1,057 | — |

**Validation alone provides ~37% of the required sample for 80% power.**

### 4.5 Additional Data Sources

If validation eligible is insufficient, supplement from:

1. **Untouched train split** — questions never used for any method development, threshold discovery, or experiment (Phase 9 audit)
2. **development_set** — excluded due to method-development exposure; may be usable for population-effect estimation only if explicitly disclosed

The confirmatory report must clearly state which data source each eligible question comes from, and stratify accordingly.

---

## 5. Data Sources

### 5.1 Primary: validation_set (UNEXPOSED)

- Source: `research/eval_sets/test_set.json` → validation split
- Exposure status: **NEVER executed** by sealed pipeline, never used for threshold discovery, never used for policy selection
- Eligible count: determined by Phase 5 compile census

### 5.2 Supplementary: untouched train split (if needed)

- Source: train splits of hotpotqa, 2wikimultihop, musique from `benchmark/`
- Exposure status: to be determined by Phase 9 audit
- Eligible count: determined by Phase 9 audit

### 5.3 Restriction

Questions from `development_set` are **NOT eligible** for confirmatory testing (used for method development).

---

## 6. Execution Protocol

### 6.1 For Each Eligible Question q

```
Plan_q = SlotCompiler(q)              # frozen plan, LLM compile only
Budget_q = {max_steps=8, max_llm_calls=96, max_retrieval_calls=8}

# Static arm execution:
Result_static(q) = execute(Plan_q, arm="static", budget=Budget_q)

# Chain arm execution:
Result_chain(q) = execute(Plan_q, arm="chain", budget=Budget_q)

# Record:
Y_static(q) = Result_static(q).EM
Y_chain(q) = Result_chain(q).EM
```

### 6.2 For Non-Eligible Questions (if reporting ATE_population)

```
Result_static(q) = execute(Plan_q, arm="static", budget=Budget_q)
Y_static(q) = Result_static(q).EM
Y_policyA(q) = Y_static(q)     # by construction
```

No chain execution needed for non-eligible questions.

### 6.3 Strict Single-Execution Rule

Each question is executed **exactly once per arm** (eligible) or **exactly once** (non-eligible). No re-runs, no retries, no budget inflation.

---

## 7. Statistical Analysis

### 7.1 Primary Test (H-STRUCT-1A)

- **Test:** McNemar exact test (continuity-corrected χ² with 1 df)
- **Population:** Eligible questions only
- **Report:** ΔEM, 95% CI ( bootstrap BCa, 10,000 resamples), discordant pairs (b, c), odds ratio, p-value (two-sided), p-value (one-sided)

### 7.2 Secondary Test (H-STRUCT-1B)

- **Estimate:** ATE_population = p_eligible × ATE_eligible
- **CI:** Stratified bootstrap (resample within each dataset), 10,000 resamples, 95% BCa
- **Not a hypothesis test** — this is an effect-size estimation

### 7.3 Per-Dataset Breakdown

Report separately for each dataset:

| Dataset | n_eligible | ΔEM | discordant b | discordant c | OR | McNemar p |
|---------|------------|-----|-------------|-------------|-----|-----------|

### 7.4 Efficiency Endpoints

| Endpoint | Definition |
|----------|-----------|
| ΔLLM_calls | mean(LLM_calls_chain) - mean(LLM_calls_static) among eligible |
| Δretrieval_calls | mean(retr_chain) - mean(retr_static) among eligible |
| cost_ratio | total_chain_calls / total_static_calls (all questions) |
| EM_per_100_LLM | EM / (LLM_calls/100) — quality-cost frontier metric |

### 7.5 Multiple Testing

- Primary test (H-STRUCT-1A): no correction needed (single test)
- Per-dataset breakdowns: exploratory, reported with nominal p-values
- If additional hypotheses are tested (e.g., topology-stratified): Holm correction applied

### 7.6 Prohibited Statistical Practices

- No optional stopping
- No mid-course sample size adjustment
- No peeking at p-values to decide whether to collect more data
- No post-hoc tau adjustment
- No Candidate A→B/C switch after seeing results
- No selective reporting of significant datasets

---

## 8. Reporting Requirements

The confirmatory report must include:

1. This pre-registration document (V1_1) referenced by hash
2. Complete flow diagram: questions → compiled → eligible → executed → analyzed
3. All exclusion reasons documented
4. Both estimands (ATE_eligible and ATE_population) reported
5. Per-dataset breakdown
6. Both p-values (one-sided and two-sided)
7. Effect size (ΔEM) with CI
8. Efficiency metrics
9. Statement: "This is a confirmatory test. No modifications were made to the policy, threshold, or analysis plan after the compile census was frozen."

---

## 9. GO Criterion for Execution

All of the following must be satisfied before confirmatory answer execution begins:

| Gate | Condition | Status |
|------|-----------|--------|
| G1 | V1.1 pre-registration frozen | THIS DOCUMENT |
| G2 | Validation compile census complete, outcome-blind | Phase 5-6 |
| G3 | Exact power analysis completed | Phase 7 |
| G4 | Eligible sample ≥ required n, OR explicitly labeled "underpowered" | Phase 8 |
| G5 | All question_ids and plan_hashes frozen | Phase 5 |
| G6 | Execution commands, budget, seed, model frozen | §6 above |

If G4 fails (validation insufficient + no additional data): the study is labeled **"underpowered confirmatory study"** and all claims are appropriately hedged.

---

## 10. Timeline

| Phase | Description | ETA |
|-------|-------------|-----|
| 5 | Validation compile census | ~4 hours (SlotCompiler on 6,494 questions) |
| 6 | Exposure firewall audit | ~1 hour |
| 7 | Power analysis | DONE (this document) |
| 8 | Eligible inventory comparison | After Phase 5 |
| 9 | Additional untouched-data audit | ~2 hours |
| 10-11 | Confirmatory design + cost endpoints | After Phase 8-9 |
| 15 | GO decision | After all gates satisfied |
| Execution | Confirmatory answers (if GO) | ~TBD based on n |

---

## Appendix A: Relationship to V1.0

| Aspect | V1.0 | V1.1 |
|--------|------|------|
| Power basis | Total sample n=600 | Eligible-stratum n |
| Required n (80% power) | Not computed correctly | 1,105 eligible |
| Estimand | Implicit | Explicit (ATE_eligible + ATE_population) |
| One/two-sided | One-sided | Two-sided primary, one-sided reported |
| Treatment domain | Not formalized | Eligible(q) = 1[hops ≥ 2] |
| Source of eligible | validation_set only | validation + untouched train (if needed) |
| Baseline | static (confirmed) | static (confirmed) |
| Policy | A (confirmed) | A (confirmed) |
| tau | 2 (confirmed) | 2 (confirmed) |
