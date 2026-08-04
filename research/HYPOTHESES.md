# HYPOTHESES.md — 研究假设池

> **维护者**: hypothesis-generator agent  
> **最后更新**: 2026-08-05T04:30:00Z  
> **活跃假设数**: 2/3 (H-005, H-006)  
> **当前轮次**: Phase 3 Round 3

---

## 假设池状态

| 状态 | 数量 |
|------|------|
| proposed | 2 (H-005, H-006) |
| testing | 0 |
| validated | 1 (H-004) |
| rejected | 2 (H-001, H-002) |
| deferred | 1 (H-003) |

---

## 活跃假设

### H-001: 检索 top_k 增加可显著提升 evidence recall

- **状态**: rejected
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

- **状态**: rejected
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

- **状态**: validated
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

- **状态**: proposed
- **描述**: recall=1.0 但 EM=0 的错误中 ~57% 是 F1≥0.5 的接近正确答案（措辞/格式与黄金答案不完全一致，如 'Crown Holdings' vs 'Crown Holdings, Inc.')。改进答案契约或措辞规范化可回收这些。
- **预测**: 对 F1≥0.5 的接近正确错误，改进答案生成提示（如要求输出规范实体名、避免描述性答案）可提升 EM
- **验证方法**: Tier 1 实验，修改 generation prompt 或 answer contract
- **预期效果**: hotpotqa primary_score +5-10%（回收 12/21 个接近正确错误）
- **风险**: 可能只是部分可回收；生成提示改动可能引入新问题
- **依赖**: H-004
- **创建时间**: 2026-08-05T04:30:00Z
- **最后更新**: 2026-08-05T04:30:00Z

### H-006: 生成阶段推理质量（evidence→answer）是 43% 明显错误的根因

- **状态**: proposed
- **描述**: recall=1.0 但 EM=0 的错误中 ~43% 是 F1<0.5 的明显错误（答案跑偏，如输出 'University of Mississippi' 但问题问别的）。说明生成阶段未正确利用已检索到的证据。
- **预测**: 改进 evidence→answer 的推理（如增加结构化证据利用）可提升
- **验证方法**: 诊断 F1<0.5 样本的生成失败原因，针对性设计
- **预期效果**: hotpotqa primary_score +3-5%
- **风险**: 根因可能是规划质量而非生成
- **依赖**: H-004
- **创建时间**: 2026-08-05T04:30:00Z
- **最后更新**: 2026-08-05T04:30:00Z

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
4. **H-005 (答案契约)**: 目标回收 57% 的接近正确错误 → 最高优先级
5. **H-006 (生成推理)**: 目标解决 43% 的明显错误 → 次高优先级
6. **H-003 (evidence quality)**: 延迟,依赖 H-004
3. **H-003 (evidence quality)**: 依赖 H-001，可叠加

---

*本文件由 hypothesis-generator agent 维护。*  
*下一轮验证: Phase 3 Tier 1 实验后更新。*
