# H_STRUCT_1_PRE_REGISTRATION.md — Confirmatory Depth-Adaptive Policy Test

> **Protocol version:** 1.0
> **Date:** 2026-08-31
> **Status:** ⛔ SUPERSEDED BEFORE DATA COLLECTION (replaced by V1_1, power-analysis correction)
> **Superseded by:** H_STRUCT_1_PRE_REGISTRATION_V1_1.md
> **Triggered by:** STRUCTURE_GATE_OFFLINE_REPLAY.md → CONDITIONAL GO (all 4 gates passed)

---

## 1. Background and Rationale

### 1.1 Exploratory Finding

The EXPLORATORY MECHANISM DISCOVERY SET (25,983 sealed items, hotpotqa/2wikimultihop/musique, test_set, 3-arm) revealed that:

1. **Depth × chain allocation interaction is significant** (permutation p=0.000 pooled, 10k perms)
2. **Chain allocation helps deep plans but hurts shallow plans**: chain-static ΔEM = +0.060 at hops≥2, −0.027 at hops<1
3. **Depth-adaptive policies outperform fixed policies**: Candidate A (chain if hops≥2, else static) achieves macro EM=0.4483 vs static=0.4434 (+0.49pt)
4. **The effect is NOT driven by HotpotQA depth≥4 alone**: LOSA (excluding Hotpot depth≥4) preserves macro EM=0.4478 vs 0.4454 (+0.24pt)

### 1.2 Terminology

- **structural_hops** = number of edges on the longest simple path in the compiled structural evidence graph (NOT "true reasoning depth")
- **structural_nodes** = structural_hops + 1
- **Threshold tau=2**: structural_hops ≥ 2 means "deep" (3+ node chains)
- Corrections applied per STRUCTURAL_DEPTH_CORRECTION_REPORT.md

### 1.3 Why Confirmatory?

The exploratory analysis:
- Used test_set for ALL 3 target datasets (100% exposure)
- Discovered tau=2 and Candidate A/B/C FROM the same data
- Generated ~20 hypothesis files with embedded question_ids

**Any claim of improvement from this data alone is circular.** A genuine confirmatory test requires an independent holdout that was never used for threshold discovery, policy selection, or failure analysis.

---

## 2. Hypothesis

**H-STRUCT-1:** A depth-adaptive arm selection policy (chain if structural_hops ≥ 2, else static) achieves macro EM ≥ static policy on a stratified holdout from validation_set.

### 2.1 Null Hypothesis

**H0:** macro_EM(A_depth_only) ≤ macro_EM(P0_static) on the holdout set.

### 2.2 Alternative Hypothesis

**H1:** macro_EM(A_depth_only) > macro_EM(P0_static) on the holdout set.

### 2.3 Direction

One-sided (we expect improvement, not harm).

---

## 3. Policy Definition (Frozen)

```
Policy A (depth_only):
  if structural_hops(plan) >= 2:
    arm = "chain"
  else:
    arm = "static"

structural_hops(plan):
  G = build_structural_evidence_graph(plan)  # joins + field_argmin/field_argmax
  return exact_longest_simple_path(G)        # DFS with backtracking, edge count
```

**Frozen parameters:**
- tau = 2 (NOT re-estimated)
- Policy = A (NOT B or C)
- Graph = joins + field_argmin/field_argmax edges
- Longest path = exact DFS with backtracking (edge count)

---

## 4. Data Source

### 4.1 Holdout Construction

Since test_set is fully exposed for hotpotqa/2wikimultihop/musique, the holdout is drawn from **validation_set**.

**Stratified random sample (seed=2027):**

| Dataset | validation_set size | Holdout sample | Sampling |
|---------|-------------------|----------------|----------|
| hotpotqa | 2,146 | 200 | Stratified by complexity (if available), else uniform |
| 2wikimultihop | 3,698 | 200 | Stratified by complexity (if available), else uniform |
| musique | 650 | 200 | Stratified by complexity (if available), else uniform |
| **Total** | **6,494** | **600** | |

### 4.2 Why 600?

- Budget: 600 items × 3 arms = 1,800 executions
- At ~56s/question serial with parallel=8: ~21 hours
- Provides adequate power for McNemar test (estimated power > 0.80 for ΔEM ≥ 0.03)

### 4.3 Restrictions

The holdout must NOT be used for:
- Adjusting tau (frozen at 2)
- Selecting between Candidate A/B/C (frozen at A)
- Tuning any hyperparameter
- Modifying the policy rule
- Any post-hoc analysis that changes the hypothesis

Any such modification invalidates the confirmatory claim.

---

## 5. Evaluation Protocol

### 5.1 Execution

- Each holdout question is executed under both Policy A and Policy A's static baseline
- Budget: matched (same max_steps=8, max_llm_calls=96, max_retrieval_calls=8)
- Services: qwen3.5-9b (generation), Qwen3-Embedding-0.6B, bge-reranker-v2-m3
- The execution MUST be logged as a new experiment (not mixed with exploratory data)

### 5.2 Primary Metric

**McNemar test** on paired binary outcomes (correct/incorrect) between Policy A and static.

- Test statistic: McNemar's χ² (with continuity correction for small samples)
- Significance level: α = 0.05 (one-sided)
- Report: p-value, odds ratio, 95% CI for difference in EM

### 5.3 Secondary Metrics

