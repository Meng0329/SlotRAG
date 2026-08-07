# HYPOTHESES.md — 研究假设池

> **维护者**: hypothesis-generator agent  
> **最后更新**: 2026-08-06T22:00:00Z  
> **活跃假设数**: 0/5（H-012 部分支持；H-013~H-020 全部拒绝）  
> **当前轮次**: Phase 3X — 局部生成干预已近穷尽（含 H-020 输出契约），但 typed relational execution（H-023~H-028）尚未验证，架构空间未穷尽

---

## 假设池状态

| 状态 | 数量 | 说明 |
|------|------|------|
| provisionally_supported_pending_stage_audit | 2 (H-004, H-012) | H-004 生成质量; H-012 叠加配置 2/5 Coverage |
| supported | 1 (H-008) | PerPath 提取修复 S2，Tier 1 验证支持 |
| stratum_specific_signal | 1 (H-001) | 仅 musique +0.108 是信号,非全局 |
| rejected_exact_budget_configuration | 1 (H-002) | 仅拒绝该预算配置 |
| rejected_exact_intervention | 9 (H-005, H-009, H-014, H-015, H-016, H-017, H-018, H-019, H-020) | H-005 entity契约; H-009 score-guided; H-014 桥接回退; H-015a 证据去重; H-016 drop short答案; H-017 生成thinking; H-018 证据保真; H-019 证据重排; H-020 候选抽取选择 |
| rejected_after_feasibility | 2 (H-010, H-021) | H-010 跨来源投票+compact-value 均不可行; H-021 确定性比较算子仅 1/9 恢复 |
| diagnostic | 1 (H-022) | 2wiki 错误最终聚类: 粒度错配不可修复 + 选型失败为真天花板 |
| deferred | 2 (H-003, H-011) | H-003 evidence quality; H-011 检索/选入修复 |

---

## 活跃假设

### H-001: 检索 top_k 增加可显著提升 evidence recall

- **状态**: stratum_specific_signal
- **描述**: SlotRAG 在 hotpotqa 上 evidence recall 0.755 vs hybrid 1.000，核心差距在于 evidence_count 1-3 vs 10。增加 hybrid retrieval top_n 和 slot materialization top_k 可提升召回。
- **预测**: 将 top_n 从 10 增加到 20，evidence recall 从 0.755 提升到 >0.85，hotpotqa primary_score 提升 5-8%
- **验证方法**: Tier 1 实验 (DEVELOPMENT_SET, n=20, hotpotqa)，修改 config 的 retrieval.top_n 和 materialization_top_k
- **预期效果**: hotpotqa primary_score +5-8%（从 0.6887 → 0.73-0.75）
- **风险**: 更多 evidence 可能引入噪音；LLM 调用成本增加；effect 可能小于预期
- **依赖**: 无
- **创建时间**: 2026-08-05T02:00:00Z
- **最后更新**: 2026-08-05T04:00:00Z
- **证据**: hotpotqa evidence_recall slotrag=0.755 vs hybrid=1.000; evidence_count slotrag=1-3 vs hybrid=10; manifest retrieval.final_k=10。**冒烟测试 (DEVELOPMENT_SET, n=20): baseline primary=0.735, evidence_recall=0.825 — 比 seed=2040 的 0.6887 高，DEVELOPMENT_SET 基线更高**

**Tier 1 验证结果 (2026-08-05)**:
- final_k 10→20 生效: retrieved_evidence_count 3.10→4.85 (+56%), documents_accessed 8.75→18.00 (+106%)
- 但 primary_score 只在 musique 提升 (+0.108), 其他 4 数据集 0/20 无差异
- musique 提升不显著 (wilcoxon p=0.13)
- **结论: 拒绝。检索更多证据不转化为答案质量提升。SlotRAG 的 slot-based 规划已足够精准，额外证据冗余。**

### H-002: 增加 LLM planning 预算可降低 musique 的 budget_exceeded 失败

- **状态**: rejected_exact_budget_configuration
- **描述**: SlotRAG 在 musique 上有 9 个 budget_exceeded 失败（全部 3hop/4hop），但 hybrid 无失败。增加 max_llm_calls 和 max_replans 可让复杂问题完成规划。
- **预测**: max_llm_calls 从 64 增加到 96，musique budget_exceeded 从 9 降至 ≤3，musique primary_score +3-5%
- **验证方法**: Tier 1 实验 (DEVELOPMENT_SET, n=20, musique)，修改 execution config
- **预期效果**: musique primary_score +3-5%（从 0.4818 → 0.50-0.51）
- **风险**: 效果可能受 slot 规划质量而非预算限制
- **依赖**: 无
- **创建时间**: 2026-08-05T02:00:00Z
- **最后更新**: 2026-08-05T04:00:00Z
- **证据**: musique budget_exceeded 9/100; 全部 3hop/4hop question type; manifest max_llm_calls=64

**Tier 1 验证结果 (2026-08-05)**:
- max_replans 16→24, max_llm_calls 64→96
- musique primary_score +0.033（从 0.4533 → 0.4867），不显著 (wilcoxon p=0.41)
- 其他 4 数据集 0/20 无差异
- **结论: 拒绝。增加预算不解决 musique 瓶颈。问题在 slot 规划质量而非预算上限。**

### H-003: 扩展 evidence 到最终生成（more evidence → better reasoning）可缩小全面差距

- **状态**: deferred
- **描述**: 当 slotrag evidence recall=1.0 但 EM=0.0 时，证据已检索到但生成失败（如 hotpotqa qid 5a739b195542: recall=1.0, em=0.0, evidence_count=15）。可能原因是 evidence 过多时 LLM 无法从中推理出正确答案，需要更精准的 evidence ranking 或 evidence filtering。
- **预测**: 增加 reranker top_n 从 10 到 20，对 recall=1.0 但 EM=0.0 的样本，em 提升 15-20%
- **验证方法**: Tier 1 实验 (DEVELOPMENT_SET, n=20, hotpotqa)，修改 reranker 配置
- **预期效果**: hotpotqa primary_score +2-3%（从 0.6887 → 0.71-0.72）
- **风险**: 更多 evidence 可能增加噪音；reranker 可能已有足够排序能力
- **依赖**: H-001 增加 evidence_count 后验证更有效
- **创建时间**: 2026-08-05T02:00:00Z
- **最后更新**: 2026-08-05T04:00:00Z
- **证据**: hotpotqa recall=1.0 但 em=0.0 的样本存在; manifest reranker.top_n=10

**延迟理由**: H-001 证明"增加检索"无效，且增加的是 noisy evidence。H-003 的"更精准 evidence"方向仍可能有效，但需先理解 slot 规划失败的根因再设计。

### H-004: SlotRAG 的答案生成质量是主要瓶颈（检索几乎不是瓶颈）

- **状态**: provisionally_supported_pending_stage_audit
- **描述**: Tier 1 证明检索更多和预算更多都不提升答案质量，且 seed=2040 诊断显示 recall=1.0 但 EM=0 的错误占主导。瓶颈在答案生成质量而非检索。
- **预测**: 对 recall=1.0 但 EM=0 的样本（检索已全对但答案错），修改生成阶段可提升
- **验证方法**: 诊断 hotpotqa/2wiki 上 recall=1.0 但 EM=0 的样本，分析生成失败原因
- **预期效果**: 理解后设计针对性假设
- **风险**: 根因可能是多方面的
- **依赖**: 无
- **创建时间**: 2026-08-05T04:00:00Z
- **最后更新**: 2026-08-05T04:30:00Z

**验证结果 (2026-08-05)**:
- seed=2040 诊断 (recall 有效):
  - hotpotqa: 43/98 EM=0，其中 **21 个 recall=1.0 但 EM=0**（检索对但答案错），仅 2 个检索错
  - 2wiki: 41/100 EM=0，其中 **21 个 recall=1.0 但 EM=0**，仅 4 个检索错
  - recall=1.0&EM=0 中: ~57% F1≥0.5（措辞/格式问题），~43% F1<0.5（明显错误）
