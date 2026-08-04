# STATE.md — SlotRAG-X 研究状态快照

> **最后更新**: 2026-08-04T21:00:00Z  
> **更新者**: documentation-writer agent  
> **当前阶段**: Phase 1（研究基础设施搭建）

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

### Phase 1: 研究基础设施 🔄 进行中
- [x] 9 个子 Agent 定义 (.claude/agents/)
- [ ] STATE.md (本文件)
- [ ] HYPOTHESES.md
- [ ] EXPERIMENT_LEDGER.csv
- [ ] FAILURE_LEDGER.csv
- [ ] DECISIONS.md
- [ ] SOTA_LEDGER.md
- [ ] RELATED_WORK_MATRIX.csv
- [ ] Makefile 入口

### Phase 2: SOTA 账本 ⏳ 待启动
### Phase 3: 假设循环 ⏳ 待启动
### Phase 4: 冻结验证 ⏳ 待启动
### Phase 5: 论文 + Artifact ⏳ 待启动

---

## 关键指标

### 评估集可用性
| 数据集 | 总 eval | 已暴露 | 干净可用 | 干净% |
|--------|---------|--------|----------|-------|
| hotpotqa | 7,405 | 250 | 7,155 | 96.6% |
| 2wikimultihop | 12,576 | 249 | 12,327 | 98.0% |
| musique | 2,417 | ~500 | ~1,900 | ~79% |
| strategyqa | 687 | ~500 | ~187 | ~27% |
| drop | 9,535 | ~500 | ~9,000 | ~95% |

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

### 风险点
1. 所有 baseline 是 adapted (exact_upstream_execution: false)
2. eval 暴露 (seed=2040 样本已污染)
3. 有效样本数不一致 (planrag 94% vs graphrag 100%)

---

## 下一步行动

### 立即 (Phase 1 剩余)
1. 创建所有研究账本文件
2. 创建 Makefile 入口
3. 用户确认后进入 Phase 2

### 短期 (Phase 2)
1. 构造三集合 (DEVELOPMENT, DISJOINT_VALIDATION, SEALED_FINAL)
2. 功效分析 (最小样本量)
3. 冻结协议 (FROZEN_PROTOCOL.md)
4. SOTA 账本

### 中期 (Phase 3)
1. 假设生成 (每轮 ≤3)
2. 预注册 → 实现 → 测试 → 统计 → 评审
3. 晋级/回滚

---

*本文件由 documentation-writer agent 维护，每次实验后更新。*
