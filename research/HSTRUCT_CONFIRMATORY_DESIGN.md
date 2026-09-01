# HSTRUCT_CONFIRMATORY_DESIGN.md — Two-Layer Confirmatory Design + Execution Plan

> **Date:** 2026-08-31
> **Protocol:** H-STRUCT-1 V1.1
> **Status:** Design complete, awaiting GO execution

---

## 1. Two-Layer Confirmatory Design (Phase 10)

### 1.1 H-STRUCT-1A: Eligible-Stratum (Primary)

**Question:** Does chain allocation improve EM among questions with structural_hops ≥ 2?

**Design:**
- Population: Eligible questions only (Eligible(q) = 1[hops ≥ 2])
- Sample: 1,105 eligible (361 validation + 744 train supplement)
- Test: McNemar exact test, two-sided α=0.05
- Paired: Each eligible question executed under both static and chain arms
- Primary outcome: ΔEM = EM_chain - EM_static

**Analysis:**
- McNemar χ² with continuity correction
- 95% BCa bootstrap CI (10,000 resamples) for ΔEM
- Discordant pairs: b (static wrong, chain right), c (static right, chain wrong)
- Odds ratio: b/c
- Effect size: Cohen's h or ΔEM

**Decision:**

| Outcome | Condition | Verdict |
|---------|-----------|---------|
| CONFIRMED | Two-sided p < 0.05 AND ΔEM > 0 | Chain beneficial for eligible |
| TENTATIVE | 0.05 ≤ p < 0.10 AND ΔEM > 0 | Insufficient evidence |
| REFUTED | p ≥ 0.10 OR ΔEM ≤ 0 | Chain not beneficial for eligible |

### 1.2 H-STRUCT-1B: Natural-Prevalence (Secondary)

**Question:** What is the expected benefit of deploying Policy A on the full test set?

**Design:**
- Population: All questions (eligible + non-eligible)
- Estimate: ATE_population = p_eligible × ATE_eligible
- Since Δ(q) = 0 for non-eligible by construction, no execution needed for non-eligible
- p_eligible from census: 5.6% (validation), to be confirmed in combined sample

**Analysis:**
- ATE_population = p_eligible × ΔEM_eligible
- Bootstrap CI: resample eligible questions, recompute p_eligible × ΔEM per resample
- Stratified by dataset

**Not a hypothesis test** — this is an effect-size estimation for engineering deployment decisions.

---

## 2. Cost Endpoints (Phase 11)

### 2.1 Efficiency Metrics

| Metric | Definition | Measurement |
|--------|-----------|-------------|
| ΔLLM_calls | mean(LLM_calls_chain) - mean(LLM_calls_static) | Per eligible question |
| Δretrieval_calls | mean(retr_chain) - mean(retr_static) | Per eligible question |
| Δmaterialization_calls | mean(mat_chain) - mean(mat_static) | Per eligible question |
| cost_ratio | total_chain_LLM_calls / total_static_LLM_calls | All questions |
| EM_per_100_LLM_chain | EM_chain / (LLM_calls_chain / 100) | Quality-cost frontier |
| EM_per_100_LLM_static | EM_static / (LLM_calls_static / 100) | Quality-cost frontier |

### 2.2 Budget Compliance

| Metric | Definition | Threshold |
|--------|-----------|-----------|
| max_steps hit rate | % questions hitting max_steps=8 | Report |
| max_llm_calls hit rate | % questions hitting max_llm_calls=96 | Report |
| max_retrieval hit rate | % questions hitting max_retrieval_calls=8 | Report |
| Compilation success rate | % questions with valid SlotPlan | 100% (census: 98.8%) |

### 2.3 Cost-Effectiveness Reporting

The paper must report:
1. EM per 100 LLM calls for each arm (chain vs static)
2. Quality-cost frontier plot (EM vs LLM calls, per arm)
3. Statement: "Chain allocation increases LLM calls in the eligible stratum, but the quality improvement justifies the cost when structural_hops ≥ 2."

---

## 3. Natural-Prevalence Execution (Phase 12)

### 3.1 Eligible Questions (both arms)

```
For each eligible q:
    Result_static(q) = execute(plan_q, arm="static", budget=Budget)
    Result_chain(q) = execute(plan_q, arm="chain", budget=Budget)
    Record: EM_static(q), EM_chain(q), LLM_calls_static(q), LLM_calls_chain(q)
```

Total: 1,105 × 2 = 2,210 executions

### 3.2 Non-Eligible Questions (static arm only)

