# H-009 预注册 — 相关性引导的提取（score-guided extraction）

> **状态**: 待注册（预注册于 H-008 后根因分析完成时）
> **日期**: 2026-08-05
> **关联**: H-008 → S5 绑定值错误根因 → 本假设

---

## 1. 背景（H-008 后根因分析）

H-008 (PerPath) SUPPORTED 后，三数据集阶段分解（gold_ids 驱动）显示：

| 数据集 | EM | BINDING_OR_GEN | NOT_SELECTED_TO_EVIDENCE |
|--------|-----|---------------|--------------------------|
| hotpotqa | 50% | **43%** | 7% |
| 2wikimultihop | 71% | **28%** | 1% |

hotpotqa/2wiki 的下一瓶颈是 BINDING_OR_GEN（绑定/生成），其中：
- **S5_WRONG_VALUE**（f1<0.5 绑定值完全错）占 52%
- S8 措辞变体占 48%

## 2. S5_WRONG_VALUE 根因（代码级确认）

**证据链**（样本 `5a84e109` / `5ac4e593` / `5a7a88e4`）:
1. gold 在**最终 evidence** 的 passage 里（如 "Seoul, South Korea" 在 Yonsei University#0）
2. 但 **rows bindings 里没有 gold 值**（提取阶段遗漏）
3. 提取提示 (`planner.py:1665-1695`) 把全部 passage **平铺**给 LLM，**无相关性信号**
4. LLM 从多 passage 中提取了最突出但**错误**的候选值（如 "Gibson acoustic" 而非 "rhythm guitar"）

**干预点**: `passage_payload` (`planner.py:1661-1664`) 只含 `source_id`+`text`，未含检索相关性分数。`RetrievalResult.score`（BM25+rerank）现成可用。

## 3. 假设

**H-009**: 在提取提示中标注每个 passage 的检索相关性分数，并引导 LLM "优先从高相关性 passage 提取绑定值"，可回收 hotpotqa/2wiki 的 S5_WRONG_VALUE 错误。

### 3.1 机制预测
提取时给 LLM 提供 `score`（BM25/rerank 相关性），高相关 passage 是 gold 所在的可能性更高 → LLM 从高相关 passage 提取正确绑定值 → S5_WRONG_VALUE 减少 → EM 提升。

### 3.2 关键预测
1. **EM 提升**: hotpotqa +3-6pt（回收 50%+ 的 S5_WRONG_VALUE），2wiki +2-4pt
2. **S5_WRONG_VALUE 减少**: hotpotqa 12 → ≤6
3. **副作用**: 提取提示更长（token 增加），但 LLM 调用数不变

## 4. 实验设计

- **方法**: `slotrag-per-path-extraction` (control) vs 新增 `slotrag-score-guided-extraction` (treatment)
  - 仅差异：提取提示含 score 引导
- **数据**: DEVELOPMENT_SET (seed=2027, 100/数据集, hotpotqa/2wikimultihop)
  - 聚焦 hotpotqa/2wiki（musique 无 gold_ids 无法精确验证 S5，且 evidence 选择主导）
- **指标**: 主要 = EM (primary_score)；次要 = evidence_recall, F1
- **统计**: 配对 wilcoxon，n=100/数据集
- **决策门禁**:
  - 若 hotpotqa EM 提升 ≥ 3pt 且 S5_WRONG_VALUE 减少 → **支持**
  - 若 EM 提升 < 1pt → **拒绝**（提取提示非瓶颈，可能是模型能力）
  - 若 1-3pt → **部分支持**，需诊断

## 5. 成本

- 2 数据集 × 100 样本 × 2 方法 = 400 样本
- 提取调用不变，token 略增（score 字段小）
- 预计 60-90 分钟（无 PerPath 的 14x 延迟，因不新增提取调用）

## 6. 预注册声明

本假设在 H-008 结果、三数据集阶段分解、S5_WRONG_VALUE 根因代码分析后预注册。干预（提取提示加 score 引导）在预注册后不修改。若证据不支持则诚实拒绝。

---

*预注册完成: 2026-08-05*