- **Macro EM**: mean per-dataset EM (hotpotqa, 2wikimultihop, musique)
- **Bootstrap CI**: 10,000 resamples, 95% BCa CI for macro EM difference
- **Cohen's d**: paired effect size
- **LLM call reduction**: mean reduction in calls per question
- **Cost ratio**: Policy A total cost / static total cost (LLM calls as proxy)

### 5.4 Per-Dataset Breakdown

Report McNemar test AND 95% CI for each dataset separately:
- hotpotqa (n=200)
- 2wikimultihop (n=200)
- musique (n=200)

---

## 6. Decision Criteria

### 6.1 Primary Decision

| Outcome | Condition | Verdict |
|---------|-----------|---------|
| PASS | McNemar p < 0.05 AND macro EM(A) > macro EM(static) | H-STRUCT-1 CONFIRMED |
| MARGINAL PASS | McNemar p < 0.10 AND macro EM(A) > macro EM(static) | H-STRUCT-1 TENTATIVE (requires larger holdout) |
| FAIL | McNemar p ≥ 0.10 OR macro EM(A) ≤ macro EM(static) | H-STRUCT-1 REFUTED |

### 6.2 Robustness Checks

- **LOSA**: exclude hotpotqa structural_hops≥4, verify effect survives
- **Per-dataset consistency**: at least 2/3 datasets show positive ΔEM
- **Budget-exceeded rate**: Policy A must not increase budget-exceeded rate by > 2pt

---

## 7. Sample Size and Power Analysis (Computed)

### 7.1 Discordant Pair Rate (from exploratory set)

From the exploratory 3-arm paired set (8,633 questions):
- Deep questions (hops≥2): n=547, chain-static ΔEM = +0.0603
- Estimated discordant pairs: b=153 (static wrong, chain right), c=120 (static right, chain wrong)
- b − c = 33 ≈ n × ΔEM = 547 × 0.0603 = 33 ✓

### 7.2 Power for Deep-Regime McNemar Test

With n=600 total holdout, expected deep questions ≈ 38 (6.3% deep rate):
- Scaled discordant pairs: b=10, c=8
- **McNemar power (one-sided, α=0.05): 0.120** — SEVERELY UNDERPOWERED
- **McNemar power (one-sided, α=0.10): 0.120** — still underpowered

### 7.3 Power for Macro-Level McNemar Test

Macro EM: Policy A = 0.4483, static = 0.4434, Δ = +0.0049
- Estimated discordant pairs: b=135, c=121
- **McNemar power (one-sided, α=0.05): 0.221** — UNDERPOWERED
- **MDE at power=0.80: ≈ 0.028 EM (2.8 percentage points)**

### 7.4 Interpretation

The exploratory macro effect (+0.49pt) is **below the minimum detectable effect** (2.8pt). The confirmatory test can only detect very large effects. This is expected: the policy's value is concentrated in the deep regime (6.3% of questions), and the macro effect is diluted by the 93.7% shallow questions where Policy A = static.

**Implication:** If the confirmatory test FAILS (p ≥ 0.05), it does NOT refute the exploratory finding — it merely fails to confirm it due to insufficient power. A larger holdout (n ≥ 2,000) would be needed for adequate power on the macro metric. The deep-regime McNemar test requires n ≥ 3,000 for 80% power.

### 7.5 Recommended Minimum Holdout for Adequate Power

| Test | Target power | Required n | Required deep n |
|------|-------------|------------|-----------------|
| Deep-regime McNemar (α=0.05) | 0.80 | ~3,000 | ~190 |
| Macro McNemar (α=0.05) | 0.80 | ~2,000 | ~126 |
| Current holdout | — | 600 | 38 |

The current n=600 holdout is a **feasibility check**, not a definitive confirmatory test.

---

## 8. Prohibited Actions

During the confirmatory phase:

1. **No tau re-estimation** — tau=2 is frozen
2. **No policy switch** — Policy A is frozen (not B or C)
3. **No post-hoc filtering** — all 600 questions are analyzed, none excluded post-hoc
4. **No model switching** — same qwen3.5-9b as exploratory
5. **No prompt modification** — same prompts as exploratory execution
6. **No look-ahead** — do not examine holdout results until all 600 questions are complete
7. **No selective reporting** — report all datasets, all metrics, both significant and non-significant

---

## 9. Registration Signatures

| Role | Name | Date |
|------|------|------|
| Hypothesis author | SlotRAG research pipeline | 2026-08-31 |
| Protocol reviewer | (pending) | |
| Execution lead | (pending) | |

---

## 10. Timeline

| Phase | Duration | Status |
|-------|----------|--------|
| Holdout construction (stratified sample) | 1 hour | PENDING |
| Execution (600 × 2 arms = 1200 runs) | ~21 hours (parallel=8) | PENDING |
| Analysis (McNemar + bootstrap + LOSA) | 2 hours | PENDING |
| Report writing | 1 hour | PENDING |
| **Total** | **~25 hours** | |

---

## Appendix: Relationship to Exploratory Findings

| Exploratory Finding | Confirmatory Test |
|---------------------|-------------------|
| Permutation p=0.000 for depth interaction | McNemar test on independent holdout |
| Candidate A macro EM=0.4483 vs static=0.4434 | Macro EM on 600-item holdout |
| LOSA preserves effect | LOSA on holdout data |
| 2Wiki no depth interaction | Per-dataset McNemar for 2wiki subset |
| R²=0.015 in regression | Not re-tested (regression requires cluster-level power) |
