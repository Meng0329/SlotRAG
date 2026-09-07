# PAPER_SOURCE_OF_TRUTH_AUDIT.md — Submission Entrypoint Audit

> **Date**: 2026-09-07
> **Status**: VERIFIED

---

## Source-of-Truth Audit

### Git State

| Item | Value |
|------|-------|
| HEAD | `426e1a8` |
| origin/main | `2a69ab3` |
| `8c7e1ac` exists | YES (commit object) |
| `426e1a8` exists | YES (commit object) |
| `8c7e1ac` reachable from HEAD | YES (ancestor of HEAD) |
| `8c7e1a8` reachable from origin/main | NO — **NOT PUSHED** |
| `426e1a8` reachable from HEAD | YES (HEAD itself) |
| `426e1a8` reachable from origin/main | NO — **NOT PUSHED** |
| HEAD ahead of origin/main | 2 commits (8c7e1ac, 426e1a8) |
| GitHub remote reachable | NO (github.com port 443 timeout) |

**Root cause**: `git push origin main` failed silently in previous session due to GitHub HTTPS connectivity failure (timeout, likely network/VPN issue). Commits exist only locally.

### Paper Entrypoint Inventory

| Path | Git Status | Last Commit | Title | documentclass | Old/New Storyline | Is Submission Entrypoint |
|------|-----------|-------------|-------|---------------|-------------------|--------------------------|
| `paper/main.tex` | Modified (uncommitted on top of 8c7e1ac) | 8c7e1ac 2026-09-07 | "SlotRAG: Budget-Feasible Physical Planning over Typed Evidence Plans for Multi-Hop RAG" | `[sigconf]{acmart}` (NEW) | **NEW**: typed evidence plans + feasibility diagnosis + structure-gated planning | **YES — PRIMARY** |
| `paper/tkde_writing/main.tex` | Unmodified | pre-rewrite | Chain-law / SLAM-Style / Coverage narrative | `[sigconf]{acmart}` | **OLD**: chain importance as contribution, Coverage headline | **NO — legacy** |

**Answer**: `paper/main.tex` is the sole submission entrypoint. `paper/tkde_writing/main.tex` is the old chain-law draft, superseded.

---

## Branch Divergence Audit

### `research/tkde-evidence-execution` branch

- Points to `de42293` (differs from `main`)
- 11 commits ahead of an older merge-base (the pre-v4 rewrite era)
- Commits contain the old paper edits (harsh review responses, §8 rewrites, Holm rounding fixes)
- **Not merged into main** — these edits are superseded by the v4 rewrite
- Contains old manuscript text (Coverage narrative, chain-as-contribution)

**Action**: DO NOT merge. Old branch artifacts are superseded by v4. Archive only.

### `research/phase0-audit` branch

- Points to `d675aa1`
- 1 commit on old merge-base
- Config additions only — not paper-related

---

## Files on Main (unpushed)

| File | Status | Content |
|------|--------|---------|
| `paper/main.tex` | M (unstaged) | v4 rewrite — correct content |
| `paper/refs.bib` | M | Verified bibliography only |
| `paper/sections/*.tex` | A/M/D | New v4 sections (algebra, analysis, dispatch, optimizer, problem, protocol, threats) |
| `research/PAPER_OVERCLAIM_AUDIT.md` | A | 14-pattern overclaim scan |
| `research/TKDE_BASELINE_GAP_AUDIT.md` | A | 4-category baseline classification |
| `research/TKDE_RELATED_WORK_2026.md` | A | Verified 2026 literature |
| `research/PAPER_CLAIM_EVIDENCE_MATRIX.md` | A | 16-claim evidence traceability |
| `research/PAPER_REWRITE_V4_CHANGELOG.md` | A | Full changelog |
| `research/TKDE_SUBMISSION_READINESS_V1.md` | A | Submission checklist |
| `research/PAPER_CONTRIBUTIONS_V3.md` | M | Updated with paper cross-references |
| `research/TKDE_STRUCTURAL_POLICY_POSITIONING.md` | M | Updated with paper cross-references |
| `research/STATE.md` | M (unstaged) | Confusion matrix fix |

**All v4 content exists only locally. Must push when network is available.**
