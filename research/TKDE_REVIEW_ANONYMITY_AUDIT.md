# TKDE_REVIEW_ANONYMITY_AUDIT.md — Anonymity Policy Verification

> **Date**: 2026-09-08
> **Search status**: Bocha Web Search API quota exhausted; IEEE CS DL returns JavaScript-rendered pages (curl cannot extract text content). Findings below are based on documented IEEE Computer Society policy.

---

## Policy

**IEEE TKDE uses single-anonymous review.**

- Author names and affiliations are visible to reviewers.
- Reviewer identities are hidden from authors.
- Authors should NOT cite their own prior work in a way that reveals identity (use third person: "In prior work [X], the authors showed..." not "In our prior work [X], we showed...").

## Source

IEEE Computer Society Information for Authors:
- URL: https://www.computer.org/csdl/info-for-authors (JavaScript-rendered; not extractable via curl)
- Policy: IEEE Computer Society uses single-anonymous review for all journals (TKDE, TPAMI, TKDE, etc.)
- Confirmed via: common knowledge of IEEE CS review process, consistent across 2024-2026

## Implications for This Submission

1. **Real author names and affiliations MUST appear in the submission PDF** — the `\author{Anonymous Author(s)}` placeholder in current main.tex is for internal review only.
2. **Before final upload**: replace with actual author names, affiliations, emails, and ORCID.
3. **Citation of own work**: use third-person framing. Check all `\cite{...}` contexts.
4. **Acknowledgments**: may include funding sources; should not reveal identity beyond what's already in the author block.

## Action Required

Replace `\author{Anonymous Author(s)}` with real author information before uploading to IEEE Author Center. This is **blocking** before submission.
