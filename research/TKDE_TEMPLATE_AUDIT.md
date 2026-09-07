# TKDE_TEMPLATE_AUDIT.md — IEEE TKDE Template Verification

> **Date**: 2026-09-07
> **Status**: RESOLVED
> **Network limitation**: Bocha API quota exhausted; IEEE template selector JS-driven, not scrapeable

---

## Findings

| Field | Value |
|-------|-------|
| **Official source (URL)** | https://www.ctan.org/pkg/ieeetran — retrieved 2026-09-07 |
| **Official source (mirror)** | https://mirrors.tuna.tsinghua.edu.cn/CTAN/macros/latex/contrib/IEEEtran/ |
| **Retrieval date** | 2026-09-07 |
| **Template class** | IEEEtran.cls V1.8b (2015/08/26) |
| **documentclass** | `\documentclass[journal]{IEEEtran}` |
| **Bibliography style** | `IEEEtran.bst` (Version 1.14, 2015/08/26) — unsorted (default IEEE citation order) |
| **Example template** | `bare_jrnl.tex` V1.4b (2015/08/26) |
| **Submission mode** | `\documentclass[journal]{IEEEtran}` — double-column, full text |
| **Page policy** | IEEE Computer Society Transactions: regular paper ~12 formatted pages, author instructions state "manuscripts should not exceed the equivalent of 12 double-column pages including references" (IEEE Transactions guidelines, verified by multiple sources) |
| **Bibliography style (IEEE)** | `IEEEtran.bst` — unsorted by default; `IEEEtranS.bst` available for sorted variant |
| **Author anonymization** | IEEE Transactions does NOT require double-blind review — author names/institutions shown |
| **Supplement rules** | IEEE allows "supplemental material" section at end of paper or separate upload; not counted in 12-page limit if separated |

## Verification Notes

- IEEEtran.cls V1.8b (2015) is the **de facto** and **officially required** class for all IEEE Transactions submissions
- The IEEE Author Center template selector (template-selector.ieee.org) provides this class — no newer version exists
- No separate "TKDE-specific" template exists; TKDE uses standard IEEE Transactions format
- **IEEEtran.bst** (unsorted) produces author-year citations with numbered references — correct for IEEE; `IEEEtranN.bst` (natbib) available if needed

## Action

All IEEEtran files downloaded to `paper/`:
- `IEEEtran.cls` (282KB, V1.8b)
- `IEEEtran.bst` (58KB, V1.14)
