# H-021 Pre-Registration: 比较类问题的确定性比较算子（绕过生成器的架构级杠杆）

**假设编号**: H-021
**状态**: **rejected_after_feasibility（2026-08-06）** — 离线模拟仅 1/9 恢复，跨实体年份归属超出确定性范畴
**日期**: 2026-08-06

## 背景（H-020 rejected 后唯一的架构级剩余杠杆）

H-005~H-020（9 个生成侧干预）全部失败：输入侧（evidence 量/排序/prompt/thinking/契约）和输出侧（extract-then-select）都改不动 qwen3.6-27b 的生成。**但 H-020 的诊断暴露了一个被忽略的架构事实**：

- H-012 Tier2 2wiki **25/100 是比较类问题**（`Who is older`, `Which film was released earlier`, `Which film has the director who died later`）
- 这 25 个里 **22 个 rows 已非空**（物化了被比较实体），但 **join_output_rows=0**（没做最终折叠）
- 只有 16/25 答对 → **9 个比较类错误**

**为什么是架构级杠杆**：比较类问题的正确答案是**纯确定性可算的**——不需要生成器"理解语义选一个"，只需要：
1. rows 物化被比较实体的**数值属性**（出生/死亡/发布年份）
2. 一个**比较算子**（`younger/older/earlier/later` → `min/max`）对数值属性做确定性排序

这完全绕过生成器，与 H-005~H-020 本质不同：**不是改生成，而是用算子替代生成**。

## 可行性诊断（2026-08-06 验证，决定性）

### rows 列分析（H-012 Tier2, n=100 2wiki）
rows 只物化了 **`answer` 列**（115 次），加上少量 `grandfather/grandmother/stepmother/album1/film1`（9/9/5/4/2 次）。**没有任何出生/死亡/发布年份列**——比较算子的前提（rows 有数值属性）在 current architecture 里不成立。

### 9 个错误比较样本的年份可解析性
| 样本 | gold | gold-in-evidence | evidence 年份 |
|------|------|------------------|---------------|
| Marius Mitu vs Bea Palya | Mitu | ✅ | 1976×2 |
| It'S All True vs Prisoner... | It'S All True | ❌(0) | 1886/1926/1935/1938 |
| Extreme Ops vs Puberun | Puberun | ✅ | 1959 |
| The Hellstrom vs The Sweet Life | Sweet Life | ✅ | 1936/1966/1971 |
| Treasure of Jamaica vs Gunfighters | Gunfighters | ✅ | 1921/1932/1950 |
| Swarg Narak vs Antardhan | Swarg Narak | ✅ | 1946/1950/1957/1998 |
| Youth in Oregon vs La Playa DC | Youth in Oregon | ❌(0) | 1976/2006/2012 |
| Ngrtd vs Everything I Love | Everything I Love | ✅(4) | 1973/2000/2002/2013 |
| The Sunset Derby vs Borrowed Plumage | Borrowed Plumage | ✅ | 1910/1923 |

**结论**: 9/9 有年份提及、7/9 gold 在 evidence。但关键不是"年份在 evidence"，而是**把年份正确归属到被比较实体**——需要 rows 物化 `birth_year`/`release_year` 列。

### 干预拆分为两个子步骤
1. **提取阶段**: slots 对比较类问题额外物化 `birth_year`/`death_year`/`release_year` 列（regex/LLM 从 evidence 提取）
2. **生成阶段**: 比较算子用这些列确定性排序，绕过生成器

### 现有确定性路径已能部分处理
- `_deterministic_output`（methods.py:1038）: rows 输出列唯一值时直接返回
- `_polar_row_consensus`（methods.py:1016）: 仅处理 polar(yes/no)，不处理比较
- 确定性路径已产生 **20/100 deterministic answers**（H-012 Tier2），其中 8/20 对

---

## 干预设计: comparison operator（确定性比较算子）

新增 MethodSpec flag `comparison_operator: bool = False`。在 `_finalize` 之前、`_deterministic_output` 之后插入比较算子阶段：

