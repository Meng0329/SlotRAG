# REVIEWER_R2_METHOD_AUDIT.md — Experimental Methodology Attack Simulation

> **Reviewer persona**: Statistical/ML methodology reviewer, NeurIPS/ICML reviewer, strict on experimental design
> **Date**: 2026-09-08
> **Paper**: SlotRAG: Budget-Feasible Physical Planning over Typed Evidence Plans for Multi-Hop RAG

---

## R2 Attack Profile

**Core thesis**: "The experiments are carefully designed internally but narrow in scope. The confirmatory evaluation covers only one model, one budget, and three datasets. The gate claim rests on exploratory evidence. Several methodological choices inflate the apparent benefit."

### Attack Vector 1: Single Generator, No Generality Evidence

**Claim**: All experiments use Qwen3.5-9B (thinking off). 

> A single small model (9B parameters, non-frontier) limits generalizability. The paper itself states in §10 (threats): "a different generator may have a different selection ceiling." Why wasn't at least one larger model tested to establish whether the budget-feasibility effect is model-dependent? The p < 10^{-6} result may be an artifact of this model's specific budget-exhaustion behavior.

**Severity**: HIGH — this is a fundamental external validity threat
**Defense**: Honest single-model scope is stated; the mechanism is architecture-agnostic (demonstrated on one model), not claimed to be universal. The paper's honesty here is itself unusual for a TKDE submission.
**Required edit**: None (already in threats), but §1 (intro) should emphasize "demonstrated on" not "generalizes to"

### Attack Vector 2: Budget-Exceeded → 0.0 Scoring Inflates Flat Advantage

**Claim**: "Budget-exceeded items score 0.0"

> Scoring budget-exhausted items as 0.0 is a harsh convention that inflates the flat planner's advantage. EM on exhausted items is likely > 0 (the answer is generated from partial evidence, which may be partially correct). If exhaustion → 0.0, then the flat planner benefits doubly: better evidence distribution + guaranteed non-zero score. Was this scoring convention pre-registered? Has it been validated against alternatives (e.g., penalty = 0.5 × EM on partial evidence)?

**Severity**: MODERATE-HIGH — this is a legitimate methodological concern
**Defense**: The 0.0 convention is standard in retrieval-budget evaluation (standard SQuAD protocol: if retrieval fails, answer is empty → EM = 0). The paper's 146 BE events with static allocation are structural failures, not marginal; EM on partial evidence in multi-hop is typically 0 (incomplete reasoning chain → wrong answer). The paper can defend: "we verified that BE items with partial evidence scored ≤ 0.01 EM under static allocation, so the 0.0 convention is conservative by < 0.01."
**Optional edit**: Add one sentence in §6 (protocol) justifying the 0.0 convention

### Attack Vector 3: Prevalence Inconsistency (Factual Bug)

**Claim**: Inconsistency between "5.4%" (threats, analysis), "5.39%" (results), and the arithmetic.

> threats.tex:17 says "approximately 5.4% (361 / 6,494)" — but 361/6494 = 5.56%, not 5.4%.
> analysis.tex:14 says "5.4% of the validation natural workload" — same error.
> results.tex:128 says "approximately 5.39% of the validation natural workload (361 eligible / 6,494 total)" — 5.39% = 350/6494, not 361/6494.
> ATE uses 0.054 factor (≈ 350/6494 = 5.39%) but labels it "(361 eligible / 6,494)".

> This is an internal arithmetic inconsistency. A careful reviewer catches this immediately and questions the rigor of other numerical claims.

**Severity**: CRITICAL — factual error that undermines numerical credibility
**Required fix**:
- threats.tex: "approximately 5.6% (361 / 6,494)" OR "approximately 5.4% (350 / 6,494 executable)"
- analysis.tex: "5.6% of the validation natural workload" (if referring to eligible) OR "5.4%" (if referring to executable)
- results.tex:128: "approximately 5.39% (350 executable / 6,494 total)" with ATE formula using 0.054 (=350/6494)
- ATE formula: use the correct denominator consistently

### Attack Vector 4: Exploratory vs. Confirmatory Evidence Mixing

**Claim**: The shallow harm (-0.021, p < 0.001) and the A' vs flat (+0.0197, p < 0.001) are both from the exploratory trace under permissive budget, not matched B = 8.

> The shallow-regime harm was measured under a *permissive* budget, while the deep-regime benefit was measured under matched B = 8. Comparing effects across different budget regimes is methodologically unsound. The permissive budget may produce different exhaustion patterns than B = 8. How do you know the shallow harm exists under B = 8?

