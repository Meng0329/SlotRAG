#!/bin/bash
# Simple watchdog for hybrid benchmark — just checks process isn't stuck in D-state >2 min
LOG="/tmp/hybrid-reranker.log"
while true; do
  PID=$(pgrep -f "run_hybrid_benchmark" | head -1)
  if [ -z "$PID" ]; then
    echo "[$(date)] No benchmark process found" >> "$LOG"
    break
  fi
  STATE=$(ps -o stat= -p "$PID" 2>/dev/null || echo "")
  if echo "$STATE" | grep -q "D"; then
    echo "[$(date)] D-state detected for PID $PID, waiting..." >> "$LOG"
    sleep 120
    STATE2=$(ps -o stat= -p "$PID" 2>/dev/null || echo "")
    if echo "$STATE2" | grep -q "D"; then
      echo "[$(date)] Still D-state after 2min, killing PID $PID" >> "$LOG"
      kill -9 "$PID" 2>/dev/null
      break
    fi
  fi
  if grep -q "RESULTS:" "$LOG" 2>/dev/null; then
    echo "[$(date)] Completed!" >> "$LOG"
    break
  fi
  sleep 60
done