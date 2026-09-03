# H_STRUCT_2_PRE_REGISTRATION.md — Chain-Importance vs Budget-Aware-Flat Control

> **Protocol version:** 1.0
> **Date:** 2026-09-03
> **Status:** FROZEN (no H-STRUCT-2 answer outcomes observed as of this timestamp)
> **Supersedes:** nothing (extends H-STRUCT-1; H-STRUCT-1 outcomes ARE available and are reused as frozen evidence, per protocol §6)
> **Amendment reason:** n/a (initial freeze)
> **NO H-STRUCT-2 FLAT ANSWER OUTCOMES OBSERVED** as of this timestamp.

---

## 0. Relation to H-STRUCT-1

H-STRUCT-1 (V1.2, frozen 2026-09-01) established that the **chain** arm
(`slotrag-g7-chain`, explicit optimizer, chain-rule importance
$\tau=2\cdot\text{depth}-1$) significantly beats the **static** arm
(`slotrag-g7-static`, deterministic physical compiler) on structurally
eligible ($\mathrm{structural\_hops}\ge2$) executable plans under a hard
8-call retrieval budget: pooled $\Delta\text{EM}={+}0.142$, CI
$[+0.099,+0.146]$, McNemar $p<0.001$ (n=1,092).

That contrast cannot distinguish *which* property of the chain arm drives the
gain, because **static and chain differ in two things at once**:

| property | static | chain |
|----------|--------|-------|
| optimizer search (`search_physical_plans`) | absent (`compile_physical_plan`) | present |
| requirement importance | none | chain-rule ($2(i+1)-1$) |

H-STRUCT-2 adds the missing control: **`slotrag-g7-flat`**, which uses the
*same* optimizer search space and hard budget as chain, but with **all
requirement importances equal to 1.0** (cost-only, budget-aware allocation).
This isolates the *only* remaining difference between flat and chain:

```
chain − flat  =  exactly the dependency-sensitive importance vector
```

Static is retained as a boundary reference, but the primary H-STRUCT-2
contrast is **chain vs flat**, not chain vs static.

---

## 1. Research Question

> Does dependency-sensitive chain importance improve effectiveness or
> efficiency beyond a budget-aware flat optimizer on structurally eligible
> executable plans?

---

## 2. Primary Population

**The 350 validation executable-eligible questions from H-STRUCT-1** —
untouched, unexposed, reused as-is:

- Source: `research/hstruct_validation_census/validation_executable_manifest.jsonl`
  (350 = 361 structurally eligible − 11 physically non-compilable).
- Both arms execute against the **same frozen SlotPlan** from this manifest
  (plan hash matches pairwise; no recompilation).
- Primary analysis is **validation-only** (n=350). No train supplement is run
  for H-STRUCT-2 unless Case A (§11) is reached.

### 2.1 Estimand

```
ATE_chain_vs_flat =
E[ Y_chain − Y_flat | Eligible=1, Executable=1 ]
```

H-STRUCT-1's estimand is simultaneously re-labeled to its correct form:

```
ATE_exec_eligible =
E[ Y_chain − Y_static | Eligible=1, Executable=1 ]
```

and is *not* called an unconditional eligible-plan ATE (11 eligible plans are
physically non-executable and are excluded from both). Population effect:

```
ATE_population = P(Eligible ∧ Executable) × ATE_exec_eligible
```

with validation census prevalence (frozen numbers):

| dataset | raw_n | eligible_n | executable_eligible_n | P_eligible | P_eligible_executable |
|---------|-------|-----------|----------------------|-----------|----------------------|
| 2wikimultihop | 3698 | 258 | 256 | 0.06977 | 0.06923 |
| hotpotqa | 2146 | 68 | 64 | 0.03169 | 0.02982 |
| musique | 650 | 35 | 30 | 0.05385 | 0.04615 |
| **pooled** | **6494** | **361** | **350** | 0.05559 | **0.05390** |

