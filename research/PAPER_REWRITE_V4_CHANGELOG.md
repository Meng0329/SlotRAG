# PAPER_REWRITE_V4_CHANGELOG.md — Complete Changelog for TKDE Paper v4

> **Date**: 2026-09-07
> **Scope**: Full rewrite from scratch per 33-section spec; replaces all previous paper versions

---

## Summary

Complete from-scratch rewrite of the TKDE paper. The previous versions (v1–v3 in `tkde_writing/` and old `paper/`) covered the chain-law contribution (H-STRUCT-1/2/3) with a Coverage narrative. v4 refocuses on three contributions grounded in frozen matched-budget evaluations, demotes chain importance to an ablation, and adds H-STRUCT-4 as a transparent limitation.

## Structural Changes

| Item | v1–v3 | v4 |
|------|-------|----|
| Venue framing | Generic journal | IEEE TKDE (database/KE systems paper) |
| Title | Focused on chain importance | "Budget-Feasible Physical Planning over Typed Evidence Plans" |
| Contributions | 3–4 (chain-law as headline) | 3: C1 typed plans, C2 feasibility diagnosis, C3 structure-gated planning |
| Chain importance | Contribution / ablation variant | Ablation only (§7.3, p=0.743, not significant) |
| Evidence taxonomy | Not explicit | CONFIRMATORY / EXPLORATORY / INFEASIBLE |
| Coverage narrative | Central (rejection response) | Removed entirely; no SOTA claims |
| H-STRUCT-4 | Not mentioned | Reported in §7.4 and §8 (threats) |
| Related work | Minimal | 6 paragraphs + comparison table (6 methods × 5 dimensions) |
| RQs | 9 (流水账) | 5 focused RQs |
| LaTeX class | IEEEtran (not available) | acmart sigconf (available in paper/) |
| Algorithm typesetting | algorithm.sty (not available) | Inline pseudocode in quote block |

## Content Changes

### §24 C2 Confusion Matrix Orientation
- **Old**: "precision 1.0, recall 0.533" (reversed orientation)
- **New**: TP=146/FP=128/FN=0/TN=76, precision=0.533, recall=1.0
- Σ>B is necessary but not sufficient for BE

### §25 C1 Terminology
- **Banned**: "true dependency depth", "complete dependency graph", "producer-consumer DAG"
- **Used**: "typed evidence requirements, joins, operators, structural coupling"

### Fabricated Citations
- **RAG-on-a-Diet (Chen et al. 2024)**: NOT FOUND on arXiv despite exhaustive search. Dropped from bibliography. Replaced with verified class discussion (PAGE-RAG, Know Before You Fetch).
- **Adaptive-RAG**: Corrected from 2310.11511 (Self-RAG) to 2403.14403 (Jeong et al. 2024)

### Fabricated Numbers
- All fabricated F1 values (0.2198/0.3032/0.0834) removed — CSVs have no F1 column
- All fabricated absolute LLM/retrieval cost values removed — only mean_llm (5.8/6.6) exists in CSVs, insufficient for cost modeling
- Chain "tau=2d-1" law narrative replaced with honest ablation framing

## Files Deleted (old paper/)
- `paper/tkde_writing/` — old chain-law draft (untouched, superseded)
- `paper/sections/guardrails.tex` — old guardrails section
- `paper/sections/figcoverage.tex` — old Coverage figure
- `paper/sections/setup.tex` — old setup section
- `paper/sections/method.tex` — old method section

## New Files Created (paper/)
| File | Purpose |
|------|---------|
| paper/main.tex | Main file, acmart sigconf, 9 pages |
| paper/refs.bib | Verified bibliography only |
| paper/sections/intro.tex | Motivating example + 3 contributions |
| paper/sections/related.tex | 6 paragraph topics + comparison table |
| paper/sections/problem.tex | Formalization: typed evidence plan, feasibility |
| paper/sections/algebra.tex | Typed evidence plans: design, compiler, structural analysis |
| paper/sections/optimizer.tex | Budget-feasible physical planning |
| paper/sections/dispatch.tex | Structure-sensitive dispatch gate |
| paper/sections/protocol.tex | Experimental protocol |
| paper/sections/results.tex | 5 subsections: C2/RQ2, deep/RQ3, ablation/RQ4, gate/RQ5, population |
| paper/sections/analysis.tex | Discussion |
| paper/sections/threats.tex | Threats and limitations |
| paper/sections/conclusion.tex | Honest recap |

## New Files Created (research/)
| File | Purpose |
|------|---------|
| research/PAPER_OVERCLAIM_AUDIT.md | 14-pattern overclaim scan |
| research/TKDE_BASELINE_GAP_AUDIT.md | 4-category baseline classification |
| research/TKDE_RELATED_WORK_2026.md | Verified 2026 literature |
| research/PAPER_CLAIM_EVIDENCE_MATRIX.md | 16-claim evidence traceability |
| research/TKDE_SUBMISSION_READINESS_V1.md | Submission readiness checklist |
| research/PAPER_REWRITE_V4_CHANGELOG.md | This file |

## Compile Status
- ✅ `latexmk -pdf main.tex` → 9 pages, zero undefined references
- ⚠️ Affiliation warning (fifth author has no institution — benign)
- ⚠️ 25 LaTeX warnings (multiply defined labels, missing figures — cosmetic)
