# REFERENCE_FINAL_VALIDATION.md — Reference Final Pass

> **Date**: 2026-09-08
> **Pass**: Final pre-submission verification of all `refs.bib` entries.

---

## Count correction

**22 bibliography entries** (not 24). The earlier "24" figure in
`TKDE_SUBMISSION_READINESS_V2.md` and `REFERENCE_VALIDATION_AUDIT.md` was a
miscount; the audit table itself lists exactly 22 keys. Corrected here.

## Entry verification

All 22 entries verified against official sources in the prior pass
(`REFERENCE_VALIDATION_AUDIT.md`). This pass re-confirms: official titles,
authors, years, and venue/DOI where available.

| bibkey | Type | Venue | DOI/ID verified |
|--------|------|-------|-----------------|
| hotpotqa | inproceedings | EMNLP | arXiv 1809.09600 |
| 2wikimultihop | inproceedings | ECAI | arXiv 2002.12667 |
| musique | inproceedings | TACL | arXiv 2108.00526 |
| strategyqa | inproceedings | TACL | arXiv 2101.02235 |
| drop | inproceedings | NAACL | arXiv 1903.00161 |
| ircot | inproceedings | ACL | arXiv 2212.10509 |
| graphrag | article | arXiv | 2404.16130 |
| react | inproceedings | ICLR | arXiv 2210.03629 |
| qwen3 | misc | Qwen blog | qwenlm.github.io |
| adaptiverag | article | arXiv | 2403.14403 |
| planrag | article | arXiv | 2607.00508 |
| pyrag | article | arXiv | 2605.12975 |
| pagerag | article | arXiv | 2608.29753 |
| dynakrag | article | arXiv | 2607.06507 |
| knowbeforeyoufetch | article | arXiv | 2606.29959 |
| program | inproceedings | ACL Findings 2026 | 10.18653/v1/2026.findings-acl.1090 |
| prunerag | article | arXiv | 2601.11024 |
| s2grag | article | arXiv | 2604.23783 |
| lotus | inproceedings | VLDB | verified |
| hover | inproceedings | Findings EMNLP | 2011.03088 |
| feverous | inproceedings | NeurIPS D&B | 2106.05707 |
| sema | article | arXiv | 2603.11622 |

## Notes

- One arXiv-only entry with an official version available: none blocked;
  `program` already upgraded to official ACL Findings with DOI.
- **RT-RAG** and **RAG-on-a-Diet**: intentionally NOT cited (unverifiable).
- Do not add references purely to inflate count — the 22 are the verified,
  actually-cited set.

## Pre-upload

Run the IEEE Reference Preparation Assistant on `refs.bib` at upload time.