# SlotRAG v74 Hybrid + Reranker Experiments

## SOTA Baselines（固定数据，不重新跑）
- 来源: `runs/vldb2027-submission-qwen36-v3-rescored-v2-final/summaries/main_comparison/summary.json`
- hotpotqa SOTA: graphrag EM=68.00%, irco EM=68.00%, gragraph/irat F1=80.87%
- 2wikimultihop SOTA: graphrag EM=73.00%, F1=81.99%

## Run 1: Hybrid (dense_k=100, BM25_k=100) + Reranker (top_n=50, bm25_weight=0.5, dense_weight=0.5)
- Stage: `qo_v74_hybrid_reranker_dev`
- Output: `runs/slotrag-v74-qwen-hybrid-reranker-dev`

| Dataset | Method | n | EM | F1 | 80% SOTA? |
|---------|--------|---|-----|-----|-----------|
| hotpotqa | slotrag | 40 | 55.00% | 59.37% | F1 ❌ (<64.70%) |
| hotpotqa | dual-access | 39 | 58.97% | 70.60% | ✅ ✅ |
| hotpotqa | evidence-bundle | 39 | 56.41% | 68.03% | ✅ ✅ |
| hotpotqa | per-path-extraction | 39 | 61.54% | 76.68% | ✅ ✅ |
| 2wikimultihop | slotrag | 40 | 67.50% | 74.31% | ✅ ✅ |
| 2wikimultihop | dual-access | 40 | 72.50% | 80.97% | ✅ ✅ |
| 2wikimultihop | evidence-bundle | 40 | 72.50% | 77.08% | ✅ ✅ |
| 2wikimultihop | per-path-extraction | 40 | 62.50% | 69.93% | ✅ ✅ |

- **唯一失败**: hotpotqa basic slotrag 的 F1=59.37% < 阈值 64.70%
- **最佳配置**: per-path-extraction + reranker (hotpotqa F1=76.68%=SOTA 94.8%)

## Run 2: V2 — bigger windows (dense_k=200, BM25_k=200, top_n=100, dense_weight=0.7)
- Stage: `qo_v74_v2_reranker_dev`
- Output: `runs/slotrag-v74-qwen-hybrid-reranker-v2`
- 仅跑 hotpotqa basic slotrag
- 结果：**更差** EM=50.00% F1=54.42%。更大检索窗口反而有害。
- 失败原因分析：basic slotrag 的 `structured_output=False`，导致模型输出推理文本。

## Run 3: V3 — **structured_output=True** 修复生成格式
- Stage: `qo_v74_v3_fix_gen`
- Output: `runs/slotrag-v74-qwen-hybrid-reranker-v3`
- 变更：`METHODS["slotrag"]` 增加 `structured_answer_contract=True`
- 结果：EM=56.41% F1=62.52% （V1 相较：EM+1.41%, F1+3.15%）
- **格式问题清除**，剩下的是证据质量瓶颈

## Run 4: V4 — **extraction_thinking + generation thinking** 提升证据推理
- Stage: `qo_v74_v4_thinking_dev`
- Output: `runs/slotrag-v74-qwen-hybrid-reranker-v4`
- 变更：
  - generation.py: `_structured_thinking_enabled` 改为始终 True
  - methods.py: slotrag MethodSpec 增加 `extraction_enable_thinking=True`
- 目标：all methods × datasets 90% SOTA
- 结果：

| Dataset | Method | n | EM | F1 | 90% EM? | 90% F1? | ΔEM vs V1 | ΔF1 vs V1 |
|---------|--------|---|-----|-----|---------|---------|-----------|-----------|
| hotpotqa | slotrag | 39 | 56.41% | 60.63% | ❌ (<61.20) | ❌ (<72.78) | +1.41 | +1.26 |
| hotpotqa | dual-access | 39 | 56.41% | 68.80% | ❌ | ❌ | -2.56 | -1.80 |
| hotpotqa | evidence-bundle | 39 | 58.97% | 69.42% | ❌ | ❌ | +2.56 | +1.39 |
| hotpotqa | per-path-extraction | 40 | 60.00% | 73.03% | ❌ | ✅ | -1.54 | -3.65 |
| 2wikimultihop | slotrag | 40 | 67.50% | 74.31% | ✅ | ✅ | 0 | 0 |
| 2wikimultihop | dual-access | 40 | 72.50% | 80.97% | ✅ | ✅ | 0 | 0 |
| 2wikimultihop | evidence-bundle | 40 | 70.00% | 75.14% | ✅ | ✅ | -2.50 | -1.94 |
| 2wikimultihop | per-path-extraction | 40 | 65.00% | 71.81% | ❌ (<65.70) | ❌ (<73.79) | +2.50 | +1.88 |

分析：
- **2wikimultihop 6/8 指标通过** 90% SOTA 阈值（仅 per-path-extraction 未通过）
- **hotpotqa 1/8 指标通过**（per-path-extraction 的 F1 以 73.03% > 72.78% 勉强通过）
- **thinking 对 hotpotqa 帮助不大**——per-path-extraction 反而倒退（F1 76.68% → 73.03%）
- **hotpotqa 瓶颈在检索**——所有方法 EM=0 数量一致（~16/40），证据不在检索结果中
- 2wikimultihop retrieval 已足够，所有方法（除 per-path-extraction）都达标
