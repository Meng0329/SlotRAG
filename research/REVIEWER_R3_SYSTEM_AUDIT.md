# REVIEWER_R3_SYSTEM_AUDIT.md — Systems/Heuristic Attack Simulation

> **Reviewer persona**: NLP/IR systems researcher, ACL/EMNLP reviewer, demands end-to-end evaluation
> **Date**: 2026-09-08
> **Paper**: SlotRAG: Budget-Feasible Physical Planning over Typed Evidence Plans for Multi-Hop RAG

---

## R3 Attack Profile

**Core thesis**: "The paper presents a series of small heuristics that operate on a plan compiler's output. The system overhead (plan compilation + slot materialization + reranking + reranking) is substantial, but the paper evaluates only answer quality under matched budget, not end-to-end cost. The 'system' contribution is thin."

### Attack Vector 1: No End-to-End Cost / Latency Comparison

**Claim**: The paper only reports EM/F1 and budget-exhaustion counts. No wall-clock latency, no total token cost, no end-to-end comparison with non-plan-based systems.

> Multi-hop RAG is used in practice because speed and cost matter. A system that reduces EM by 7 points but doubles latency or quadruples token cost is not a practical advance. The paper never measures the overhead of the SlotRAG pipeline (slot compilation + materialization + budget planning) versus a simpler iterative retrieval baseline (IRCoT or ReAct). If the goal is a "system" contribution (it is in the title), where are the system metrics?

**Severity**: CRITICAL for a systems venue (TKDE), MODERATE for an ML venue
**Defense**: The paper frames itself as a "physical planning" mechanism, not a full-stack system; the pipeline overhead (planner + diagnosis) is computationally trivial (single arithmetic check + allocation) — the dominant cost is the LLM calls themselves, which are budget-capped identically across arms
**Required edit**: Add one paragraph in §5 (analysis) or §10 (threats) stating: "The structural analysis (§4) and gate evaluation (§5) add negligible overhead: slot count, edge count, structural depth, and feasibility predicate are all O(n) deterministic computations. The budget-aware flat planner performs a single concave allocation. The dominant cost in all arms is the LLM and retrieval calls, which are budget-capped identically. We do not measure wall-clock latency because the planning overhead is zero within the resolution of single-question execution time."

### Attack Vector 2: Slot Compilation Is the Real Bottleneck

**Claim**: Slot compilation uses an LLM call (qwen3.5-9b, same model as generation). The paper evaluates slot plans but not the quality of compilation.

> The entire system depends on the slot compiler producing good plans. If the compiler produces 3-slot plans for questions that only need 1 retrieval call, the budget is wasted. If it produces 1-slot plans for 3-hop questions, the budget is insufficient. The paper never evaluates compilation quality (slot accuracy, join accuracy, operator accuracy). The structural depth metric (hops ≥ 2) is a property of the compiled plan, not the question. A different compiler would produce different plans and different results.

**Severity**: HIGH — acknowledged as a threat (§10, "plan compiler") but could be stronger
**Defense**: The paper is honest about compiler dependence; the mechanism is designed to operate on whatever plan the compiler produces, not to improve the compiler itself
**Optional edit**: In §3, add one sentence clarifying: "We do not evaluate plan compilation quality; the contribution is the execution mechanism downstream of an arbitrary plan compiler."

### Attack Vector 3: Gate Threshold Is Arbitrary, No Sensitivity Analysis

**Claim**: The gate threshold hops ≥ 2 is used without justification. Why not hops ≥ 1? Why not hops ≥ 3? What if the threshold is slightly off?

> The gate condition (hops ≥ 2 ∧ F = 0 → flat, else static) uses hops ≥ 2 as the cutoff between "deep" (budget-aware) and "shallow" (static). This is never justified empirically. Was the threshold pre-registered before seeing data? Was a sensitivity analysis over {1, 2, 3} conducted? The finding that shallow plans are harmed could be an artifact of the specific threshold choice.

**Severity**: MODERATE-HIGH — the threshold was determined by the eligibility definition in the frozen protocol, not post-hoc, but the paper does not explicitly state this
**Defense**: hops ≥ 2 is the eligibility criterion from the structural census protocol (H-STRUCT-1 pre-registration), defined before results were observed; 1-hop plans have at most 2 slots with 1 join — these are trivially feasible under B=8
**Required edit**: In §6 or §5, add: "The threshold hops ≥ 2 is the eligibility criterion from the V1.2 frozen census (§6), pre-registered before any experimental results were observed."

