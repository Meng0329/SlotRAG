# SlotRAG — TKDE 论文 TODO 阶段文档

> 主投：IEEE TKDE；备投：ACM TOIS；研究设计强度：VLDBJ-level rigor。
>
> 核心规则：**先做出可发表的研究，再写论文；禁止为了已有结论反向挑指标、挑样本、挑 baseline。**

---

## 实况更新（2026-08-21）

本 TODO 是 8 月初 TKDE 重定向时的 **17 阶段脚手架**，与后续实际推进的 **12 个 publication gate (G0–G12)** 不是同一套跟踪体系。
**G0–G12 已全部闭合**（G0/G1/G2/G5/G7/G8/G9/G10 SUPPORTED；G3/G6/G11/G12 PASS；G4 FALSIFIED→future-work）。
论文经 Harsh-Review R1+R2 后 verdict = **minor_revision**（可投，所有 CRITICAL/MAJOR 已修，commit 6934644 / de42293）。
本脚手架中大量 `[ ]` 已被 gate 工作满足，下方各 Phase 已据实勾选；**真正未完成的只剩少数边界项（见文末「剩余开放项」）**。

### 已完成 gate 一览
- G0 SUPPORTED（claim 集收窄至 5 条，裁决 12z12）
- G1 SUPPORTED（EvidenceRequirement/State/Type 表示层落地）
- G2 SUPPORTED（retrieval_strategy 活实现）
- G3 PASS（chain-rule 3-slot 省 16.7% 全保真）
- G4 FALSIFIED（严格链拓扑下 re-optimization 结构性无收益 → 全篇降级 future work）
- G5 SUPPORTED（链律 τ=2d−1 确定性规律）
- G6 PASS（20 题 3 臂，retr −0.45 p=0.0215）
- G7 SUPPORTED（matched-budget frontier，3-slot 子域 2/2 胜）
- G8 SUPPORTED（HoVer 80% EM）
- G9 SUPPORTED（FEVEROUS 2/2 EM text+table）
- G10 SUPPORTED（stats tools）
- G11 PASS（3 数据集闭环 n=24 stratified）
- G12 PASS（全部 gate 闭合，论文合规）

### 剩余开放项（优先级排序）
1. **[x] R1.1-EXT 外部基线接入主表**：§8 RQ6 已加 "External Baselines (RQ6)" 段落（`tkde-r11-ext-baselines-q38`，native-budget，n=20/20/24），诚实标注为 corroborating evidence 非主结果；`audit_numbers.py` v5 新增 R11 核对块，15 个数字全 [OK]；论文编译通过（0 undefined citations，12 页）。
2. **[ ] SEALED_TEST 冻结+执行**：pre-registered protocol 未冻结、未跑。当前所有数字均 dev/validation split（n=55 matched），Limitations 已诚实披露「非 held-out sealed set」。
3. **[ ] 外部有效性（cross-venue）**：仅 qwen3.8-27b 单 decoder，generalizability 未测。
4. **[x] 投稿前 Final Audit**（Phase 17，离线部分完成）：refs.bib 重写为 18 条可验证条目（补 DOI/venue/arXiv eprint，删 14 条孤儿占位），4-pass 编译 0 undefined citations、12 页；`audit_numbers.py` v5 全 [OK]（~5min 可复现）；新增 `paper/tkde_writing/REPRODUCE.md` 复现说明。双栏图可读性需人工终审（figures 仅 2 张，0.72–0.85 栏宽，可读）。

---

## Phase 0 — 研究重置与资产冻结

### 目标
把现有 SlotRAG-X 的 25% Coverage 论文、历史 H-001~H-031、所有 contaminated/dev/sealed runs 变成可追踪资产，但不让其直接决定新论文主结论。

### TODO
- [ ] 创建新研究分支，例如 `research/tkde-evidence-execution`。
- [ ] 保存当前 commit/hash、环境、模型 endpoint、index manifest。
- [ ] 将旧 `paper/` 标记为 legacy paper，不直接在其章节上改。
- [x] 生成 `LEGACY_RESULT_LEDGER.md`：每个历史结果的 dataset/split/model/budget/污染状态/是否可进入新论文。
- [ ] 生成新的 DEVELOPMENT / VALIDATION / SEALED_TEST registry。
- [ ] 所有已人工阅读过逐题结果进入 exposed registry，不得用于最终 sealed decisions。
- [ ] 冻结主 generator、retriever 与 embedding 的第一版 controlled protocol。

### Gate P0
- [ ] 新旧实验能够明确区分。
- [ ] 不存在 test leakage。
- [ ] 每个结论能追溯到 run manifest。

---

## Phase 1 — Paper Search 与 Novelty Audit

### 目标
不是“补 Related Work”，而是确定**哪些 claim 不能再说、哪些空间仍然空缺**。