- **结论: 检索几乎不是瓶颈（仅 2-4/98-100 检索错）。瓶颈是答案生成质量。**

### H-005: 答案契约/措辞规范化可回收 ~50% 的"接近正确"错误

- **状态**: rejected_exact_intervention
- **描述**: recall=1.0 但 EM=0 的错误中 ~57% 是 F1≥0.5 的接近正确答案（措辞/格式与黄金答案不完全一致，如 'Crown Holdings' vs 'Crown Holdings, Inc.')。改进答案契约或措辞规范化可回收这些。
- **预测**: 对 F1≥0.5 的接近正确错误，改进答案生成提示（如要求输出规范实体名、避免描述性答案）可提升 EM
- **验证方法**: Tier 1 实验，修改 generation prompt 或 answer contract
- **预期效果**: hotpotqa primary_score +5-10%（回收 12/21 个接近正确错误）
- **风险**: 可能只是部分可回收；生成提示改动可能引入新问题
- **依赖**: H-004
- **创建时间**: 2026-08-05T04:30:00Z
- **最后更新**: 2026-08-05T06:00:00Z

**Tier 2 验证结果 (2026-08-05, DEVELOPMENT_SET n=20)**:
- entity_answer_contract=True: hotpotqa 0.6902→0.6702, strategyqa 0.85→0.80, 全数据集下降或持平
- 根因: 强制"规范实体名"过度约束模型。多实体答案被截断（如 'U.S. Public Health Service, Dr. John Roderick...' 被截断为 'U.S. Public Health Service'，F1 0.40→0.00）
- **结论: 拒绝。答案格式问题不能靠提示词约束解决。**

### H-006: 生成阶段推理质量（evidence→answer）是 43% 明显错误的根因

- **状态**: deferred（前提不成立, 2026-08-05）
- **描述**: recall=1.0 但 EM=0 的错误中 ~43% 是 F1<0.5 的明显错误（答案跑偏，如输出 'University of Mississippi' 但问题问别的）。说明生成阶段未正确利用已检索到的证据。
- **预测**: 改进 evidence→answer 的推理（如增加结构化证据利用）可提升
- **验证方法**: 诊断 F1<0.5 样本的生成失败原因，针对性设计
- **预期效果**: hotpotqa primary_score +3-5%
- **风险**: 根因可能是规划质量而非生成
- **依赖**: H-004
- **创建时间**: 2026-08-05T04:30:00Z
- **最后更新**: 2026-08-05T06:00:00Z

**可行性重新评估 (2026-08-05)**:
- H-010 的 F1<0.5 细分诊断显示：hotpotqa 的 6/8 明显错误是**检索/选入问题（gold 不在 evidence）**，非生成推理问题
- 2wiki 的 11/16 明显错误是提取遗漏（gold 在 evidence 但未入 rows）
- **生成推理干预的适用面极窄**：只对"gold 已入 rows 但生成选错"的样本有效，这在 F1<0.5 子群中占少数
- **结论: 延迟**。H-006 的"改进生成推理"无法针对主要失败机制（提取遗漏+检索选入），需先解决 S5 的上游问题

### H-007: 诊断 — 阶段级失败归因 + Oracle Headroom（已完成）

- **状态**: 诊断完成
- **内容**: 不修改方法，仅执行 DEVELOPMENT_SET 完整诊断（300 样本），识别首失败点 + 计算四级 Oracle headroom
- **结果（完整）**:
  - hotpotqa: EM=0.52, S2 捆绑丢失 29, S5 绑定 13 | headroom: Span +30, Candidate +13, Path +5
  - 2wiki: EM=0.68, S5 绑定 10, S1 选入 9 | headroom: Span +19, Candidate +10
  - musique: EM=0.36, S5 绑定 43, S3 空束 15 | headroom: Candidate +58, Span +15
  - **结论**: 瓶颈在 Span（bundle 构建）+ Candidate（绑定），非检索/生成
- **根因（代码级）**: UnionExtractor 单次提取全部 fused passages → 第二个 gold source 的行丢失（S2）
- **产物**: `ANSWER_PIPELINE_AUDIT.md/csv`, `ORACLE_HEADROOM.md/csv`, `ENTITY_SELECTION_CASES.md/csv`

### H-008: PerPathExtractor 切换可回收 hotpotqa 的 S2 捆绑丢失

- **状态**: supported（Tier 1 验证完成, 2026-08-05）
- **描述**: H-007 显示 hotpotqa S2 捆绑丢失 29/100。根因是 UnionExtractor 单次提取所有 fused passages，LLM 只从最突出 source 生成行，第 2 个 gold source 的行丢失（e.g. Utena 折叠进 Ingrida）。`PerPathExtractor`（已实现于 evidence_bundle.py:229）按每个检索路径独立提取再合并，可恢复丢失行。
- **前提验证**: hotpotqa 29/29 个 S2 样本的丢失 gold source 都在检索候选里（PerPath 可恢复率 100%）
- **验证方法**: Tier 1 实验 (DEVELOPMENT_SET, n=100×3)，slotrag-evidence-bundle vs slotrag-per-path-extraction 配对对比（单一变量）
- **创建时间**: 2026-08-05T11:45:00Z
- **预注册文档**: `H008_PRE_REGISTRATION.md`

**Tier 1 验证结果 (2026-08-05, n=276 配对)**:
| 数据集 | ΔEM | wilcoxon p | evidence_recall Δ |
|--------|-----|-----------|-------------------|
| hotpotqa | +2.1pt | 0.48 | +0.027 |
| 2wikimultihop | +3.0pt | 0.18 | +0.053 |
| musique | **+8.4pt** | **0.020** | 0.000 (已=1.0) |
| **pooled** | **+4.4pt** | **0.010** | — |

- 3 数据集一致正向，无负向；musique 显著 (p<0.05)，pooled 显著 (p<0.05)
- evidence_recall 在 hotpotqa/2wiki 提升（S2 修复生效）；musique 已满
- **门禁判定: 支持**。单看 hotpotqa (+2.1pt) 未达预注册 3pt 门槛→部分支持，但 musique +8.4pt 显著、pooled 显著、3 数据集一致正向 + evidence_recall 提升，综合判定 SUPPORTED
- **附带修复**: retrieval.py 移除 heterogeneous sparse-mode 检查（此前使所有 dual-access 方法在 dense 环境 100% 失败）
- **副作用**: PerPath 使每样本 LLM 调用 2-6 次（延迟 ~14x control），但可接受

### H-009: 相关性引导的提取（score-guided extraction）可回收绑定值错误

- **状态**: rejected_exact_intervention（Tier 1 验证完成, 2026-08-05）
- **描述**: H-008 后三数据集阶段分解显示 hotpotqa/2wiki 的下一瓶颈是 BINDING_OR_GEN（43%/28%），其中 52% 是 S5_WRONG_VALUE（绑定值完全错）。根因：gold 在最终 evidence 的 passage 里，但提取提示 (`evidence_bundle.py`) 把全部 passage 平铺给 LLM 无相关性信号，LLM 提取了最突出但错误的值（如 "Gibson acoustic" 而非 "rhythm guitar"）。
- **前提验证**: 3 样本 (5a84e109/5ac4e593/5a7a88e4) 的 gold 都在 evidence passage 里但不在 rows bindings → 提取阶段遗漏，非传播/检索
- **干预**: 提取提示加检索相关性 score 引导 LLM 优先从高相关 passage 提取
- **创建时间**: 2026-08-05T16:00:00Z
- **预注册文档**: `H009_PRE_REGISTRATION.md`

