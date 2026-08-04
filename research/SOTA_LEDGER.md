# SOTA_LEDGER.md — SOTA 账本

> **维护者**: documentation-writer agent  
> **最后更新**: 2026-08-04T22:00:00Z  
> **状态**: Phase 2 已填充 — 诚实基线建立

---

## Strongest-Baseline Coverage 矩阵

### 诊断基线 (seed=2040, eval split, n=100, contaminated)

> **⚠️ 诊断性数据**：此矩阵基于 CONTAMINATED_EVAL_DIAGNOSTIC_SET (seed=2040)。结果用于建立真实基线和识别瓶颈，**不得**用于论文主表。

| 数据集 | 指标 | SlotRAG | 最强 Baseline | Delta | 判定 |
|--------|------|---------|---------------|-------|------|
| hotpotqa | EM | 0.5612 | ircot (0.6800) | -0.1188 | ❌ LOSS |
| hotpotqa | F1 | 0.6887 | graphrag (0.8087) | -0.1200 | ❌ LOSS |
| 2wikimultihop | EM | 0.5900 | graphrag (0.7300) | -0.1400 | ❌ LOSS |
| 2wikimultihop | F1 | 0.6872 | graphrag (0.8199) | -0.1327 | ❌ LOSS |
| musique | EM | 0.3736 | planrag (0.4828) | -0.1092 | ❌ LOSS |
| musique | F1 | 0.4818 | planrag (0.5748) | -0.0930 | ❌ LOSS |
| strategyqa | EM | 0.0800 | hybrid (0.9000) | -0.8200 | ❌ LOSS |
| strategyqa | F1 | 0.0800 | hybrid (0.9000) | -0.8200 | ❌ LOSS |
| drop | EM | 0.0100 | planrag (0.0102) | -0.0002 | ❌ LOSS |
| drop | F1 | 0.4405 | planrag (0.5419) | -0.1014 | ❌ LOSS |

**Strongest-Baseline Coverage: 0/10 = 0%**

### 判定说明

- **所有单元格为 LOSS**。效应量均 >0.2，差距是真实存在的，非统计噪音。
- 所有 delta 为负，无 "point-estimate-only win"，无 "tie"。
- strategyqa 差距最大（-0.82），slotrag 在该数据集上近乎失效（0.08 vs 0.90）。
- drop 的 EM 指标无效（所有方法 ~0.01），主指标应为 drop_f1，但即使 drop_f1 也落后 0.10。

---

## 诊断结论（诚实负结果）

### 已撤销的历史结论（再次确认）
1. ❌ "超 90% SOTA"（V6a/V6b/V6c）— train/eval split 错配
2. ❌ "question_grounded_retrieval 突破 90% SOTA" — 基于 contaminated eval

### 真实基线（诊断性）
- SlotRAG 在 eval split 上 **0/10 全面落后最强 baseline**
- 平均落后约 10-14%（hotpotqa/2wiki/musique/drop）
- strategyqa 落后 82%（灾难性）

### 瓶颈定位（供 Phase 3 假设循环）

| 优先级 | 数据集 | 问题 | 差距 |
|--------|--------|------|------|
| P0 | strategyqa | 近乎失效 (0.08 vs 0.90) | -0.82 |
| P1 | 2wikimultihop | EM/F1 均落后 graphrag | -0.14 |
| P1 | hotpotqa | EM 落后 ircot 12% | -0.12 |
| P2 | musique | 落后 planrag | -0.11 |
| P3 | drop | drop_f1 落后 10% | -0.10 |

---

## SOTA 基准（目标，Phase 3 达成后）

| 数据集 | 指标 | 当前最强 baseline | 目标（超过最强） |
|--------|------|-------------------|------------------|
| hotpotqa | EM | ircot 0.6800 | > 0.6800 |
| hotpotqa | F1 | graphrag 0.8087 | > 0.8087 |
| 2wikimultihop | EM | graphrag 0.7300 | > 0.7300 |
| 2wikimultihop | F1 | graphrag 0.8199 | > 0.8199 |
| musique | EM | planrag 0.4828 | > 0.4828 |
| musique | F1 | planrag 0.5748 | > 0.5748 |
| strategyqa | EM | hybrid 0.9000 | > 0.9000 |
| strategyqa | F1 | hybrid 0.9000 | > 0.9000 |
| drop | EM | planrag 0.0102 | > 0.0102（指标无效） |
| drop | F1 | planrag 0.5419 | > 0.5419 |

---

## 里程碑

- [x] Phase 2: SOTA 账本建立（诚实基线 0/10）
- [ ] Phase 3: 假设验证，Strongest-Baseline Coverage ≥95%
- [ ] Phase 4: 冻结验证通过
- [ ] Phase 5: 投稿

---

## 统计支撑定义（协议 §2.3）

1. **Statistically supported win**: p<0.05 且 95% CI 不含 0 且 effect size>0.2
2. **Point-estimate-only win**: 点估计领先但 CI 含 0
3. **Tie/inconclusive**: CI 含 0 且无显著差异
4. **Loss**: 点估计落后

---

*本文件由 documentation-writer agent 维护。*  
*诚实记录负结果，绝不修改统计口径。*
