# SOTA_LEDGER.md — SOTA 账本

> **维护者**: documentation-writer agent  
> **最后更新**: 2026-08-06T06:00:00Z  
> **状态**: Phase 3R — H-012 公平基线重跑完成，Coverage 40%

---

## Strongest-Baseline Coverage 矩阵

### DEVELOPMENT_SET 公平对比 (seed=2027, eval split, n=100, H-012 叠加配置)

> **✅ 公平数据**：此矩阵基于 DEVELOPMENT_SET (seed=2027)，SlotRAG 叠加配置 (`slotrag-grounded-frontier-perpath-guard`) 与 6 个 adapted baseline 在**同 100 样本**上配对对比。此数据可用于论文主表。
>
> **H-012 叠加配置**：frontier 执行守卫 + anchor 保护 + per-path 提取（三机制正交叠加）

| 数据集 | 指标 | SlotRAG | 最强 Baseline | Delta | p | 判定 |
|--------|------|---------|---------------|-------|-----|------|
| hotpotqa | F1 | 0.8331 | graphrag (0.8351) | -0.0019 | 0.94 | ⚖️ tie |
| 2wikimultihop | F1 | 0.6287 | react (0.7936) | -0.1649 | 0.0006 | ❌ LOSS |
| musique | F1 | 0.5790 | ircot (0.4828) | +0.0961 | 0.11 | ✅ point-win |
| strategyqa | acc | 0.8900 | graphrag/react/srag (0.8100) | +0.0800 | 0.09 | ✅ point-win |
| drop | drop_f1 | 0.6277 | graphrag (0.7613) | -0.1336 | 0.0018 | ❌ LOSS |

**Strongest-Baseline Coverage: 2/5 = 40%**（musique、strategyqa 领先；hotpotqa 持平；2wiki、drop 落后）

### 配对详情（叠加 vs 各 baseline）

| 数据集 | baseline | Δ | p | 判定 |
|--------|----------|------|-----|------|
| hotpotqa | graphrag 0.835 | -0.002 | 0.94 | tie |
| hotpotqa | hybrid 0.839 | -0.006 | 0.80 | tie |
| hotpotqa | ircot 0.835 | -0.002 | 0.86 | tie |
| hotpotqa | planrag 0.765 | +0.068 | 0.057 | point-win |
| hotpotqa | srag 0.775 | +0.059 | **0.034** | ✅ WIN |
| 2wiki | graphrag 0.763 | -0.135 | 0.002 | ❌ LOSS |
| 2wiki | hybrid 0.777 | -0.149 | 0.0009 | ❌ LOSS |
| 2wiki | ircot 0.783 | -0.155 | 0.0007 | ❌ LOSS |
| 2wiki | planrag 0.760 | -0.131 | 0.011 | ❌ LOSS |
| 2wiki | react 0.794 | -0.165 | 0.0006 | ❌ LOSS |
| 2wiki | srag 0.497 | +0.131 | 0.002 | ✅ WIN |
| musique | graphrag 0.236 | +0.343 | <0.0001 | ✅ WIN |
| musique | hybrid 0.372 | +0.208 | 0.0001 | ✅ WIN |
| musique | ircot 0.483 | +0.096 | 0.11 | point-win |
| musique | planrag 0.457 | +0.122 | 0.025 | ✅ WIN |
| musique | react 0.416 | +0.163 | 0.009 | ✅ WIN |
| musique | srag 0.381 | +0.198 | <0.0001 | ✅ WIN |
| strategyqa | graphrag 0.810 | +0.080 | 0.088 | point-win |
| strategyqa | hybrid 0.790 | +0.100 | 0.041 | ✅ WIN |
| strategyqa | ircot 0.790 | +0.100 | 0.041 | ✅ WIN |
| strategyqa | planrag 0.710 | +0.180 | 0.0007 | ✅ WIN |
| strategyqa | react 0.810 | +0.080 | 0.088 | point-win |
| strategyqa | srag 0.810 | +0.080 | 0.011 | ✅ WIN |
| drop | graphrag 0.761 | -0.134 | 0.0018 | ❌ LOSS |
| drop | hybrid 0.716 | -0.088 | 0.027 | ❌ LOSS |
| drop | ircot 0.752 | -0.125 | 0.005 | ❌ LOSS |
| drop | planrag 0.744 | -0.117 | 0.007 | ❌ LOSS |
| drop | react 0.761 | -0.133 | 0.0005 | ❌ LOSS |
| drop | srag 0.523 | +0.105 | 0.004 | ✅ WIN |

