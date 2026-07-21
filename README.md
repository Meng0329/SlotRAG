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
