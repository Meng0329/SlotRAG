# INTRODUCTION_DEFENSE_AUDIT.md — Introduction Attack Test

> **Date**: 2026-09-08
> **Scope**: Sentence-by-sentence attack on §1 (Introduction), testing each claim against a hostile reviewer.

---

## §1.1 "From decomposition to execution"

### Sentence 1
> "Multi-hop RAG systems increasingly decompose questions into structured evidence-acquisition steps—typed retrieval calls, join constraints, relational operators—that are planned before execution."

**Attack**: Who are these "increasingly" systems? Most production multi-hop RAG (IRCoT, ReAct) do NOT use "typed retrieval calls, join constraints, relational operators" — those are SlotRAG-specific terms. "Increasingly" overstates the prevalence of structured decomposition in multi-hop RAG.

**Defense**: PlanRAG, PyRAG, PROGRAM, DynaKRAG all use structured decomposition. The word "increasingly" is supported by the 2026 literature surge (cited: planrag, pyrag, program, dynakrag).

**Verdict**: ✅ PASS — the cited systems justify the trend claim

### Sentence 2
> "This decomposition provides logical validity: each step specifies what evidence is needed. But logical validity does not guarantee physical executability."

**Attack**: The logical/physical distinction is presented as novel insight but is the classic database principle.

**Defense**: The paper does not claim to invent the distinction — it observes that multi-hop RAG systems suffer from it. The insight is empirical (41.7% budget exhaustion), not theoretical.

**Verdict**: ✅ PASS

### Sentence 3
> "A decomposition into three steps that each locally require four retrieval calls is not executable when the global budget is eight calls, regardless of its logical coherence."

**Attack**: This is a tautology (4+4+4=12 > 8). Is the paper contributing arithmetic?

**Defense**: The arithmetic is the necessary condition; the contribution is (a) identifying this occurs in practice (41.7% of deep plans) and (b) developing a fix (flat planner + gate). The motivating example is pedagogical, not the contribution.

**Verdict**: ✅ PASS — the example serves its purpose

## §1.2 "Why a universal optimizer is insufficient"

### Sentence 1
> "An intuitive response is to apply a budget-aware optimizer globally. However, large-scale retrospective analysis reveals that the optimizer's treatment effect is conditioned on plan structure."

**Attack**: "conditioned on plan structure" — this is the main empirical claim. The reviewer will ask: how large is the conditioning? Is this a robust finding or a dataset artifact?

**Defense**: The +0.0771 EM improvement on deep plans and -0.021 EM harm on shallow plans are both statistically significant and on different n (350 vs 8,085). The finding is consistent across 3 datasets for the deep effect.

**Verdict**: ✅ PASS

### Sentence 2
> "On structurally deep plans (where evidence requirements involve three or more slots joined through intermediate bindings), budget-aware allocation improves answer quality by 7.7 EM points and eliminates all budget-exhaustion events under a matched protocol."

**Attack**: "three or more slots joined through intermediate bindings" — is this the exact definition of deep? The actual definition is hops ≥ 2. A 2-slot plan with a join AND an operator could be hops=2.

**Defense**: The parenthetical is an informal gloss, not a formal definition. The formal definition (hops ≥ 2) is in §3. The gloss is approximately correct: a 3-slot chain (A→B→C) has hops=2, which is the canonical case.

**Verdict**: 🟡 SOFTEN — change to "(where evidence requirements form a structural chain of depth ≥ 2)"

### Sentence 3
> "On shallow plans (one or two independent slots), the same optimizer can reduce answer quality by 2.1 EM points (p < 0.001 in exploratory analysis), with the harm concentrated on specific datasets."

**Attack**: "in exploratory analysis" is present — good. But the 2.1 EM harm is from permissive budget, not B=8. This could be questioned.

**Defense**: The paper correctly labels this as exploratory and notes the budget regime difference in §7.

**Verdict**: 🟡 SOFTEN — add "under permissive budget" for precision

## §1.3 "Scope and contributions"

### C1 (Typed evidence plans)
> "We introduce a typed intermediate representation that separates multi-hop evidence requirements—slots, joins, operators—from their physical materialization."

**Attack**: DB community will see this as logical/physical independence (Codd 1970). NLP community may see it as over-formalization of what IRCoT does implicitly.

**Defense**: The typed plan vocabulary is specific to multi-hop RAG evidence (not general queries), and the structural analysis (hops, join count, feasibility predicate) is uniquely enabled by this representation.

**Verdict**: ✅ PASS — correctly scoped as application of separation to RAG

### C2 (Feasibility diagnosis)
> "We show that independent per-slot physical allocations need not compose into a globally feasible plan under a retrieval-call budget. A necessary condition for static budget exhaustion is derivable from the plan structure at compile time."

**Attack**: "derivable from the plan structure at compile time" — this is Σa_i > B, a single inequality. Calling this "derivable" inflates a trivial computation.

**Defense**: "derivable" is correct (formally proven in §4); the condition is simple but non-obvious to practitioners who assume per-slot defaults compose. The empirical confirmation (recall=1.0, precision=0.533) validates the condition.

**Verdict**: 🟡 PASS — "derive" is defensible but the phrasing invites the "trivial insight" attack

### C3 (Structure-gated planning)
> "We develop a budget-aware physical planner that reallocates retrieval calls across slots under a global constraint, and a deterministic structural-depth gate that applies it."

**Attack**: The planner is a simple concave allocation. The gate is a two-condition if-else. Calling these "developments" inflates heuristic engineering.

**Defense**: The novelty is not the complexity of the components but the empirical finding that regime-sensitive dispatch (flat on deep, static on shallow) is beneficial. The simplicity is a design principle (§5).

**Verdict**: ✅ PASS

### C3 continued
> "Confirmatory experiments on deep executable plans show the planner improves answer quality and eliminates budget exhaustion. Large-scale exploratory replay provides evidence that retaining static execution outside the deep regime is justified."

**Attack**: The exploratory label is present. But "provides evidence that retaining static execution is justified" is a strong claim for an exploratory finding.

**Defense**: "provides evidence" is appropriately hedged — it does not say "confirms" or "establishes." The evidence is large-scale (8,632 plans) and statistically significant (p<0.001).

**Verdict**: ✅ PASS

## §1.4 "Motivating example"

> "Consider a three-slot plan whose static allocation assigns four retrieval calls to each slot: 4+4+4=12 > B=8."

**Attack**: The system's actual static allocator does even allocation: ⌊8/3⌋ = 2, remainder → 3-3-2, which does NOT exceed B=8. The example uses an ad-hoc 4-4-4 that doesn't match the system.

**Defense**: The example is pedagogical ("Consider a three-slot plan whose static allocation assigns four retrieval calls to each slot"). It illustrates the general problem (local vs global allocation mismatch), not the specific system's behavior. However, this could confuse reviewers who check the actual system.

**Verdict**: 🔴 REPAIR — clarify that the example uses a hypothetical allocation to illustrate the problem, not the system's actual static allocator. Add: "This can occur when slot-specific retrieval policies independently request calls, regardless of the system's default allocator."

---

## Introduction Overall Verdict

**Score**: 8/10 PASS, 2/10 SOFTEN

The introduction is well-structured and honest. The three attack points are:
1. "three or more slots" gloss vs formal hops ≥ 2 definition
2. Motivating example uses 4-4-4 allocation that doesn't match the system's static allocator
3. "in exploratory analysis" could add budget regime qualifier

None of these are fatal. The introduction's strength is its clear problem statement and the honest C3 disclosure.
