# H-019 Pre-Registration: 生成前证据相关性重排序（question-aware evidence re-ranking）

**假设编号**: H-019
**状态**: proposed → 待 Tier 1 验证
**日期**: 2026-08-06

## 背景（诊断证据）

H-012 Tier 2 逐样本分析（n=100, DEVELOPMENT_SET）：

**2wikimultihop** (46/100 wrong):
- **34/46 gold 在 evidence 里，但仅 3/46 gold 在 rows 里**
- slot-join 架构不把 gold 物化进 rows → 生成器拿到的是**无排序的原始 passage 堆**（平均 7.7 条，59% 含重复）
- graphrag 优势 = 给生成器**按问题相关性排序**的干净 passage；SlotRAG 倾倒所有 slot 物化物

**hotpotqa** (29/100 wrong):
- 25/29 gold 在 evidence，但生成器从 12-18 条无序 passage 中选错事实（Ham House 案例: 12 条 → 选 '22 September 1840' 错）

**关键区分**:
- H-015a (dedupe+cap 截断) 已失败 0/20 — 那是**删减**
- H-019 是**重排序** — 不删任何 passage，只按问题相关性把最相关的排前面。这是未尝试过的机制

## 干预设计

MethodSpec 新 flag `evidence_rerank: bool = False`。在 `_finalize` 生成前：
1. 用现有 reranker (`bge-reranker-v2-m3`, `retriever.reranker_client`) 对 `result.evidence` 的每个 `source_span` 与 `question.question` 打分
2. 按 score 降序重排 evidence
3. 可选 top-k 截断（如 8）——**保留重排序**，截断是次要的

**与 graphrag 对齐**: graphrag 给生成器排序 passage → 生成器聚焦最相关事实。SlotRAG 目前无排序。

## 验证方法

- **Tier 1** (n=20, 2wiki): `slotrag-grounded-frontier-perpath-guard` vs `slotrag-grounded-frontier-perpath-rerank` 配对
- **门禁**:
  - 2wiki F1 Δ ≥ +3pt（2wiki 当前 0.629 vs react 0.794，差距 -16.5pt）
  - 34 个 gold-in-evidence wrong 中恢复 ≥30%
  - both-right 样本零回归
- **Tier 2**（若通过）: n=100 全量，2wiki 目标 F1 ≥ react 0.794 或接近

## 预期效果

- 2wiki: 生成器从"无排序 12+ 条"变为"相关性排序 top-8"，gold passage 更可能被选中 → 34 个 in-evidence wrong 中恢复一批
- hotpotqa 同理（25 in-evidence wrong）

## 风险

- reranker 对 evidence-vs-question 的排序可能不准确（检索 score ≠ 生成相关性）
- 重排可能把噪声 passage 排前面（依赖 reranker 质量）
- 又一个生成侧干预（第 8 个）——但机制不同（排序 vs 截断/提示）
- reranker 调用成本（每样本 +1 次，max 8 条 doc，可接受）

## 后续方向

- 通过 → 2wiki F1 提升，hotpotqa 可能同步受益，Coverage 可到 3/5
- 拒绝 → 生成瓶颈是模型能力而非 evidence 呈现，确认接受 2/5