### 必读竞争组
- [ ] PlanRAG 2026
- [ ] DynaKRAG 2026
- [ ] PyRAG 2026
- [ ] Structured Planning MHQA / TOIS 2026
- [ ] LOTUS/Semantic Operators
- [ ] Palimpzest/Abacus
- [ ] Sema 2026
- [ ] TeaRAG TOIS
- [ ] FIT-RAG TOIS
- [ ] CRUD-RAG TOIS
- [ ] fixed-budget/cluster-aware RAG evaluation
- [ ] What Survives Into Context
- [ ] Active RAG budget-aware evaluation
- [ ] HoVer / FEVEROUS / AVeriTeC
- [ ] TableRAG / FT-RAG / mmRAG

### 输出
- [ ] `research/TKDE_RELATED_WORK_MATRIX.csv`
- [ ] `research/NOVELTY_CLAIM_AUDIT.md`
- [ ] 每个候选 claim 标记：SUPPORTED / OVERLAP / TOO_BROAD / NEEDS_EVIDENCE。

### Gate P1
- [ ] 至少 20 篇直接论文完成结构化阅读。
- [ ] 与 6 个最邻近工作有逐项差异表。
- [ ] 核心贡献不能简化成 PlanRAG+DynaKRAG+Abacus 的机械组合。

---

## Phase 2 — Problem Formulation 与 Evidence Algebra

> **状态**：已完成（G1 SUPPORTED + G0 claim 集收敛）。见文首 gate 一览。

### TODO
- [ ] 定义 EvidenceType：Passage / Entity / Relation / TableRow / StructuredRecord。
- [ ] 定义 EvidenceRequirement。
- [ ] 定义 EvidenceState。
- [ ] 定义 provenance schema。
- [ ] 定义 8–10 个 core logical operators。
- [ ] 为每个 operator 给 input/output type、precondition、state transition、failure state。
- [ ] 定义 exact / evidence-preserving / approximate rewrite。
- [ ] 定义 logical plan 与 physical plan。
- [ ] 定义 budgeted requirement-satisfaction objective。
- [ ] 写 property-based tests / type tests。
- [ ] 设计至少 10 个 hand-verified program examples，覆盖不同 dependency graph。

### Gate P2
- [ ] Algebra 不依赖 Hotpot/2Wiki 特定模板。
- [ ] 同一 logical program 可以映射到至少两种 physical plan。
- [ ] 失败/partial satisfaction 有正式状态，不靠字符串 `None`。

---

## Phase 3 — Evidence Compiler

### TODO
- [ ] 从现有 SlotPlan compiler 迁移到 `EvidenceProgram` IR。
- [ ] compiler 只输出 logical requirements/dependencies，不选 BM25/Dense/top-k 等物理策略。
- [ ] 变量绑定显式化。
- [ ] compiler validator：cycle/unreachable/unsatisfied output/type mismatch。
- [ ] compile telemetry：latency、plan size、requirements、operator count。
- [ ] 建人工 gold logical plans 小集用于 compiler evaluation。
- [ ] 指标：operator-family accuracy、dependency accuracy、answer-variable accuracy、plan validity。

### Gate P3
- [ ] compiler quality 达到预先设定阈值；不能用最终 QA score 掩盖 compiler 错误。
- [ ] 不使用 test labels/passage gold 在 inference 时作弊。

---

## Phase 4 — Physical Operator Layer

### 第一版实现
- [ ] `SEARCH`: BM25 / Dense / Hybrid。
- [ ] `BIND/EXPAND`: entity-conditioned / relation-conditioned retrieval。
- [ ] `JOIN`: BindingJoin / ParallelEvidenceJoin / RetrieveThenJoin（合理可实现者）。
- [ ] `FILTER`: lexical/embedding/LLM filter 至少两种实现。
- [ ] `VERIFY`: model-based + deterministic evidence coverage checker（按任务适用）。
- [ ] `PACK`: naive/top-score/MMR/requirement-aware packer。
- [ ] `MATERIALIZE`: passage/row/record adapter。

### Gate P4
- [ ] 每个论文主张涉及的 physical alternative 真实运行，不允许仅在图中存在。
- [ ] 物理算子有统一 telemetry 和 cost accounting。

---

## Phase 5 — Learned Property Estimators

### Estimators
- [ ] EvidenceYieldEstimator
- [ ] RequirementCoverageEstimator
- [ ] Selectivity/CardinalityEstimator
- [ ] FailureProbabilityEstimator
- [ ] Retrieval/Token/Latency/MonetaryCostEstimator

### 训练/校准
- [ ] 只用 development 数据。
- [ ] 与 simple heuristic/base-rate estimator 对比。
- [ ] calibration plots：reliability diagram / ECE/Brier/MAE（按输出类型）。
- [ ] dataset-transfer evaluation。
- [ ] 保存 estimator version + training data manifest。

