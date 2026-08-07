# PROTOCOL_AMENDMENT_V1_1.md — Coverage 分母修正案

> **状态**: ⏳ **待用户审批**（审批前，8-cell 与 5-cell Coverage 同时报告）
> **提出时间**: 2026-08-07 · **协议版本**: v1.0 → v1.1
> **触发审计**: Phase 3X Section 0.1 — Coverage 分母不一致

---

## 1. 问题陈述

FROZEN_PROTOCOL v1.0 §2.1 定义：

> **单元格** = dataset × 预注册 primary metric × matched-budget regime

§2.2 预注册指标矩阵为：

| 数据集 | Primary Metric |
|--------|---------------|
| hotpotqa | EM, F1 |
| 2wikimultihop | EM, F1 |
| musique | EM, F1 |
| strategyqa | accuracy |
| drop | drop_f1 |

**理论上是 8 个 primary cells**（hotpotqa EM/F1 + 2wiki EM/F1 + musique EM/F1 + strategyqa acc + drop drop_f1）。

但 Phase 3R 以来，竞争力报告统一使用 **dataset × 单 primary metric**（hotpotqa F1、2wiki F1、musique F1、strategyqa acc、drop drop_f1），实际只有 **5 个 cells**。

**这是协议变化**——按 §12 修正案流程，禁止静默修改。本修正案正式记录差异并分别计算。

---

## 2. 差异来源

| 差异 | 5-cell（Phase 3R 现行） | 8-cell（协议 §2.2 字面） |
|------|------------------------|--------------------------|
| hotpotqa | F1 一个 | EM + F1 两个 |
| 2wikimultihop | F1 一个 | EM + F1 两个 |
| musique | F1 一个 | EM + F1 两个 |
| strategyqa | acc 一个 | acc 一个 |
| drop | drop_f1 一个 | drop_f1 一个 |
| **合计** | **5 cells** | **8 cells** |

5-cell 是**为每个数据集挑选单一最能代表的主指标**（F1 对 span-based、acc 对布尔、drop_f1 对数字）；
8-cell 是**完整保留协议 §2.2 的每个 primary metric**。

**为什么二者不同**：同数据集下 EM 与 F1 不必然同向（如 hotpotqa EM +2pt 但 F1 -0.2pt；musique EM +8pt 与 F1 +9.6pt 均领先）。只报单指标会丢失部分领先/落后信息。

---

## 3. 8-cell Coverage（A）

**数据**: H-012 Tier2, DEVELOPMENT_SET (seed=2027), n=100, vs 各数据集最强 baseline（逐题配对）

| Cell | Δ | p | 点估计 | 统计支持 (p<0.05) |
|------|-----|-----|--------|--------------------|
| hotpotqa.EM | **+0.0200** | 0.53 | ✅ WIN | ❌ ns |
| hotpotqa.F1 | -0.0019 | 0.94 | ⚖️ tie | ❌ ns |
| 2wiki.EM | -0.1700 | **0.0012** | ❌ LOSS | ❌（显著落后） |
| 2wiki.F1 | -0.1650 | **0.0010** | ❌ LOSS | ❌（显著落后） |
| musique.EM | **+0.0800** | 0.20 | ✅ WIN | ❌ ns |
| musique.F1 | **+0.0961** | 0.12 | ✅ WIN | ❌ ns |
| strategyqa.acc | **+0.0800** | 0.14 | ✅ WIN | ❌ ns |
| drop.drop_f1 | -0.1336 | **0.0023** | ❌ LOSS | ❌（显著落后） |

**A. ORIGINAL_8_CELL_COVERAGE**:
- 点估计 Coverage = **4/8 = 50%**
- 统计支持 Coverage（协议 §2.3 标准）= **0/8 = 0%**
- 显著 LOSS = 3/8

---

## 4. 5-cell Coverage（B）

**数据**: 同上，但每数据集仅取单一 primary（hotpotqa F1、2wiki F1、musique F1、strategyqa acc、drop drop_f1）

| Cell | Δ | p | 点估计 | 统计支持 |
|------|-----|-----|--------|----------|
| hotpotqa.F1 | -0.0019 | 0.94 | ⚖️ tie | ❌ |
| 2wiki.F1 | -0.1650 | **0.0010** | ❌ LOSS | ❌ |
| musique.F1 | **+0.0961** | 0.12 | ✅ WIN | ❌ |
| strategyqa.acc | **+0.0800** | 0.14 | ✅ WIN | ❌ |
| drop.drop_f1 | -0.1336 | **0.0023** | ❌ LOSS | ❌ |

**B. DATASET_PRIMARY_5_CELL_COVERAGE**:
- 点估计 Coverage = **2/5 = 40%**
- 统计支持 Coverage = **0/5 = 0%**
- 显著 LOSS = 2/5

---

## 5. 修正案结论与建议

### 5.1 为什么必须同时报告

- 5-cell 是 Phase 3R 的实际度量口径（40%），历史可追溯
- 8-cell 是协议字面口径（50%），但**更保守的统计支持口径下都是 0%**
- **无论哪种口径，都远低于 95% 目标**；统计支持口径下均为 0%

### 5.2 建议采纳的口径

**建议采用 8-cell + 统计支持标准作为正式 Coverage**（更严格、与协议 §2.2/§2.3 一致）。理由：
1. 协议 §2.2 明确列出 8 个 primary metric，5-cell 是对它的静默收缩
2. 统计支持（p<0.05 且 95%CI 不含 0 且 effect>0.2）是 §2.3 的唯一合法判定
3. 点估计口径会把「+2pt ns」误报为领先，误导审稿人

### 5.3 对 Phase 3X 目标的含义

**Phase 3X milestone A 应基于 8-cell 统计支持口径重新设定**：
- 目标不是「点估计覆盖 ≥50%」，而是「统计支持覆盖 ≥3/8」
- 2wiki/drop 必须从显著 LOSS 转正（typed relational executor 的核心目标）
- musique/strategyqa 必须把 ns 转成 sig（需改变效应形态，见 EMPIRICAL_POWER_AUDIT.md）

### 5.4 对协议其他部分的影响

- **§6 功效分析**: 由 EMPIRICAL_POWER_AUDIT.md 取代（n=100 不能支撑 1-2% 可检测）
- **§2.1 Coverage 定义**: 保持「dataset × primary metric」不变，但明确 primary metric 按 §2.2 全列（8 cells）
- **§2.3 判定**: 保持，但 Coverage 计算改用「统计支持」而非「点估计」

---

## 6. 审批要求

本修正案**在用户审批前**，所有 Coverage 报告必须**同时标注 8-cell 与 5-cell**，不得只报其一。

请审批：
- [ ] 采用 8-cell + 统计支持口径作为正式 Coverage
- [ ] 或 保持 5-cell，但明确声明为「点估计 Coverage」（非协议 §2.3 标准）

---

*修正案 v1.1 · 2026-08-07 · 待用户审批*
