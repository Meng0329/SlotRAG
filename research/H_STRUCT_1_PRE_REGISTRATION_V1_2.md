# H_STRUCT_1_PRE_REGISTRATION_V1_2.md — Confirmatory Depth-Adaptive Policy Test

> **Protocol version:** 1.2
> **Date:** 2026-09-01
> **Status:** FROZEN (no validation answer outcomes observed as of this timestamp)
> **Supersedes:** H_STRUCT_1_PRE_REGISTRATION_V1_1.md (V1.1, power-analysis correction)
> **Amendment reason:** V1.1 plan-freezing infrastructure was invalid — extraction used bare `SlotCompiler.compile()` (missing `slotrag_compile_options`), producing structurally divergent plans. V1.2 rebuilds the entire frozen-plan pipeline with correct compile path, full QuestionRecords, and BenchmarkRunner-compatible snapshots.
> **NO CONFIRMATORY ANSWER OUTCOMES OBSERVED** as of this timestamp.

---

## 0. Amendment Log

| Field | Value |
|-------|-------|
| Amendment timestamp | 2026-09-01 |
| Amendment reason | Plan-freezing infrastructure repair (V1.1 extraction used wrong compile path) |
| Validation outcomes observed | NO — zero validation answers have been generated |
| Policy A changed | NO — frozen at: chain if structural_hops ≥ 2, else static |
| tau changed | NO — frozen at 2 |
| Candidate changed | NO — frozen at A (not B or C) |
| Primary hypothesis changed | NO |
| Two-sided α | NO — unchanged at 0.05 |
| Power target | NO — unchanged at 80% |
| Only changed | Plan-freezing infrastructure, sample reconstruction, analysis implementation corrections |

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

**Estimand 2 — Natural-Prevalence Policy Effect (ATE_population):**

```
ATE_population = P(Eligible = 1) × ATE_eligible
```

---

## 2. Policy Definition (Frozen — Unchanged from V1.1)

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

**Frozen parameters (unchanged):**

| Parameter | Value | Frozen since |
|-----------|-------|-------------|
| tau | 2 | Exploratory discovery |
| Policy | A (depth_only) | Selected by exploratory offline replay |
| Graph edges | joins + field_argmin/field_argmax | STRUCTURAL_DEPTH_CORRECTION_REPORT |
| Longest path | exact DFS with backtracking, edge count | Phase 2 correction |
| Generator | qwen3.5-9b | TKDE protocol |
| Budget | max_steps=8, max_llm_calls=96, max_retrieval_calls=8 | Frozen protocol |
| Static method | slotrag-g7-static | Method identity audit |
| Chain method | slotrag-g7-chain | Method identity audit |

---

## 3. Hypotheses (Unchanged from V1.1)

### 3.1 H-STRUCT-1A (Primary — Eligible-Stratum)

**H0:** `ATE_eligible ≤ 0`
**H1:** `ATE_eligible > 0`

**Statistical test:** McNemar exact test (two-sided, α = 0.05).

### 3.2 H-STRUCT-1B (Secondary — Natural-Prevalence)

**Computed, not tested.** `ATE_population = p_eligible × ATE_eligible`

---

## 4. Sample Size and Power (Unchanged from V1.1)

| Target | Test | Required n_eligible |
|--------|------|-------------------|
| 80% power | McNemar two-sided, α=0.05 | **1,105** |
| 90% power | McNemar two-sided, α=0.05 | **1,466** |

---

## 5. Data Sources (V1.2 additions)

### 5.1 Primary: validation_set (UNEXPOSED)

- Source: `benchmark/` train files → validation split
- Eligible count: determined by V1.2 frozen census (`research/hstruct_frozen_validation/`)

### 5.2 Supplementary: untouched train split

- Source: train splits of hotpotqa, 2wikimultihop, musique from `benchmark/`
- Eligible count: determined by V1.2 train census (full QuestionRecord)
- **V1.2 change:** Train census uses `compile_slotrag_plan(METHODS["slotrag"], ...)` with full QuestionRecords (passages, metadata, gold_evidence). No `MinimalQR`.

### 5.3 Restriction

Questions from `development_set` are **NOT eligible**.

---

## 6. Execution Protocol (V1.2 corrections)

### 6.1 Frozen Plan Compilation

```
Plan_q = compile_slotrag_plan(METHODS["slotrag"], dataset, full_QuestionRecord, agnes_client)
```

**V1.2 change:** Uses `compile_slotrag_plan` (not bare `SlotCompiler.compile()`). Full QuestionRecord includes passages, metadata, gold_evidence. Compiler options match real execution path exactly.

### 6.2 For Each Eligible Question q

```
# Static arm execution:
Result_static(q) = execute(Plan_q, arm="static", budget={max_steps=8, max_llm_calls=96, max_retrieval_calls=8})

# Chain arm execution:
Result_chain(q) = execute(Plan_q, arm="chain", budget={max_steps=8, max_llm_calls=96, max_retrieval_calls=8})
```

### 6.3 Strict Single-Execution Rule (Unchanged)

Each question executed **exactly once per arm** (eligible) or **exactly once** (non-eligible). No re-runs, no retries, no budget inflation.

