# SlotRAG-TKDE — Artifact Reproducibility README

This document specifies how every number in the SlotRAG-TKDE paper's main
tables is independently reproduced from the frozen per-question attempt
records under `runs/`. No number in a paper table is trusted unless this
procedure reproduces it.

## 0. Integrity ground rules

- **Reproduction is from raw per-question records** (`runs/*/items/*/*/*.json`),
  never from summary files (which can be hand-edited or stale).
- The repository's `metrics.py` computes EM/F1; the reproduction scripts read
  the already-computed `scores.em` / `scores.f1` from each item record rather
  than re-deriving them, so a reproduction cannot silently disagree with the
  official scorer.
- A reproduction that yields different numbers than the paper is a **finding**,
  not an error to paper over.
- The `research/tkde-evidence-execution` branch is the paper branch; the main
  experiment runs it consumes are under `runs/tkde-g6`, `runs/tkde-g6-2wiki`,
  `runs/tkde-g11-musique`, and `runs/tkde-r11-baselines`.

## 1. Reproduce the main table

### G6 optimizer ablation (HotpotQA, DEVEL, n=20)

```bash
python tools/summarize_tkde_main_table.py \
  --run-dir runs/tkde-g6 --stage g6-effective --dataset hotpotqa \
  --arms slotrag-g7-static slotrag-g7-flat slotrag-g7-chain
```

Expected output (verified 2026-08-19):

```
slotrag-g7-static  19  52.6  0.65  2.95  -0.37  0.077  [-0.84,0.00]
slotrag-g7-flat    20  55.0  0.67  2.95  -0.20  0.080  [-0.45,0.00]
slotrag-g7-chain   20  55.0  0.67  2.75
```

These are the `tab:overall` HotpotQA rows (n=19 matched pair basis; the
static n=19 / flat n=20 / chain n=20 discrepancy is the one chain-ok but
static-missing sample, hash `5add695a…`).

### G6 optimizer ablation (2WikiMultiHopQA, DEVEL, n=20)

```bash
python tools/summarize_tkde_main_table.py \
  --run-dir runs/tkde-g6-2wiki --stage g6-effective --dataset 2wikimultihop \
  --arms slotrag-g7-static slotrag-g7-flat slotrag-g7-chain
```

Expected output (verified 2026-08-19): each arm n=19 on the matched-pair
basis (one sample, hash `b081e084…`, is `other` on all three arms and
excluded symmetrically), EM 57.9% / F1 0.69 for all arms; chain calls 2.47.

### G11 MuSiQue 3-hop

```bash
python tools/summarize_tkde_main_table.py \
  --run-dir runs/tkde-g11-musique --stage g11-musique-3hop --dataset musique \
  --arms slotrag-g7-static slotrag-g7-chain
```

### R1.1 external baselines (when complete)

```bash
python tools/summarize_tkde_main_table.py \
  --run-dir runs/tkde-r11-baselines --stage tkde-r11-baselines --dataset hotpotqa \
  --arms hybrid ircot react slotrag-g7-static slotrag-g7-chain
```

## 2. What is NOT reproduced by these scripts

- The **matched-budget frontier** figures (`fig:frontier`) — these aggregate
  2/2 validation chains; the reproduction is by inspection of the two stored
  item records, not by a table script.
- The **R1.4 multi-run variance** — requires re-running the experiment (see
  Section 4); it cannot be reconstructed from a single stored run.
- **Statistical test details** (Holm, McNemar) — recomputed independently in
  the scripts and cross-checked against `research/TKDE_ADVERSARIAL_REVIEW_LOOP.md`.

## 3. How to run a fresh experiment (e.g., R1.1 baselines)

```bash
# env: SLOTRAG_AGNES_BASE_URL / SLOTRAG_EMBEDDING_BASE_URL / SLOTRAG_RERANKER_BASE_URL
#      (see .env.example; doctor verifies all three)
set -a; . ./.env; set +a
.venv/bin/slotrag benchmark run \
  --config configs/default.yaml \
  --suite configs/experiments/tkde-r11-baselines.yaml \
  --output-dir runs/tkde-r11-baselines \
  tkde-r11-baselines
```

Matched budget: all arms run under `max_retrieval_calls: 8`; IRCoT/ReAct step
loops were patched (`methods.py`) to thread that budget so they share the same
ceiling as SlotRAG arms.

## 4. R1.4 multi-run variance protocol

R1.4 confirmed that **qwen3.6-27b is deterministic at temperature 0** on
identical (seed, sample) inputs: three independent runs of the same G6 config
produced zero EM/F1 variance across all three arms (see `research/R1_4_VARIANCE_REPORT.md`).

The experiment was run with three identical configs (seed 2027, n=10) to
three output dirs, using `/tmp/tkde-g6-run{1,2,3}.yaml`:

```bash
python tools/r14_variance.py \
  --runs runs/tkde-g6-r14-run1 runs/tkde-g6-r14-run2 runs/tkde-g6-r14-run3
```

This aggregate-only mode reads the three pre-existing dirs and reports
per-arm mean ± std (all zero). To re-run from configs:

```bash
python tools/r14_variance.py \
  --configs /tmp/tkde-g6-run1.yaml /tmp/tkde-g6-run2.yaml /tmp/tkde-g6-run3.yaml
```

**Boundary**: zero variance proves same-input determinism; it does NOT address
cross-seed sampling variance (different stratified samples across seeds), which
is a separate axis (candidate for R1.5 if the paper requires it).

## 5. Accounting disclosure (budget-exceeded asymmetry)

Two records in the matched-pair basis are budget-exceeded on the baseline
(static) arm and ok on the method (chain) arm. They are:

- **HotpotQA** `5add695a…`: static reached retrieval-call ceiling (8 calls),
  EM=0; chain solved within budget, EM=1. Symmetric pair excluded; matched-pair
  basis is n=19 (52.6%/52.6%); full-sample n=20 (50.0%/55.0%).
- **MuSiQue** `3hop1__406043…`: same pattern; matched-pair basis n=22
  (50.0%/45.5%); full-sample n=24 (45.8%/45.8%).

Both accounting conventions are disclosed in Section 7 (EX-P6). The
matched-pair rule is used throughout the paper; the full-sample alternative
is provided in the artifact README for completeness.
