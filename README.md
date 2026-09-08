# SlotRAG

SlotRAG is a research prototype for cost-aware, query-specific evidence
materialization in multi-hop retrieval-augmented generation. Its benchmark
facade compares SlotRAG with shared-provider adaptations of Hybrid RAG, IRCoT,
ReAct, PlanRAG, SRAG, and GraphRAG under identical retrieval and call budgets.

## Quick start

Use Python 3.11 and install the package in editable mode:

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
set -a; . ./.env; set +a
slotrag doctor --config configs/default.yaml
```

The service credentials are read only from environment variables. The default
endpoints and model names mirror the local API notes in `docs/` and can be
overridden in YAML or with environment variables.

## Public benchmark suite

The tracked downloader prepares HotpotQA, 2WikiMultiHopQA, MuSiQue,
StrategyQA, and DROP beneath `benchmark/`. Dataset files are ignored by Git;
the benchmark audit records their SHA-256 checksums in the run artifacts.

```bash
python benchmark/download_datasets.py
slotrag benchmark audit --output runs/pilot-v1/dataset-audit.json
slotrag benchmark prepare preflight --output-dir runs/pilot-v1
slotrag benchmark run preflight --output-dir runs/pilot-v1
slotrag benchmark summarize preflight --output-dir runs/pilot-v1
```

Stages are declared in `configs/experiments/pilot.yaml`: `preflight`, `smoke`,
`diagnostic`, `tune`, `ablations`, `validation`, and `final`. Samples are deterministic and
stratified. Every execution is persisted as an immutable attempt plus an atomic
latest-result snapshot, so rerunning the same command resumes unfinished work
without erasing failed attempts. Summaries include per-question, method,
stratum, and cross-dataset macro views; answer and evidence quality; planning,
execution, resource, and token/call cost proxies; failure categories; paired
bootstrap confidence intervals, effect sizes, and Holm-adjusted tests. Evidence
quality is reported as `N/A` for datasets without gold evidence labels.

## Paper Reproduction

The paper "SlotRAG: Budget-Feasible Physical Planning over Typed Evidence
Plans for Multi-Hop Retrieval-Augmented Generation" (IEEE TKDE submission,
source in `paper/`) is supported by frozen artifacts and offline analyses.

### Reproducibility boundary

| Boundary | What | How |
|----------|------|-----|
| **FULLY REPRODUCIBLE** from stored artifacts | statistics, offline replay, figures, confusion matrices | Python only, no network |
| **REQUIRES EXTERNAL MODEL/API** | fresh plan compilation, fresh RAG execution | needs Qwen3.5-9B, Qwen3-Embedding-0.6B, bge-reranker-v2-m3 + API keys |
| **HISTORICAL / NOT RECOMMENDED TO RE-RUN** | obsolete pilot experiments | read-only ledger records |

### Claim → command → output

| Claim (paper §) | Command | Expected output |
|-----------------|---------|-----------------|
| Confusion matrix / feasibility diagnosis (§7.2) | `python3 -c "..."` reading `research/hstruct_validation_census/validation_structural_census.csv` | TN=76, FP=128, FN=0, TP=146; recall=1.0, precision=0.533 |
| H-STRUCT-2 paired statistics (flat vs static, §7.3) | `python3 research/hstruct_validation_census/…/hstruct2_flat_results.csv` | ΔEM = +0.0771, 95% CI [+0.049, +0.109], p = 1.4e-6 |
| H-STRUCT-3 replay (gate, §7.4) | `python3 …/hstruct3_gate_test.csv` | shallow Δ = −0.021 (n=8,085); A' vs flat +0.0197 (n=8,632) |
| Figures (all 4) | `cd paper/figures && python3 gen_all_figs.py` | regenerates `*.pdf` from embedded frozen values |
| Paper build | `cd paper && pdflatex main && bibtex main && pdflatex main && pdflatex main` | `main.pdf`, 10 pages |

The full audit trail (pre-registrations, final reports, ledgers, review-game
audits) lives in `research/` and is the source of truth for the numbers
above. See `submission/SUBMISSION_MANIFEST.md` for what belongs in the
submission package (the `research/` directory is internal provenance, not
submission supplement).
