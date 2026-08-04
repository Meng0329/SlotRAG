# CURRENT_STATE_AUDIT.md — 阶段 0 审计报告

> **审计时间**: 2026-08-04  
> **审计范围**: 全部历史 run、manifest、per_question 结果、配置演化、代码防护  
> **审计方法**: 只读，不修改核心代码，仅生成诊断报告

---

## Q1. 哪些 eval 样本已暴露？

**结论**: seed=2040 的 n=100/数据集 eval 样本已暴露。

| 数据集 | 总 eval 样本 | 已暴露 | 暴露率 | 干净可用 |
|--------|-------------|--------|--------|----------|
| hotpotqa | 7,405 | 250 | 3.4% | 7,155 |
| 2wikimultihop | 12,576 | 249 | 2.0% | 12,327 |
| musique | 2,417 | ~500 | ~21% | ~1,900 |
| strategyqa | 687 | ~500 | ~73% | ~187 |
| drop | 9,535 | ~500 | ~5% | ~9,000 |

**来源**: `research/EXPOSED_SAMPLE_REGISTRY.csv` — 扫描 124 个历史 run 的 samples/ 目录和 per_question.csv。

**关键发现**: hotpotqa 和 2wikimultihop 有大量干净样本（96-98%），完全足够构造 SEALED_FINAL_SET。strategyqa 暴露率较高，需谨慎处理。

---

## Q2. 哪些逐题结果已读？

**结论**: 以下逐题结果文件已被读取并暴露：

1. **`runs/vldb2027-submission-qwen36-v3-rescored-v2-final/summaries/main_comparison/per_question.csv`**
   - 7 方法 × 5 数据集 × n=100 = 500 行
   - 包含 question_id, method, dataset, em, f1, status, answer, prediction
   - **已读取**: 在 previous conversation 中用于分析 "超 90% SOTA" 结论

2. **`runs/slotrag-v74-qwen-hybrid-reranker-v6/training_2k_progress.jsonl`**
   - V6c 训练集逐题结果（train split）
   - **已读取**: 在 previous conversation 中用于分析失败模式

3. **各 baseline 的 items/ 目录下的 .json 文件**
   - 包含完整推理轨迹、检索结果、生成过程
   - **已暴露**: 但未在对话中逐条分析

**影响**: 所有已读取的逐题结果构成 contaminated diagnostic data，不能用于 Tier4/Tier5 验证。

---

## Q3. 哪些配置是在看过 eval 结果后产生的？

**结论**: 以下配置演化是在查看 eval 结果后进行的：

1. **V5c generation fix** (`generation.py`):
   - `_structured_thinking_enabled()` 返回 `False`
   - **触发原因**: V4 实验发现 thinking 导致 over-caution，EM 下降
   - **是否基于 eval 结果**: 是，基于 V4 在 seed=2040 样本上的表现

2. **V6a question_grounded_retrieval** (`methods.py`):
   - `question_grounded_retrieval=True` 永久合并到基础 slotrag 方法
   - **触发原因**: V6a 实验发现仅此一项就让 EM 从 59% 提升到 61.54%
   - **是否基于 eval 结果**: 是，基于 V6a 在 seed=2040 样本上的表现

3. **V6b 200 样本规模验证**:
   - **触发原因**: V6a 通过 90% SOTA 后进行规模验证
   - **是否基于 eval 结果**: 是，基于 V6a 在 seed=2040 样本上的表现

**影响**: 这些配置调整是**基于 contaminated eval 样本的诊断结果**进行的。虽然调整本身合理（fix 明显 bug），但不能声称这些配置是"独立验证"的。

---

## Q4. 是否有数据泄漏（leakage）？

**结论**: **有，但有限**。

### 已确认的泄漏：

1. **train/eval split 错配**（已由 agent 2 逐 qid 证实）：
   - V6c `qo_v74_training_2k` 的 597 个 hotpotqa 题全部来自 **train set**（逐 qid 验证）
   - 所有 baseline 跑在 **evaluation split**（seed=2040）
   - **影响**: "超 90% SOTA" 结论无效，因为比较的是不同 split

