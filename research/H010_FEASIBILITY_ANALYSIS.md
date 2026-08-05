# H-010 可行性分析 — 绑定值选择干预（2026-08-05 否决）

## 背景

H-009 (score-guided extraction) 被拒绝后，假设循环定位到 S5_GOLD_BINDING_MISSING（hotpotqa 20/100, 2wiki 25/100）作为下一瓶颈。本研究对两个候选干预方向做系统性可行性分析，**在投入实验前**否决。

## 数据与方法

- **数据**: H-009 treatment (`slotrag-score-guided-extraction`) 的 45 个 S5 样本（hotpotqa 20, 2wiki 25）
- **对照**: `slotrag-per-path-extraction`（H-008 SUPPORTED 的基线）
- **工具**: `research/classify_stages.py` S5 分类 + 自写可行性分析脚本
- **样本源**: `runs/slotrag-phase3r-h009-dev/samples/h009_dev/{hotpotqa,2wikimultihop}.jsonl`

## 候选 A：跨来源绑定值投票

**假设**: 多条独立检索路径对同一 (slot, value) 的一致性是强信号，可区分 gold 与干扰值。

**验证**: 对每个 S5 样本，统计 gold 值 vs 错误值在各 row 绑定中的出现次数。

| 指标 | hotpotqa | 2wiki | pooled |
|------|----------|-------|--------|
| S5 样本数 | 20 | 25 | 45 |
| gold 在 rows 中 | 5 (25%) | 14 (56%) | 19 (42%) |
| 跨来源投票可恢复 | **2** (10%) | **0** | **2/45 (4%)** |

**结论**: 58% 的 S5 样本 gold 根本不在 rows 里（投票无从谈起）。仅 2/45 (4%) 可恢复，远低于预注册门禁（3pt ≈ 5-8 样本）。**否决**。

## 候选 B：compact-value 提取

**假设**: 提取器过度精细化（把 `Solothurn` 提取成 `Solothurn, Switzerland`），约束其输出证据中最紧凑变体可恢复。

**验证**: 检查 45 个 S5 样本中 gold 紧凑形式与 row 绑定值的子串关系，及 gold 在 evidence 中的出现情况。

### 关键发现：过度提取是真实的

A_gold_in_pred 子群（2wiki 10-14 样本）：
- gold 紧凑形式在 evidence 中出现 ≥2 次（如 `Solothurn` 2 次）
- gold 已在 rows 里（`rows[0]={'place': 'Solothurn, Switzerland'}`）
- **扩展发生在提取阶段**：提取器选了 `Solothurn, Switzerland` 而非 `Solothurn`
- 在 control (per-path) 和 treat (score-guided) 中**都错** → PerPath 结构固有，与 score-guided 无关

### 致命缺陷：无 oracle 规则可区分

1. `London` → `Tooting, London, England`：gold 该紧凑，但 `Tooting, London, England` 是**合法完整答案**
2. `1969 until 1974` → `1969–1974`：标点差异，不是精细化
3. `the east of Ireland` → `east`：gold 是描述性短语，无法紧凑化
4. `dinosaur` → `silhouette of a large green dinosaur`：gold 太宽泛

没有任何确定性规则能判断"该紧凑化"与"不该紧凑化"。H-005（答案契约）已证明提示词约束不可靠。

**结论**: **否决**。无 oracle 情况下 compact-value 干预不可行。

## 决定性诊断：S5 的两个独立失败机制

| 子群 | hotpotqa | 2wiki | 机制 |
|------|----------|-------|------|
| F1≥0.5（措辞/粒度） | 11/20 | 11/25 | over-generate，提取精细化 |
| F1<0.5, gold 在 evidence | 2/8 | 11/16 | **提取遗漏**（gold 在 evidence 未入 rows） |
| F1<0.5, gold 不在 evidence | **6/8** | **5/16** | **检索/选入问题** |

**关键洞察**: hotpotqa 的 F1<0.5 明显错误中 75% (6/8) 是检索/选入问题——gold 完全不在 evidence 里，**超出提取/生成干预范围**。2wiki 的 F1<0.5 中 69% (11/16) 是提取遗漏。

## 对假设循环的影响

1. **H-010 否决**（本报告）——两个候选方向均不可行
2. **H-006 延迟**——"改进生成推理"只对"gold 已入 rows 但生成选错"有效，这在 F1<0.5 子群中占少数。主要失败机制是提取遗漏+检索选入
3. **H-011 新增（deferred）**——检索/选入阶段修复（hotpotqa 6/8 的 gold 不在 evidence），但 H-001 (top_k)/H-002 (budget) 已证明"增加检索/预算"无效，方向不明

## 与已知干预的模式对比

所有已测试干预都呈现同一模式：**提示词级约束（H-005/H-009）在某数据集有效、另一个无效，且无法精确恢复**。S5 的修复需要同时解决提取遗漏+检索选入两个机制，没有单一确定性干预能覆盖。

## 产物

- `research/HYPOTHESES.md` — H-010 rejected_after_feasibility, H-006 deferred, H-011 added
- `research/classify_stages.py` — S5 分类逻辑
- `runs/slotrag-phase3r-h009-dev/` — 45 个 S5 样本的完整 run 数据