**Tier 1 验证结果 (2026-08-05, n=188 配对)**:
| 数据集 | ΔEM | wilcoxon p | wins/losses |
|--------|-----|-----------|-------------|
| hotpotqa | **-3.2pt** | 0.18 | 1/4 |
| 2wikimultihop | +5.3pt | 0.059 | 6/1 |

- **结论: 拒绝**。score-guided 效果取决于检索 score 质量——2wiki 的 score 可靠（正效果），hotpotqa 的 score 误导（负效果）。不一致，非稳健改进。
- 与 H-005 同模式：某干预一个数据集有效、另一个无效。

### H-010: 绑定值选择干预（跨来源投票 / compact-value 提取）— 可行性否决

- **状态**: rejected_after_feasibility（未投入实验, 2026-08-05）
- **描述**: H-009 后定位到 S5_WRONG_VALUE 的两个候选干预方向，均被系统性可行性分析否决。
- **干预候选 A — 跨来源行投票**（多条独立检索路径对同一 (slot, value) 的一致性）：
  - 45 个 S5 样本中仅 2/45 (4%) gold 的"跨来源票数"超过错误值
  - 58% 的 S5 样本 gold 根本不在 rows 里（投票无从谈起）
  - **不可行**——最多恢复 4%
- **干预候选 B — compact-value 提取**（约束提取器输出证据中最紧凑的实体变体）：
  - A_gold_in_pred 子群（2wiki 10-14 样本）gold 紧凑形式确实在 evidence 出现≥2 次且已在 rows 里（如 `Solothurn`→`Solothurn, Switzerland`）
  - 但无 oracle 规则能区分"该紧凑化"（`Solothurn`）与"不该紧凑化"（`Tooting, London, England` 是合法答案）
  - hotpotqa 的 SUBSTR 子群是措辞/标点差异（`1969–1974` vs `1969 until 1974`）、描述性 gold（`the east of Ireland`），无法紧凑化
  - **不可行**——H-005（答案契约）已证明提示词约束不可靠，且无确定性恢复规则

**可行性分析证据**:
- 45 个 S5 样本：gold 在 rows 里 19/45 (42%)，但跨来源投票可恢复仅 2/45 (4%)
- F1<0.5 明显错误细分：
  - hotpotqa 8 个：2/8 gold 在 evidence（提取遗漏），**6/8 gold 不在 evidence（检索/选入问题）**
  - 2wiki 16 个：11/16 gold 在 evidence（提取遗漏），5/16 不在
- A_gold_in_pred 子群（2wiki）在 control 和 treat 都错 → PerPath 结构固有，与 score-guided 无关

**结论**: S5 的修复需要同时解决提取遗漏（gold 在 evidence 但未入 rows）和检索/选入（gold 不在 evidence）两个机制，没有单一确定性干预能覆盖。与 H-005/H-009 同模式的"提示词干预"已两次证明不可靠。

### H-011: 检索/选入阶段修复 gold 不在 evidence 的错误 — 待探索

- **状态**: deferred（未进入验证）
- **描述**: F1<0.5 的 S5 中，hotpotqa 6/8、2wiki 5/16 的 gold 完全不在 evidence 里。这些不是提取问题，是检索候选或选入环节丢失。H-007 已证明 hotpotqa S0=0（检索零失败），因此是 S1/S2 选入环节。但 musique 的 EVIDENCE_NOT_SELECTED (37%) 已显示这是数据集特有的硬瓶颈，PerPath 修复有限。
- **风险**: H-001 (top_k) 和 H-002 (budget) 已证明"增加检索/预算"不转化答案质量。选入环节的修复方向不明。

### H-012: frontier 执行守卫 + anchor 保护 + per-path 提取叠加可系统性领先 baseline

- **状态**: provisionally_supported_pending_stage_audit（2026-08-06）
- **描述**: 三个已验证改进维度机制正交，叠加后应同时修复多个失败机制：
  1. `frontier_safe_selection`（执行顺序守卫）——防止传递变量 join 失败（train 上 frontier-guard hotpotqa 0.82/2wiki 0.84/musique 0.61）
  2. `grounded_entity_anchor_substitution + protect_known_binding_values`（anchor 保护）——保护已绑定值不被错误覆盖（eval 上 binding-guard hotpotqa 0.71/2wiki 0.72/musique 0.54，已超 musique ircot）
  3. `evidence_bundle + per_path_extraction + dual_access_bundle`（S2 捆绑修复）——修复第二个 gold source 行丢失（pooled +4.4pt, p=0.0105）
- **前提验证**: 三者从未叠加；方法构造已验证兼容（physical_plan=False, incremental_join=True）
- **验证方法**: Tier 1 (n=20) 冒烟 → Tier 2 (n=100) DEVELOPMENT_SET 配对对比 6 baseline
- **Tier 1 冒烟 (n=20)**: ✅ PASSED（2wiki +17.6pt, hotpotqa +11.8pt vs 最优现有; musique EM 3:1 净胜）
- **Tier 2 完整矩阵 (n=100)**: Coverage **2/5 = 40%**
  - **WIN**: musique (F1 0.579 vs ircot 0.483, +9.6pt), strategyqa (acc 0.890 vs graphrag 0.810, +8pt)
  - **TIE**: hotpotqa (F1 0.833 vs graphrag 0.835, -0.2pt, p=0.94)
  - **LOSS**: 2wiki (F1 0.629 vs react 0.794, **-16.5pt**), drop (drop_f1 0.628 vs graphrag 0.761, **-13.4pt**)
- **预期效果**: hotpotqa/2wiki F1 ≥ baseline（graphrag 0.81/0.82），musique/strategyqa/drop 持平或领先
- **结果判定**: **部分支持** — 叠加配置在 musique/strategyqa 显著领先、hotpotqa 持平，但在 2wiki/drop 显著落后。S2 修复（per-path）在 2wiki 上不充分（28% 样本 F1=0），drop 生成质量仍是瓶颈（H-004 一致）。
- **风险**: 组合效应非加性已证实（2wiki 倒退）；per-path 的 LLM 调用成本较高
- **创建时间**: 2026-08-05T19:30:00Z
- **预注册文档**: 见本计划文件
- **配套修复**: strategyqa facts 加载回归修复（commit 8ae9a40，local_context 保留 facts）

---

## 已拒绝假设

*暂无。*

## 延迟假设

*暂无。*

---

## 诊断基线 (供参考)

| 数据集 | SlotRAG | 最强 baseline | 差距 | 最强 |
|--------|---------|---------------|------|------|
| hotpotqa | 0.6887 | 0.8087 | -0.1200 | graphrag |
| 2wikimultihop | 0.6872 | 0.8199 | -0.1327 | graphrag |
| musique | 0.4818 | 0.5748 | -0.0930 | planrag |
| strategyqa | 0.8400 | 0.9000 | -0.0600 | hybrid |
| drop | 0.6245 | 0.7120 | -0.0875 | planrag |

## 优先级说明

1. **H-001 (top_k)**: ❌ 已拒绝 (n=20, 仅 musique +0.108, p=0.13)
2. **H-002 (LLM budget)**: ❌ 已拒绝 (musique +0.033, p=0.41)
3. **H-004 (生成质量)**: ✅ 已验证 — 检索不是瓶颈，57% 错误是措辞/格式，43% 是明显错误
4. **H-005 (答案契约)**: ❌ 已拒绝 — entity 约束过度导致多实体答案被截断
5. **H-006 (生成推理)**: 目标解决 43% 的明显错误 → 次高优先级
6. **H-007 (阶段诊断)**: ✅ 完成 — S2 捆绑是瓶颈, Oracle headroom 证实
7. **H-008 (PerPath提取)**: ✅ **SUPPORTED** — 修复 S2, 平均 dEM=+4.4pt(p=0.0105), musique +8.4pt(p=0.020)
8. **H-003 (evidence quality)**: 延迟,依赖 H-004

---

*本文件由 hypothesis-generator agent 维护。*  
*下一轮验证: Phase 3 Tier 1 实验后更新。*