### 判定说明

- **策略修复 (2026-08-06)**：strategyqa 的 facts 加载回归已修复（`adapt_record` 保留 facts 供 local_context），此前全 700 题 empty 是回归产物，修复后正常（叠加 100 ok）。
- **2wiki LOSS 根因**：叠加配置 28% 样本 F1=0（baseline 仅 14-18%），其中 **27/28 join_output_rows=0**（join 断链）。深挖：S1 提取不出跨 passage 的中间实体（如 director），导致 S2 join 断链 → rows=0 → 瞎猜。union/per-path 提取均无法解决（H-013 否定，p=0.786）——**架构级困难（跨 passage 推理）**。
- **drop LOSS 根因**：drop_f1 落后 -0.134，32 个 F1=0 样本**全部 join_output_rows=0**（同 2wiki 模式）。drop 特殊：gold 是多值数字（'88.32 88.32 11.68'），slot 提取压缩为单值 → F1=0。graphrag 无 slot 架构、自由文本生成 → 无 join 断链 → 效果好。**SlotRAG 的 slot 提取架构对 drop 多值数字答案不适配**。
- **drop LOSS 根因**：drop_f1 落后 -0.134，答案生成质量是瓶颈（H-004 历史结论一致）。
- **musique 显著领先**：叠加 +20~34pt vs 弱 baseline（graphrag/hybrid/srag），+10~16pt vs 强 baseline（ircot/planrag/react）。
- **strategyqa 修复后领先**：+8~18pt，planrag 最弱（0.71），叠加最强（0.89）。

---

## 诊断基线（历史参考，seed=2040, eval split, n=100, contaminated）

> **⚠️ 诊断性数据**：此矩阵基于 CONTAMINATED_EVAL_DIAGNOSTIC_SET (seed=2040)。结果用于建立真实基线和识别瓶颈，**不得**用于论文主表。已被上方 DEVELOPMENT_SET 公平矩阵取代。

| 数据集 | 指标 | SlotRAG | 最强 Baseline | Delta | 判定 |
|--------|------|---------|---------------|-------|------|
| hotpotqa | primary (F1) | 0.6887 | graphrag (0.8087) | -0.1200 | ❌ LOSS |
| 2wikimultihop | primary (F1) | 0.6872 | graphrag (0.8199) | -0.1327 | ❌ LOSS |
| musique | primary (F1) | 0.4818 | planrag (0.5748) | -0.0930 | ❌ LOSS |
| strategyqa | primary (acc) | 0.8400 | hybrid (0.9000) | -0.0600 | ❌ LOSS |
| drop | primary (drop_f1) | 0.6245 | planrag (0.7120) | -0.0875 | ❌ LOSS |

**诊断基线 Coverage: 0/5 = 0%**

### 诊断基线判定说明

- **strategyqa 修正**：EM=0.08 是格式假象（yes/no vs True/False），accuracy=0.84 是真实水平。差距仅 -0.06。
- **drop 修正**：EM=0.01 无效，drop_f1=0.62 是真实水平。
- 真实差距从平均 -0.25 修正为平均 -0.10（按主指标）。

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
- [x] Phase 3: H-012 叠加配置公平重跑（Coverage 40%）
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
