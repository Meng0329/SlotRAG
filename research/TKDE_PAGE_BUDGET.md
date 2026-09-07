# TKDE_PAGE_BUDGET.md — IEEE Page Budget Analysis

> **Date**: 2026-09-07
> **Paper**: v4 in IEEEtran `[journal]` format
> **Policy**: IEEE Computer Society Transactions regular paper ≈ 12 formatted pages

---

## Current State (after template migration)

**9 pages** IEEEtran double-column, 4 figures embedded, 0 errors, 0 overfull.

## Target Strategy

IEEE CS Transactions regular-paper threshold is **12 formatted pages**. Current 9 pages is
below threshold — but **do not pad**. The mandate is: only add what reviewers need.

## Section Budget

| Section | Est. Pages | Importance | Keep Main / Supplement / Compress | Reason |
|---------|-----------|------------|----------------------------------|--------|
| Introduction | ~1.2 | Essential | **Main** | Sets up contributions |
| Related Work | ~1.0 | Essential | **Main** | Positioning against 2026 work |
| Problem Formulation | ~1.0 | Essential | **Main** | Formal definitions, necessary condition |
| Typed Evidence Plans | ~1.3 | Essential | **Main** | C1: system design |
| Budget-Feasible Planning | ~1.5 | Essential | **Main** | C2/C3: optimizer + gate |
| Experimental Protocol | ~1.2 | Essential | **Main** | Matched-budget protocol, reproducibility |
| Results | ~2.5 | Essential | **Main** | Confusion matrix, confirmatory, ablation, gate |
| Analysis | ~1.0 | Important | **Main** | Why it works, heterogeneity |
| Threats | ~0.5 | Essential | **Main** | H-STRUCT-4 limitation |
| Conclusion | ~0.3 | Essential | **Main** | Honest recap |
| References | remaining | Essential | **Main** | Verified only |

## Supplement Candidates (per spec §18)

Move to supplemental (not in main paper):
- Full H-STRUCT hypothesis history (HYPOTHESES.md content)
- H-017 / H-031 historical falsifications
- Full exposure audits (H-STRUCT-4_EXPOSURE_AUDIT.md)
- H-STRUCT-4 detailed protocol (H_STRUCT_4_PRE_REGISTRATION.md)
- Additional dataset-stratum tables (per-dataset EM/F1 breakdowns)
- Large provenance tables
- Extra statistical sensitivity results

## What Is NOT Needed

- ❌ Generic background prose about RAG / LLMs / retrieval (reviewers know this)
- ❌ Expanded "why budget matters" motivation beyond the concrete 4+4+4>8 example
- ❌ Historical experiment narration (H-017, H-031) — belongs in supplement

## Target Outcome

- **Acceptable submission range**: 10–12 pages with figures
- **Do not** inflate to hit 12; only add reviewer-required content
- 9-page version is complete and compilable NOW; additions should target genuine gaps