```
For each non-eligible q:
    Result_static(q) = execute(plan_q, arm="static", budget=Budget)
    Record: EM_static(q), LLM_calls_static(q)
    EM_policyA(q) = EM_static(q)  # by construction
```

Total: ~5,389 × 1 = 5,389 executions

### 3.3 Total Execution Budget

| Component | Count | Notes |
|-----------|-------|-------|
| Eligible × static arm | 1,105 | Primary test (paired) |
| Eligible × chain arm | 1,105 | Primary test (paired) |
| Non-eligible × static arm | ~5,389 | Population effect estimate |
| **Total executions** | **~7,599** | |
| LLM calls (estimated) | ~87,000 | Order of magnitude |

### 3.4 Execution Order

1. Draw 744 train eligible (stratified by dataset proportional to census rates)
2. Freeze all question_ids + plan_hashes (manifest.jsonl)
3. Execute eligible questions (static arm first, then chain arm)
4. Execute non-eligible questions (static arm only)
5. Score all results (EM/F1 for hotpotqa/2wiki/musique)
6. Statistical analysis (McNemar + bootstrap CI)

---

## 4. Primary Baseline (Phase 13)

### 4.1 Baseline Definition

The primary baseline is **static arm** — the default allocation where all slots use static evidence materialization.

**Why not flat or universal-chain?**

- **Flat** (no compilation): Not comparable — different pipeline
- **Universal-chain** (chain for all questions): This is what Policy A is correcting FROM — universal chain causes aggregate harm on shallow plans
- **Static** is the natural baseline: it represents the "no chain allocation" condition, which is what Policy A selects for non-eligible questions

### 4.2 Baseline Justification

| Candidate baseline | Reason rejected |
|-------------------|----------------|
| Flat (no compilation) | Different pipeline, not comparable |
| Universal-chain | Policy A's improvement is relative to this — measuring against it would be circular |
| Random allocation | Not a meaningful operational baseline |
| **Static** | The "no chain" condition — Policy A's counterfactual |

### 4.3 Report Structure

For each dataset:

| Metric | Static (baseline) | Chain (eligible only) | Policy A (combined) |
|--------|------------------|----------------------|---------------------|
| EM | ... | ... | ... |
| F1 | ... | ... | ... |
| LLM calls | ... | ... | ... |
| Retrieval calls | ... | ... | ... |

Policy A column = chain for eligible, static for non-eligible.

---

## 5. Reporting Requirements (Phase 14-15 framework)

### 5.1 Mandatory Report Elements

1. Pre-registration reference (V1.1, commit hash)
2. Flow diagram: 6,494 → 361 eligible (validation) + 744 eligible (train) → 1,105 total eligible → executed → analyzed
3. All exclusion reasons (compile failures, non-eligible)
4. Both estimands (ATE_eligible, ATE_population)
5. Per-dataset breakdown
6. McNemar p-values (two-sided primary, one-sided reference)
7. Effect size (ΔEM) with 95% BCa CI
8. Discordant pairs (b, c), odds ratio
9. Efficiency metrics (ΔLLM_calls, EM per 100 LLM calls)
10. Statement: "This is a confirmatory test. No modifications were made to the policy, threshold, or analysis plan after the compile census was frozen."

### 5.2 Statistical Corrections

- Primary test (H-STRUCT-1A): no correction needed (single test)
- Per-dataset breakdowns: exploratory, reported with nominal p-values
- If additional hypotheses tested: Holm correction applied
- No optional stopping, no mid-course sample adjustment

---

## 6. Source Disclosure (for paper)

The paper must state:

> "The confirmatory sample includes 361 eligible questions from the validation set and 744 eligible questions drawn from the untouched train split (stratified by dataset). Train-to-eval contamination was verified to be zero. Per-split results are reported in Appendix X."

---

## 7. Timeline (Updated)

| Step | Description | ETA |
|------|-------------|-----|
| Draw train supplement | 744 eligible from train (stratified) | ~1 hour (script) |
| Freeze manifest | All 1,105 question_ids + plan_hashes | After draw |
| Execute eligible (static) | 1,105 executions | ~TBD (depends on parallelism) |
| Execute eligible (chain) | 1,105 executions | ~TBD |
| Execute non-eligible (static) | ~5,389 executions | ~TBD |
| Score all results | EM/F1 per dataset | ~30 min |
| Statistical analysis | McNemar + bootstrap CI | ~1 hour |
| Report writing | Confirmatory report | ~2 hours |
| **Total** | | **~TBD** |