---

### H-013: per-path 提取在 2wiki 上负效果（S1 空提取/污染导致 join 断链）——待设计

- **状态**: proposed（2026-08-06）
- **根因证据**（H-012 Tier 2 分析）:
  1. 2wiki 叠加方法 F1=0.629 vs baseline 0.78-0.79（**-16pt**）
  2. 28/100 样本 F1=0，其中 **27/28 join_output_rows=0**（96%）
  3. 手动复现：per-path 提取时 Dell Henderson#0 空 rows、Dana Blankstein#0 提取错误实体；union 提取（1 次看全部）正确提取 Dell Henderson
  4. Tier 1 (n=20) 叠加 0.776 >> 单维度 0.59，但 Tier 2 (n=100) 叠加 0.629——**Tier 1 是幸运样本，冒烟测试陷阱**
- **机制**: per-path 每 passage 独立提取，2wiki 需跨 passage 推理时产生空提取/无关实体，污染 S1 绑定 → join 断链
- **候选修复**: 
  a) 2wiki 上回退 union 提取（关系过滤后合并）
  b) per-path 提取后做关系过滤（只保留与问题相关的实体）
  c) 条件化：复杂多跳数据集禁用 per-path
- **风险**: per-path 在 musique/strategyqa 上正效果（那些数据集 WIN），全局移除会丢收益
- **待验证**: 需在 2wiki 上对比 union vs per-path 的 S1 提取质量

---

### H-013 验证结果 (2026-08-06, Tier 1 n=20, 2wiki)

**union vs per-path 配对**: wins=1 losses=2 ties=17, mean_diff=-0.021, p=0.786
- **结论: 否定简单回退方向**。union 提取在 2wiki 上不优于 per-path（甚至略差）。
- 2wiki 的 join 断链不是"per-path 提取"的锅——union 同样无法从跨 passage 推理提取中间变量。
- **真实根因**: 2wiki 的跨 passage 推理本质困难。S1 需要的中间实体（如 director）需从多 passage 交叉推理，单点提取器（无论 union/per-path）都无法可靠解决。
- **方向修正**: H-013 需转向架构级方案（如多 hop 迭代重检索、evidence 链推理），而非提取器切换。

---

### H-014: 桥接实体重检索回退可修复 2wiki join 断链

- **状态**: rejected_exact_intervention（Tier 1 验证完成, 2026-08-06）
- **根因证据**（H-012 Tier 2 + 手动验证）:
  1. 2wiki 叠加方法 28/100 样本 F1=0，其中 **27/28 join_output_rows=0**
  2. S1 提取不出跨 passage 的中间实体（如 director = Dell Henderson），per-path 空 rows 或错误实体
  3. S2 用空/错误绑定 → 检索无果 → `if not rows:` → status="empty" → 瞎猜
  4. **手动验证可行**: LLM 显式 "BRIDGE entity" 提示能正确推理出 "Dell Henderson"
- **机制**: slot 执行是链式的，任一环节空提取就整体断链。架构缺"推理中间实体 → 回填绑定 → 重试物化"的回退。
- **干预**: `ExecutionOptions.bridge_entity_fallback`。空提取/join 断链时（`if not rows:` + join-empty 分支），LLM 推理候选桥接实体 → 合成新 binding_context → `materialize_many` 重试。单轮、开关默认关闭。
- **验证方法**: Tier 1 (n=20, 2wiki) perpath-guard vs perpath-bridge → Tier 2 (n=100) 配对对比
- **预期效果**: 2wiki F1 从 0.629 提升至 ≥ react 0.794；join_output_rows=0 样本数下降 ≥50%
- **风险**: LLM 桥接推理不可靠；额外调用成本（仅空提取时触发）；drop 不受益（不同根因）
- **创建时间**: 2026-08-06
- **预注册文档**: 本计划文件 + 代码 commit 1ed57e2

**Tier 1 验证结果 (2026-08-06, n=20, 2wiki)**:
| 指标 | perpath-guard | perpath-bridge | Δ |
|------|--------------|----------------|-----|
| F1 | 0.7262 | 0.6333 | **-9.3pt** |
| join_output_rows=0 | 20/20 | 20/20 | 0 |
| budget_exceeded | 1 | 3 | +2 |
| bridge fallback 触发 | 0 | 8 | +8 |
| bridge 修复成功 | 0 | 7 | +7 |

- **结论: 拒绝**。桥接回退**机制层面**有效（8 次触发 7 次成功重检索），但 **答案质量不升反降**（F1 -9.3pt）：
  1. **修复后 join 仍空**：重检索的 rows 最终仍为空（`rows: []`），bridge 修复的实体与 S1 锚点仍不匹配——join 链结构性断裂，单实体推理无法修复
  2. **答案来自 evidence 而非 rows**：2wiki 答案生成走 evidence-based 路径（`_deterministic_output`），rows 空不影响答案，bridge 修复的 rows 从未到达生成阶段
  3. **预算副作用**：bridge 重物化消耗 LLM/检索预算，3 个样本因预算耗尽失败（guard 仅 1）
- **根因洞察**: 2wiki 的 join 断链不是"缺中间实体推理"，而是**多跳推理本质困难**（Dell Henderson 手动可推理，但规模化时 LLM 候选与 S1 锚点值不一致）。与 H-013 结论一致：2wiki 需要的不是提取器/重检索修复，而是**跨 passage 联合推理**（如 evidence 链直接生成答案，绕开 slot join 架构）。
- **生成证据再诊断**（Tier 1 n=20 追加）: 4 个 F1=0 样本中 **3 个 gold 在 evidence 里但生成选错**（如 Ham House 12 条 passage，答案却给 '22 September 1840'）。说明 2wiki 的失败不只在 join——**生成阶段在噪声/过量的 evidence 中选错事实**。graphrag 的优势是给生成器干净的前 10 排序 passage，SlotRAG 则倾倒所有 slot 检索物（可 12+ 条无排序）。
- **方向修正**: 不再尝试修复 join 链。2wiki 的修复应聚焦**生成证据策展**：给生成器提供筛选/排序后的 evidence（而非全量倾倒），或跨 passage 联合推理直接出答案。

---

### H-015: 生成证据策展（evidence curation）可修复 2wiki 生成错误

- **状态**: proposed（2026-08-06）
- **根因证据**（H-014 Tier 1 追加诊断）:
  1. 2wiki F1=0 样本中 3/4 gold 在 evidence 里但**生成选错**
  2. Ham House 案例: 12 条 evidence passage，生成器给 '22 September 1840'（错）而非 gold 'Ham House'
  3. graphrag 优势: 给生成器**干净的前 10 排序 passage**；SlotRAG 倾倒所有 slot 检索物（无排序、可 12+ 条）
- **干预**: 生成阶段证据策展。两个候选:
  a) **证据去重+上限**: 生成前对 evidence 去重、按槽位/相关性截断到 top-N（如 8 条），减少噪声
  b) **二次排序**: 用 question 对 evidence 重新排序（轻量 rerank），把最相关 passage 放前面
- **机制**: 生成器在噪声/过量 evidence 中无法聚焦问题相关事实。策展后 evidence 信号更清晰，生成更准。
- **验证方法**: Tier 1 (n=20, 2wiki) guard vs guard+curation → Tier 2 (n=100)
- **预期效果**: 2wiki F1 从 0.629 提升至 ≥ react 0.794（回收 gold-in-evidence-but-wrong 的 3/4）
- **风险**: 策展可能截掉必要 passage（多跳需跨 passage）；与 H-001/H-003 的"加 evidence"方向相反（但那些是检索侧，这是生成侧）
- **依赖**: H-014（已实现 bridge 可复用其证据选择逻辑）
- **创建时间**: 2026-08-06

