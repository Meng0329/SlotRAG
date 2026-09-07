# PAPER_OVERCLAIM_AUDIT.md — Overclaim Scan for TKDE Paper v4

> **Date**: 2026-09-07
> **Scope**: paper/, research/, src/ — all patterns listed in spec §28
> **Status**: Corrections applied

---

## Findings

| # | File | Pattern | Old Wording | Replacement | Status |
|---|------|---------|-------------|-------------|--------|
| 1 | paper/sections/results.tex (old, removed) | precision 1.0 | "precision = 1.0" / "0 个「预测可完成却 BE」" | "precision = 0.533, recall = 1.0 (Σ>B is necessary but not sufficient)" | FIXED in v4 C2 section |
| 2 | research/HYPOTHESES.md §12 | precision 1.0 recall 0.533 | "TN 76 / FP 0 / FN 128 / TP 146; precision 1.0, recall 0.533" | Corrected: TP=146/FP=128/FN=0/TN=76, precision 0.533, recall 1.0 | FIXED commit 2a69ab3 |
| 3 | research/H_STRUCT_3_FINAL_REPORT.md §12 | precision 1.0 recall 0.533 | Same confusion as #2 | Corrected orientation | FIXED commit 2a69ab3 |
| 4 | research/PAPER_CONTRIBUTIONS_V3.md C2 | precision 1.0 | "precision 1.0" in C2 core evidence | Replaced with §24 orientation: precision 0.533, recall 1.0 | FIXED commit 2a69ab3 |
| 5 | research/TKDE_STRUCTURAL_POLICY_POSITIONING.md §5 | precision 1.0 | "precision 1.0" in approved claims | Updated to necessary-but-not-sufficient wording | FIXED commit 2a69ab3 |
| 6 | paper/sections/related.tex (new v4) | "RAG-on-a-Diet" | Spec references it as Chen et al. 2024 | NOT FOUND on arXiv by any search method; replaced with verified class discussion (PAGE-RAG, Know Before You Fetch) | FIX: no fabricated citation |
| 7 | paper/sections/related.tex (new v4) | "first" claims | None present | Clean — no first/novelty claims in v4 draft | VERIFIED CLEAN |
| 8 | paper/sections/related.tex (new v4) | SOTA | None present | Clean — no SOTA comparisons in v4 draft | VERIFIED CLEAN |
| 9 | paper/sections/intro.tex (new v4) | "true dependency depth" / "complete dependency" / "producer-consumer DAG" | None present | Clean — using "typed evidence requirements, joins, operators, structural coupling" | VERIFIED CLEAN (§25) |
| 10 | paper/sections/threats.tex (new v4) | "structure gate independently validated" | Not claimed | Correctly: "empirically motivated but not independently confirmed" | VERIFIED CLEAN |
| 11 | paper/sections/results.tex (new v4) | H-STRUCT-4 as negative result | Not framed as negative result | Correctly: "could not be executed" — infrastructure limitation, not method failure | VERIFIED CLEAN |
| 12 | paper/sections/analysis.tex (new v4) | "universally" harm | Not claimed | "on average, flat allocation harms the shallow exploratory stratum, with the effect concentrated primarily in 2WikiMultiHopQA" | VERIFIED CLEAN |
| 13 | old paper/tkde_writing/abstract.tex | chain-law as contribution | "dependency-sensitive importance law" / "τ = 2d-1" as headline | Removed — chain is ablation in v4 | LEGACY FILE, not in v4 |
| 14 | old paper/sections/results.tex (old Coverage paper) | "selection ceilings" / Coverage narrative | Entire paper | Replaced with v4 structural-budget-feasibility narrative | COMPLETELY REPLACED |

**Total overclaims found and corrected**: 5 (precision/recall orientation ×4, fabricated citation ×1)
**Total clean**: 9 patterns verified clean in v4 draft
**Legacy issues**: 2 items in old tkde_writing/ (superseded by v4)
