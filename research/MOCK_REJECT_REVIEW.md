# MOCK_REJECT_REVIEW.md — Simulated TKDE Rejection Review

> **Date**: 2026-09-08
> **Confidence**: This simulates the worst-case plausible rejection. If all 10 concerns below are adequately addressed in revision, the paper is RECOMMEND ACCEPT.

---

## Review Summary

**Score**: 2 (Reject)

This paper studies budget-feasible physical planning for multi-hop RAG. The core observation — that per-slot retrieval allocations must compose under a global budget — is valid. However, the paper has 8 major concerns and 4 minor concerns that collectively undermine the contribution.

---

## Major Concerns

### M1. Prevalence arithmetic is internally inconsistent (CRITICAL)

The paper states "approximately 5.4% (361 / 6,494)" in threats.tex and analysis.tex, but 361/6494 = 5.56%, not 5.4%. Results.tex states "approximately 5.39% (361 eligible / 6,494 total)" — but 5.39% = 350/6494, not 361/6494. The ATE formula uses 0.054 (=350/6494 ≈ 5.39%) but labels it "(361 eligible / 6,494)". There are three different numbers (5.4%, 5.39%, 5.56%) used for the same quantity with no consistent numerator. This is a factual inconsistency that undermines the paper's claim to numerical rigor. Authors must fix this and ensure all prevalence figures are internally consistent.

### M2. Gate claim rests on exploratory evidence only (HIGH)

The structure-gated dispatch (Policy A') is presented as a contribution (C3), but its benefit on shallow plans is supported only by exploratory trace analysis under a permissive budget. The confirmatory matched-budget test (H-STRUCT-4) was pre-registered but infeasible. Zero shallow plans were executed under B = 8. The paper cannot claim C3 as a confirmed contribution; it can only claim it as an open hypothesis. The paper does acknowledge this but still lists C3 as a contribution.

### M3. No cross-system empirical comparison (HIGH)

The paper compares only internal ablation variants (static/flat/chain/gate). The closely related systems (IRCoT, ReAct, PAGE-RAG, PruneRAG, KBYF) are discussed qualitatively (Table 1) but never run. For a TKDE system paper, the absence of head-to-head comparison with at least one external baseline is a significant weakness. The claim that these are "different decision points" is valid but insufficient — budget-capped IRCoT is a natural competitor.

### M4. Budget-exceeded → 0.0 scoring convention is never justified (MODERATE-HIGH)

Budget-exhausted items score 0.0. This convention inflates the flat planner's advantage because it benefits from both (a) better evidence distribution and (b) guaranteed non-zero scoring. The paper never justifies why 0.0 is appropriate versus, say, penalizing by the fraction of materialized slots. The choice materially affects the results (146 × 0.0 = 0 for static vs 146 × >0 for flat).

### M5. No end-to-end cost or latency reporting (MODERATE-HIGH)

The paper positions itself as a "system" (title: "SlotRAG") but never reports wall-clock time, token cost, or any system metric beyond EM/F1 and budget-exhaustion counts. The slot compilation step requires an additional LLM call per question. The materialization step performs multiple retrieval calls. These overheads are real. The paper should at minimum report total LLM calls and retrieval calls per method, even if absolute latency is model-dependent.

### M6. Single model, no generality evidence (MODERATE)

All experiments use qwen3.5-9b (thinking off). This is a non-frontier 9B-parameter model. The paper's own threats section acknowledges the results are model-dependent. A mechanism validated on a single small model is not sufficient for a TKDE system contribution. At least one additional model (e.g., a larger or different-family model) should be tested to establish whether the budget-feasibility effect is model-dependent.

### M7. The 7.7-point EM improvement is on absolute EM of 0.17 (MODERATE)

The deep-plan static EM is 0.1714 — meaning the baseline answers 83% of deep questions incorrectly. The flat planner improves to 0.2486 — still answering 75% incorrectly. While the relative improvement is significant, the absolute performance suggests the underlying system is not competitive with published multi-hop baselines. The paper does not compare its EM with published numbers on these datasets.

### M8. Confusion matrix interpretation requires the paper to explain FP = 128 (MODERATE)

128 plans are predicted infeasible (Σa_i > B) but do NOT exhaust the budget. The paper explains this is because other termination criteria (step limit, LLM-call limit) are reached first. But this means 36.6% of "infeasible" plans are safe under static allocation — the feasibility diagnosis is not very useful as a trigger. Why not just always run flat when deep? (The answer is the shallow harm, but the confusion matrix alone does not justify the gate.)

---

## Minor Concerns

### m1. No effect sizes reported alongside p-values (§7.3)

McNemar p = 1.4 × 10^{-6} is reported without Cohen's d or odds ratio for the discordant pairs.

### m2. Chain ablation p = 0.743 is presented as a "falsification" but is simply a null result

A null result at 74% power (if powered) means "no evidence of difference," not "evidence of no difference." The paper conflates these in the conclusion ("falsified").

### m3. The "honest contribution" framing in the abstract is atypical

"We report the system's honest contribution" uses meta-language that is unusual in technical abstracts. A reviewer may read this as the paper apologizing for insufficient results.

### m4. The motivating example (§1.4) uses an ad-hoc allocation (4+4+4=12 > 8)

The paper does not explain how static allocation is actually computed in the system. The example assumes 4 per slot, but the system's static allocator is "even allocation across slots" — which for a 3-slot plan with B=8 gives 2-3-3 (not 4-4-4). The example is pedagogically clear but numerically inconsistent with the actual system.

---

## Recommendation

**Score**: 2 (Reject)

The core observation is valid and the paper is unusually honest about limitations. However, the prevalence arithmetic error (M1), the lack of cross-system comparison (M3), and the exclusively-exploratory evidence for the gate (M2) are each individually sufficient for rejection. Fixing M1 is mandatory. M2 and M3 may be addressable within the paper's scope (M2 by downgrading C3 from confirmed to open; M3 by strengthening the positioning argument).

---

## Revision Verdict

If the authors:
1. Fix the prevalence arithmetic consistently (M1)
2. Explicitly downgrade C3's evidence level from confirmatory to exploratory (M2)
3. Add one paragraph on cross-system non-comparability justification (M3)
4. Justify the 0.0 scoring convention (M4)
5. Add token/call counts as system metrics (M5)

the paper would be suitable for MAJOR REVISION with reasonable chance of acceptance.