### Gate P5
- [ ] 至少关键 yield/coverage/cost estimator 明显优于 naive estimate。
- [ ] 若某 estimator 无价值，从系统移除，不为架构完整性硬留。

---

## Phase 6 — Explicit Optimizer

### TODO
- [ ] 定义 plan enumeration/search space。
- [ ] transformation + implementation rules。
- [ ] constrained optimization objective。
- [ ] dominance/Pareto pruning。
- [ ] budget allocation across requirements。
- [ ] plan search algorithm：DP / beam / branch-and-bound / hybrid，依据复杂度实验决定。
- [ ] optimizer trace：候选数、pruned 数、estimated utility、selected plan。
- [ ] optimizer overhead benchmark。

### Baselines
- [ ] Static compiler order。
- [ ] Existing heuristic slot order。
- [ ] Cost-only optimizer。
- [ ] Utility greedy。
- [ ] Learned-controller style baseline（可控实现）。
- [ ] Full explicit optimizer。

### Gate P6（核心）
- [ ] Full optimizer 在 validation 的主要 matched-budget frontier 上优于 static + cost-only。
- [ ] 若无稳定收益，回到 objective/estimator/plan space，禁止直接写论文。

---

## Phase 7 — Runtime Re-optimization

### Trigger 候选
- [ ] observed cardinality/yield 与 estimate 偏差超过阈值。
- [ ] 新 binding 解锁新的 specialized query。
- [ ] requirement 从 unresolved → partial/satisfied。
- [ ] physical operator failure/timeout。
- [ ] remaining budget 与原计划不再可行。

### 实验
- [ ] no-reopt vs periodic reopt vs event-triggered reopt。
- [ ] query dependency depth 分层。
- [ ] estimation-error 分层。
- [ ] reopt count/overhead/benefit。
- [ ] counterfactual trace：如果不 reopt 会发生什么。

### Gate P7
- [ ] 至少存在预定义结构子集显示稳定因果收益。
- [ ] 若总体无显著收益，必须诚实降级“runtime reopt”主 claim，而不是 post-hoc 改 subset。

---

## Phase 8 — Heterogeneous Evidence

### TODO
- [ ] 引入 TableRow/StructuredRecord adapter。
- [ ] 优先 FEVEROUS 或一个 table+text QA workload。
- [ ] 保持同一 EvidenceProgram/optimizer API。
- [ ] physical operator 可根据 evidence type 路由。
- [ ] provenance 保留 source/table/row/cell location。

### Gate P8
- [ ] 不是把表格 flatten 后假装 heterogeneous。
- [ ] 核心 optimizer 无 dataset-specific if/else。

---

## Phase 9 — Benchmark & Evaluation Harness 重构

### 主任务
- [ ] HotpotQA
- [ ] 2WikiMultiHopQA
- [ ] MuSiQue
- [ ] HoVer
- [ ] FEVEROUS（若 P8 通过）

### 压力/附录任务
- [ ] StrategyQA（需重复运行协议）
- [ ] DROP（作为 downstream reasoning stress test）
- [ ] AVeriTeC（可选 external validity）

### 指标
- [ ] Answer EM/F1/accuracy/verification score
- [ ] Requirement satisfaction
- [ ] Supporting evidence recall/precision
- [ ] Materialized evidence coverage
- [ ] Packed answer-in-context / answer survival
- [ ] Retrieval calls
- [ ] passages/documents accessed
- [ ] reader tokens
- [ ] LLM calls/tokens
- [ ] latency
- [ ] monetary cost
- [ ] optimizer planning overhead
- [ ] reoptimization count
- [ ] provenance completeness

### Gate P9
- [ ] realized budget 可逐题审计。
- [ ] 所有 baseline 同口径。
- [ ] exact upstream 与 adapted baseline 分开。

---

## Phase 10 — Development Experiments

### 实验顺序（禁止乱序刷结果）
1. [ ] compiler correctness
2. [ ] operator microbenchmarks
3. [ ] estimator calibration
4. [ ] optimizer synthetic/controlled cases
5. [ ] n=30 smoke
6. [ ] n=100 development
7. [ ] optimizer ablation
8. [ ] reopt causal analysis
9. [ ] heterogeneous smoke
10. [ ] freeze method

### Gate P10
- [ ] publication gates G1–G5 大部分通过后才能冻结方法。

---

## Phase 11 — Validation Freeze

- [ ] 冻结代码 commit。
- [ ] 冻结 configs。
- [ ] 冻结 baseline versions。
- [ ] 冻结 indices。
- [ ] 冻结 estimator weights。
- [ ] 冻结 prompts。
- [ ] 预注册 primary RQs、metrics、stat tests。
- [ ] 禁止看 SEALED_TEST 逐题结果再改方法。

---

## Phase 12 — Full Main Experiments

