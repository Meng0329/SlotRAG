# H-020 Pre-Registration: extract-then-select 生成（候选抽取→选择，堵死内部先验）

**假设编号**: H-020
**状态**: proposed → 待 Tier 1 验证
**日期**: 2026-08-06

## 背景（诊断证据，refined）

前 8 个生成干预（H-005/009/014/015a/016/017/018/019）**全部改变输入侧**（evidence 量/排序/prompt 措辞/thinking/契约），**没有一个是改变输出契约**。

2wiki 的病灶（gold 连续性诊断）:
- **34/46 wrong 样本 gold 连续在单个 evidence passage 里**（gold='Konstfack' 在 1476 字 passage, gold='Hollywood' 在 George B. Seitz 页）
- 但生成器**自由发挥写内部先验答案**（'Laurence Fishburne' 而非 'Andy García'）
- H-019 证明: 即使重排 evidence，生成器仍无视 → 因为**它根本没有被要求从 evidence 里选答案**

**核心洞察**: 生成器有"内部答案先验"，自由生成时先验泄漏。架构级修复 = **从构造上约束输出必须 grounded**：先枚举候选（只允许 from evidence），再选择（必须匹配问题）。

## 干预设计: extract-then-select 输出契约

新增 MethodSpec flag `extract_then_select: bool = False`。`_finalize` 生成阶段换成两段式：

**Step 1 — 候选抽取**（工具调用，temperature=0）:
- 新工具 `emit_candidate_spans`: 输入 = question + evidence passages
- 输出 = 最多 5 个候选答案 span（必须是 evidence 里的**连续子串**，grounded by construction）
- 工具 schema 强制: `{"spans": ["..."], "passage_ids": [...]}`

**Step 2 — 选择**（工具调用，temperature=0）:
- 新工具 `emit_selected_answer`: 输入 = question + candidates
- 输出 = 从候选中选一个（或 None 若无匹配）
- 若有工具拒绝/空，回退到现有 `emit_final_answer` 自由生成

**为什么不同**:
- H-005~H-019 是"输入侧提示"，生成器仍可自由写
- H-020 是"输出侧构造"——候选必须来自 evidence，选择必须基于问题，无自由发挥空间

## 验证方法

- **Tier 1** (n=20, 2wiki): guard vs `slotrag-grounded-frontier-perpath-select`
- **门禁**: 2wiki F1 Δ ≥ +3pt；34 个 gold-contiguous wrong 中恢复 ≥50%；both-right 零回归

## 预期效果

- 2wiki: gold 连续在 evidence 的 34 个样本，候选抽取覆盖 gold → 选择器选对 → F1 大幅提升
- drop 不适用（gold 不连续，仅 6%）
- 风险: 候选抽取可能漏掉 gold（长 passage 截断）；选择器可能仍选错

## 后续方向

- 通过 → 2wiki F1 提升，Coverage 可到 3/5
- 拒绝 → 确认 2wiki 需要更强模型，接受 2/5 或换模型
