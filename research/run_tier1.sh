#!/usr/bin/env bash
# Tier 1 实验：验证 H-001 (final_k=20) 和 H-002 (max_replans=24)
# 在 DEVELOPMENT_SET (n=20×5) 上运行 baseline + 2 变体
# 用法: bash research/run_tier1.sh

set -euo pipefail
export PYTHONPATH=src:.

SUITE="configs/experiments/slotrag-phase3-tier1.yaml"
STAGE="tier1_dev"
BASE_OUT="runs/slotrag-phase3-dev"

echo "=============================================="
echo "Tier 1: 验证 H-001 (final_k=20) + H-002 (max_replans=24)"
echo "=============================================="

run_config() {
  local NAME="$1"
  local CONFIG="$2"
  local OUT_DIR="$3"
  echo ""
  echo "=== 运行 $NAME (config=$CONFIG) ==="
  mkdir -p "$OUT_DIR/samples/$STAGE"
  # 复用已生成的样本（同一 DEVELOPMENT_SET）
  cp "$BASE_OUT/samples/$STAGE/"*.jsonl "$OUT_DIR/samples/$STAGE/" 2>/dev/null || true
  # 运行实验
  python3 -m slotrag.cli benchmark run "$STAGE" \
    --suite "$SUITE" \
    --config "$CONFIG" \
    --output-dir "$OUT_DIR"
  echo "✅ $NAME 完成"
}

# baseline config
run_config "baseline" "configs/default.yaml" "$BASE_OUT/baseline"

# H-001: final_k=20, materialization_top_k=10
run_config "h001-finalk20" "configs/assumptions/h001-finalk20.yaml" "$BASE_OUT/h001-finalk20"

# H-002: max_replans=24
run_config "h002-morebudget" "configs/assumptions/h002-morebudget.yaml" "$BASE_OUT/h002-morebudget"

echo ""
echo "=== 所有 Tier 1 实验完成 ==="
echo "结果目录:"
ls -d "$BASE_OUT"/{baseline,h001-finalk20,h002-morebudget} 2>/dev/null || echo "  (等待生成)"
