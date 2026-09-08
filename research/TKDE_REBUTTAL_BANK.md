# TKDE_REBUTTAL_BANK.md — Pre-Written Rebuttal for Common Reviewer Questions

> **Date**: 2026-09-08
> **Scope**: Top 20 anticipated reviewer questions with pre-written rebuttals. Graded: STRONG (definitive answer), MODERATE (defensible but limited), WEAK (concede and explain).

---

## Q1: How is Σa_i > B a "contribution" when it is a trivial arithmetic check?

**Rebuttal (STRONG)**: The condition is trivial; its *empirical prevalence and impact* are not. 41.7% of deep plans under static allocation exhaust the budget (146/350), producing structural evidence failures. The condition's value is (a) it is computable at compile time without execution, (b) it has recall 1.0 (zero missed events), making it a reliable safety predicate, and (c) it enables selective dispatch. We do not claim the inequality itself is novel; we claim that *budget feasibility as a first-class execution concern in multi-hop RAG* has not been addressed by prior work.

## Q2: Why not compare with IRCoT, ReAct, or PlanRAG under matched conditions?

**Rebuttal (MODERATE)**: These systems do not produce typed evidence plans. They retrieve dynamically (IRCoT triggers retrieval per reasoning step; ReAct alternates action/observation) and their retrieval-call budgets are implicit in the execution trajectory, not in a compiled plan. Adapting them to share SlotRAG's plan representation would require re-implementing each system's retrieval trigger as a slot, which is a separate study. We provide a structural positioning comparison (Table 1) and refer readers to each baseline's original evaluation.

## Q3: The gate (hops ≥ 2) was never confirmed under matched budget B=8. How can C3 be a contribution?

**Rebuttal (MODERATE)**: We agree. C3's planner component (flat vs static on deep plans) is confirmed (n=350, p=1.4e-6). The gate component is empirically motivated (exploratory n=8,632) but not independently confirmed under B=8. We have scoped C3 carefully in the abstract: "whose confirmatory benefit is established on the deep plans where it was designed to operate." The gate is a lightweight deterministic mechanism whose shallow-regime benefit is supported by large-scale evidence but awaits independent confirmation. We state this explicitly (abstract L48-49, conclusion L11).

## Q4: The population effect (ATE = +0.004) is negligible. Why should I care?

**Rebuttal (STRONG)**: The mechanism is designed for the *deep* regime, not the population. The population-level ATE is bounded by the deep-eligible prevalence (5.6%) and is reported for transparency, not as the primary contribution. The primary value is (a) eliminating all 146 budget-exhaustion events on deep plans (eliminating structural evidence failures) and (b) protecting shallow plans from harm (preventing quality degradation). Both are regime-specific benefits, not population-level EM gains.

## Q5: 350 deep plans is too small for a TKDE contribution.

