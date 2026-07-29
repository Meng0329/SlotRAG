#!/bin/bash
# Reliable launch for hybrid benchmark — pre-warms Python imports + data files
# to avoid ext4 D-state hangs during startup.

DIR="/data/mzb/SlotRAG"
cd "$DIR" || exit 1

LOG="$1"
[ -z "$LOG" ] && LOG="/tmp/hybrid-v2.log"

echo "[$(date)] Warming Python imports..." >> "$LOG"
.venv/bin/python -c "
from slotrag.config import AppConfig; print('config OK')
from slotrag.benchmarking.datasets import DATASETS, load_sample; print('datasets OK')
from slotrag.providers import AgnesClient, EmbeddingClient, RerankerClient; print('providers OK')
from slotrag.retrieval import HybridRetriever, SparseBM25Index, FieldedSparseBM25Index; print('retrieval OK')
from slotrag.benchmarking.metrics import score_record; print('metrics OK')
from slotrag.benchmarking.methods import run_method; print('methods OK')
from slotrag.benchmarking.runner import _BudgetedRetriever, _BudgetedAgnes; print('runner OK')
import numpy as np, hashlib, json, time; print('stdlib OK')
print('IMPORTS READY')
" >> "$LOG" 2>&1
echo "[$(date)] Imports warm, launching benchmark..." >> "$LOG"

.venv/bin/python -u tools/run_hybrid_benchmark.py >> "$LOG" 2>&1 &
PID=$!
echo "[$(date)] Benchmark started, PID=$PID" >> "$LOG"