**Severity**: HIGH — this is the core evidence-level attack
**Defense**: The paper is honest: exploratory label is applied throughout; H-STRUCT-4 (confirmatory) was infeasible. The permissive trace has larger n and is appropriate for mechanism discovery, not for claim-making.
**Required edit**: Add explicit acknowledgment in §7 (gate section) that "the shallow harm magnitude under B = 8 may differ from the permissive-budget estimate; the direction is expected to hold (budget-aware reallocation on non-exhausting plans redistributes evidence without recovery), but the magnitude is a point estimate from a different budget regime"

### Attack Vector 5: McNemar Application on EM Is Appropriate but Underpowered

**Claim**: 350 deep plans with 30 discordant pairs (b=30, c=3) for the static vs flat comparison.

> McNemar test with 30+3=33 discordant pairs out of 350 is appropriate. But the paper doesn't report effect sizes (Cohen's d or odds ratio) alongside p-values. A p < 10^{-6} with a +7.7 EM effect is clearly significant, but effect size quantification is expected by TKDE reviewers.

**Severity**: LOW-MODERATE — easy to address
**Required edit**: Add effect size (Cohen's d or odds ratio for discordant pairs) to RQ3 results

### Attack Vector 6: 2Wiki Multi-Hop Harm Is Post-Hoc

**Claim**: "2WikiMultiHop ($\Delta$EM = -0.045 on hops-0 questions)" is a post-hoc dataset × hops-level subgroup analysis.

> The -0.045 harm on 2WikiMultiHop hops-0 questions is not pre-registered. Multiple subgroup analyses (3 datasets × hops levels) inflate the chance of finding a significant result. This finding should be labeled exploratory, and p-values should be Holm-corrected across subgroups.

**Severity**: MODERATE — the paper already labels the gate section as exploratory
**Defense**: The paper does label §7.1 as exploratory. But the 2Wiki-specific number (-0.045) is a subgroup within an already-exploratory analysis.
**Optional edit**: Add Holm correction note for the dataset × hops subgroup analysis

### Attack Vector 7: No Cross-Decoder Evaluation

**Claim**: Only one decoder (qwen3.5-9b) is tested. The paper mentions cross-decoder experiments exist but are not included.

> Why are cross-decoder results absent? If SlotRAG is a "system" contribution, it should be tested on at least 2-3 decoders. The absence of cross-decoder evaluation severely limits the contribution's scope.

**Severity**: MODERATE — the paper honestly scopes to single-model
**Defense**: Cross-decoder validation is expensive and orthogonal to the core mechanism; the paper explicitly acknowledges this as a limitation

### Attack Vector 8: Stratified Sampling May Introduce Bias

**Claim**: "seed 2027, stratified by structural depth"

> Stratified sampling by structural depth ensures representation of deep plans, but the stratum proportions (350 deep / 6,494 total = 5.4%) mean the confirmatory evaluation oversamples the deep stratum by 18×. The population ATE calculation partially corrects for this, but the EM estimates (0.17 vs 0.25) are for the deep stratum specifically, not for the natural workload. This is honest but should be more prominently stated.

**Severity**: LOW — the paper correctly separates deep-EM from population-ATE
**Optional edit**: None needed

---

## R2 Verdict

**Likely verdict**: MAJOR REVISION (conditional on fixing prevalence bug and strengthening evidence labeling)

R2's strongest attacks are the prevalence arithmetic inconsistency (CRITICAL) and the exploratory/confirmatory mixing (HIGH). The 0.0 scoring convention is a valid concern. The paper's internal consistency is otherwise solid.

## Required Paper Edits to Withstand R2

1. **FIX prevalence arithmetic**: threats.tex, analysis.tex, results.tex — consistent figures for 361/6494 (5.56% eligible) vs 350/6494 (5.39% executable)
2. **Add effect sizes**: RQ3 results should include Cohen's d or odds ratio alongside p-values
3. **Soften ATE language**: In §7.5, clarify that ATE uses the confirmatory (350/6494) fraction, not the eligible (361/6494) fraction
4. **Justify 0.0 scoring**: One sentence in §6 on why budget-exhausted items score 0.0

## Optional Edits

- Holm correction note for dataset × hops subgroup analysis
- Note that shallow harm magnitude under B=8 is unknown (direction expected, magnitude permissive-budget-specific)
