# STATE.md — SlotRAG-X 研究状态快照

> **最后更新**: 2026-08-06T20:00:00Z  
> **更新者**: documentation-writer agent  
> **当前阶段**: Phase 3（假设循环）— H-017/H-018 rejected，生成瓶颈模型级不可解，Coverage 维持 40%

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

### Phase 3: 假设循环 🔄 已恢复（H-012 公平重跑完成，Coverage 40%）
- [x] 深度失败诊断完成
  - **strategyqa EM=0.08 是格式假象**：用 primary_score (accuracy) 实际 0.84
  - **drop EM 无效**：已用 drop_f1 (0.62)
  - **真实瓶颈 (H-004)**: 检索不是瓶颈，是答案生成质量
    - hotpotqa: 21/98 recall=1.0 但 EM=0（检索对，答案错）
    - 2wiki: 21/100 recall=1.0 但 EM=0
    - ~57% 措辞/格式问题 (F1≥0.5)，~43% 明显错误 (F1<0.5)
- [x] 采样一致性 bug 修复 (generate_sealed_samples.py)
- [x] **Tier 1 实验完成**: H-001 rejected (p=0.13), H-002 rejected (p=0.41)
- [x] H-004 validated (生成质量是瓶颈)
- [x] H-005 rejected (entity contract, -0.02~-0.05)
- [x] **3 连续假设拒绝 → STOP_REPORT 触发**
- [x] H-008 SUPPORTED (PerPath 修复 S2, pooled +4.4pt p=0.0105)
- [x] H-009 REJECTED (score-guided 不一致)
- [x] H-010 REJECTED (跨来源投票/compact-value 均不可行, 可行性分析否决)
- [x] **H-012 叠加配置 Tier 1 PASSED** (2026-08-05)
  - `slotrag-grounded-frontier-perpath-guard` 组合 frontier 守卫 + anchor 保护 + per-path 提取
  - Tier 1 (n=20×3): 2wiki +17.6pt, hotpotqa +11.8pt vs 最优现有; musique EM 3:1 净胜
- [x] **H-012 Tier 2 完整矩阵完成** (2026-08-06, n=100×5 数据集)
  - Coverage **2/5 = 40%**: musique (+9.6pt vs ircot)、strategyqa (+8pt vs graphrag) WIN
  - hotpotqa tie (-0.2pt, p=0.94); **2wiki (-16.5pt)、drop (-13.4pt) LOSS**
  - strategyqa facts 加载回归修复 (commit 8ae9a40)
  - **结论**: 叠加配置部分有效，2wiki/drop 需针对性改进
- [x] **H-013 已拒绝** (union vs per-path 提取, n=20, p=0.786)
- [x] **H-014 已拒绝** (桥接实体重检索回退, Tier 1 n=20, 2wiki)
  - 机制层面有效 (8 触发 7 成功重检索)，但 F1 -9.3pt (0.726→0.633)
  - 根因: 2wiki 答案走 evidence-based 路径，rows 空不影响生成；bridge 修复的 rows 未达生成阶段
  - 追加诊断: 4 个 F1=0 中 3 个 gold 在 evidence 但生成选错（噪声/过量 evidence）
- [x] **H-015a 已拒绝** (生成证据去重+截断, Tier 1 n=20, 2wiki)
  - evidence 7.3→4.5 条，但 0/20 样本答案变化 (F1 0.7262 不变)
  - 洞察: 生成错误不是 evidence 数量/噪声问题，是推理深度问题
- [x] **H-016 已拒绝** (drop 自由文本 short 答案, Tier 1 n=20, drop)
  - short 改 1 样本且变差 (drop_f1 0.581→0.531, gold '70.7' → '70.7%' %破坏 token)
  - 洞察: drop F1=0 是**算术推理失败**（gold 是计算值，仅 3/100 在原文），非格式/证据问题
  - 2wiki+drop 均定位为**推理深度**瓶颈，需显式推理链或接受 LOSS
- [x] **H-017 已拒绝** (生成阶段显式推理链 thinking, Tier 1 n=20×2, 2wiki+drop, commit 7987181)
  - 2wiki 20/20 答案一字不差 (F1 0.7262→0.7262, Δ=0)；drop 19/20 不变、1 样本因 provider SchemaError 变差 (0.6305→0.5805)
  - thinking 机制**已生效** (enable_thinking=True 首次尝试走通) 但 qwen3.6-27b 的 thinking 不改变任何生成决策
  - 与 H-005/H-009 同模式：提示级/模式级干预在生成阶段已穷尽，零效果
- [x] **H-018 已拒绝** (生成证据保真 prompt, Tier 2 n=100, hotpotqa)
  - guard 0.8131 → fidelity 0.8242 (**+1.1pt, p=0.60**), wins=7 losses=6
  - 修复截断 (`east`→`the east of Ireland` +0.5)、错实体 (`English`→`Scottish` 0→1.0) 但**回归 4 个 previously-correct** (Dallas→Dallas Texas, McLaren Vale 过度扩展)
  - 软保真指令无法区分"该完整"与"该简短"（无 gold 信号）→ +1.1pt 不显著，违反零回归门禁
- [x] **H-019 已拒绝** (生成前证据相关性重排序, Tier 1 n=20, 2wiki)
  - guard 0.7262 → rerank 0.7262 (**Δ=0.0000**), 20/20 一字不差
  - 机制生效 (reranker_calls=2)；**10/20 样本 evidence>8 被重排+截断到 8，0/10 答案变化**
  - 决定性证据: 生成器**完全无视 evidence 呈现**（重排 12+→8 无影响），有内部答案先验
- [x] **系统性结论（8 个生成侧干预全失败）**: 检索/证据量/证据排序/提示措辞/thinking/契约——全部不影响 qwen3.6-27b 生成。瓶颈是模型自身答案先验，架构侧无解
- [ ] **下一步**: 唯一剩余杠杆 = 模型级生成器升级（换更强推理模型），或接受 Coverage 2/5 收尾
- [ ] **下一步**: 显式推理链生成（2wiki 多跳 / drop 算术），或接受 2wiki+drop LOSS 保 Coverage 3/5

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
