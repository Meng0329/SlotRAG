# REVIEWER_R1_NOVELTY_AUDIT.md — Novelty/Positioning Attack Simulation

> **Reviewer persona**: Senior systems/IR researcher, H-index 60+, TPAMI/TKDE PC member
> **Date**: 2026-09-08
> **Paper**: SlotRAG: Budget-Feasible Physical Planning over Typed Evidence Plans for Multi-Hop RAG

---

## R1 Attack Profile

**Core thesis**: "This paper presents a straightforward engineering technique (reallocate retrieval calls under budget) wrapped in formal notation. The novelty is thin, and the formalism adds complexity without proportional insight."

### Attack Vector 1: Trivial Core Insight

**Claim under attack**: C2 (compile-time feasibility diagnosis)

> The feasibility condition Σa_i > B is a single arithmetic inequality. Calling this a "compile-time diagnosis" inflates what is essentially checking whether a sum exceeds a constant. Any practitioner would naturally do this. The confusion matrix (precision 0.533) further shows the condition is imprecise — nearly half of infeasible plans don't actually exhaust the budget. What does a "diagnostic" with ~53% precision actually buy?

**Paper's position** (§2 abstract, §4 RQ2):
- Condition is *necessary but not sufficient* (recall 1.0, FN = 0)
- Used as trigger for gate dispatch, not as a standalone accuracy prediction

**Severity**: HIGH — a common-sense objection that reviewers will raise
**Rebuttal grade**: MODERATE — the framing as "diagnosis" is technically justified (recall = 1.0 means zero missed events, which is what a safety condition needs), but the paper's title language ("compile-time feasibility diagnosis") may invite this attack

### Attack Vector 2: Logical/Physical Separation Is Classical DB

**Claim under attack**: C1 (typed evidence plans)

> The separation of logical evidence requirements from physical materialization is the logical/physical independence principle from relational database theory (Codd, 1970). SlotRAG repackages this 50-year-old abstraction for RAG evidence retrieval. How is this more than an application of an established DB principle to a narrow subdomain?

**Paper's position** (§3): explicitly acknowledges typed operators and separation as design principles
**Severity**: MODERATE — the paper correctly identifies the contribution as the *application* to multi-hop evidence plans, not as inventing the separation principle
**Rebuttal grade**: STRONG if reframed as "bringing structured query optimization to RAG evidence materialization" — the novelty is in the slot/join/relational-operator vocabulary specific to RAG plans and the compile-time feasibility analysis unique to retrieval-call budgets

### Attack Vector 3: No Empirical Novelty Over Budget-Aware Baselines

**Claim under attack**: Positioning vs. PAGE-RAG, Know Before You Fetch, PruneRAG

> Table 1 positions SlotRAG against PAGE-RAG, KBYF, and PruneRAG on "budget feasibility?" but reports no empirical comparison with these systems. How can you claim superiority if you don't run them? The budget-aware routing decision in KBYF or the tree pruning in PruneRAG may achieve similar or better accuracy without your plan formalism.

**Paper's position** (§2): comparisons are purely descriptive (Table 1, no numbers)
**Severity**: HIGH — the paper honestly acknowledges different decision points, but a hostile reviewer will demand empirical evidence
**Rebuttal grade**: MODERATE — the different abstraction levels (what-to-retrieve vs. how-to-allocate within a plan) make direct comparison methodologically complex; the paper can defend this via the "different decision point" argument, but it weakens the contribution claim

### Attack Vector 4: "Structure-Gated Dispatch" Is a Threshold Heuristic

**Claim under attack**: C3 gate condition (hops ≥ 2 ∧ F = 0 → flat, else static)

> The "gate" is a two-condition if-else statement. Calling it "structure-sensitive dispatch" is euphemistic. Why is hops ≥ 2 the correct threshold? Was hops ≥ 1 tested? Was the gate pre-registered before or after seeing the data? The paper itself admits H-STRUCT-4 (independent confirmation) was infeasible, leaving the gate without confirmatory evidence.

**Paper's position** (§5, §7.4): gate is deterministic, non-parametric; H-STRUCT-4 infeasible
**Severity**: HIGH — combines novelty objection with evidence objection
**Rebuttal grade**: MODERATE — the two-condition gate is deliberately simple (design principle §5: "This simplicity is a property, not a limitation"); but the threshold question is unanswered. However, the paper does NOT claim a learned gate — it's a structural property threshold, and the paper honestly reports the exploratory-only evidence level

### Attack Vector 5: Population Effect Is Negligible

**Claim under attack**: ATE_pop = +0.00416 EM/question

> A 0.4 EM-point population-level effect is negligible. Even on the eligible deep plans, the absolute EM improves from 0.17 to 0.25 — both well below 50%. The paper admits "the gate targets a small but structurally high-risk regime." Is this a contribution or a curiosity?

**Paper's position** (§7.5, §9): explicitly honest about the small population effect
**Severity**: MODERATE — the paper does not overclaim population benefit, but the small effect size could signal limited practical significance
**Rebuttal grade**: STRONG — the paper frames the contribution correctly (regime-targeted mechanism, not population-level EM improvement)

---

## R1 Verdict

**Likely verdict**: BORDERLINE WEAK REJECT → REVISE

R1 will focus on the thinness of the core insight and the absence of cross-system empirical comparison. The strongest defense is the honest scoping (confirmatory vs exploratory evidence levels) and the falsification of chain importance. The weakest point is the prevalence of the eligible regime (5.56%) and the population effect magnitude.

## Required Paper Edits to Withstand R1

1. **Strengthen positioning language**: In §2 (related), add one sentence per system explicitly stating *why* they are not directly comparable (different abstraction level, not "Budget feasibility?" column alone)
2. **Soften "diagnosis" language**: In title and abstract, "feasibility diagnosis" → "feasibility check" or "feasibility analysis" to lower the bar for the insight
3. **Clarify gate pre-registration**: State explicitly in §6 (protocol) whether the gate threshold (hops ≥ 2) was pre-registered or determined post-hoc on exploratory data

## Optional Edits

- §2 Table 1: add a "Performance comparison?" column with "N/A (different abstraction)" for non-comparable systems, making the honest non-comparison a feature of the table rather than a gap
- §7: add a sentence on limitations of the ATE framing — "the mechanism's value is demonstrated on deep plans, not as a population-level accuracy booster"