2. **eval 样本已暴露**：
   - seed=2040, n=100/数据集 的 eval 样本已运行多个 baseline
   - **影响**: 不能用于 Tier4/Tier5 验证，只能作 diagnostic

3. **配置演化基于 contaminated eval**：
   - V5c, V6a, V6b 的配置调整基于 seed=2040 样本
   - **影响**: 不能声称这些配置是"独立验证"的

### 未发现的泄漏：

1. **没有 train 样本被用于 eval 比较**（除了 V6c 的 split 错配）
2. **没有 eval 样本被用于训练**（SlotRAG 是 inference-time 方法，无训练）
3. **没有代码修改基于 eval 结果的泄漏**（除了上述配置调整）

**总结**: 泄漏主要来自 split 错配和 eval 暴露，但范围有限，可通过 SEALED_FINAL_SET 修复。

---

## Q5. 哪些历史结论必须撤销？

**结论**: 以下结论必须撤销：

### 必须撤销：

1. **"超 90% SOTA"**（V6a, V6b, V6c）：
   - **原结论**: hotpotqa EM=61.54% > 68% (ircot)，超 90% SOTA
   - **撤销原因**: train/eval split 错配，比较的是不同数据
   - **正确做法**: 在 SEALED_FINAL_SET 上重新评估

2. **"question_grounded_retrieval 突破 90% SOTA"**（V6a）：
   - **原结论**: 仅此一项就让 basic slotrag 通过 90% SOTA
   - **撤销原因**: 基于 contaminated eval 样本
   - **正确做法**: 在 SEALED_FINAL_SET 上重新验证

3. **"V6b 200 样本规模验证通过"**：
   - **原结论**: 4/4 指标超 90% SOTA
   - **撤销原因**: 基于 contaminated eval 样本
   - **正确做法**: 在 SEALED_FINAL_SET 上重新验证

### 可保留但需限定：

1. **"V5c generation fix 有效"**：
   - **可保留**: thinking 导致 over-caution 是明显 bug，修复合理
   - **需限定**: 修复本身有效，但效果量需在 SEALED_FINAL_SET 上重新测量

2. **"baseline 归一化一致"**：
   - **可保留**: SQuAD/HotpotQA 标准归一化，EM/F1 比较本身公平
   - **需限定**: 归一化一致不等于 split 一致

---

## Q6. 哪些 baseline 只是 adapted？

**结论**: **所有 baseline 都是 adapted**。

| 方法 | exact_upstream_execution | 适配说明 |
|------|------------------------|----------|
| hybrid | false | 使用 SlotRAG 框架的 hybrid 检索，非官方实现 |
| ircot | false | 使用 SlotRAG 框架的 ircot 调度，非官方实现 |
| react | false | 使用 SlotRAG 框架的 react 调度，非官方实现 |
| planrag | false | 使用 SlotRAG 框架的 planrag 调度，非官方实现 |
| srag | false | 使用 SlotRAG 框架的 srag 调度，非官方实现 |
| graphrag | false | 简化实现，非官方 graphrag |
| slotrag | - | 本方法 |

**来源**: manifest.json 中 `verification_status: "UNVERIFIED"`，`exact_upstream_execution_verified: false`。

**影响**: adapted baseline 不能作为 "exact upstream baseline" 用于主覆盖率计算。只能进入补充表或 adapted comparison。

---

## Q7. 哪些 baseline 用了不同预算/模型？

**结论**: **所有 baseline 共享相同预算和模型**。

| 配置项 | 值 |
|--------|-----|
| model | qwen3.6-27b |
| max_tokens | 2048 |
| temperature | 0.0 |
| max_steps | 4 |
| max_llm_calls | 64 |
| max_retrieval_calls | 4 |
| question_timeout_seconds | 300.0 |