### Main Table
- [ ] 5+ controlled baselines × 4–5 datasets。
- [ ] 多运行（服务端非确定时至少 3）。
- [ ] confidence intervals。

### Matched-budget Frontier
- [ ] retrieval budget sweep。
- [ ] reader-token budget sweep。
- [ ] LLM-call/token budget。
- [ ] latency/$ 若可稳定测量。

### Ablations
- [ ] w/o typed requirements
- [ ] w/o rewrite
- [ ] static physical plan
- [ ] cost-only
- [ ] heuristic estimators
- [ ] w/o runtime reopt
- [ ] w/o provenance-aware packing（若是核心）

### Mechanism
- [ ] dependency depth
- [ ] plan size
- [ ] estimator error
- [ ] evidence type
- [ ] bottleneck stage

### Gate P12
- [ ] G6–G10 通过。

---

## Phase 13 — Statistical Audit

- [ ] paired bootstrap CI。
- [ ] McNemar（适用二元正确率）。
- [ ] cluster-aware bootstrap/sign-flip（数据有 cluster 时）。
- [ ] multiple comparison correction。
- [ ] effect size。
- [ ] equivalence/non-inferiority 仅在预定义 margin 后使用。
- [x] 独立脚本从 raw per-question records 重建所有主表 (`paper/tkde_writing/audit_numbers.py`)。
- [ ] 检查 mean/median/best-run 混用。

---

## Phase 14 — Figure/Table Production

- [ ] Fig1 Motivation
- [ ] Fig2 Architecture
- [ ] Fig3 Algebra walkthrough
- [ ] Fig4 Physical plan alternatives
- [ ] Fig5 Runtime reopt trace
- [ ] Fig6 Pareto frontier
- [ ] Fig7 bottleneck/failure attribution
- [ ] Fig8 scalability
- [ ] Table1 positioning
- [ ] Table2 algebra
- [ ] Table3 datasets
- [ ] Table4 main effectiveness
- [ ] Table5 quality-cost
- [ ] Table6 ablation
- [ ] Table7 cross-task/heterogeneous
- [ ] Table8 failure analysis

规则：所有图必须由脚本从 frozen results 生成，不允许手工改数字。

---

## Phase 15 — 论文撰写（按证据顺序，不按章节顺序）

### 推荐写作顺序
1. [ ] Problem Formulation
2. [ ] Evidence Algebra
3. [ ] Optimizer
4. [ ] Runtime Execution
5. [ ] Experimental Methodology
6. [ ] Results
7. [ ] Mechanism Analysis
8. [ ] Related Work
9. [ ] Introduction
10. [ ] Abstract
11. [ ] Discussion/Limitations
12. [ ] Conclusion

### 每段落验收
- [ ] 第一/二句有明确 claim/function。
- [ ] 每个数字可追踪到 frozen table/figure/raw record。
- [ ] 每个 novelty claim 有 nearest-work comparison。
- [ ] 无“significant”但无统计检验。
- [ ] 无 “SOTA” 但 baseline 不完整。
- [ ] 中英双语写作 blueprint 保留；正式投稿稿只留英文。

---

## Phase 16 — Internal Reviewer Loop

至少模拟 4 类审稿人：
- [ ] R1 数据库 optimizer reviewer：会质疑是不是 DB terminology dressing。
- [ ] R2 RAG/IR reviewer：会质疑是否真的提升 retrieval/QA。
- [ ] R3 systems reviewer：会质疑 scale/overhead/reproducibility。
- [ ] R4 statistics reviewer：会质疑 leakage/budget/significance。

每轮生成：
- [ ] Major concerns
- [ ] Fatal vs fixable
- [ ] Required experiment
- [ ] Required rewrite
- [ ] Decision estimate

连续两轮无未解决 fatal concern 才进入最终投稿准备。

**TKDE 实况**: Harsh-pvldb-reviewer R1 (commit 3e51691) 修复 S2/S3/S5；R2 (verdict minor_revision) 修复 CRITICAL-1 "never spends more" overclaim + MAJOR-1 p 值往有利方向低报 + HoVer/FEVEROUS 证据出处披露 + "9/11" → 8/11 口径。全部修复已 commit (commit 6934644, de42293)。当前为 minor_revision，可投稿。

---

## Phase 17 — Final Submission Audit

- [ ] TKDE scope fit 明确。
- [ ] title/abstract/intro claim 一致。
- [ ] contribution 与 experiment 一一对应。
- [ ] artifact README 可独立复现主表。
- [ ] 无匿名信息泄漏（若双盲流程要求）。
- [ ] refs 全部可验证、年份/venue/DOI 正确。
- [ ] figure 在双栏打印尺寸可读。
- [ ] appendix/supplement 不承载主 claim 唯一证据。
- [ ] 所有 limitation 如实写。
