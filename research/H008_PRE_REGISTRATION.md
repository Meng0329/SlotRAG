# H-008 预注册 — PerPathExtractor 对 S2 捆绑丢失的修复验证

> **状态**: 待注册（预注册于 H-007 完成后的根因复核）
> **日期**: 2026-08-05
> **关联**: H-007 → S2 根因分析 → 本假设

---

## 1. 背景（H-007 阶段审计）

H-007 (DEVELOPMENT_SET, seed=2027, 300 样本) 阶段审计显示：
- **hotpotqa**: S2 捆绑丢失 29/100 (29%)，S5 绑定丢失 13/100
- **2wiki**: S5 绑定丢失 10/100，S1 选入失败 9/100
- **musique**: S5 绑定丢失 43/100，S3 空束 15/100

Oracle headroom 显示 **Span 层（S0-S3）在 hotpotqa 有 +30 EM 空间**。

## 2. S2 根因（已代码级确认）

**证据链**（样本 `5a7261635542997f8278398a`）:
1. gold `[Ingrida Ardišauskaitė#0, Utena#0]` 都进入检索候选（Utena rank 2/4）
2. 都选入 materialization（selected_source_ids 含 Utena）
3. **但 UnionExtractor 一次提取所有 fused passages**（`evidence_bundle.py:139-142`），LLM 只从 Ingrida 生成行，`Utena#0` 没有独立行
4. Utena 信息（`{city: Utena}`）折叠进 Ingrida 的行 → evidence 只有 Ingrida → evidence_recall=0.5 → S2

**代码位置**:
- `UnionExtractor.extract` (`src/slotrag/evidence_bundle.py:115-223`): 合并所有 passage 一次提取
- `PerPathExtractor.extract` (`src/slotrag/evidence_bundle.py:229-365`): **每路径独立提取，跨路径去重合并**
- `methods.py:218` `slotrag-per-path-extraction`: 现成的 per_path_extraction=True 变体

## 3. 假设

**H-008**: 将 evidence 提取从 UnionExtractor 切换到 PerPathExtractor（`slotrag-per-path-extraction`），使每个检索路径独立提取行，可回收 hotpotqa 的 S2 捆绑丢失，EM 从 0.52 → 0.58-0.65。

### 3.1 机制预测
PerPathExtractor 对每个 search 路径独立提取（每路径候选含 Utena），合并时保留不同 source 的行 → Utena 的行不再丢失 → evidence_recall 从 0.775 → 0.85+，EM 提升。

### 3.2 关键预测
1. **evidence_recall 提升**: hotpotqa 0.775 → 0.82-0.88（S2 样本的 recall 从 0.5 → 1.0）
2. **EM 提升**: hotpotqa 0.52 → 0.58-0.65（回收 ~30-50% 的 S2）
3. **副作用**: PerPathExtractor 增加 LLM 调用（每路径一次），成本上升但可控

## 4. 实验设计

- **方法**: `slotrag` (control) vs `slotrag-per-path-extraction` (treatment)
- **数据**: DEVELOPMENT_SET (seed=2027, 100/数据集, hotpotqa/2wiki/musique)
- **指标**: 主要 = EM (primary_score)；次要 = evidence_recall, F1
- **统计**: 配对 wilcoxon，n=100/数据集
- **决策门禁**:
  - 若 hotpotqa EM 提升 ≥ 3pt 且 evidence_recall 提升 → **支持**，promote 到验证
  - 若 EM 提升 < 1pt → **拒绝**（S2 根因不只是提取，可能还有别的问题）
  - 若 1-3pt → **部分支持**，需诊断

## 5. 成本

- 每数据集 100 样本 × 2 方法 = 200 样本/数据集
- 3 数据集 = 600 样本
- PerPathExtractor 每槽 2 次提取（dual_access）→ LLM 调用翻倍
- 预计 60-90 分钟，需确认 budget

## 6. 预注册声明

本假设在 H-007 结果、S2 根因代码分析后预注册。干预（切换 extractor）在预注册后不修改。若证据不支持则诚实拒绝，不调整方法。

---

*预注册完成: 2026-08-05*
