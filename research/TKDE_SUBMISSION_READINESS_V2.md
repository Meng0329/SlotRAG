# TKDE_SUBMISSION_READINESS_V2.md — Final Submission Audit

> **Date**: 2026-09-07
> **Paper**: v4 in IEEEtran `[journal]` format, 10 pages
> **Status**: READY WITH LIMITATIONS

---

## Checklist

### Template
- [x] Correct IEEE template: `IEEEtran` V1.8b `\documentclass[journal]{IEEEtran}`
- [x] Official source verified: CTAN `ieeetran` package (2015/08/26)
- [x] `IEEEtran.bst` V1.14 bibliography style
- [x] Template audit documented: `research/TKDE_TEMPLATE_AUDIT.md`

### Content Alignment
- [x] Title: "SlotRAG: Budget-Feasible Physical Planning over Typed Evidence Plans for Multi-Hop RAG"
- [x] Abstract: three contributions stated, honest about H-STRUCT-4 limitation
- [x] C1/C2/C3 aligned with evidence
- [x] Confusion matrix orientation correct: precision=0.533, recall=1.0
- [x] H-STRUCT-4 INFEASIBLE correctly positioned in §8 Threats
- [x] No SOTA claims, no "first adaptive RAG" claims
- [x] Chain importance correctly positioned as ablation only (§7.3)
- [x] Model: correctly reported as `qwen3.5-9b` throughout

### Evidence Labels
- [x] CONFIRMATORY (H-STRUCT-1/2, n=350)
- [x] EXPLORATORY (H-STRUCT-3, n=8,632)
- [x] INFEASIBLE (H-STRUCT-4, zero execution)

### Old-Story Contamination Check
- [x] "25% Coverage" — NOT present in paper
- [x] "Qwen3.6-27B" — NOT present in paper
- [x] Old 4-call main protocol — NOT present in paper
- [x] "SLAM-Style" — NOT present in paper
- [x] "Coverage Ceilings" — NOT present in paper

### References
- [x] 24 entries in `refs.bib`
- [x] All verified via arXiv / ACL Anthology / official sources
- [x] PROGRAM: official ACL Findings 2026 citation with DOI
- [x] PruneRAG (2601.11024), S2G-RAG (2604.23783) added
- [x] RT-RAG: NOT cited (not found on arXiv — documented)
- [x] RAG-on-a-Diet: NOT cited (unverifiable — documented)
- [x] Reference validation audit: `research/REFERENCE_VALIDATION_AUDIT.md`

### Figures
- [x] Figure 1 (system overview): `paper/figures/system_overview.pdf`
- [x] Figure 2 (budget mismatch + confusion matrix): `paper/figures/budget_mismatch.pdf`
- [x] Figure 3 (structural regime effect): `paper/figures/regime_effect.pdf`
- [x] Figure 4 (three-arm ablation): `paper/figures/three_arm_ablation.pdf`
- [x] All 4 figures referenced in paper text
- [x] All 4 render in compiled PDF

### Tables
- [x] Positioning table (resizebox, no overfull)
- [x] Confusion matrix table (resizebox, no overfull)
- [x] Deep results table, ablation table, shallow table, gate table

### LaTeX Compilation
- [x] `pdflatex → bibtex → pdflatex × 2`: PASS
- [x] Undefined references: **0**
- [x] Undefined citations: **0**
- [x] Multiply-defined labels: **0**
- [x] Overfull boxes: **0**
- [x] Page count: **10 pages**, 406KB

### Page Policy
- [x] IEEE CS Transactions: regular paper ~12 pages
- [x] Current 10 pages: acceptable (content complete, no padding)
- [x] Supplement candidates identified: `research/TKDE_PAGE_BUDGET.md`

### Repository State
- [x] Branch: `main`
- [x] HEAD: `426e1a8`
- [x] All Phase 0-22 changes on local `main`
- [x] Paper source: `paper/main.tex` (sole entrypoint)
- [x] Old paper archived: `paper/archive/tkde_writing/`
- [x] Old-story contamination: NONE
- [x] **NOT PUSHED**: GitHub HTTPS unreachable from this environment; push must be retried when network available

### Audit Trail Documents
1. `research/PAPER_SOURCE_OF_TRUTH_AUDIT.md`
2. `research/TKDE_TEMPLATE_AUDIT.md`
3. `research/TKDE_PAGE_BUDGET.md`
4. `research/REFERENCE_VALIDATION_AUDIT.md`
5. `research/PAPER_OVERCLAIM_AUDIT.md`
6. `research/TKDE_BASELINE_GAP_AUDIT.md`
7. `research/TKDE_RELATED_WORK_2026.md`
8. `research/PAPER_CLAIM_EVIDENCE_MATRIX.md`
9. `research/PAPER_REWRITE_V4_CHANGELOG.md`
10. `research/TKDE_SUBMISSION_READINESS_V2.md`

## Known Limitations

1. **Not pushed to origin**: GitHub HTTPS connection failed in this environment; 2 prior rewrite commits + all new changes remain local only.
2. **9→10 pages**: below 12-page target — acceptable per spec §8, only reviewer-required content should be added.
3. **No independent shallow confirmation**: H-STRUCT-4 INFEASIBLE; shallow gate benefit supported only by exploratory trace.
4. **Single generator**: qwen3.5-9b only.
5. **No external baseline under matched conditions**: different decision points prevent fair direct comparison.
