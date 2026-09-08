# TKDE_PORTAL_CHECKLIST.md — Submission Portal Steps

> **Date**: 2026-09-08
> **Workflow**: IEEE Author Center / ScholarOne for IEEE TKDE

---

## Pre-submission gate

- [ ] **BLOCKING**: Fill `research/AUTHOR_METADATA_CHECKLIST.md` (real author names, affiliations, ORCID)
- [ ] Replace `\author{Anonymous Author(s)}` in `paper/main.tex` with real author block
- [ ] Regenerate `paper/main.pdf`
- [ ] Run IEEE PDF Checker on final PDF
- [ ] Run IEEE Reference Preparation Assistant on `refs.bib`

## Portal steps (in order)

| # | Step | Value / File |
|---|------|--------------|
| 1 | Article type | Regular Paper (full research) |
| 2 | Title | "SlotRAG: Budget-Feasible Physical Planning over Typed Evidence Plans for Multi-Hop Retrieval-Augmented Generation" |
| 3 | Abstract | `submission/abstract.txt` (hash-verified) |
| 4 | Keywords | `submission/keywords.txt` (7 terms) |
| 5 | Authors | from AUTHOR_METADATA_CHECKLIST (order fixed) |
| 6 | ORCID | each author's ORCID (mandatory at publication) |
| 7 | Affiliations | from AUTHOR_METADATA_CHECKLIST |
| 8 | Corresponding author | exactly one, with institutional email |
| 9 | Cover letter | `submission/cover_letter.txt` |
| 10 | Manuscript PDF | `paper/main.pdf` |
| 11 | Source files | `paper/main.tex`, `paper/sections/`, `paper/refs.bib`, `.cls`, `.bst` |
| 12 | Figures | 4 PDF files (or embedded in PDF) |
| 13 | Supplement | `supplement/supplement.pdf` + `supplement/README.md` |
| 14 | Conflicts / suggested reviewers | per `REVIEWER_SELECTION_GUIDE.md` (manual) |
| 15 | OA/traditional choice | per institution policy |
| 16 | Declarations | confirm original work, not under review elsewhere, all authors approved |
| 17 | Final generated PDF verification | re-download, confirm page count + fonts |

## Post-submission

- [ ] Record manuscript number
- [ ] Do NOT upload `research/` docs or `runs/` artifacts
- [ ] Do NOT upload `main_anonymous.tex`
