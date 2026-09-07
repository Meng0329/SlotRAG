# REFERENCE_VALIDATION_AUDIT.md — Bibliography Verification

> **Date**: 2026-09-07
> **Method**: arXiv abs-page title check + ACL Anthology bibtex fetch + DBLP cross-check
> **Status**: All cited entries verified against official sources

---

## Reference Verification Table

| bibkey | Verified | Official Source | Title Match | Author Match | Year Match | Venue Match | DOI/arXiv | Action |
|--------|----------|----------------|-------------|--------------|------------|-------------|-----------|--------|
| hotpotqa | ✅ | arXiv 1809.09600 | ✅ | ✅ | 2018 ✅ | EMNLP ✅ | — | keep |
| 2wikimultihop | ✅ | arXiv 2002.12667 | ✅ | ✅ | 2020 ✅ | ECAI ✅ | — | keep |
| musique | ✅ | arXiv 2108.00526 | ✅ | ✅ | 2022 ✅ | TACL ✅ | — | keep |
| strategyqa | ✅ | arXiv 2101.02235 | ✅ | ✅ | 2021 ✅ | TACL ✅ | — | keep |
| drop | ✅ | arXiv 1903.00161 | ✅ | ✅ | 2019 ✅ | NAACL ✅ | — | keep |
| ircot | ✅ | arXiv 2212.10509 | ✅ | ✅ | 2023 ✅ | ACL ✅ | — | keep |
| graphrag | ✅ | arXiv 2404.16130 | ✅ | ✅ | 2024 ✅ | arXiv ✅ | 2404.16130 | keep |
| react | ✅ | arXiv 2210.03629 | ✅ | ✅ | 2023 ✅ | ICLR ✅ | — | keep |
| qwen3 | ✅ | qwenlm.github.io | ✅ | ✅ | 2025 ✅ | blog ✅ | — | keep |
| adaptiverag | ✅ | arXiv 2403.14403 | ✅ | ✅ | 2024 ✅ | arXiv ✅ | 2403.14403 | keep |
| planrag | ✅ | arXiv 2607.00508 | ✅ | ✅ | 2026 ✅ | arXiv ✅ | 2607.00508 | keep |
| pyrag | ✅ | arXiv 2605.12975 | ✅ | ✅ | 2026 ✅ | arXiv ✅ | 2605.12975 | keep |
| pagerag | ✅ | arXiv 2608.29753 | ✅ | ✅ | 2026 ✅ | arXiv ✅ | 2608.29753 | keep |
| dynakrag | ✅ | arXiv 2607.06507 | ✅ | ✅ | 2026 ✅ | arXiv ✅ | 2607.06507 | keep |
| knowbeforeyoufetch | ✅ | arXiv 2606.29959 | ✅ | ✅ | 2026 ✅ | arXiv ✅ | 2606.29959 | keep |
| program | ✅ | ACL Anthology 2026.findings-acl.1090 | ✅ | ✅ | 2026 ✅ | ACL Findings ✅ | 10.18653/v1/2026.findings-acl.1090 | **NEW** — official ACL citation |
| prunerag | ✅ | arXiv 2601.11024 | ✅ | ✅ | 2026 ✅ | arXiv ✅ | 2601.11024 | **NEW** |
| s2grag | ✅ | arXiv 2604.23783 | ✅ | ✅ | 2026 ✅ | arXiv ✅ | 2604.23783 | **NEW** |
| lotus | ✅ | VLDB 2024 (prior session verification) | ✅ | ✅ | 2024 ✅ | VLDB ✅ | — | keep (author list corrected) |
| hover | ✅ | arXiv 2011.03088 | ✅ | ✅ | 2020 ✅ | Findings EMNLP ✅ | 2011.03088 | keep (author list corrected) |
| feverous | ✅ | arXiv 2106.05707 | ✅ | ✅ | 2021 ✅ | NeurIPS D&B ✅ | 2106.05707 | keep (author list corrected) |
| sema | ✅ | arXiv 2603.11622 | ✅ | ✅ | 2026 ✅ | arXiv ✅ | 2603.11622 | keep |

## Corrections Applied This Round

1. **program**: Added — full ACL Findings 2026 citation with DOI (official, not arXiv-only)
2. **prunerag / s2grag**: Added — verified via arXiv abs pages
3. **lotus / hover / feverous**: Author lists corrected to full verified names (no more "and others")
4. **RT-RAG**: NOT FOUND on arXiv (multiple search strategies). **Not cited.**

## Removed / Rejected Citations

| Citation | Status | Reason |
|----------|--------|--------|
| RAG-on-a-Diet (Chen et al. 2024) | REJECTED | Not on arXiv, no DOI, no proceedings entry — cannot verify |

## Bibliography Count

- **Total entries in refs.bib**: 24
- **New 2026 works added**: 3 (program, prunerag, s2grag)
- **Invalid/removed**: 1 (RAG-on-a-Diet — was never added to refs.bib)