---

## 3. Arms (Frozen)

| arm | method key | physical plan | optimizer | importance | execution |
|-----|-----------|--------------|-----------|-----------|-----------|
| static | `slotrag-g7-static` | `compile_physical_plan` | absent | n/a (uniform) | **REUSED** from H-STRUCT-1 |
| flat | `slotrag-g7-flat` | `search_physical_plans` | explicit, budget-aware | all = 1.0 | **NEW** (this protocol) |
| chain | `slotrag-g7-chain` | `search_physical_plans` | explicit, budget-aware | $2(i+1)-1$ | **REUSED** from H-STRUCT-1 |

Only **flat** is executed under H-STRUCT-2. Static and chain outcomes are
reused verbatim from `research/hstruct_validation_census/validation_confirmatory_results.csv`.

### 3.1 Identity requirement (STOP condition)

Flat and chain must differ **only** in `requirement_importance`. All of the
following are fixed and identical across flat and chain:

- frozen SlotPlan (same `plan_json`, same plan hash)
- question, corpus, retriever, reranker, generator (qwen3.5-9b)
- budgets: `max_steps=8`, `max_retrieval_calls=8`, `max_llm_calls=96`
- prompt, execution code, optimizer search space (orders × strategy variants)

If the identity audit (`H_STRUCT_2_METHOD_IDENTITY_AUDIT.md`) shows any other
difference, execution **STOPS**.

---

## 4. Hypotheses (Frozen)

### 4.1 H-STRUCT-2A (Primary)

```
H0: EM_chain ≤ EM_flat
H1: EM_chain > EM_flat
```

Statistic: **two-sided** exact McNemar (binomial on discordant pairs),
$\alpha = 0.05$. Two-sided is used for the *test*, per frozen H-STRUCT-1
convention; the direction of any effect is reported separately.

### 4.2 H-STRUCT-2B (Secondary — efficiency)

Compare `LLM calls`, `retrieval calls`, `budget_exceeded`, and (if present)
token/latency fields across static / flat / chain.

---

## 5. Statistical Plan (Frozen)

Per set (validation primary; pooled = validation only for H-STRUCT-2):

- Exact McNemar via `scipy.stats.binomtest(b, n=b+c, p=0.5,
  alternative="two-sided")` → `p_exact_binomial` is the **primary** p-value.
- `p_midp` (H-STRUCT-1 V1.2 sensitivity) and `p_chi_square` (continuity
  corrected) reported as secondary.
- Full-N paired bootstrap CI on the per-question EM differences
  ($d_i = \mathrm{EM}_{chain,i}-\mathrm{EM}_{flat,i}$), 10,000 resamples,
  seed=2027, implemented as `paired_bootstrap_vector` over **all N** paired
  differences (question-level resampling, not dataset-stratified first-slice).
- Report $\Delta\text{EM}$, CI, b, c, OR, $\Delta\text{LLM\_calls}$.

### 5.1 H-STRUCT-1 statistics correction (bundled, offline)

The same corrected machinery is applied to the H-STRUCT-1 evidence and
reported in `H_STRUCT_1_FINAL_REPORT_V2.md`:
- `paired_bootstrap_vector` (fixes the per-dataset `boot_comps[0]` slice bug).
- `binomtest` as primary McNemar (mid-p demoted to sensitivity).
- Label: **STATISTICAL CORRECTION ONLY** — no model re-execution, no
  hypothesis change, no effect-size change.

---

## 6. Execution Protocol (Frozen)

1. Verify flat plan identity: for every manifest item,
   `plan_sha256(flat) == plan_sha256(static existing) == plan_sha256(chain existing)`
   (all derived from the same frozen `plan_json`).
2. Execute `slotrag-g7-flat` **exactly once** per 350 validation question.
3. No re-run of static or chain. Strict single-execution per arm/question.
4. `budget_exceeded` is a legitimate matched-budget outcome (empty answer →
   EM=0), never retried. Only infra `error` rows are retried via the frozen
   resume path.
