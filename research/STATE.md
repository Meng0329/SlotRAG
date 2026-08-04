# STATE.md — SlotRAG-X 研究状态快照

> **最后更新**: 2026-08-04T22:00:00Z  
> **更新者**: documentation-writer agent  
> **当前阶段**: Phase 2（SOTA 账本）— 已完成，诚实基线建立

---

## 项目概况

| 项目 | 状态 |
|------|------|
| 项目名称 | SlotRAG-X: Slot-based Retrieval-Augmented Generation |
| 目标会议 | PVLDB 2027 |
| 当前方法 | SlotRAG v74 hybrid + reranker |
| 核心架构 | Slot Compiler → Adaptive Slot Materializer → Generator |
| LLM | qwen3.6-27b (internal endpoint) |
| Embedding | Qwen3-Embedding-0.6B (1024-dim) |
| Reranker | bge-reranker-v2-m3 |

---

## 当前阶段状态

### Phase 0: 审计 ✅ 已完成
- [x] git checkpoint 创建 (`research/phase0-audit`, `e11d4fc`)
- [x] EXPOSED_SAMPLE_REGISTRY.csv 生成 (3,508 unique samples)
- [x] CURRENT_STATE_AUDIT.md 生成 (12 问全部回答)
- [x] EXPERIMENT_BUDGET.md 生成
- [x] 现有测试运行 (355 pass, 1 fail, 1 skip)
- [x] 数据集校验和验证 (manifest 中已有)

### Phase 1: 研究基础设施 ✅ 已完成
- [x] 9 个子 Agent 定义 (.claude/agents/)
- [x] STATE.md
- [x] HYPOTHESES.md
- [x] EXPERIMENT_LEDGER.csv
- [x] FAILURE_LEDGER.csv
- [x] DECISIONS.md
- [x] SOTA_LEDGER.md
- [x] RELATED_WORK_MATRIX.csv
- [x] Makefile 入口

### Phase 2: SOTA 账本 ✅ 已完成 — 诚实基线
- [x] 三集合构造 (DEVELOPMENT 30% / VALIDATION 30% / TEST 40%, seed=2027)
- [x] 功效分析 (n=100 足够, 所需 n=2-18)
- [x] FROZEN_PROTOCOL.md 冻结
- [x] SOTA_LEDGER.md 诚实填充 (**0/10 = 0% Strongest-Baseline Coverage**)
- [x] 最强 baseline 确定 (ircot/graphrag/planrag/hybrid)
- [x] drop 主指标改为 drop_f1 (EM 对所有方法无效)

### Phase 3: 假设循环 🔄 进行中
- [x] 深度失败诊断完成
  - **strategyqa EM=0.08 是格式假象**：用 primary_score (accuracy) 实际 0.84
  - **drop EM 无效**：已用 drop_f1 (0.62)
  - **真实瓶颈**：hotpotqa/2wiki evidence_recall 低 (0.755/0.810 vs 1.000)，musique budget_exceeded (9个)
- [x] 第一轮假设生成 (H-001 top_k, H-002 LLM budget, H-003 evidence quality)
- [x] 采样一致性 bug 修复 (generate_sealed_samples.py)
- [x] Tier 1 实验启动 (baseline + H-001 + H-002, DEVELOPMENT_SET n=20×5)
- [ ] Tier 1 实验结果分析

### Phase 4: 冻结验证 ⏳ 待启动
### Phase 5: 论文 + Artifact ⏳ 待启动

---

## 关键指标