### Attack Vector 4: Only 3 Datasets, No Large-Scale Demonstration

**Claim**: HotpotQA, 2WikiMultiHopQA, MuSiQue — all standard multi-hop benchmarks with known ceiling effects. The deep plans only constitute 5.6% of questions. Where are the 50-question qualitative case studies? Where is the error analysis? Where is the in-domain evaluation?

> The paper evaluates on 350 deep plans from 3 datasets. This is a narrow evaluation by TKDE standards. No real-world dataset (e.g., natural multi-hop queries from a search engine, industrial QA logs) is tested. The contribution is academic rather than practical.

**Severity**: MODERATE — typical for venue, but 350 confirmatory deep plans is indeed small
**Defense**: The frozen protocol constrains the evaluation to what was pre-registered; expanding to new datasets would require new pre-registration and is outside scope
**Optional edit**: None needed — the limitation is honestly scoped

### Attack Vector 5: Figures Show Small Absolute Numbers

**Claim**: EM goes from 0.17 to 0.25 on deep plans. Both are very low. For practical use, 25% EM is not acceptable.

> The best system achieves 24.9% EM on deep plans. This means it answers 3 out of 4 deep questions incorrectly. Is this useful in practice? The paper presents a +7.7-point relative improvement (45% relative), but the absolute level (25% EM) suggests the underlying system is far from production-ready.

**Severity**: MODERATE — the paper never claims production readiness, but the absolute level is striking
**Defense**: The paper benchmarks a mechanism, not a production system; 25% EM is competitive with baselines on multi-hop datasets using qwen3.5-9b; the mechanism's value is in the *delta*, not the absolute
**Optional edit**: In §8 (analysis), add one sentence: "The absolute EM level (0.25) reflects the generator model's ceiling on these deep multi-hop plans; the mechanism's contribution is the 7.7-point improvement within this constrained budget regime."

### Attack Vector 6: No Comparison With Non-Plan-Based Iterative Systems

**Claim**: IRCoT, ReAct, PlanRAG are cited as "adapted baselines" but never empirically compared under matched conditions.

> The paper compares static/flat/chain within its own system. But the strongest baselines in multi-hop RAG (IRCoT, ReAct, PlanRAG, DynaKRAG) are never run. How does SlotRAG compare to an iterative ReAct baseline under the same B=8 budget? The paper claims this is impossible due to different decision points, but IRCoT and ReAct also operate under retrieval-call budgets — they simply don't have explicit plan-level allocation. A budget-capped ReAct could be a direct competitor.

**Severity**: HIGH — this is the strongest systems-level objection
**Defense**: The paper honestly acknowledges the cross-system comparison gap; adapting baselines to use the same retrieval-call budget and slot plan as SlotRAG would require re-implementing each baseline, which is outside scope
**Required edit**: In §2 (related) or §10 (threats), add: "We do not include cross-system empirical comparisons because the baseline systems (IRCoT, ReAct, PlanRAG) operate at a different abstraction level: they do not produce typed evidence plans, and their retrieval-call budgets are not directly comparable. Adapting these systems to share SlotRAG's plan representation would constitute a separate study. We provide a structural comparison (Table 1) and direct the reader to each baseline's original evaluation for absolute performance."

---

## R3 Verdict

**Likely verdict**: MAJOR REVISION → WEAK ACCEPT (after revision)

R3's strongest attacks are the lack of end-to-end cost metrics and the absence of cross-system comparison. The paper's weakness is that it evaluates only internal ablation (static/flat/chain/gate) rather than competing systems. The gate threshold justification is another gap. However, the paper's honesty about scope limitations is atypical and may soften R3's critique.

## Required Paper Edits to Withstand R3

1. **Add overhead paragraph**: State explicitly in §5 or §10 that planning overhead is O(n) and negligible vs LLM/retrieval cost
2. **Justify hop ≥ 2 threshold**: State that it was pre-registered in the census protocol before results
3. **Clarify cross-system gap**: One sentence in §2 or §10 explaining why IRCoT/ReAct are not directly comparable under matched conditions
4. **Address absolute EM**: One sentence noting the absolute level reflects the model ceiling, not the mechanism's value

## Optional Edits

- Add one example of a shallow plan (1-2 slots, easily within B=8) to make the deep/shallow distinction concrete for R3
- Add runtime comparison between static and flat allocation on the 350 confirmatory plans (both should be near-instant; reporting this would preempt the latency objection)
