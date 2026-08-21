# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

SlotRAG-X is a **research prototype** (targeting PVLDB 2027), not a product. It benchmarks a slot-based, cost-aware evidence-materialization approach for multi-hop RAG against shared-provider adaptations of Hybrid RAG, IRCoT, ReAct, PlanRAG, SRAG, and GraphRAG. The experiments are governed by a frozen, pre-registered protocol; the deliverable is an honest, statistically-grounded results narrative plus a paper (`paper/`), not a library API. Treat the research rules in the next section as load-bearing — they are enforced by repo agents and embodied in ledgers.

Core idea: a question is compiled by an LLM into typed `Slot`s (predicates + variable arguments) joined together; the materializer retrieves/joins each slot's bindings into rows; the generator produces the answer under a structured answer contract; evidence sufficiency and a physical action policy decide when to stop retrieving. The method surface is continuously extended; a "WIN" only counts when it beats the strongest-frozen baseline per dataset×metric×budget cell.

## Quick start (repro)

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'   # pyproject.toml, src-layout
cp .env.example .env
set -a; . ./.env; set +a           # credentials are env-only
slotrag doctor --config configs/default.yaml   # check config + 3 services
```

The three external services (Agnes/qwen3.6-27b generation, Qwen3-Embedding-0.6B, bge-reranker-v2-m3) are reached only via env vars (`SLOTRAG_*_API_KEY/BASE_URL/MODEL`); endpoints/models are also overridable in YAML. `DOCTOR`/live tests need the services up.

## Commands

- **Tests** (offline): `make test` → `PYTHONPATH=src:. python3 -m pytest tests/ -x -q`. Single file: `PYTHONPATH=src:. python3 -m pytest tests/test_planner_bridge_fallback.py -x -q`. `pytest -m live` calls external providers — skip unless services are up and you mean it.
- **Datasets**: `python benchmark/download_datasets.py` fetches HotpotQA, 2WikiMultiHopQA, MuSiQue, StrategyQA, DROP into `benchmark/` (gitignored; SHA-256 audited into run manifests).
- **Benchmark lifecycle**: `slotrag benchmark audit|sample-audit|baseline-audit|records-audit|gate|prepare|run|summarize|factorial-analyze|paired-analyze|inspect-plan` plus `slotrag data fetch|normalize`. Typical flow: `prepare` (stratified deterministic samples) → `run` → `summarize`. Full public-suite example is in `README.md`; stage names are declared in `configs/experiments/*.yaml`.
- **Research ledger entry points** (Makefile): `make audit|budget|state|hypotheses|experiments|failures|decisions|sota|related` print the corresponding `research/` ledger.
- **Paper build**: LaTeX in `paper/` (`main.tex` + `sections/` + `figures/`), acmart class, compiled via latexmk; reproducible build note lives in STATE.md.

## Architecture

Python 3.11, src-layout, `slotrag` typer CLI in `src/slotrag/`. Config is pydantic (`config.py`) loaded from `configs/` YAML.

**Pipeline (execution-facing, `planner.py`, ~3900 lines):** `SlotCompiler` (LLM compiles a question into a typed slot+join plan) → `SlotMaterializer` (per-slot retrieval + binding, joins rows, applies typed relational `operators` — compare/extremum/polar), orchestrated by `AdaptiveExecutor`. Key supporting modules:
- `evidence_bundle.py`/`sufficiency.py` — evidence assembly and sufficiency calibration (when to stop retrieving).
- `binding.py` — `AdaptiveBindingBeam`; `query_optimization.py`/`qo.py` — physical plan + complementary query actions.
- `action_policy.py` — physical action policy; `models.py` — pydantic contracts (`Slot`, `SlotPlan`, `BindingRow`, `RelationalOperator`, `RunMetrics`, …).
- `retrieval.py` — `HybridRetriever` (BM25 + dense RRF + reranker); `providers.py` — service clients; `generation.py`/`tracing.py`/`concurrency.py` — generation, tracing, rate/parallel throttling.

**Benchmark facade (`src/slotrag/benchmarking/`):** the reproducible comparison harness. `runner.py` (`BenchmarkRunner`) persists every execution as an immutable attempt + atomic latest-result snapshot; `methods.py` holds the `METHODS` registry / `MethodSpec` (each slotrag method variant is a spec composing flags like `physical_plan`, `evidence_sufficiency`, `dual_access_bundle`, `question_grounded_retrieval`; baseline adaptations live here too). `datasets.py` defines the 5 datasets + downloads, `corpus.py` builds corpora, `metrics.py`/`statistics.py` produce paired bootstrap CIs, Cohen's d, Holm-adjusted tests, failure categories.

**Research process (`research/`, maintained by doc agents):** frozen protocol (`FROZEN_PROTOCOL.md`), current status (`STATE.md`), hypothesis pool + logs (`HYPOTHESES.md`, `H*_PRE_REGISTRATION.md`, `H*_FINAL_REPORT.md`), and ledgers (`EXPERIMENT_LEDGER.csv`, `FAILURE_LEDGER.csv`, `DECISIONS.md`, `SOTA_LEDGER.md`, `RELATED_WORK_MATRIX.csv`). `runs/` holds irreversible experiment artifacts; `runs_archive/` is archived historical runs (gitignored).

## Basic protocol rules (read `research/FROZEN_PROTOCOL.md` for the full, frozen text)

- The primary metric is **Strongest-Baseline Coverage** — a numbered WIN counts only if it strictly beats, at the dataset×metric×matched-budget cell, the strongest baseline that was *frozen before* results were seen. Baselines are compared under identical retrieval and call budgets.
- Per-dataset primary metrics: hotpotqa/2wiki/musique → EM & F1; strategyqa → accuracy; **drop → `drop_f1`** (SQuAD EM is ~0 for all methods on drop).
- "Leading" is graded: statistically-supported win (p<0.05, 95% CI excl. 0, d>0.2) > point-estimate win > tie > loss.
- Datasets split DEVELOPMENT/VALIDATION/TEST (30/30/40, seed=2027); samples are deterministic and stratified; interpretations must remain honest about Coverage denominators (multiple cells exist: 4 headlined vs 5 including non-win robust ties).

## Working notes

- Experiment configs live under `configs/experiments/` (e.g. `slotrag-phase3r-h*.yaml` tracks hypothesis-h), tuning under `configs/tuning/`, assumption variants under `configs/assumptions/`.
- Because results feed PVLDB claims, prefer updating the ledgers/STATE.md over ad-hoc claims, and keep Coverage honesty. When testing a new hypothesis, follow the H-pre-registration → run → H-final-report pattern.
- `.env`, `runs/`, downloaded datasets, and build artifacts are gitignored; ledgers/CSVs in `research/` are force-kept.