**Tier 1 验证结果 (2026-08-06, n=20, 2wiki, variant a: dedupe+cap)**:
| 指标 | perpath-guard | perpath-curate | Δ |
|------|--------------|----------------|-----|
| F1 | 0.7262 | 0.7262 | 0 |
| evidence count | 7.3 | 4.5 | -2.8 |
| 变化的样本 | — | 0/20 | 0 |

- **结论: 拒绝 variant a**。证据去重+截断（7.3→4.5 条）**完全没改变任何答案**（0/20 变化）。
- **洞察**: 生成错误不是证据**数量/噪声**问题——即使只给 4.5 条策展后的 evidence，生成器仍选错。证据去重只去除重复源，但 2wiki 的跨 passage 推理需要**联合阅读**多条 passage，截断反而可能丢失必要信息。
- **方向**: H-015 剩余候选 b（question 相关性二次排序）可能更对症，但证据表明生成瓶颈是**推理深度**而非证据呈现。2wiki 需更根本的方案（如显式多跳推理链生成），或接受 2wiki LOSS 专注 drop。

---

### H-016: drop 用自由文本答案（short）替代 number 约束可修复多 token 答案

- **状态**: rejected_exact_intervention（Tier 1 验证完成, 2026-08-06）
- **根因证据**:
  1. 93/100 drop gold 是多 token 集合（`'99 99'`、`'Marriage living together'`）
  2. `_answer_kind` 对 drop 返回 `"number"` → 强迫生成器只输出单个数字
  3. 19 个 SlotRAG-only F1=0 中 17 个是多 token gold
- **干预**: MethodSpec.drop_short_answer → `_answer_kind` 对 drop 用 `"short"`（自由简洁多 token span）
- **Tier 1 验证结果 (n=20, drop)**:
  | 指标 | guard (number) | short | Δ |
  |------|---------------|-------|-----|
  | drop_f1 | 0.5805 | 0.5305 | **-5pt** |
  | 变化的样本 | — | 1 (worse) | -1 |
- **结论: 拒绝**。short 只改了 1 个样本且变差（gold `'70.7'` guard 输出 `'70.7'` F1=1.0，short 输出 `'70.7%'` F1=0.0——`%` 破坏 token 集）。生成器未因去约束而产出多 token 答案。
- **真实根因（追加诊断）**: 多 token gold 中 F1=0 的样本（如 gold `'13144 13144'` → pred `'7,761'`，gold `'255 3754'` → pred `'1,482 whites...'`）是**算术推理失败**（算错数），不是格式问题。drop 的 gold 是**计算值**（仅 3/100 在原文 passage 中出现），slot 提取无法做算术。
- **方向修正**: drop 的瓶颈是**算术推理能力**，非答案格式/证据/提取。SlotRAG 需在生成阶段显式做算术（类似 graphrag 的 thinking），或接受 drop LOSS（该数据集 gold 不可提取）。

---

### H-017: 生成阶段显式推理链（thinking）可修复 2wiki 多跳 + drop 算术

- **状态**: rejected_exact_intervention（Tier 1 验证完成, 2026-08-06）
- **根因证据**（H-014/H-015a/H-016 汇总）:
  1. 2wiki F1=0 样本中 3/4 gold 在 evidence 但**生成选错**（推理深度不足）
  2. drop 32 个 F1=0 全是**算术推理失败**（gold 是计算值，仅 3/100 在原文）
  3. graphrag 的优势 = 生成器 free-text thinking（逐步多跳/算术推理）
  4. SlotRAG `_structured_thinking_enabled` 硬编码 False（V5c 修复 thinking→over-caution）
- **干预**: MethodSpec.generation_thinking → `generate_answer_response` 首次尝试开启 `enable_thinking`（生成器先逐步推理再出最终 span），空答案重试时关闭（over-caution 恢复）。目标同时修复 2wiki（多跳推理）+ drop（算术）。
- **验证方法**: Tier 1 (n=20×2, 2wiki+drop) perpath-guard vs perpath-think 配对对比（单一变量）
- **预期效果**: 2wiki F1 ≥ 0.794（react）；drop drop_f1 ≥ 0.761（graphrag）
- **创建时间**: 2026-08-06
- **commit**: 7987181

**Tier 1 验证结果 (2026-08-06, n=20 2wiki + n=20 drop)**:
| 数据集 | guard | think | Δ | wins/losses/ties |
|--------|-------|-------|-----|------------------|
| 2wikimultihop | 0.7262 | 0.7262 | **0.0000** | 0/0/20 |
| drop | 0.6305 | 0.5805 | **-0.0500** | 0/1/19 |

- **结论: 拒绝**。显式 reasoning chain **完全无效**——2wiki 20/20 答案一字不差，drop 19/20 不变。
  1. **thinking 机制已生效**：`enable_thinking=True` 走通（generation_llm_calls=1 且首次尝试开启），但生成器输出的最终 span 与关闭 thinking 时**完全相同**——qwen3.6-27b 的 thinking 没有改变任何决策。
  2. **唯一变差的样本是 provider 异常**：drop_2548 think 返回 `SchemaError: expected exactly one Agnes tool call named emit_evidence_rows`（提取工具调用数异常 → status=failed, failure_category=configuration），与 thinking 无关，guard 同样本正常。
  3. **与 H-005/H-009 同模式**：又一种"提示/模式干预"在两个数据集上零效果。生成阶段瓶颈不是"缺思考时间"，而是**模型本身在给定 evidence 上的答案生成能力**（或检索/选入）。
- **方向修正**: 2wiki/drop 的生成瓶颈无法通过 `enable_thinking` 开关修复。剩余方向：
  a) **接受 2wiki+drop LOSS**，保 Coverage 3/5=60%——两个 LOSS 数据集 gold 均难以从 evidence 直接生成
  b) 生成器模型升级（qwen3.6-27b → 更强推理模型），但改模型超出 slot 架构干预范围
  c) drop 的算术问题：需要专门的数值计算模块（symbolic execution），非 LLM 生成可解

---

### H-019: 生成前证据相关性重排序（question-aware evidence re-ranking）可修复 2wiki

- **状态**: rejected_exact_intervention（Tier 1 验证完成, 2026-08-06）
- **根因证据**:
  1. 2wiki 46/100 wrong，其中 **34/46 gold 在 evidence 但仅 3/46 在 rows** —— slot-join 不物化 gold，生成器拿到无序 passage 堆
  2. graphrag 优势 = 给生成器排序的干净 passage；SlotRAG 倾倒无排序物化
  3. 与 H-015a 区别: H-015a 是**删减**（dedupe+cap），H-019 是**排序**（不删，只按问题相关性排前）
- **干预**: MethodSpec.evidence_rerank → `_finalize` 生成前用 bge-reranker 对 evidence source_span vs question 重排，取 top-8（排序为主，截断次要）。`reranker_calls` 遥测确认机制触发。
- **Tier 1 (n=20, 2wiki)**: guard 0.7262 → rerank 0.7262 (**Δ=0.0000**), 20/20 答案一字不差
  - 机制**已生效**: reranker_calls=2（排序确实执行）
  - **10/20 样本 evidence>8（rerank 截断到 8 确实改变了生成器看到的证据），0/10 答案变化**
- **结论: 拒绝**。生成器**完全无视 evidence 呈现**——即使把 12+ 无序 passage 重排为相关性 top-8，答案一字不差。生成器有内部答案先验，不因证据排序改变决策。
- **第 8 个连续零效果生成侧干预**: H-005/009/014/015a/016/017/018/019。
- **决定性洞察（Phase 3X §0.4 修正）**: 检索、证据量、证据排序、提示措辞、thinking、契约——全部不影响 qwen3.6-27b 的生成。**瓶颈是模型自身的答案先验**。但这限定在 scalar-slot architecture 的生成侧；typed relational execution（让 executor 承担 JOIN/COMPARE）是否改变此结论未验证（H-023~H-028）。

---

