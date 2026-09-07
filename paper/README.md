# SlotRAG TKDE Paper — Submission Source

## CURRENT SUBMISSION SOURCE

```
paper/main.tex
```

IEEE TKDE submission, IEEEtran `[journal]` format (V1.8b), 10 pages double-column.

## Structure

| Path | Role |
|------|------|
| `main.tex` | **Submission entrypoint** (do not create another) |
| `sections/` | Content sections (intro … conclusion) |
| `figures/` | Publication figures (vector PDF + PNG preview) |
| `refs.bib` | Bibliography (verified only) |
| `IEEEtran.cls` / `IEEEtran.bst` | IEEE journal class + bibliography style |
| `archive/` | **Superseded** drafts (not submission sources) |

## Build

```bash
cd paper
pdflatex main
bibtex main
pdflatex main
pdflatex main
```

Requirements: pdflatex + bibtex (TeX Live), `booktabs`, `amsmath`, `amssymb`, `graphicx`, `url`.

## Archive Notice

`archive/tkde_writing/` is the pre-v4 chain-law draft (ACM sigconf format, Coverage narrative).
It is **NOT** a submission source and is kept only for provenance. Do not edit.