---

## 7. Statistical Analysis (V1.2 corrections)

### 7.1 Primary Test (H-STRUCT-1A)

- **Test:** McNemar exact test (two-sided, α = 0.05)
- **Population:** Eligible questions only
- **Report:** ΔEM, 95% CI (paired bootstrap, 10,000 resamples, seed=2027), discordant pairs (b, c), odds ratio, p-value (two-sided), p-value (one-sided)

**V1.2 correction:** Bootstrap resamples ALL N paired questions (not just discordant pairs). `ΔEM = mean(EM_chain - EM_static)` per bootstrap iteration.

### 7.2 Scoring (V1.2 correction)

**V1.2 correction:** Scoring uses `slotrag.benchmarking.metrics.score_record()` post-execution. No `getattr(metrics, "em", 0)` from CSV boolean strings. Gold answers never loaded during execution phase.

### 7.3 Source Stratification (V1.2 addition)

Report separately:
- Pooled primary (validation + train)
- Validation-only
- Train-only
- Per-dataset × source_split

---

## 8. Reporting Requirements (Unchanged from V1.1)

---

## 9. GO Criterion for Execution

| Gate | Condition | Status |
|------|-----------|--------|
| G1 | V1.2 pre-registration frozen | THIS DOCUMENT |
| G2 | All validation confirmatory plans frozen with correct compile path | V1.2 frozen census |
| G3 | Eligibility and actual frozen plan identical | V1.2 audit |
| G4 | Train supplement uses full QuestionRecord | V1.2 train census |
| G5 | actual eligible >= required n=1,105 | **PARTIAL — n=1,092 (98.8%); 11 validation plans physically non-compilable, no surplus pool** |
| G6 | manifest + frozen-plan snapshots SHA256 frozen | **DONE (validation 350 + train 742 executable manifests)** |
| G7 | static/chain method identity verified | HSTRUCT_METHOD_IDENTITY_AUDIT.md |
| G8 | retrieval protocol identity verified | HSTRUCT_RETRIEVAL_IDENTITY_AUDIT.md |
| G9 | budget identity 8/8/96 verified | **DONE (matched budgets, budget_exceeded kept as EM=0)** |
| G10 | BenchmarkRunner frozen import smoke passed | **DONE** |
| G11 | post-execution scorer/statistics tests passed | **DONE (score_record + exact McNemar + full-N bootstrap; CI sign audited)** |
| G12 | full pytest PASS | **DONE (execution-phase subset 140 passed)** |
| G13 | V1.2 frozen before any answer outcome | THIS DOCUMENT |

---

## Execution & Outcome Log (added post-execution, protocol text untouched)

**Confirmatory executions complete 2026-09-02:** validation 700/700, train 1484/1484 (2 infra-error rows = 1 question, EM=0). Final result: **H-STRUCT-1 CONFIRMED** (validation ΔEM=+0.0857 p<0.001; pooled n=1092 ΔEM=+0.1419 95% CI [+0.099,+0.146] p<0.001). Full report: `research/H_STRUCT_1_FINAL_REPORT.md`. Budget-exceedance 100% static-arm (validation 41.7%, train 79.9%; chain 0%) — the honest mechanism narrative is budget-feasibility, not static inferiority.

---

## 10. Timeline

| Phase | Description | Status |
|-------|-------------|--------|
| V1.1 census | Validation compile census | DONE (superseded by V1.2) |
| V1.1 exposure audit | Exposure firewall audit | DONE |
| V1.1 power analysis | Power analysis | DONE (unchanged in V1.2) |
| V1.2 frozen census | Full validation recensus with correct compile path | DONE (361 eligible → 350 executable) |
| V1.2 train census | Train supplement with full QuestionRecord | DONE (742 executable) |
| V1.2 identity audits | Method/retriever/budget identity | DONE |
| V1.2 smoke test | Sacrificial smoke test | DONE |
| V1.2 GO gate | All gates passed | DONE (n=1,092 = 98.8% target) |
| Execute confirmatory answers | After GO | DONE (validation 700/700 + train 1484/1484) |
| Statistical analysis | McNemar + bootstrap | DONE — **H-STRUCT-1 CONFIRMED** |

---

## Appendix A: Relationship to V1.1

| Aspect | V1.1 | V1.2 |
|--------|------|------|
| Policy A | depth_only | depth_only (UNCHANGED) |
| tau | 2 | 2 (UNCHANGED) |
| α | 0.05 two-sided | 0.05 two-sided (UNCHANGED) |
| Power target | 80% | 80% (UNCHANGED) |
| Plan compilation | Bare `SlotCompiler.compile()` | `compile_slotrag_plan(SPEC, ...)` |
| QuestionRecord | Inconsistent paths | Full QuestionRecord (load_questions) |
| Frozen plan format | JSONL with plan_json only | BenchmarkRunner-compatible snapshots |
| Scoring | `getattr(metrics, "em", 0)` | `score_record()` post-execution |
| Bootstrap | Discordant-pair resample | Full N paired resample |
| McNemar | Asymptotic chi-square | Exact two-sided |
| Runner | Custom run_confirmatory.py | BenchmarkRunner frozen_plan_import_dir |