**来源**: manifest.json `provider_config.agnes` 和 `suite.budget`。

**影响**: 预算一致，但 adapted baseline 的实现效率可能不同（如 planrag 有 30 个 timeout failures）。

---

## Q8. 是否有 baseline 失败样本被排除？

**结论**: **有，但未被排除**。

### Baseline 失败统计：

| 方法 | 总样本 | 有效 n | 失败数 | 失败率 |
|------|--------|--------|--------|--------|
| graphrag | 500 | 500 | 0 | 0% |
| hybrid | 500 | 500 | 0 | 0% |
| ircot | 500 | 500 | 0 | 0% |
| react | 500 | 500 | 0 | 0% |
| planrag | 500 | 470 | **30** | **6%** |
| slotrag | 500 | 489 | 11 | 2.2% |
| srag | 500 | 494 | 6 | 1.2% |

**来源**: per_question.csv 中 status != 'ok' 的行。

**关键发现**: planrag 有 30 个 timeout failures（主要是 hotpotqa n=90, musique n=87）。这些失败样本**未被排除**，而是保留在结果中（status='failed'）。

**影响**: 直接比较 EM/F1 时，planrag 的有效样本数较少（94%），可能导致不公平比较。需要在统计分析中处理。

---

## Q9. 是否有不同有效样本数却直接比较？

**结论**: **有，存在潜在不公平比较**。

### 各数据集各方法有效样本数：

**hotpotqa**:
- graphrag, hybrid, ircot, react, srag: n=100
- slotrag: n=98
- planrag: **n=90** (10 failures)

**2wikimultihop**:
- graphrag, hybrid, ircot, react, slotrag: n=100
- srag: n=99
- planrag: n=96

**musique**:
- graphrag, hybrid, ircot, react: n=100
- srag: n=95
- slotrag: n=91
- planrag: **n=87** (13 failures)

**strategyqa**:
- 所有方法: n=100 (无失败)

**drop**:
- 所有方法: n=100 (无失败)

**影响**: planrag 在 hotpotqa 和 musique 上有效样本数显著较少（90% 和 87%）。如果直接比较 EM/F1 而不报告 valid_n，可能误导读者。

**建议**: 主表必须报告 valid_n，统计分析需处理不同有效样本数（如 bootstrap CI）。

---

## Q10. 是否有缓存/索引/语料版本错配？

**结论**: **无明显错配**。

### 语料版本检查：

1. **Passage index**:
   - hotpotqa: 483,921 passages (4.5GB base)
   - 2wikimultihop: 401,090 passages
   - **一致性**: 所有 baseline 和 SlotRAG 使用相同索引

2. **Embedding model**:
   - Qwen3-Embedding-0.6B (1024-dim)
   - **一致性**: 所有方法使用相同 embedding

3. **Reranker model**:
   - bge-reranker-v2-m3
   - **一致性**: 所有方法使用相同 reranker

4. **LLM model**:
   - qwen3.6-27b (via agnes endpoint)
   - **一致性**: 所有方法使用相同 LLM

**来源**: manifest.json `provider_config` 和 memory 文件。

**影响**: 无版本错配，检索/生成基础设施一致。

---

## Q11. 是否有 train/eval 命名与真实数据来源不一致？

**结论**: **有，已确认的不一致**。

### 不一致实例：

1. **V6c `qo_v74_training_2k`**:
   - **命名暗示**: "training_2k" 可能暗示使用 train split
   - **实际来源**: hotpotqa 的 train split（逐 qid 验证）
   - **问题**: 与 baseline 的 evaluation split 不一致
   - **影响**: 导致 "超 90% SOTA" 结论无效

2. **stage 名称 vs split 映射**:
   - manifest.json 中 `stages.main_comparison.split = "evaluation"`
   - 但 V6c 的 stage `qo_v74_training_2k` 未在 manifest 中定义
   - **影响**: 无法通过 manifest 自动推断 split，需人工验证

