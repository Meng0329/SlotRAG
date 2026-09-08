# MOCK_MAJOR_REVISION.md — Simulated TKDE Major Revision Review

> **Date**: 2026-09-08
> **Confidence**: This simulates the best-case plausible review. If the paper addresses these 6 major and 4 minor items, it is RECOMMEND ACCEPT.

---

## Review Summary

**Score**: 3 (Major Revision)

This paper addresses an important practical problem in multi-hop RAG: budget feasibility of evidence plans under retrieval-call budgets. The observation that logical validity does not guarantee physical executability is well-motivated and the experimental design is rigorous (frozen plans, paired comparisons, confirmatory + exploratory separation). However, several issues need to be addressed before publication.

---

## Major Concerns

### M1. Prevalence figures are internally inconsistent (REQUIRED REVISION)

Threats.tex and analysis.tex state "approximately 5.4% (361 / 6,494)" but 361/6494 = 5.56%. Results.tex states "5.39% (361 eligible / 6,494 total)" but 5.39% = 350/6494. The ATE formula uses 0.054 (≈ 350/6494) but labels it "(361 eligible / 6,494)". These must be made consistent. Suggested fix: report both figures clearly — deep-eligible (361/6,494 = 5.56%) and deep-executable (350/6,494 = 5.39%) — and use the correct one in the ATE formula.

### M2. Gate evidence level must be more prominently stated (REQUIRED REVISION)

The paper acknowledges the gate benefit on shallow plans is exploratory, but the abstract and C3 contribution description do not make this sufficiently clear. The abstract states "a lightweight deterministic structural-depth gate" without qualifying that the gate's benefit is exploratory. Suggested fix: add "(exploratory evidence)" or "(retrospective evidence)" to the gate claim in the abstract and C3 description.

### M3. Scoring convention needs one sentence of justification (REQUIRED REVISION)

The 0.0 convention for budget-exhausted items is used without justification. Even one sentence — e.g., "Budget-exhausted items score 0.0 because multi-hop questions require all evidence slots to be materialized; partial evidence from truncated plans yields EM ≈ 0.0" — would preempt this concern.

### M4. End-to-end system metrics are missing (STRONGLY RECOMMENDED)

The paper reports only EM/F1 and budget-exhaustion counts. For a systems paper (TKDE), at minimum total LLM calls and total retrieval calls per method should be reported. These are already tracked internally and require no new experiments. A small table showing {method, total_llm_calls, total_retrieval_calls, EM} would significantly strengthen the systems contribution.

### M5. Cross-system comparison gap needs explicit defense (REQUIRED REVISION)

The paper does not compare with IRCoT, ReAct, or other multi-hop baselines under matched conditions. The "different decision points" argument is valid but should be stated more explicitly in the paper (not just implied). A paragraph in §2 or §10 explicitly explaining why cross-system comparison is not feasible within this study's scope would help.

### M6. The "falsification" of chain importance overstates the conclusion (REVISION RECOMMENDED)

The paper states the chain importance law is "falsified" (§1.5, conclusion). However, the evidence is a non-significant result (p = 0.743) on n = 350, which means "no evidence of improvement" rather than "evidence of no improvement." The paper should soften "falsified" to "not supported by the evidence" or "ablation shows no significant improvement."

---

## Minor Concerns

### m1. Effect sizes alongside p-values

§7.3 (RQ3) reports McNemar p = 1.4 × 10^{-6} without an effect size (Cohen's d, odds ratio). Include at least one effect size metric.

### m2. Motivating example numerical inconsistency

The motivating example (§1.4) assumes static allocation of 4+4+4=12 > B=8. But the system's actual static allocator does even allocation: floor(8/3) = 2, remainder distributed → 3-3-2. A 3-slot plan with 3-3-2 allocation does not exceed B=8. The example is pedagogically useful but should note that real static allocations on 3-slot plans may or may not exceed B=8, and the diagnosis identifies which ones do.

### m3. "Honest contribution" framing in abstract

"We report the system's honest contribution" is atypical for a technical abstract. Consider rephrasing to "We report a mechanism for regime-sensitive physical planning..." to maintain the same humility without meta-language.

### m4. Table 1 omits several cited systems

The comparison table (Table 1) includes 6 systems (Adaptive-RAG, PlanRAG, PyRAG, PAGE-RAG, KBYF, SlotRAG) but cites 18 systems in §2. The table should either include more systems (PROGRAM, DynaKRAG, S2G-RAG, PruneRAG) or explain the selection criterion.

---

## Recommendation

**Score**: 3 (Major Revision)

The paper makes a valid and well-scoped contribution. The frozen protocol and honest evidence labeling are strengths. The main issues are factual consistency (prevalence figures), evidence-level clarity (gate), and system metrics (end-to-end costs). None of these require new experiments — they are editorial and presentational improvements.

**Acceptance probability after revision**: 65-75% (the factual consistency fix and evidence-level tightening are straightforward; the cross-system gap remains but is honestly scoped)