### H-020: extract-then-select 输出契约（候选抽取→选择，从构造上堵死内部先验）

- **状态**: rejected_exact_intervention（Tier 1 验证完成, 2026-08-06）
- **动机**: 前 8 个生成干预（H-005~H-019）全部改变**输入侧**（evidence 量/排序/prompt 措辞/thinking/契约）。2wiki 的病灶却在**输出侧**：34/46 wrong 样本 gold 连续在 evidence 里（如 'Konstfack' 在 1476 字 passage、'Hollywood' 在 George B. Seitz 页），但生成器自由发挥写内部先验答案。**架构级修复 = 从构造上约束输出必须 grounded。**
- **干预**: MethodSpec.extract_then_select → 两段式输出契约:
  1. Step 1 `emit_candidate_spans`: 只允许枚举 evidence 里的**连续子串**（verbatim），候选 grounded by construction
  2. Step 2 `emit_selected_answer`: 从候选中选一个（或空），必须匹配问题
  3. 契约失败（无候选/空选择/工具错误）→ **回退到自由生成**，只加不加伤
- **Tier 1 (n=20, 2wiki, commit ee4e4b3)**: guard 0.7262 → select 0.6155 (**Δ=-0.1107**), wins=0 losses=3 ties=17
  - 机制**已生效**: select 的 generation_llm_calls=2（两段各一次调用），guard=1
  - **3 个样本答案被改变，全部变差**: `Beji Caid Essebsi`→`Baker Brownell` (1.0→0)、`Broken Laws`→`Roy William Neill` (1.0→0)、`Schloss Persenbeug...`→`Archduke Hubert Salvator of Austria` (0.5→0.286)
  - **2/2 回归的是 previously-correct (F1 1.0)**；**8 个 guard-wrong 样本 0 个被恢复**
  - 两个 previously-correct 的 gold（'Broken Laws'、'Beji Caid Essebsi'）**都连续在 evidence 里**（'Broken Laws (1924)... directed by Roy William Neill'），但候选抽取把**导演名字**抽成候选、选择器选了导演而非电影名——比较类问题（"Which film has the director died earlier"）的中间实体泄漏进答案
- **结论: 拒绝**。即使把输出契约收窄到"只能从 evidence 选"、两段式强制 grounded，qwen3.6-27b 依然选错——不是它**不愿**从 evidence 选，而是**选不准**（比较类问题的推理选型本身超出该模型能力）。候选抽取成功（gold 在候选中）但选择步骤无法对齐问题语义。
- **第 9 个连续零/负效果生成干预**: H-005/009/014/015a/016/017/018/019/020 全部失败。
- **决定性洞察**: 生成器既无视 evidence 的**呈现**（H-019），也无法在 grounded 候选里**选准**（H-020）——瓶颈已从"输出契约"收敛到"模型选型能力"，架构侧（无论输入还是输出侧）无解。
- **后续**: 唯一剩余杠杆 = 模型级生成器升级（换更强推理模型）；否则接受 Coverage 2/5 收尾。

---

### H-021: 比较类问题的确定性比较算子（绕过生成器的架构级杠杆）

- **状态**: rejected_after_feasibility（2026-08-06）
- **动机**: H-020 暴露 2wiki **25/100 是比较类问题**（`Who is older`/`Which film was released earlier`），9 个比较类错误。比较类的正确答案是纯确定性可算的——如果 rows 物化了被比较实体的数值属性（出生/死亡/发布年份），一个 `min/max` 比较算子就能绕过生成器。这是 H-005~H-020 之后唯一的架构级杠杆（不碰生成器，用算子替代）。
- **可行性诊断**（H-012 Tier2 n=100）:
  1. **rows 无年份列**: rows 只物化 `answer` 列（115 次）+ 少量关系列，**没有任何出生/死亡/发布年份列**
  2. **离线 regex 模拟**: 对 9 个错误比较样本提取年份 + 排序 → **仅 1/9 恢复**（Marius Mitu vs Bea Palya，两实体出生日期精确到日在同 passage）
  3. **其余 8 个失败根因**: 年份**无法归属到实体**（Extreme Ops 只有 1959 一个年份 / Ngrtd 有 4 个年份分不清归属）、gold 不在 evidence（2/9）、**需要跨 passage join 到导演再找导演生日**（The Hellstrom / Treasure / Sunset Derby 等，导演关系跨 passage）
- **判决: 拒绝**。正确的年份归属本身就需要跨 passage multi-hop 推理（先 join 到导演，再物化导演的出生年）——这正是 H-014 桥接已证失败的环节。regex 做不到，而 LLM 提取又已被 H-014/H-020 证明在跨实体归属上不可靠。**恢复率 11% 远低于门禁 ≥50%**。
- **闭环**: 2wiki 的比较类错误既不能被提示修复（H-005~H-019），也不能被确定性算子修复（H-021）。比较类的正确答案依赖"先 join 到导演实体 → 再物化导演的出生年"——这个 join 是架构的 hard case，需要更强模型的跨实体推理。
- **系统性结论（Phase 3X §0.4 修正）**: 输入侧（H-005~H-019）+ 输出侧（H-020）+ scalar-rows 确定性算子（H-021）在 **current scalar-slot execution architecture 下已基本穷尽**。**但**：H-021 只证明「现有 rows 无足够 typed attributes 时 regex comparator 不可行」，**不排除 typed relational execution**（logical plan 明确要求物化比较属性）。2wiki/drop LOSS 的**最终判定延后**至 H-023~H-026 验证后。

### H-022: 2wiki 错误最终聚类——粒度错配不可修复 + 选型失败为真天花板（诊断, 非干预）

- **状态**: diagnostic（2026-08-06, H-012 Tier2 2wiki n=100 逐样本聚类）
- **动机**: H-021 后尝试纯后处理"答案收窄"（pred 截断到大写前缀）以修复过扩展——验证发现零改进、32 回归，转而做**逐样本错误聚类**定位真天花板。
- **错误账目**（2wiki n=100, 54 exact / 18 partial / 28 zero）:
  1. **粒度错配 14**（`Konstfack department of graphic design` vs `Konstfack`、`Hollywood, California` vs `Hollywood`、`Canadian-American` vs `Canadian`）: pred⊃gold，gold 是 pred 的有序子序列。**关键发现: evidence 里 gold 和 pred 两种粒度都连续出现**（`Konstfack` 和 `Konstfack department of graphic design` 同在 passage）→ 生成器选的是 evidence 里"更精细的下层实体标签"，不是幻觉。**信息论不可修复**——指标要求 gold 精确粒度，而后处理无法无监督推断问题语义要哪个粒度。
  2. **选型失败 20**（gold 连续在 evidence 但生成器选错候选）: 比较二选一选反（`Marius Mitu`/`Puberun`/`The Sweet Life Of Count Bobby`）、粒度二选一选错（`Sweden` vs `Greek-Swedish`）、错误地理位置（`Crenshaw` vs `South Los Angeles`、`Constantinople` vs `Hungary`）。**全部 status='ok'**（27/28 F1=0 是 ok 非 empty/budget）→ 架构链已跑通，失败纯在生成/选型。
  3. **其他 23**: 截断 4 + 实体选错 2 + 其余。
- **后处理不可行的决定性证据**:
  - naive 前缀收窄（pred→首个大写 run）：9 恢复但 **32 回归**（净 -9.97/100）——因为 already-correct 样本（`The Man with the Glass Eye`）同样是大写前缀结构
  - "循证收窄"（完整 pred 在 evidence 则不动，否则收窄到最长连续前缀）：0 改进 3 回归——因为**两类样本的完整 pred 都在 evidence 里连续**，判别条件无区分力
