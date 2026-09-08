# SUBMISSION_PRIVACY_SCAN.md — Secret / Privacy Scan

> **Date**: 2026-09-08
> **Scope**: `submission/`, `paper/` (source + compiled), `supplement/`

---

## Scan patterns

Searched for: API keys (`ghp_`, `sk-`, `bearer`), tokens, private endpoints,
server IPs, usernames, absolute local paths (`/home/`, `/data/`, `/tmp/`),
personal emails (if anonymous version), LLM provider secrets, internal
organization names.

## Results

| Directory | Findings | Status |
|-----------|----------|--------|
| `paper/sections/*.tex` | 0 | ✅ CLEAN |
| `paper/main.tex` | 0 | ✅ CLEAN |
| `paper/main_anonymous.tex` | 0 | ✅ CLEAN |
| `paper/refs.bib` | 0 | ✅ CLEAN |
| `submission/*` | 0 | ✅ CLEAN |
| `supplement/*` | 0 | ✅ CLEAN |

## Confirmations

- No `ghp_` GitHub tokens in any submission file
- No Bocha/Agnes API keys (`sk-...`) in submission or paper files
- No `http://` provider endpoints hardcoded in paper/supplement/cover letter
- No absolute local paths in any text
- No real author names/emails (anonymous draft uses placeholder only)
- No internal organization name disclosed

## Residual notes

- `paper/figures/gen_all_figs.py` contains no paths outside `paper/figures/`
- The root repo `.env` (gitignored) holds real credentials but is NOT part of
  the submission package and is excluded from `slotrag_tkde_source.zip`
- The git remote URL embeds a `ghp_` token — the ZIP excludes `.git/`, but
  authors should rotate this token before/after submission for hygiene

**Final: 0 secrets found in submission package.**
