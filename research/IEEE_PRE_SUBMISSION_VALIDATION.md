# IEEE_PRE_SUBMISSION_VALIDATION.md — Pre-Submission Validation Record

> **Date**: 2026-09-08
> **Paper**: v4 IEEEtran `[journal]`, final revision `3009551`

---

## LaTeX compile

| Check | Result |
|-------|--------|
| `pdflatex main` | PASS |
| `bibtex main` | PASS |
| `pdflatex main` ×2 | PASS |
| Undefined references | 0 |
| Undefined citations | 0 |
| Multiply-defined labels | 0 |
| Overfull/underfull boxes | 0 |
| Warnings | 0 |
| Page count | 10 pages |
| PDF size | ~407 KB |

## PDF / fonts

| Check | Result |
|-------|--------|
| Embedding all fonts | TBD at IEEE PDF Checker (pdflatex embeds Type-1 fonts by default) |
| Graphics | 4 vector PDFs, embedded fonts |
| Page dimensions | IEEEtran journal letter-size standard |
| File size | 407 KB (well within typical 10 MB limit) |

## References

| Check | Result |
|-------|--------|
| Bibliography entries | 24 (verified in `REFERENCE_VALIDATION_AUDIT.md`) |
| IEEEtran.bst V1.14 | PASS |
| Citation format | IEEE numeric, official DOIs where available |
| Reference Preparation Assistant | run before upload |

## Tools

- IEEE LaTeX Analyzer: `paper/` source conforms to IEEEtran `[journal]` class
- IEEE PDF Checker: run `main.pdf` at upload time
- IEEE Reference Preparation Assistant: run `refs.bib` at upload time

## Notes

- The IEEE LaTeX Analyzer and PDF Checker are web tools at the IEEE Author
  Center; final validation must be run at upload time with the finished PDF.
- Anonymous draft (`main_anonymous.tex`) must NOT be uploaded; it is
  internal-only. The submission PDF must carry real author metadata
  (single-anonymous review).