- **判决: 2wiki LOSS = 模型级选型天花板**。生成器在 evidence 呈现多个合法候选（比较的两个实体 / 两种粒度）时无法选对，且该选型能力 qwen3.6-27b 不具备。**无架构侧杠杆剩余**——后处理（收窄/循证）破坏 > 收益，算子（H-021）不可归属，提示/契约（H-005~H-020）零效果。
- **对论文的含义**: 2wiki LOSS 是"选型能力"的模型级天花板，非 SlotRAG 架构缺陷。诚实基线 Coverage 维持 40%（2/5），除非模型级生成器升级。

---

### H-023: Typed Relational Query-IR 离线编译审计（structure compiler, 非执行）

- **状态**: 部分支持（Phase 3X §22 step 7, 2026-08-07）
- **假设**: 复杂查询被压缩为标量绑定是根因；句型-结构驱动的确定性 Query-IR 编译器（→AnswerSchema + operator family + 逻辑 plan）能在不换模型下覆盖现有启发式模板之外的复杂问题。
- **方法**: 离线审计 DEVELOPMENT_SET 5×100（=H-012 同批），LLM-free 规则编译器测 plan_valid / answer_schema / operator_family 三个 gate。
- **结果**:
  | gate | 阈值 | 结果 |
  |------|------|------|
  | plan_valid | ≥95% | **100%** ✅ |
  | operator_family | ≥90% | **92.4%** ✅（分母=196 需运算题） |
  | answer_schema | ≥95% | **91.0%** ❌ |
- **关键发现**:
  1. **现有启发式模板覆盖仅 0-11%**（2wiki field_extremum 4/100）；句型-结构编译器把 operator_family 提到 92.4% —— 证明确定性编译器能覆盖模板之外的结构
  2. 2wiki 有 ~30 个未命中比较题，全是同一逻辑结构的不同措辞（`died earlier`/`who is older`/`released earlier`）→ 泛化 `_GENERIC_EXTREMUM` 可覆盖
  3. **answer_schema 91% 是单类别表达力上限**：drop 的 `JaMarcus Russell 29`、`33.7% were of germans` 是实体+数字复合，单类别无法表达 → 需 AnswerSchema 复合类别（COMPOSITE_ENTITY_NUMERIC / MULTI_SPAN / DATE_RANGE）
- **审计脚本**: `research/phase3x/run_h023_audit.py`（确定性、LLM-free、可复现）
- **判决**: **部分支持**。operator_family 92.4% 证明结构编译器是可行且必要的闭合法基础（覆盖 11%→92%）。answer_schema gate 未过（91% vs 95%），但瓶颈是**设计（单类别表达力）**非执行——升级 AnswerSchema 复合类别后复测。
- **下一步**: (1) AnswerSchema 复合类别升级复测； (2) 已进入 H-024 (Demand-Driven Materialization) 验证物化端（编译器已判对算子族 92.4%，但 date/number 属性列未可靠物化）

---

### H-024: Demand-Driven Attribute Materialization（typed 契约 date/number 扩展）

- **状态**: **rejected**（Tier 1, 2026-08-07, n=20, 2wiki+drop）— 从 pass_with_caveats 修正
- **假设**: H-023 只证明结构编译器能判对 operator_family，但 compare/arithmetic/field_argmin 需要的 typed 属性列（date/number）没被可靠物化——`extraction_tool` 只对 boolean 走 typed 契约，date/number 以 string 强转失败。把 typed 契约推广到 date/number（→ 规范化 ISO date / bare float），`_ordered_scalar`/`_as_number` 即可可靠消费。
- **方法**: `_normalize_typed_value` 规范化 + inline/bundle 双路径 abstention + `_field_extremum_template` BirthDate 标注 `variable_types=date`。新方法 `slotrag-grounded-frontier-perpath-typed`（=perpath-guard + typed on）。Tier 1 n=20 2wiki+drop，guard vs typed。
- **实现**: 已完成（commits `6db3f47` + `7767412`）。376 测试全过（2 个回归单测：bundle join-anchor 重附 + bundle typed metric 计数）。
- **诊断中修复的 pre-existing bugs**（独立于 H-024）:
  1. **bundle 路径 join 锚丢失** (`_extract_via_bundle`, planner.py:2082): role-projected extraction 丢弃 bound join key → `_join_rows` 0 匹配 → 2wiki 全部 join_out=0。修复: bundle 路径镜像 inline 路径的 `effective_bindings` 重挂（commit `8a40309`）。
  2. **bundle 路径 typed_extraction_answers 未计数** (planner.py:2101): inline 路径计数 typed_extraction_answers 但 bundle 路径只计 abstentions → H-024 gate metric 不可测量。修复: bundle 路径加对称计数（commit `7767412`）。
- **Tier 1 门禁结果（aggregate）**:

| 维度 | 2wiki | drop | 门禁？ |
|---|---|---|---|
| `typed_parse_success_rate` | 5/5 = **100%** | N/A (0 contracts) | ✅ |
| 比较/算术 F1 (Δ≥-2pt) | +0.48pt | 0.00pt | ✅(aggregate) |
| 全量 F1 无回归 | +0.48pt | 0.00pt | ✅(aggregate) |

- **⚠️ 判决修正：aggregate 门禁通过是假象**（by typed-attribution）
  - 3 个 aggregate "win"（6ebdbede0b/+0.17, fa3e9b640b/+1.0, 89a3abec0b/+0.43）**全部 typed_contracts=0** → 是 run 间噪声，非 typed 效果
  - **typed 契约净效应 = 帮助 0 题 + 破坏 1 题**：
    - 5 个 typed contracts → 3 题（b081, 1b36, e084）
    - b081/1b36: guard F1 也 0 → typed 未纠正任何错误
    - **e084: guard 1.0 → typed 0.0**（ISO 日期 `1955-01-26` echo，gold 表面形式 `"January 26, 1955"`）
  - **由机制决定、非随机**: typed 契约 `extraction_tool` 指示 LLM "Output as ISO YYYY-MM-DD"（planner.py:176）→ rows 变 ISO → 答案生成器 echo ISO。**typed date 契约与 2wiki 答案格式天然冲突**。
  - drop: 20 样本全 `EvidenceAnsweringQuestion` 单 slot 计划，0 operators/0 joins → number-typed 架构性不可用
- **结论**: **拒绝**。typed date 契约把内部消费值（ISO）与外部呈现值（表面形式）混淆——`extraction 契约` 强制 ISO 输出，破坏 2wiki 答案格式，且 0 题被 typed 挽回。typed 契约要成立需**区分内部值 vs 呈现值**（算子层消费 ISO、答案层回注表面形式），但 H-024 无此区分，且 `_ordered_scalar`/`_as_number` 本就能从表面形式解析（预规范化是个冗余破坏）。
- **判决**: rejected（H-024 所需的方向保持开放，需 H-025 用"答案层回注表面形式"而非"提取层强制 ISO"实现）

### H-025: typed 契约保留表面形式（surface-form preservation，撤销 ISO 重写）

- **状态**: **pass（有保留）**（Tier 1, 2026-08-07, n=20, 2wiki+drop）
- **假设**: H-024 的 ISO 重写是纯破坏——`_ordered_scalar`/`_as_number` 本就能从表面形式 `"January 26, 1955"` 解析（`_as_date` 支持 `%B %d %Y`），预规范化 bindings 是假设了不存在的瓶颈。typed 契约的正确形态是 "validate-only, 不改写"：LLM 从 passage 原样提取，bindings 保持表面形式，`_normalize_typed_value` 只校验可解析性（不可解析 → abstain）。
- **方法**: `typed_surface_form: bool` flag（MethodSpec + SlotMaterializer）。`extraction_tool` date/number schema 改指示 "extract verbatim"；`_normalize_typed_value` 加 `preserve_surface=True` 返回原字符串。新方法 `slotrag-grounded-frontier-perpath-typed-surface`。Tier 1 n=20 2wiki+drop，guard vs typed-surface。
- **实现**: 已完成（commit `a6373c7`）。380 测试全过（含 6 个 H-025 surface-form 单测）。
- **Tier 1 门禁结果**:

