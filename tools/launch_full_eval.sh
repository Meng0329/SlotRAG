#!/bin/bash
# Full eval: run improved slotrag on 7405 hotpotqa + 12576 2wikimultihop evaluation questions
# Proper pre-warming + graceful shutdown + timeout
DIR="/data/mzb/SlotRAG"
cd "$DIR" || exit 1
LOG="/tmp/hybrid-full-eval.log"
> "$LOG"

echo "[$(date)] Starting full eval (7405 hotpotqa + 12576 2wikimultihop)" | tee -a "$LOG"

# Pre-warm data files
echo "[$(date)] Pre-warming data files..." | tee -a "$LOG"
for f in \
  runs/slotrag-global-index-v74-hybrid/qo_v74_development_hybrid/hotpotqa/embeddings.npy \
  runs/slotrag-global-index-v74-hybrid/qo_v74_development_hybrid/2wikimultihop/embeddings.npy; do
  echo "  Warming $f..." | tee -a "$LOG"
  dd if="$f" of=/dev/null bs=1M count=100 2>/dev/null
  echo "  Done" | tee -a "$LOG"
done

# Warm all imports too
echo "[$(date)] Warming imports..." | tee -a "$LOG"
.venv/bin/python -c "
from slotrag.config import AppConfig; from slotrag.benchmarking.datasets import DATASETS, load_all_questions, load_sample
from slotrag.benchmarking.metrics import score_record; from slotrag.benchmarking.methods import run_method, METHODS
from slotrag.providers import AgnesClient, EmbeddingClient, RerankerClient
from slotrag.retrieval import HybridRetriever, SparseBM25Index, FieldedSparseBM25Index
from slotrag.benchmarking.runner import _BudgetedRetriever, _BudgetedAgnes
from slotrag.benchmarking.corpus import CorpusManifest, SharedCorpusIndex
from slotrag.models import Passage
import numpy as np, hashlib, json, time
print('IMPORTS WARM')
" >> "$LOG" 2>&1

echo "[$(date)] Launching full eval..." | tee -a "$LOG"
nohup .venv/bin/python -u tools/run_full_eval.py >> "$LOG" 2>&1 &
PID=$!
echo "$PID" > /tmp/hybrid-full-eval.pid
echo "[$(date)] Launched PID=$PID" | tee -a "$LOG"
echo "Monitor: tail -f $LOG"
echo "Progress: python3 -c \"from pathlib import Path; import json; p=Path('runs/slotrag-v74-qwen-hybrid-reranker-v6/full_eval_progress.jsonl'); [print(json.loads(l)['id'][:40],json.loads(l)['dataset'],json.loads(l).get('em',0)) for l in p.read_text().strip().split('\n') if l.strip()]\" 2>/dev/null | tail -5"
echo "Stop: kill -TERM \$PID"