**建议**: 所有新 run 必须在 manifest 中明确声明 split，禁止依赖命名约定。

---

## Q12. 当前能合法成立的最强结论？

**结论**: 以下结论**当前合法成立**：

### 1. 代码级事实（已验证）：

1. **V5c generation fix 有效**:
   - `_structured_thinking_enabled()` 返回 `False`
   - thinking 导致 over-caution 是明显 bug
   - **证据**: V4 → V5c EM 提升（但效果量需重新测量）

2. **baseline 归一化一致**:
   - SlotRAG 和 baseline 使用相同 SQuAD/HotpotQA 标准
   - EM/F1 计算逻辑逐字符一致
   - **证据**: `src/slotrag/benchmarking/metrics.py` 代码审计

3. **publication_gate.py 有防护**:
   - `training_split_not_for_publication` 检查
   - **证据**: `src/slotrag/benchmarking/publication_gate.py` 代码审计

### 2. 仅文档记载（未独立验证）：

1. **"question_grounded_retrieval 有效"**:
   - 文档声称 EM 从 59% 提升到 61.54%
   - **问题**: 基于 contaminated eval 样本
   - **待验证**: 需在 SEALED_FINAL_SET 上重新测量

2. **"V6b 200 样本规模验证通过"**:
   - 文档声称 4/4 指标超 90% SOTA
   - **问题**: 基于 contaminated eval 样本
   - **待验证**: 需在 SEALED_FINAL_SET 上重新测量

### 3. 不可比较结果（需重新评估）：

1. **所有 "超 90% SOTA" 结论**:
   - **问题**: train/eval split 错配
   - **待重新评估**: 需在 SEALED_FINAL_SET 上重新比较

### 4. 当前最强配置（待验证）：

- **SlotRAG v74 hybrid + reranker**
- **配置**: BM25 + Qwen3-Embedding-0.6B + bge-reranker-v2-m3 + question_grounded_retrieval=True
- **声称效果**: hotpotqa EM≈68%, F1≈78%（基于 train split，待验证）
- **待验证**: 需在 SEALED_FINAL_SET 上重新测量

### 5. 真实瓶颈：

1. **planrag timeout failures**: 30 个样本因 timeout 失败（6%）
2. **slotrag planning failures**: 11 个样本因 "no join path" 失败（2.2%）
3. **split 错配**: 导致所有历史结论无效

### 6. 风险点：

1. **adapted baseline**: 所有 baseline 都是 adapted，不能作为 exact upstream
2. **eval 暴露**: seed=2040 样本已污染，不能用于 Tier4/Tier5
3. **统计功效**: n=100 可能不足以检测小效应量

---

## 审计结论

### 当前状态：

1. **Phase 0 审计完成**: EXPOSED_SAMPLE_REGISTRY.csv 已生成，CURRENT_STATE_AUDIT.md 已完成
2. **干净评估集可用**: hotpotqa 7,155 (96.6%), 2wiki 12,327 (98.0%)
3. **publication_gate.py 有防护**: 可阻止 train split 结果发表
4. **历史结论需撤销**: "超 90% SOTA" 结论无效

### 下一步（Phase 1+）：

1. **构造三集合**: DEVELOPMENT_SET, DISJOINT_VALIDATION_SET, SEALED_FINAL_SET
2. **功效分析**: 确定最小样本量
3. **冻结协议**: FROZEN_PROTOCOL.md
4. **重新评估**: 在 SEALED_FINAL_SET 上重新测量 SlotRAG 和 baseline

### 用户确认点：

**请确认 CURRENT_STATE_AUDIT.md 内容，然后进入 Phase 1。**

---

*审计完成时间: 2026-08-04*  
*审计方法: 只读，不修改核心代码*  
*审计依据: manifest.json, per_question.csv, EXPOSED_SAMPLE_REGISTRY.csv, publication_gate.py, metrics.py*