### 诊断基线 (seed=2040, eval split, n=100, contaminated)
| 数据集 | 指标 | SlotRAG | 最强 Baseline | Delta | 判定 |
|--------|------|---------|---------------|-------|------|
| hotpotqa | EM | 0.5612 | ircot (0.6800) | -0.1188 | ❌ LOSS |
| hotpotqa | F1 | 0.6887 | graphrag (0.8087) | -0.1200 | ❌ LOSS |
| 2wikimultihop | EM | 0.5900 | graphrag (0.7300) | -0.1400 | ❌ LOSS |
| 2wikimultihop | F1 | 0.6872 | graphrag (0.8199) | -0.1327 | ❌ LOSS |
| musique | EM | 0.3736 | planrag (0.4828) | -0.1092 | ❌ LOSS |
| musique | F1 | 0.4818 | planrag (0.5748) | -0.0930 | ❌ LOSS |
| strategyqa | EM | 0.0800 | hybrid (0.9000) | -0.8200 | ❌ LOSS |
| strategyqa | F1 | 0.0800 | hybrid (0.9000) | -0.8200 | ❌ LOSS |
| drop | EM | 0.0100 | planrag (0.0102) | -0.0002 | ❌ LOSS |
| drop | F1 | 0.4405 | planrag (0.5419) | -0.1014 | ❌ LOSS |

**Strongest-Baseline Coverage: 0/10 = 0%**

### 评估集可用性
| 数据集 | 总 eval | 已暴露 | 干净可用 | 干净% |
|--------|---------|--------|----------|-------|
| hotpotqa | 7,405 | 250 | 7,155 | 96.6% |
| 2wikimultihop | 12,576 | 249 | 12,327 | 98.0% |
| musique | 2,417 | ~500 | ~1,900 | ~79% |
| strategyqa | 687 | ~500 | ~187 | ~27% |
| drop | 9,535 | ~500 | ~9,000 | ~95% |

### 三集合（Phase 2 已构造）
| 集合 | 比例 | seed | 样本数 | checksum |
|------|------|------|--------|----------|
| DEVELOPMENT | 30% | 2027 | ~9,412 | e914456d... |
| VALIDATION | 30% | 2027 | ~9,412 | 88dffd52... |
| TEST (SEALED) | 40% | 2027 | ~12,557 | 3eceb4f5... |

### Baseline 覆盖率 (seed=2040, n=100/dataset)
| 方法 | valid_n | failed | coverage |
|------|---------|--------|----------|
| graphrag | 500 | 0 | 100% |
| hybrid | 500 | 0 | 100% |
| ircot | 500 | 0 | 100% |
| react | 500 | 0 | 100% |
| planrag | 470 | **30** | 94% |
| slotrag | 489 | 11 | 97.8% |
| srag | 494 | 6 | 98.8% |

### SlotRAG V6c 训练集 (train split)
| 数据集 | valid_n | failed | total |
|--------|---------|--------|-------|
| hotpotqa | 834 | 4 | 838 |
| 2wikimultihop | 4 | 0 | 4 |

---

## 已确认的事实

### 代码级事实
1. V5c generation fix 有效 (thinking → over-caution)
2. baseline 归一化一致 (SQuAD/HotpotQA 标准)
3. publication_gate.py 有 train split 防护

### 必须撤销的结论
1. ❌ "超 90% SOTA" (train/eval split 错配)
2. ❌ "question_grounded_retrieval 突破 90% SOTA" (contaminated eval)
3. ❌ "V6b 200 样本规模验证通过" (contaminated eval)

### 诚实基线 (Phase 2, 诊断性)
- **Strongest-Baseline Coverage = 0/10 (0%)** — 在 eval split 上全面落后
- strategyqa 近乎失效 (0.08 vs 0.90, -0.82)
- drop 的 SQuAD EM 对所有方法无效 (~0.01)，主指标用 drop_f1

### 风险点
1. 所有 baseline 是 adapted (exact_upstream_execution: false)
2. eval 暴露 (seed=2040 样本已污染)
3. 有效样本数不一致 (planrag 94% vs graphrag 100%)

---

## 下一步行动

### 立即 (Phase 3)
1. 从 0/10 基线开始假设循环 (每轮 ≤3 假设)
2. P0: strategyqa 近乎失效 — 诊断 root cause
3. P1: 2wikimultihop/hotpotqa EM 落后 — 检索/生成瓶颈
4. 预注册 → 实现 → 测试 → 统计 → 评审 → 晋级/回滚

### 短期 (Phase 4)
1. 冻结验证
2. 一次性运行 SEALED_FINAL_SET

### 中期 (Phase 5)
1. 论文 + Artifact
2. 投稿 PVLDB 2027

---

*本文件由 documentation-writer agent 维护，每次实验后更新。*
