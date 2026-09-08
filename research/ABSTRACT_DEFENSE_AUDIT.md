# ABSTRACT_DEFENSE_AUDIT.md — Abstract Attack Test

> **Date**: 2026-09-08
> **Scope**: Sentence-by-sentence attack on the abstract. Each sentence is tested against a hostile reviewer's reading.

---

## Abstract Text and Attack

### Sentence 1
> "Multi-hop retrieval-augmented generation (RAG) systems decompose complex questions into multiple evidence-acquisition steps."

**Attack**: Uncontroversial background. No issue.
**Verdict**: ✅ PASS

### Sentence 2
> "We observe that a decomposition that is logically valid need not be physically executable under a global retrieval budget: independent per-slot allocations may sum to exceed the system's hard retrieval-call limit, causing budget exhaustion before answer generation."

**Attack**: The "observation" is a trivially true arithmetic fact. Σ > B means not all slots can be served. Is this an "observation" or a definition?
**Defense**: The insight is not the inequality itself but that *this specific failure mode occurs in practice* — 41.7% of deep plans under static allocation exhaust the budget. The abstract correctly frames it as an empirical observation with a quantitative consequence.
**Verdict**: ✅ PASS — the empirical grounding (41.7%) makes it non-trivial

### Sentence 3
> "We address this with budget-feasible physical planning over typed evidence plans—a separation of logical evidence requirements from their physical materialization strategy."

**Attack**: "Typed evidence plans" sounds like a novel contribution but the description is vague. What makes them "typed"?
**Defense**: The term is defined in §3 (algebra) with concrete type system (Slot, Join, RelationalOperator). The abstract is appropriately high-level.
**Verdict**: ✅ PASS

### Sentence 4
> "We derive a compile-time feasibility condition on static allocations and confirm it against frozen matched-budget executions on 350 deep structural plans: every observed budget exhaustion violated global allocation feasibility (recall 1.0), although many infeasible plans terminated without exhausting the budget (precision 0.533)."

**Attack**: 
- "derive" for Σ > B? A reviewer sees this as inflating a trivial derivation
- 350 deep plans is a small confirmatory sample
- "precision 0.533" means the condition is wrong 47% of the time — this is not a good "diagnostic"
**Defense**: "derive" is appropriate for a formal condition (§4); "frozen matched-budget executions" is the gold standard; recall=1.0 means zero missed events (the correct safety property); the paper never claims the condition is a good diagnostic — it is necessary, not sufficient.
**Verdict**: 🟡 PASS with caveat — "derive" is defensible but could be softened to "identify" or "state"

### Sentence 5
> "A budget-aware physical planner improves answer quality by 7.7 EM points over static allocation on deep plans under a matched budget (p < 10^{-6}, exact McNemar), and eliminates all 146 observed budget-exhaustion events."

**Attack**: 
- "eliminates all 146 observed" — is this an engineering claim or a research result? Σa_s ≤ B guarantees no budget exhaustion by construction. Is reporting this as a result circular?
- 7.7 EM points is the main empirical claim. The p-value is strong. But EM 0.17 → 0.25 is still low.
**Defense**: The elimination of BE events is a *consequence* of the allocation constraint — the flat planner's constraint guarantees Σa_s ≤ B, which makes budget exhaustion structurally impossible. This is stated as an engineering consequence, not a surprise. The 7.7 EM improvement is the research result.
**Verdict**: ✅ PASS — the BE elimination is correctly framed as a design consequence

### Sentence 6
> "Dependency-sensitive importance weighting is ablated: a uniform budget-aware optimizer outperforms a dependency-weighted variant on deep plans (EM difference +0.009, p = 0.743) while being strictly simpler."

**Attack**: 
- "outperforms" with p = 0.743 is statistically unjustified
- "strictly simpler" — both are O(n) allocations; the difference is one formula
- The ablation is framed as "falsification" elsewhere but the abstract is more measured ("ablated")
**Defense**: "outperforms" is factually accurate for point estimate (+0.0086), but the non-significance means the "outperformance" is not statistically supported. "Strictly simpler" is defensible (uniform weights vs dependency weighting).
**Verdict**: 🟡 SOFTEN — change "outperforms" to "matches" or "does not significantly differ from" for a non-significant result

### Sentence 7
> "Large-scale exploratory replay (8,632 plans) indicates that applying the budget-aware optimizer to structurally shallow plans can reduce answer quality (-0.021 EM, p < 0.001), motivating a lightweight deterministic structural-depth gate."

**Attack**: 
- "exploratory" label is present — good
- But "motivating" implies the gate is a solution, which is not yet confirmed for shallow plans
- The gate was not tested on the 8,632 plans — only the harm was tested. The A' vs flat comparison is a separate analysis on the same data.
**Defense**: "motivating" is appropriate — the harm finding motivates the gate design. The A' vs flat result is also on the same trace. The paper correctly labels this as exploratory.
**Verdict**: ✅ PASS — appropriately hedged

### Sentence 8
> "The gate's independent confirmation on shallow matched-budget executions was pre-registered but could not be executed because frozen shallow plan payloads were unavailable in the earlier census."

**Attack**: This is an unusual admission in an abstract. It invites the question: why include a contribution you can't confirm?
**Defense**: This is a deliberate honest disclosure — the paper's scoping requires stating what is and isn't confirmed. This prevents the reviewer from discovering the gap independently and holding it against the paper.
**Verdict**: ✅ PASS — honest and unusual, a strength

### Sentence 9
> "We report the system's honest contribution: a mechanism for regime-sensitive physical planning whose confirmatory benefit is established on the deep plans where it was designed to operate."

**Attack**: 
- "honest contribution" — meta-language unusual in technical abstracts
- Could be read as the paper apologizing for limited scope
**Defense**: The meta-language is a deliberate framing choice — it sets expectations and prevents overclaiming. However, it may backfire by inviting more scrutiny.
**Verdict**: 🟡 SOFTEN — change to "We present a mechanism for regime-sensitive physical planning, confirmed on deep plans (n=350) and exploratory on shallow plans (n=8,632)." Remove "honest" to avoid meta-apology framing.

---

## Abstract Overall Verdict

**Score**: 7/9 PASS, 2/9 SOFTEN

The abstract is unusually honest and well-scoped for a TKDE submission. The two softenings are:
1. A5: "outperforms" → "matches" for the chain ablation (non-significant)
2. A9: "honest contribution" → remove meta-language

These are optional edits that improve tone without changing substance. The factual claims in the abstract are all supported.

**Key defense strengths**: The admission of H-STRUCT-4 infeasibility in the abstract itself is a significant strategic choice that disarms the "gate unconfirmed" attack. Most papers bury such admissions in the threats section.

**Key vulnerability**: The chain ablation language ("outperforms" with p=0.743) is the most likely trigger for a reviewer's statistical objection. Changing to "matches" or "is statistically indistinguishable from" is a low-cost, high-value fix.
