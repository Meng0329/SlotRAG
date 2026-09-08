# SUBMISSION_MANIFEST.md — What Goes to the TKDE Portal

> **Date**: 2026-09-08
> **Rule**: The `research/` directory is INTERNAL PROVENANCE. Do NOT upload its
> dozens of audit documents as submission supplement.

---

## MAIN

| File | Description |
|------|-------------|
| `paper/main.pdf` | Submission manuscript (10 pages) — must carry real author block |

## SOURCE

| File | Description |
|------|-------------|
| `paper/main.tex` | Sole submission entrypoint |
| `paper/sections/*.tex` | Content sections |
| `paper/refs.bib` | Bibliography (24 entries) |
| `paper/IEEEtran.cls` / `paper/IEEEtran.bst` | IEEE journal class + style |
| `paper/main_anonymous.tex` | **INTERNAL ONLY** — do not upload |

## FIGURES

| File | Description |
|------|-------------|
| `paper/figures/system_overview.pdf` | Fig. 1 |
| `paper/figures/budget_mismatch.pdf` | Fig. 2 |
| `paper/figures/regime_effect.pdf` | Fig. 3 |
| `paper/figures/three_arm_ablation.pdf` | Fig. 4 |

## SUPPLEMENT

| File | Description |
|------|-------------|
| `supplement/supplement.pdf` | Supplementary document (2 pages) |
| `supplement/README.md` | Supplement README |

## OPTIONAL

| File | Description |
|------|-------------|
| `submission/slotrag_tkde_source.zip` | Source archive (builds standalone) |

## EXCLUDED

- `research/` — internal provenance, ledgers, audit docs (never upload)
- `runs/`, `runs_archive/` — experiment artifacts (gitignored, huge)
- `benchmark/` — downloaded datasets (gitignored)
- `.env`, API keys, credentials
- `.git/`, caches, model outputs

## TEXT FILES (typed into portal)

| File | Description |
|------|-------------|
| `submission/cover_letter.txt` | Cover letter |
| `submission/abstract.txt` | Abstract (hash-verified against main.tex) |
| `submission/keywords.txt` | Keywords / index terms |

## SUBMISSION METADATA (portal forms)

| File | Description |
|------|-------------|
| `submission/TKDE_PORTAL_CHECKLIST.md` | Portal entry checklist |
| `submission/REVIEWER_SELECTION_GUIDE.md` | Reviewer criteria (no names) |
| `research/AUTHOR_METADATA_CHECKLIST.md` | Author fields (BLOCKING: TODO) |
