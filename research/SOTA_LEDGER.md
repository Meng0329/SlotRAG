# SOTA_LEDGER.md — SOTA 账本

> **维护者**: documentation-writer agent  
> **最后更新**: 2026-08-04T21:00:00Z  
> **状态**: 待填充（Phase 2）

---

## SOTA 定义

### Strongest-Baseline Coverage
- 单元格 = dataset × 预注册 primary metric × matched-budget regime
- 每格只与该 regime 下**最强合法 baseline** 比较
- `Strongest_Baseline_Coverage = SlotRAG-X 严格领先最强合法 baseline 的单元格数 / 全部预注册合法可比单元格数`

### 统计定义
- **Statistically supported win**: p < 0.05 且 95% CI 不包含 0 且效应量 > 0.2
- **Point-estimate-only win**: 点估计领先但 CI 包含 0
- **Tie/inconclusive**: CI 包含 0 且无显著差异
- **Loss**: 点估计落后

---

## SOTA 基准 (90% 阈值)

### 已撤销的 SOTA 基准
| 数据集 | 指标 | 90% 阈值 | 状态 |
|--------|------|----------|------|
| hotpotqa | EM | ≥61.20% | ❌ 已撤销 (train/eval 错配) |
| hotpotqa | F1 | ≥72.78% | ❌ 已撤销 (train/eval 错配) |
| 2wikimultihop | EM | ≥65.70% | ❌ 已撤销 (train/eval 错配) |
| 2wikimultihop | F1 | ≥73.79% | ❌ 已撤销 (train/eval 错配) |

### 待建立的 SOTA 基准
*Phase 2 完成后，在 SEALED_FINAL_SET 上重新建立。*

---

## Strongest-Baseline Coverage 矩阵

*待 Phase 2 完成后填充。*

| 数据集 | 指标 | 最强 baseline | SlotRAG | 统计显著 | 胜/负/平 |
|--------|------|---------------|---------|----------|----------|
| hotpotqa | EM | ? | ? | ? | ? |
| hotpotqa | F1 | ? | ? | ? | ? |
| 2wikimultihop | EM | ? | ? | ? | ? |
| 2wikimultihop | F1 | ? | ? | ? | ? |
| musique | EM | ? | ? | ? | ? |
| musique | F1 | ? | ? | ? | ? |
| strategyqa | EM | ? | ? | ? | ? |
| strategyqa | F1 | ? | ? | ? | ? |
| drop | EM | ? | ? | ? | ? |
| drop | F1 | ? | ? | ? | ? |

---

## 里程碑

- [ ] Phase 2: SOTA 账本建立
- [ ] Phase 3: 假设验证，Strongest-Baseline Coverage ≥95%
- [ ] Phase 4: 冻结验证通过
- [ ] Phase 5: 投稿

---

*本文件由 documentation-writer agent 维护。*