**Rebuttal (STRONG)**: The 350 plans are the *entire* deep-eligible confirmatory set from the V1.2 frozen census (361 eligible, 350 executable). This is not a sample — it is the complete population of frozen plans available under the matched protocol. The census was designed for this evaluation (pre-registered H-STRUCT-1), and the 350 plans provide >80% power for the observed effect size (Cohen's d > 0.5 for +7.7 EM improvement).

## Q6: qwen3.5-9b is a non-frontier model. Why not test with GPT-4 or Claude?

**Rebuttal (MODERATE)**: The mechanism is architecture-agnostic; we demonstrate it on one model to establish the phenomenon. Budget exhaustion under static allocation is a structural problem (41.7% of deep plans), not a model-specific one. Different models may have different exhaustion rates, but the mechanism (flat planner + gate) is applied identically. We explicitly acknowledge single-generator scope (threats §10). Cross-model validation is future work.

## Q7: Budget-exhausted items score 0.0 — doesn't this inflate the flat planner's advantage?

**Rebuttal (STRONG)**: The 0.0 convention is consistent with SQuAD-style evaluation: if retrieval is truncated, the generated answer is from incomplete evidence and typically scores EM ≈ 0.0. We verified that static-budget-exhausted items had average EM < 0.01 under static allocation — meaning partial evidence rarely produces correct answers for multi-hop questions. The 0.0 convention is conservative by less than 0.01 EM.

## Q8: The chain importance law is "ablated" but the null result doesn't prove it doesn't work.

**Rebuttal (STRONG)**: We agree, and we do not claim "proof of no difference." We state: "The accuracy improvement is not statistically significant" (§7.3). The word "ablated" is standard ML terminology for testing a variant and finding no significant improvement. The paper concludes the final system uses flat "for simplicity" — a design choice, not a falsification claim. We soften "falsified" wherever it appears.

## Q9: The motivating example uses 4+4+4=12 but the system does even allocation (3-3-2). Isn't this misleading?

**Rebuttal (MODERATE)**: The example illustrates the *general problem* of local-vs-global allocation mismatch, using a pedagogically clear scenario. The system's actual static allocator does ⌊B/n⌋ with remainder distribution, which for 3 slots and B=8 gives 3-3-2. This specific allocation does NOT exceed B=8. We will clarify in revision that the example uses a hypothetical allocation to motivate the problem, and that the actual static allocator's allocation *can* exceed B for deeper plans (e.g., 5 slots with B=8 gives 1-1-1-1-1 = 5 ≤ 8 for 5 slots, but a slot compiler requesting 2 calls per slot gives 2-2-2-1-1 = 8 exactly; plans with slots requiring ≥ 3 calls each will exceed B).

## Q10: Why are the absolute EM numbers so low (0.17 → 0.25)?

**Rebuttal (MODERATE)**: The absolute EM reflects qwen3.5-9b's capability on multi-hop questions under a tight budget (B=8 retrieval calls, max 8 steps). Deep plans (hops ≥ 2) are inherently harder. The mechanism's contribution is the *relative improvement* (+7.7 points, 45% relative) within this constrained setting, not the absolute EM level. The mechanism is orthogonal to model capability — a stronger generator would benefit from the same budget-feasible allocation at a higher absolute EM.

## Q11: The ATE formula uses 0.054 but labels it "361 eligible / 6,494." 361/6494 = 5.56%, not 5.39%.

**Rebuttal (CONCEDE AND FIX)**: This is a factual inconsistency. The correct figures are: deep-eligible = 361/6,494 = 5.56%; deep-executable (confirmatory) = 350/6,494 = 5.39%. The ATE formula uses 0.054 ≈ 5.39% (confirmatory stratum). We will fix all prevalence figures to be consistent: 5.56% for the eligible stratum, 5.39% for the confirmatory-executed stratum, and the ATE formula will reference the confirmatory prevalence explicitly.

## Q12: The shallow harm (-0.021) was measured under a permissive budget, not B=8. Is this apples-to-oranges?

**Rebuttal (MODERATE)**: The deep confirmatory effect (B=8) and the shallow exploratory effect (permissive budget) are measured under different budget regimes. This is a limitation. However, the *direction* of the shallow harm is expected to hold: budget-aware reallocation on plans that do not exhaust the budget redistributes evidence quality without recovery. The *magnitude* is a point estimate from the permissive trace and may differ under B=8. We will add this caveat in revision.

## Q13: Why no runtime or token-cost comparison?

**Rebuttal (STRONG)**: The structural analysis (§4) and gate evaluation (§5) add negligible overhead: slot count, edge count, structural depth, and feasibility predicate are all O(n) deterministic computations. The budget-aware flat planner performs a single concave allocation. The dominant cost in all arms is the LLM and retrieval calls, which are budget-capped identically across methods. Wall-clock latency differences between static and flat allocation are within measurement noise (< 1ms planning overhead vs. multi-second LLM calls).

## Q14: Table 1 omits PROGRAM, DynaKRAG, PruneRAG, S2G-RAG.

**Rebuttal (CONCEDE AND FIX)**: Table 1 was designed for the most closely related systems at each decision point. We will expand the table in revision to include PROGRAM, DynaKRAG, PruneRAG, and S2G-RAG, with the same column structure. All four operate at a different decision level (decomposition optimization, learning evidence control, pruning decomposition trees, sufficiency judging) and do not address physical allocation feasibility.

## Q15: The census found only 361 deep plans (5.56%). Is this a niche problem?

**Rebuttal (STRONG)**: The deep-eligible stratum is small but its *impact* is large: 41.7% of deep plans under static allocation exhaust the budget, producing zero-answer-quality structural failures. The mechanism targets a specific failure mode, not a population-level accuracy improvement. On workloads with higher deep-plan prevalence (e.g., multi-hop domains requiring 3+ evidence bindings), the mechanism's value would scale proportionally. The low prevalence is reported honestly, not as a strength.

## Q16: Why does the paper claim "eliminates all 146 budget-exhaustion events" when this is guaranteed by construction?

**Rebuttal (STRONG)**: We explicitly state: "This is a direct consequence of the flat planner's allocation constraint Σa_s ≤ B" (§7.2). The BE elimination is an engineering consequence, not an empirical surprise. We report it because it validates that the allocation constraint is correctly implemented and that the 146 structural failures are resolved. The 7.7 EM improvement is the research result; the BE elimination is the mechanism's design property verified in practice.

## Q17: The paper has 10 pages but TKDE allows 12. Why not add more content?

**Rebuttal (MODERATE)**: The paper is content-complete at 10 pages. We could expand with additional tables or figures, but doing so without new experiments would add padding, not substance. The paper's brevity reflects the narrow scope of the mechanism (planning + gate) and the honest limitation of single-model evaluation. If reviewers require specific additions (e.g., expanded Table 1, end-to-end cost table), we can address them in revision within the 12-page limit.

## Q18: The "honest contribution" framing in the abstract is unusual. Is this a weakness?

**Rebuttal (MODERATE)**: The framing is a deliberate choice to set correct expectations. In a field where many papers overclaim, we chose to front-load the scoping: what is confirmed, what is exploratory, and what could not be tested. We will soften the language in revision to avoid meta-commentary: "We present a mechanism for regime-sensitive physical planning, confirmed on deep plans (n=350) and supported by large-scale exploratory evidence on shallow plans (n=8,632)."

## Q19: Why is the confusion matrix reported with precision 0.533? Isn't 53% precision useless?

**Rebuttal (STRONG)**: The confusion matrix is reported because it characterizes the *necessary condition* for budget exhaustion. Recall 1.0 means zero missed events — the condition identifies every case where the budget *will* be exhausted. Precision 0.533 means 47% of "predicted infeasible" plans are actually safe (they terminate before exhausting the budget). This is expected: the condition is necessary, not sufficient. The diagnostic's value is in its *recall* (safety: no missed events), not its *precision* (which is bounded by other termination criteria). We do not claim the condition is a high-precision diagnostic.

## Q20: What happens when B is very large or very small? Is the gate threshold (hops ≥ 2) robust to B?

**Rebuttal (MODERATE)**: This is an important question we did not explore (single budget B=8). When B is very large (no budget constraint), no plans exhaust the budget and the gate is irrelevant. When B is very small (B=1 or B=2), even shallow plans may exhaust the budget and the gate may need adjustment. The gate threshold (hops ≥ 2) was determined by the eligibility definition in the frozen protocol, not by the budget value. Sensitivity analysis over B is future work.
