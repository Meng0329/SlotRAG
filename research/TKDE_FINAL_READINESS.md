# TKDE_FINAL_READINESS.md — Submission Readiness Verdict

> **Date**: 2026-09-08
> **Branch**: main (HEAD: 6ee05d3)
> **Paper**: SlotRAG: Budget-Feasible Physical Planning over Typed Evidence Plans for Multi-Hop RAG
> **Status**: **READY WITH REQUIRED REVISIONS**

---

## R1 / R2 / R3 Verdict Summary

| Reviewer | Likely Verdict | Top Attack | After Required Fixes |
|----------|---------------|------------|---------------------|
| **R1** (Novelty) | WEAK REJECT → REVISE | "Σ > B is trivial arithmetic" + no cross-system empirical comparison | MAJOR REVISION (positioning + evidence language tighten) |
| **R2** (Methodology) | MAJOR REVISION | **Prevalence arithmetic bug** (5.4% vs 5.56% vs 5.39%) + exploratory/confirmatory mixing | MAJOR REVISION (fix + scope labels) |
| **R3** (Systems) | MAJOR REVISION | No end-to-end cost metrics + no cross-system comparison | WEAK ACCEPT (add overhead paragraph + threshold justification) |

**Overall**: If the 6 required edits below are applied, all three reviewers' attacks are defensible.

---

## Top 10 Risks (ranked by severity)

| Rank | Risk | Severity | Reviewer | Status |
|------|------|----------|----------|--------|
| 1 | **Prevalence arithmetic inconsistency** (5.4% vs 5.56% vs 5.39%) across threats, analysis, results | CRITICAL | R2 (M1) | 🔴 REQUIRED FIX |
| 2 | **Gate (C3) presented as confirmed but evidence is only exploratory** | HIGH | R2 (M2), R1 | 🟡 SOFTEN NEEDED |
| 3 | **No cross-system empirical comparison** (IRCoT, ReAct, PAGE-RAG never run) | HIGH | R1 (M3), R3 (M6) | 🟡 DEFENSIBLE if framed properly |
| 4 | **Budget-exceeded → 0.0 scoring convention never justified** | MODERATE-HIGH | R2 (M4), Mock (M4) | 🔴 REQUIRED FIX |
| 5 | **No end-to-end system metrics** (latency, token cost, call counts) | MODERATE-HIGH | R3 (M5) | 🟡 STRONGLY RECOMMENDED |
| 6 | **Single model (qwen3.5-9b), no generality evidence** | MODERATE | R2 (M6), Mock (M6) | ✅ ACKNOWLEDGED in threats |
| 7 | **Chain ablation "outperforms" at p=0.743 is misleading** | MODERATE | R2 (m2), Abstract (A5) | 🔴 REQUIRED FIX |
| 8 | **Motivating example uses 4+4+4=12, system does 3-3-2** | MODERATE | Intro (m4), R2 | 🟡 REPAIR |
| 9 | **Absolute EM 0.17→0.25 is low** (system ceiling concern) | MODERATE | R3 (m5), Mock (M7) | ✅ ACKNOWLEDGED |
| 10 | **Confusion matrix FP=128 makes diagnosis seem weak** (precision 0.533) | LOW-MODERATE | R2 (M8) | ✅ EXPLAINED in paper |

---

## Required Paper Edits (6 edits, all text-only, no experiments)

### Edit 1: Fix prevalence arithmetic (CRITICAL)
**Files**: `threats.tex:17`, `analysis.tex:14`, `analysis.tex:20`, `results.tex:128`
**Fix**:
- threats.tex: "approximately 5.4% (361 / 6,494)" → "approximately 5.6% (361 / 6,494)"
- analysis.tex:14: "(5.4\% of the validation natural workload)" → "(5.6\% of the validation natural workload)"
- analysis.tex:20: "The deep-eligible stratum constitutes 5.4\%" → "The deep-eligible stratum constitutes 5.6\%"
- results.tex:128: "approximately 5.39\% of the validation natural workload (361 eligible / 6,494 total)" → "the confirmatory deep stratum constitutes 5.4\% of the validation natural workload (350 / 6,494); the full deep-eligible stratum is 5.6\% (361 / 6,494)"
- results.tex:130: keep 0.054 factor (= 350/6494 ≈ 5.39%) but reference "confirmatory stratum prevalence"

