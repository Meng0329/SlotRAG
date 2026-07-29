#!/bin/bash
# Watchdog: restart benchmark if it dies (D-state hang).
# Safe because already-completed items are skipped.
PID="$1"
LOG="/tmp/hybrid-experiment.log"
CMD="/data/mzb/SlotRAG/.venv/bin/python -u tools/run_hybrid_benchmark.py"
DIR="/data/mzb/SlotRAG"

while true; do
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "[$(date)] PID $PID died, restarting..." >> "$LOG"
    cd "$DIR" && nohup $CMD >> "$LOG" 2>&1 &
    PID=$!
    echo "[$(date)] Restarted as PID $PID" >> "$LOG"
  fi
  # Check if log has finished line
  if grep -q "RESULTS:" "$LOG" 2>/dev/null; then
    echo "[$(date)] Benchmark completed!" >> "$LOG"
    break
  fi
  sleep 120
done
