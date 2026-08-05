# HYPOTHESES.md — 研究假设池

> **维护者**: hypothesis-generator agent  
> **最后更新**: 2026-08-05T18:30:00Z  
> **活跃假设数**: 0/5 (H-010 已否决, H-006 依赖缺失)  
> **当前轮次**: Phase 3R — H-010 可行性否决（投票/compact-value 均不可行），H-006 前提不成立

---

## 假设池状态

| 状态 | 数量 | 说明 |
|------|------|------|
| proposed | 0 | — |
| supported | 1 (H-008) | PerPath 提取修复 S2，Tier 1 验证支持 |
| provisionally_supported_pending_stage_audit | 1 (H-004) | 待阶段级审计 |
| stratum_specific_signal | 1 (H-001) | 仅 musique +0.108 是信号,非全局 |
| rejected_exact_budget_configuration | 1 (H-002) | 仅拒绝该预算配置 |
| rejected_exact_intervention | 2 (H-005, H-009) | H-005 entity契约; H-009 score-guided提取 |
| rejected_after_feasibility | 1 (H-010) | 跨来源投票+compact-value 均不可行 |
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