5. No-peeking: execution logs only progress; scoring happens post-hoc with
   `score_record()`.

---

## 7. Interpretation Gate (Frozen BEFORE outcomes)

| Case | Observed | Conclusion |
|------|----------|-----------|
| **A** | chain significantly > flat (p<0.05, CI excl. 0, ΔEM>0) | **CHAIN-SPECIFIC VALUE CONFIRMED** → extend flat to 742-train supplement, then budget sensitivity |
| **B** | chain ≈ flat (no significant difference) | **BUDGET-AWARE OPTIMIZATION CONFIRMED; CHAIN-SPECIFIC VALUE NOT ESTABLISHED** → do NOT run train flat; paper method renamed to *Structure-Gated Budget-Feasible Physical Planning*; chain importance demoted to one implementation / ablation |
| **C** | chain < flat (significant, negative ΔEM) | **CHAIN IMPORTANCE REJECTED** → paper must not recommend chain-rule; switch to depth gate → flat budget-aware optimizer; re-run offline Policy A' (`if hops≥2: flat else: static`) |

This gate is declared here, before any flat outcome exists.

---

## 8. Infrastructure Deviation Handling (Frozen)

H-STRUCT-1's train run had one symmetric infrastructure failure
(`facfc8f3…`, both arms, persistent ReadTimeout@60s on the frozen resume
path). Accurate record (replaces any earlier "zero retries" wording):

> A symmetric infrastructure failure was retried through the frozen resume
> path and failed in both arms.

Sensitivity: report both **ITT-style** (facfc8 = 0/0) and **complete-pair
exclusion** of that single question; verify the H-STRUCT-1 primary conclusion
does not change.

---

## 9. Gates (frozen before execution)

| Gate | Condition | Status |
|------|-----------|--------|
| G1 | This pre-registration frozen | THIS DOCUMENT |
| G2 | `slotrag-g7-flat` identity audit passes (importance-only diff) | pending (P6) |
| G3 | plan hashes flat == static == chain (pairwise, 350/350) | pending (P7 pre-check) |
| G4 | flat executes exactly once per 350, reusing H-STRUCT-1 frozen plans | pending (P7) |
| G5 | no static/chain re-execution | by construction |
| G6 | corrected statistics validated (paired_bootstrap_vector + binomtest) | pending (P1) |
| G7 | interpretation gate declared pre-outcome | THIS DOCUMENT §7 |
| G8 | no-peeking maintained | by construction |

---

## 10. Reporting

- `research/H_STRUCT_2_FINAL_REPORT.md`
- `research/H_STRUCT_2_METHOD_IDENTITY_AUDIT.md`
- `research/H_STRUCT_1_FINAL_REPORT_V2.md` (corrections only)
- `research/STATIC_BUDGET_FEASIBILITY_ANALYSIS.md`
- `hstruct2_flat_results.csv`, `hstruct2_three_arm_comparison.csv`,
  `hstruct1_corrected_statistics.csv`, `budget_feasibility_frontier.csv`

---

## Appendix A: Static feasibility mechanism (declared method, not hypothesis)

Programmatic explanation of static budget exhaustion (no LLM inference):
for each frozen plan, `Feasible_static(q) = Σ_s allocation_static(s) ≤ B`
where `allocation_static` is the per-slot retrieval-call request of the
deterministic physical compiler. Build a confusion matrix of
`actual static budget_exceeded` vs `predicted static infeasible`; if near-
perfect, the paper may formally claim a **local-allocation / global-budget
mismatch** mechanism rather than a hand-waving one. CPU-only budget
counterfactual frontier `B ∈ {4,6,8,12,16}` (static/flat/chain plan-feasible
rate, allocated calls, slot coverage) is also computed to check whether B=8 is
an anomalous budget choice.
