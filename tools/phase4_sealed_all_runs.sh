#!/usr/bin/env bash
# Continue all 4 remaining datasets' SEALED trace eval across 3 runs, SEQUENTIALLY.
# Fresh output dirs b1/b2/b3 each hold ONLY the 4 heavy datasets' samples (strategyqa excluded)
# to keep a single clean manifest per run (strategyqa already frozen in -trace/-r2/-r3).
# Global rate-limiter (runs/.rate-limits) shared → must not run concurrently.
#
# CRITICAL: this script must NOT modify git state (no commits during a run).
# The provenance guard (runner.py:1014) hashes code_revision; a mid-run git commit
# causes code_drift → RuntimeError → returncode 1 for remaining datasets.
set -uo pipefail
cd /data/mzb/SlotRAG
set -a; source .env; set +a

PY=.venv/bin/python
SUITE=configs/experiments/slotrag-phase4-tier3.yaml
CONFIG=configs/experiments/slotrag-phase4-trace.yaml
LOG_DIR=logs
mkdir -p "$LOG_DIR"

for R in slotrag-phase4-trace-b1 slotrag-phase4-trace-b2 slotrag-phase4-trace-b3; do
  echo "===== [$R] starting $(date -u '+%F %T') =====" | tee -a "$LOG_DIR/phase4-sealed-launcher.log"
  OUT="runs/$R"
  # NOTE: --dataset flags restrict which of the 5 configured datasets actually run.
  PYTHONPATH=src "$PY" tools/run_benchmark_matrix.py tier3_sealed \
    --suite "$SUITE" \
    --config "$CONFIG" \
    --output-dir "$OUT" \
    --dataset hotpotqa --dataset 2wikimultihop --dataset musique --dataset drop \
    --workers 4 \
    >> "$LOG_DIR/phase4-sealed-$R.log" 2>&1
  RC=$?
  echo "===== [$R] finished rc=$RC $(date -u '+%F %T') =====" | tee -a "$LOG_DIR/phase4-sealed-launcher.log"
done
echo "CHAIN COMPLETE $(date -u '+%F %T')" | tee -a "$LOG_DIR/phase4-sealed-launcher.log"
