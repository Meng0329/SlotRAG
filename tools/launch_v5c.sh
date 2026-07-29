#!/bin/bash
# Launch V5c (corrected) with retry loop for ext4 D-state
DIR="/data/mzb/SlotRAG"
cd "$DIR" || exit 1
LOG="/tmp/hybrid-v5c.log"
> "$LOG"

for attempt in 1 2 3 4 5; do
  echo "[$(date)] Attempt $attempt/5" >> "$LOG"

  # Warm imports + data
  .venv/bin/python -c "
from slotrag.config import AppConfig; from slotrag.benchmarking.datasets import DATASETS, load_sample
from slotrag.providers import AgnesClient, EmbeddingClient, RerankerClient
from slotrag.retrieval import HybridRetriever, SparseBM25Index, FieldedSparseBM25Index
from slotrag.benchmarking.metrics import score_record; from slotrag.benchmarking.methods import run_method, METHODS
from slotrag.benchmarking.runner import _BudgetedRetriever, _BudgetedAgnes
import numpy as np, hashlib, json, time
print('IMPORTS WARM')
" >> "$LOG" 2>&1

  # Warm npy files
  echo "  Warming data files..." >> "$LOG"
  cat runs/slotrag-global-index-v74-hybrid/qo_v74_development_hybrid/hotpotqa/embeddings.npy > /dev/null 2>&1
  cat runs/slotrag-global-index-v74-hybrid/qo_v74_development_hybrid/2wikimultihop/embeddings.npy > /dev/null 2>&1
  echo "  Data files warmed" >> "$LOG"

  # Launch
  .venv/bin/python -u tools/run_hybrid_benchmark.py >> "$LOG" 2>&1 &
  PID=$!
  echo "  Launched PID=$PID" >> "$LOG"

  sleep 30
  STATE=$(ps -o stat= -p "$PID" 2>/dev/null || echo "dead")
  if echo "$STATE" | grep -q "D"; then
    echo "  D-state detected, killing..." >> "$LOG"
    kill -9 "$PID" 2>/dev/null
    sleep 3
    continue
  fi
  if [ "$STATE" = "dead" ]; then
    echo "  Process died, retrying..." >> "$LOG"
    continue
  fi
  echo "[$(date)] Success! PID=$PID running (state=$STATE)" >> "$LOG"
  exit 0
done

echo "[$(date)] All attempts failed" >> "$LOG"
exit 1