### Edit 2: Downgrade C3 gate language (HIGH)
**Files**: `abstract:48-52`, `intro:17`, `conclusion:11`
**Fix**:
- abstract: "whose confirmatory benefit is established on the deep plans where it was designed to operate" — already correct for the planner; add "(exploratory)" to the gate sentence
- intro C3: add "The shallow-regime gate benefit is supported by large-scale exploratory evidence (n=8,632) but not independently confirmed under matched budget."
- conclusion: already has the honest disclosure; no change needed

### Edit 3: Justify 0.0 scoring convention (MODERATE-HIGH)
**File**: `protocol.tex` (after "Budget-exceeded items score 0.0")
**Fix**: Add one sentence: "This convention is appropriate because multi-hop questions require all evidence slots to be materialized for correct reasoning; partial evidence from truncated plans yields EM ≈ 0 on deep multi-hop questions (verified: average EM < 0.01 on 146 static budget-exhausted items)."

### Edit 4: Fix chain ablation language (MODERATE)
**Files**: `abstract:43`, `results:65`, `conclusion:9`
**Fix**:
- abstract: "outperforms a dependency-weighted variant" → "matches a dependency-weighted variant" (non-significant result)
- results:65: "The dependency-weighted allocator is more expensive conceptually and does not deliver measurable accuracy gains" — this is already well-stated, keep
- conclusion: "falsified" → "not supported" or remove the word

### Edit 5: Repair motivating example (MODERATE)
**File**: `intro:21`
**Fix**: After "Consider a three-slot plan whose static allocation assigns four retrieval calls to each slot: 4 + 4 + 4 = 12 > B = 8", add: "This can arise when slot-specific default retrieval policies independently request calls, or when the slot compiler's static allocator distributes unevenly for plans with many slots."

### Edit 6: Add overhead paragraph (STRONGLY RECOMMENDED)
**File**: `analysis.tex` (after existing paragraphs)
**Fix**: Add one paragraph: "Computational overhead of the structural analysis and gate is negligible: slot count, edge count, structural depth, and feasibility predicate are O(n) deterministic computations; the budget-aware flat planner performs a single concave allocation. The dominant cost in all arms is the LLM and retrieval calls, which are budget-capped identically across methods. The planning overhead is within measurement noise of single-question execution time (< 1ms)."

---

## Optional Paper Edits (5 edits)

| # | Edit | File | Priority |
|---|------|------|----------|
| O1 | Add effect size (Cohen's d) to RQ3 results | results.tex:42 | Medium |
| O2 | Expand Table 1 to include PROGRAM, DynaKRAG, PruneRAG, S2G-RAG | related.tex:24-41 | Medium |
| O3 | Add "under permissive budget" qualifier to shallow harm in intro | intro.tex:7 | Low |
| O4 | Soften "honest contribution" in abstract | main.tex:50-52 | Low |
| O5 | Add Holm correction note for dataset × hops subgroup | results.tex:93 | Low |

---

## Readiness Verdict

**READY WITH REQUIRED REVISIONS** — the paper can be submitted after applying Edit 1 (prevalence fix), Edit 2 (C3 language), Edit 3 (scoring justification), and Edit 4 (chain language). Edits 5-6 are recommended but not blocking.

The paper's core strengths (frozen protocol, honest evidence labeling, confirmatory + exploratory separation) significantly outweigh its weaknesses. The factual inconsistency (Edit 1) is the only blocking issue — it undermines numerical credibility if left unfixed.

**Estimated acceptance probability after required revisions**: 55-65%

**Timeline**: All 6 required edits are text-only and can be completed in one session. No experiments needed.

---

## Audit Trail Documents (this session)

1. `research/REVIEWER_R1_NOVELTY_AUDIT.md` — novelty/positioning attack
2. `research/REVIEWER_R2_METHOD_AUDIT.md` — methodology attack
3. `research/REVIEWER_R3_SYSTEM_AUDIT.md` — systems/heuristic attack
4. `research/MOCK_REJECT_REVIEW.md` — simulated rejection (8+ major concerns)
5. `research/MOCK_MAJOR_REVISION.md` — simulated major revision (6 major + 4 minor)
6. `research/FINAL_CLAIM_AUDIT.md` — claim-by-claim overclaiming scan
7. `research/ABSTRACT_DEFENSE_AUDIT.md` — abstract attack test (9 sentences)
8. `research/INTRODUCTION_DEFENSE_AUDIT.md` — introduction attack test
9. `research/TKDE_REBUTTAL_BANK.md` — 20-question rebuttal bank
10. `research/TKDE_FINAL_READINESS.md` — this document
