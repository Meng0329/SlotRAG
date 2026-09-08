# Supplementary Material — README

## Contents

- `supplement.tex` — LaTeX source
- `supplement.pdf` — compiled supplement (upload to IEEE Author Center as a separate file)

## File descriptions

| File | Description |
|------|-------------|
| `supplement.tex` | Source of the supplementary document |
| `supplement.pdf` | Compiled PDF (separate upload) |

## Main-paper mapping

| Supplement section | Main paper section |
|--------------------|--------------------|
| §1 Pre-registration history (H-STRUCT) | §6 Experimental Protocol; §7.5 H-STRUCT-4 |
| §2 Statistical protocol | §6 Experimental Protocol |
| §3 H-STRUCT-4 infeasible attempt | §7.5 Attempted independent confirmation; §10 Threats |
| §4 Extended dataset-stratum tables | §7.4 Structure-Gate Exploratory Analysis |
| §5 Additional failure analysis | §8 Analysis and Discussion |
| §6 Reproducibility and provenance | README.md |

## Software requirements

- TeX Live with `booktabs`, `amsmath`, `amssymb`, `graphicx`, `hyperref`
- Python 3.11 (for reproduction of main-paper analyses)

## Reproduction commands

```bash
cd supplement
pdflatex supplement && pdflatex supplement
```

## Expected outputs

`supplement.pdf` (~6 pages).

## Random seeds

Seed 2027 (bootstrap iterations, stratified sampling).

## Dataset acquisition

HotpotQA, 2WikiMultiHopQA, MuSiQue: see main `README.md` under
`benchmark/download_datasets.py`.

## Model dependencies

Main-paper results use Qwen3.5-9B (plan compilation and answer generation),
Qwen3-Embedding-0.6B (dense retrieval), and bge-reranker-v2-m3 (reranking).
External model/API access is required only for fresh pipeline execution; all
statistical analyses and figures reproduce from stored artifacts offline.

## Known limitations

- The supplement deliberately does not restate main conclusions (those are in
  the main paper).
- H-STRUCT-4 (independent shallow confirmation) was infeasible; this is
  documented in §3 and in the main paper's threats section.
