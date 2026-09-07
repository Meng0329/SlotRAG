# TKDE_SUBMISSION_READINESS_V1.md — Submission Readiness Checklist for TKDE Paper v4

> **Date**: 2026-09-07
> **Paper version**: v4 (complete rewrite)
> **Target venue**: IEEE TKDE

---

## Artifact Inventory

| # | Deliverable | Status | Notes |
|---|-------------|--------|-------|
| 1 | paper/main.tex + 11 sections + refs.bib | ✅ DONE | Compiles clean, 9 pages, zero undefined refs |
| 2 | PAPER_REWRITE_V4_CHANGELOG.md | ✅ DONE | Full changelog with before/after |
| 3 | PAPER_CLAIM_EVIDENCE_MATRIX.md | ✅ DONE | 16 claims × 6 columns |
| 4 | PAPER_OVERCLAIM_AUDIT.md | ✅ DONE | 14 patterns, 5 corrected, 9 clean |
| 5 | TKDE_BASELINE_GAP_AUDIT.md | ✅ DONE | 4 categories, 9 baselines classified |
| 6 | TKDE_RELATED_WORK_2026.md | ✅ DONE | 5 verified 2026 papers + 6 foundations |
| 7 | TKDE_SUBMISSION_READINESS_V1.md | ✅ DONE | This file |

## Checklist

### Content
- [x] Three contributions clearly stated (C1, C2, C3)
- [x] Chain importance demoted to ablation (§7.3, p=0.743)
- [x] §24 confusion matrix: precision=0.533, recall=1.0 (not reversed)
- [x] §25 C1 terminology: no "true dependency depth" etc.
- [x] H-STRUCT-4 in threats (§8), not appendix
- [x] No SOTA claims, no "first adaptive RAG" claims
- [x] Evidence taxonomy explicit: CONFIRMATORY / EXPLORATORY / INFEASIBLE
- [x] 5 focused RQs (not 9 RQ流水账)
- [x] Related work covers Adaptive-RAG, RAG-on-a-Diet class, PlanRAG, budget-aware
- [x] Comparison table: 6 methods × 5 dimensions

### Statistical Integrity
- [x] All numbers verified against source CSVs
- [x] No fabricated F1 values
- [x] No fabricated cost values
- [x] McNemar test correctly reported (discordant pairs b=30/c=3)
- [x] Population effect ATE correctly derived
- [x] Evidence levels explicitly distinguished (CONFIRMATORY vs EXPLORATORY)

### Citations
- [x] No fabricated citations
- [x] RAG-on-a-Diet dropped (unverifiable)
- [x] Adaptive-RAG ID corrected (2403.14403, not 2310.11511)
- [x] All arXiv IDs verified via API

### LaTeX
- [x] Compiles with zero undefined references
- [x] acmart sigconf class (IEEEtran not available)
- [x] No algorithm.sty dependency (inline pseudocode)
- [x] 9 pages (target: 12–15 double-column; expandable with figures)

### Open Items (not blockers)
- [ ] Figures: no actual figures generated yet (text placeholders only)
- [ ] Author list: fifth author has no institution (benign warning)
- [ ] Expansion to 12–15 pages requires figures + expanded discussion
- [ ] External baseline comparison under matched conditions (out of scope per frozen protocol)