| 维度 | 2wiki | drop | 门禁？ |
|---|---|---|---|
| `typed_parse_success_rate` | 5/5 = **100%** | N/A (0 contracts) | ✅ |
| 比较/算术 F1 (Δ≥-2pt) | -1.67pt（回归样本 typed_contracts=0, 纯噪声） | 0.00pt | ✅ |
| 全量 F1 无回归 | -1.67pt | 0.00pt | ✅ |
| **e084 恢复** | treat=1.0, guard=1.0, answer `"January 26, 1955"` surface | — | ✅ |
| join_output_rows | treat=35 = guard=35（算子零退化） | 0/0 | ✅ |

- **typed 契约样本明细（仅 3 题命中, 5 contracts）**:
  - `e084363c`（Birthday date×2）: treat=1.0 = guard=1.0。**对比 H-024 的 ISO 重写 0.0 → surface-form 恢复 1.0**。表面形式保留机制验证 ✅
  - `b081e084`（BirthDate date×2）: 两侧均 `budget_exceeded`（非回归，typed 2/2 提取成功）
  - `1b36c01f`（answer boolean×1）: 两侧均 0.0，boolean 契约是 H-012 既有功能，非 H-025 新代码
- **唯一 F1 回归** `6ebdbede`（2wiki -0.333）: **typed_contracts=0**，plan 不同（`BuriedIn` vs `BurialPlace`）→ run-to-run plan 不稳定噪声，非 H-025 因果
- **drop 未激活**: 0 个 number/date-typed slots 被编译（与 H-024 同根因：arithmetic 算子不编译 typed variable_types）→ date/number surface 提取在 drop 无法评估
- **结论**: **通过（有保留）**。决定性证实了 H-025 核心假设：**typed 契约的正确形态是 validate-only 保留表面形式**（e084 从 H-024 的 0.0 恢复到 1.0，parse rate 100% 不降，算子零退化）。但 n=20 下 typed 契约仅激活 5 次、aggregate 中性——**治疗相对"无契约"的真实增益未测出**（guard 侧 e084 本就 1.0）。需要 Tier 2（n=100）判断 surface-form 契约是否有净收益，或作为 H-026/H-027 算子层 typed 执行的正确基底。
- **价值定位**: 修正 H-024 的错误设计（内部值 vs 呈现值分离），不是独立收益假设。为 H-026/H-027 的算子层 typed 执行铺路。

### H-026: 确定性子类型-关系编译器回退（close 编译→算子激活缺口）

- **状态**: **closed（未构建）**（2026-08-07, 方向重估决定）
- **动机（激活缺口）**: H-023 离线审计证明确定性编译器能把 operator_family 覆盖从模板 11% 提到 **92%**（2wiki 36/100 需运算、drop 82/100），但**运行时从未激活**：
  - `slot_plan_tool` schema 已允许 LLM 输出 `variable_types` + `operators`（planner.py:72/108），但 LLM 在普通题上几乎不产出 typed 算子
  - 仅 2 个硬编码模板标注 typed：`_field_extremum_template`（只匹配 `born` 极值）覆盖 4/100 2wiki；`_polar_comparison_template`（`same/both`）覆盖 5-7%
  - H-024/H-025 运行时确认: 2wiki typed 契约仅激活 5 次，drop **0 激活**（0 number/date typed slots 被编译）
- **拟议干预**（用户已否决构建）: 把 H-023 的确定性检测器（`_COMPAR_SUPER`/`_NUMERIC`/`_GENERIC_EXTREMUM`）接成 compile fallback——当问题需要 typed op 且 LLM 产出退化 plan 时，用 `OperatorClassifier.alloc_plan`（typed operators + variable_types）替代
- **为何停止（诚实重估）**:
  1. **算子执行层不是瓶颈**（H-025 已证: `apply_operators` 已能从表面形式解析，join_output_rows 双侧一致）
  2. **瓶颈在编译→算子激活**，而激活只能靠把 H-023 的**审计分类器**引入运行时——那是把"离线 oracle"移植成"运行时编译器"，超出当前假设范围（H-023 是审计、非执行）
  3. **2wiki/drop LOSS 的最终判定**已由 H-022（选型天花板）+ H-024/H-025（typed 物化在运行时几乎不激活）双重确认: typed relational execution 在 dev 集上**无可用基底**
- **结论**: **typed relational execution 方向在 DEVELOPMENT_SET 上暂停**。H-026/H-027/H-028 无构建价值——编译→算子激活缺口只能由"把审计分类器升级为运行时编译器"闭合，那是架构级新方向（超出 Phase 3X 的干预假设框架），且不保证换模型前能改变 qwen3.6-27b 的生成决策
- **Coverage 影响**: 维持 **40%**（2/5: musique/strategyqa WIN, 2wiki/drop LOSS, hotpotqa TIE）。typed relational 不构成覆盖提升路径

### H-018: 生成证据保真（evidence-fidelity prompt）可修复 hotpotqa 截断/超集错误

- **状态**: rejected_exact_intervention（Tier 2 验证完成, 2026-08-06）
- **根因证据**（H-012 Tier 2 逐样本分析, hotpotqa）:
  1. 29/100 答案错，其中 **25/29 gold 在 evidence 里**但生成选错边界/实体
  2. 机制拆分: **7 截断** (pred⊂gold, 如 `'east'` vs `'the east of Ireland'`)、**8 超集** (gold⊂pred)、**14 错实体** (disjoint)
  3. 根因: 生成 prompt "Return only a concise answer span" 纯简洁偏好
  4. 可行性否决: 机械 span 扩展破坏 17/66 both-right 样本（F1 1.0→<0.3）→ 禁止边界手术
- **干预**: MethodSpec.generation_fidelity → short/number 分支用软保真指令（"return the fuller form present in evidence, do not shorten names/drop qualifiers"）。与 H-005 区别: 软性朝"更完整"推，非硬 canonical 强制。
- **Tier 1 (n=20)**: guard 0.7933 → fidelity 0.8183 (+2.5pt, 1 win/0 loss), `'east'`→`'the east of Ireland'` 截断恢复 ✓ → 通过门禁
- **Tier 2 (n=100)**: guard 0.8131 → fidelity 0.8242 (**+1.1pt, p=0.60**), wins=7 losses=6
  - **改善 7**: 截断恢复 (`east`→`the east of Ireland` +0.5), 错实体纠正 (`English`→`Scottish` 0→1.0), 空答案修复 (`''`→`Rio Ferdinand` 0→0.8), 超集收窄 (`Intelligent Design: ...`→`Intelligent Design (book)`)
  - **回归 6/4 个 previously-correct**: **4 个 F1 1.0 样本被破坏** (`Dallas`→`Dallas, Texas`, `McLaren Vale`→`McLaren Vale and Willunga`, `Brent Robert Barry`→`Brent Barry`, `The Simpson family`→`...except for Lisa...`)
- **结论: 拒绝**。软保真指令修复截断但引入**过度扩展**新失败模式——模型无法区分"该完整"与"该简短"（无 gold 信号）。+1.1pt 不显著 (p=0.60)，且回归的 4 个 previously-correct 违反"both-right 零回归"门禁。
- **第 7 个连续零/负效果生成干预**: H-005(契约)/H-009(score)/H-014(桥接)/H-015a(策展)/H-016(short)/H-017(thinking)/H-018(保真) 全部失败。
- **系统性结论**: hotpotqa 剩余 29 错误的生成瓶颈**无法用 prompt 级干预修复**（模型无法无 gold 区分边界）。路径只剩:
  a) **模型级生成器升级**（更强推理模型，超出 slot 架构范围）
  b) **接受 hotpotqa TIE**，Coverage 保持 2/5
  c) 2wiki/drop 同理——全数据集生成瓶颈模型级不可解