**触发条件**:
- 问题匹配比较模式: `(who|which|what) ... (younger|older|earlier|later|earliest|latest) ... (or|than) ...`
- rows 至少包含 2 个被比较实体的行
- rows 中能找到被比较实体的数值属性列（出生/死亡/发布年份, 从 evidence 提取）

**比较逻辑**:
1. 从问题提取两个被比较实体（`X or Y` 的 X/Y）
2. 从 rows 找到每个实体对应的数值年份（`birth year` / `death year` / `release year`, 由比较词决定）
3. 确定性比较: `younger → max(birth)`, `older → min(birth)`, `earlier → min(release)`, `later → max(release)`, `died earlier → min(death)`, `died later → max(death)`
4. 返回选中的实体名

**关键约束**:
- **只加不加伤**: 仅在比较模式匹配 + rows 有数值属性时触发；否则走原路径
- 数值属性**从 evidence 提取**（slots 物化时带上年份列），不从 rows 现成答案猜
- 与 H-005~H-020 的本质区别: 不碰生成器, 用确定性算子替代

## 验证方法

- **Tier 1** (n=20, 2wiki): guard vs `slotrag-grounded-frontier-perpath-compare`
- **门禁**: 比较算子路径的 F1 ≥ 生成路径 + 2pt；both-right 零回归（非比较样本一字不差）

## 预期效果

- 2wiki 25% 比较类问题中, 9 个错误里能确定性恢复的样本（rows 有年份数据）→ F1 提升
- 若 Tier 1 通过, Tier 2 (n=100) 与 react 0.794 对比
- Coverage 目标: 2wiki 从 LOSS 转 WIN → Coverage 3/5=60%

## 风险

- rows 可能未物化年份列（只有答案列）→ 需要 slots 提取阶段带上数值属性
- 比较词到算子的映射可能不完全（`same age` 等边缘情况）
- 非比较样本必须零回归（严格 only-when-compared）

## 后续方向

- 通过 → 2wiki F1 提升, Coverage 3/5
- 拒绝 → 确认 2wiki 需要更强模型, 接受 2/5 或换模型

---

## 可行性判决（2026-08-06 最终）

### 离线模拟: 9 个错误比较样本的确定性恢复

对 H-012 Tier2 的 9 个 wrong comparison 样本做离线 regex 年份提取 + 排序模拟:

| 样本 | 恢复? | 原因 |
|------|-------|------|
| Marius Mitu vs Bea Palya | ✅ | 两实体出生日期精确到日（1976-09-10 vs 1976-11-11），同 passage |
| It'S All True vs Prisoner | ❌ | gold 不在 evidence，跨实体 join 缺失 |
| Extreme Ops vs Puberun | ❌ | 年份无法归属到实体（只有 1959 一个年份） |
| The Hellstrom vs The Sweet Life | ❌ | 需要 join 到导演再找导演生日（跨 passage） |
| Treasure vs Gunfighters | ❌ | 同左，导演死亡年跨 passage |
| Swarg Narak vs Antardhan | ❌ | 年份无法归属 |
| Youth in Oregon vs La Playa | ❌ | gold 不在 evidence |
| Ngrtd vs Everything I Love | ❌ | 4 个年份无法归属到 album |
| The Sunset Derby vs Borrowed Plumage | ❌ | 导演出生年跨 passage |

**恢复率: 1/9 (11%)**，远低于门禁的 ≥50%。

### 判决: rejected_after_feasibility

**根因**: 正确的年份归属本身就需要跨 passage multi-hop 推理（先 join 到导演，再找导演生日）。这是 2wiki 的 hard case，regex 做不到，而 LLM 提取又已被 H-014（桥接）/H-020（extract-then-select）证明在跨实体归属上不可靠。

**与 9 个生成干预闭环**: 2wiki 的比较类错误既不能被提示修复（H-005~H-019），也不能被确定性算子修复（H-021）。比较类的正确答案依赖"先 join 到导演实体 → 再物化导演的出生年"——这个 join 正是 H-014 已证失败的环节。

**结论**: 2wiki 需要更强模型的跨实体推理，架构侧（输入/输出/确定性算子）全部穷尽。
