# H-018 Pre-Registration: 生成证据保真（evidence-fidelity generation）

**假设编号**: H-018
**状态**: proposed → 待 Tier 1 验证
**日期**: 2026-08-06

## 背景（诊断证据）

H-012 Tier 2 完整跑（n=100, DEVELOPMENT_SET, hotpotqa）显示 guard 方法 29/100 答案错，其中 **25/29 gold 在 evidence 里**但生成选错边界/实体：

| 机制 | 数量 | 说明 |
|------|------|------|
| A 截断 (pred ⊂ gold) | 7 | `'east'` vs gold `'the east of Ireland'`; `'five'` vs `'five months'`; `'Best Musical'` vs `'for Best Musical'` |
| B 超集 (gold ⊂ pred) | 8 | `'the silhouette of a large green dinosaur'` vs gold `'dinosaur'` |
| C 错实体 (disjoint) | 14 | `'Laurence Fishburne'` vs gold `'Andy García'` |

**根因**: 生成 prompt 用 "Return only a concise answer span" — 纯简洁偏好。模型为最短形式优化，丢弃限定语/全名/短语。

**可行性验证**:
- 机械 span 扩展会破坏正确答案（模拟 66 个 both-right 样本中 17 个 F1 1.0→<0.3）→ **禁止边界手术**
- prompt 硬约束（H-005 entity contract）已失败（多实体答案被截断）→ **禁止硬 canonical 约束**

## 干预设计

在 `generate_answer_response` 的 short-answer format_instruction 加**软保真指令**（不改变 answer_kind、不加工具、不做边界手术）：

> "Return the answer as a contiguous span taken from the supplied evidence. If the evidence contains a fuller form (full name, qualifiers, or complete phrase) that answers the question, return that fuller form rather than a shortened version. Do not shorten names or drop qualifiers."

**为什么不同于 H-005**: H-005 强制"canonical entity name"（过度约束 → 多实体截断）；H-018 是软性"优先更完整的形式"（朝反方向推，不强制单一形式）。

**实现**: MethodSpec 新 flag `generation_fidelity: bool = False`。`_finalize` 传给 `generate_answer_response`，在 short/number 分支替换 format_instruction。**单一变量**。

## 验证方法

- **Tier 1** (n=20, hotpotqa): `slotrag-grounded-frontier-perpath-guard` vs `slotrag-grounded-frontier-perpath-fidelity` 配对（seed=2027, 同 DEVELOPMENT_SET 20 样本）
- **门禁**:
  - F1 Δ ≥ +2pt 且不倒退（wilcoxon 参考）
  - 25 个 gold-in-evidence wrong 中 A 类（截断）恢复 ≥50%
  - both-right 66 个样本**零回归**（0 个 F1 下降）
- **Tier 2**（若 Tier 1 通过）: n=100 全量配对，hotpotqa 目标 F1 ≥ graphrag 0.835 (WIN)

## 预期效果

- hotpotqa 截断类（7）回收 5-7 → 净 +10~+20pt 局部，总体 F1 0.833 → 0.85+，**TIE → WIN**
- 超集类（8）部分回收（gold⊂pred 时若生成器收窄）
- 错实体类（14）不受益（需检索/选择改进）

## 风险

- **软指令可能无效**（qwen3.6-27b 对 prompt 措辞不敏感 — H-017 已证明 thinking 无效）
- **可能过度扩展**（描述性答案变长 → F1 反降）— 靠 both-right 零回归门禁拦截
- 与 H-005 混淆风险 — 明确这是"保真优先"而非"canonical 强制"

## 后续方向（无论通过与否）

- 通过 → hotpotqa WIN，Coverage 3/5=60%，下一步 2wiki
- 拒绝 → hotpotqa 生成瓶颈同样非 prompt 可解，确认接受 2/5 或走模型级
