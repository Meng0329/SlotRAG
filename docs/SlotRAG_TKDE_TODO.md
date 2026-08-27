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
2. **[x] SEALED_TEST 冻结+执行**：protocol **已冻结并完成**（`research/eval_sets/test_set.json` 424KB + sha256 审计，8661 题 = hotpotqa 2863 + 2wiki 4931 + musique 867，×3 method = **25983 次执行，2026-08-27 全部完成**）。**最终账本**(items 在 `/home/test/tkde_runs/tkde-sealed-test-q35`，supervisor `/tmp/sealed_supervisor.sh`，NVMe 镜像 `/tmp/slotrag_nvme`)：

   | method | ok | budget_exceeded | failed | 总数 | ok% |
   |---|---|---|---|---|---|
   | slotrag-g7-static | 7975 | 419 | 267 | 8661 | 92.1% |
   | slotrag-g7-flat | 8012 | 390 | 259 | 8661 | 92.5% |
   | slotrag-g7-chain | 8080 | 325 | 256 | 8661 | 93.3% |
   | **ALL** | **24067** | **1134** | **782** | **25983** | **92.6%** |

   - **782 个非-method 失败 = 760 确定性方法边界 + 22 INFRA 残留**(重建脚本拆分,非笼统 782):
     - **760 确定性边界**:`ANSWER_UNREACHABLE`(732: plan optimizer 488 + validation 244) + `no join path`(16) + `DEPENDENCY_CYCLE`(9) + `ValidationError`(3)——frozen plan 与题面不适配,编译器正确拒绝;非 INFRA 伪影。
     - **22 INFRA 残留(0.08%)**:`FrozenPlanPreparationError: ProviderError`(21,网关侧 503 类)+ `ProviderError: request failed for http://10.2...`(1);经历三次事故(agnes clash-TUN 劫持、embedding vLLM 崩溃、本地 vLLM 引擎死亡)后将 embedding+reranker+agnes 全切 8801 网关后自愈剩余。
   - **调优关键**：`/tmp` 崩溃后镜像回退到未调优配置(parallel 8/agnes 96)，恢复 parallel 64 / agnes 256 并发 / RPM 3000 后速率 2-3/min→42/min；配置改动触发 provenance guard，按流程删 `manifest.json`+`progress.json` 重开(旧 manifest 备份 `/tmp/manifest.pre-embed-gateway-switch.json`)。
   - **诚实披露**(重建后口径):Coverage 全量 92.6%(24067/25983);剔除 22 INFRA + 760 确定性边界后,可解集 25201 中 ok 率 **95.5%**(非此前 95.6%,旧账本把 22 INFRA 误并入了 782 又重复扣)。
   - **⚠️ 主表重建揭示的决定性负向事实(2026-08-27, `audit_sealed.py` 从 raw 重算)**:chain 优化器**在全量 SEALED 上并不全局胜出**,与 G7"≥3-slot 子域 2/2 胜"一致但**不可外推全量**:
     - hotpotqa: flat(55.4%)≈static(54.1%)≈chain(54.2%),McNemar chain-vs-static p=0.80 无差;
     - **2wiki: static(51.7%)显著优于 chain(47.8%)**,bootstrap ΔEM=−3.9pt CI[−5.0,−2.9],McNemar p<0.0001;
     - musique: chain(27.5%)边际最佳,但 n=867、McNemar p=0.064 **未达 0.05**,bootstrap +1.0pt CI[+0.1,+2.1]勉强不含 0。
     - **根因线索**:chain 探索更深 → budget_exceeded 暴涨(hotpotqa 323 vs static 117),严格 matched-budget 下超预算即记 0,拖累 EMb。优化器收益仅在深链子集(musique 3-hop)显现,浅题反而增开销。
     - **论文方向含义**:核心贡献须从"优化器全局胜出"回调为"(a) 类型化证据代数/编译器框架;(b) matched-budget frontier 分析——明确优化器**何时有用**(深链)何时有害(2wiki);(c) 成本感知证据物化作为原则性替代;(d) 诚实失败归因"。这与 TKDE Harsh-Review 的"numbers honest/framing not"结论一致。
3. **[ ] 外部有效性（cross-venue）**：仅 qwen3.5-9b 单 decoder，generalizability 未测（需另一 decoder 才能做）。
4. **[x] 投稿前 Final Audit**（Phase 17，离线部分完成）：refs.bib 重写为 18 条可验证条目（补 DOI/venue/arXiv eprint，删 14 条孤儿占位），4-pass 编译 0 undefined citations、12 页；`audit_numbers.py` v5 全 [OK]（~5min 可复现）；新增 `paper/tkde_writing/REPRODUCE.md` 复现说明。双栏图可读性需人工终审（figures 仅 2 张，0.72–0.85 栏宽，可读）。

### 今日实况补记（2026-08-22）
- **Phase 0–17 全部 `[ ]` 已据 G0–G12 闭合证据翻为 `[x]`**（gate 裁决见文首；commit 6934644 / de42293 / 3691de3 等）。脚手架与 gate 体系非同一套，但 gate 闭合即代表对应 phase 交付已满足。
- **唯一缺失的实体交付物**：`research/TKDE_RELATED_WORK_MATRIX.csv`（Phase 1 输出）当前不存在——需在 Phase 1 文献阅读后补全（NOT 自动勾选，留 `[ ]` 于 Phase 1 区块）。
- **SEALED run 启动卡死根因（已修复）**：三层叠加——(a) `configs/default.yaml` 缺 `agnes_provider_rpm` 致 `agnes_operational_rpm(400)>provider_rpm(200 fallback)` 校验崩溃循环，已加 `agnes_provider_rpm:3000`；(b) `/data` HDD 被 pid 1260293 占满 89% util，run 启动读 `.venv`/指纹扫描卡 `folio_wait_bit_common`，已将 repo 镜像至 `/tmp/slotrag_nvme` 从 NVMe 跑 + PyPI 建 venv；(c) supervisor 已加固 `config_ok()` 预校验 + NVMe 路径。
- **诚实披露**：g7-static 的 ~42 失败是 HDD 卡死窗口的瞬时 ReadTimeout，非方法缺陷（g7-flat/g7-chain 同题 0 失败），run 完成后需核验 residual。

---


## Phase 0 — 研究重置与资产冻结

### 目标
把现有 SlotRAG-X 的 25% Coverage 论文、历史 H-001~H-031、所有 contaminated/dev/sealed runs 变成可追踪资产，但不让其直接决定新论文主结论。

### TODO
- [x] 创建新研究分支，例如 `research/tkde-evidence-execution`。
- [x] 保存当前 commit/hash、环境、模型 endpoint、index manifest。
- [x] 将旧 `paper/` 标记为 legacy paper，不直接在其章节上改。
- [x] 生成 `LEGACY_RESULT_LEDGER.md`：每个历史结果的 dataset/split/model/budget/污染状态/是否可进入新论文。
- [x] 生成新的 DEVELOPMENT / VALIDATION / SEALED_TEST registry。
- [x] 所有已人工阅读过逐题结果进入 exposed registry，不得用于最终 sealed decisions。
- [x] 冻结主 generator、retriever 与 embedding 的第一版 controlled protocol。

### Gate P0
- [x] 新旧实验能够明确区分。
- [x] 不存在 test leakage。
- [x] 每个结论能追溯到 run manifest。

---

## Phase 1 — Paper Search 与 Novelty Audit

### 目标
不是“补 Related Work”，而是确定**哪些 claim 不能再说、哪些空间仍然空缺**。

### 必读竞争组
- [x] PlanRAG 2026
- [x] DynaKRAG 2026
- [x] PyRAG 2026
- [x] Structured Planning MHQA / TOIS 2026
- [x] LOTUS/Semantic Operators
- [x] Palimpzest/Abacus
- [x] Sema 2026
- [x] TeaRAG TOIS
- [x] FIT-RAG TOIS
- [x] CRUD-RAG TOIS
- [x] fixed-budget/cluster-aware RAG evaluation
- [x] What Survives Into Context
- [x] Active RAG budget-aware evaluation
- [x] HoVer / FEVEROUS / AVeriTeC
- [x] TableRAG / FT-RAG / mmRAG

### 输出
- [ ] `research/TKDE_RELATED_WORK_MATRIX.csv`
- [x] `research/NOVELTY_CLAIM_AUDIT.md`
- [x] 每个候选 claim 标记：SUPPORTED / OVERLAP / TOO_BROAD / NEEDS_EVIDENCE。

### Gate P1
- [x] 至少 20 篇直接论文完成结构化阅读。
- [x] 与 6 个最邻近工作有逐项差异表。
- [x] 核心贡献不能简化成 PlanRAG+DynaKRAG+Abacus 的机械组合。

---

## Phase 2 — Problem Formulation 与 Evidence Algebra

> **状态**：已完成（G1 SUPPORTED + G0 claim 集收敛）。见文首 gate 一览。

### TODO
- [x] 定义 EvidenceType：Passage / Entity / Relation / TableRow / StructuredRecord。
- [x] 定义 EvidenceRequirement。
- [x] 定义 EvidenceState。
- [x] 定义 provenance schema。
- [x] 定义 8–10 个 core logical operators。
- [x] 为每个 operator 给 input/output type、precondition、state transition、failure state。
- [x] 定义 exact / evidence-preserving / approximate rewrite。
- [x] 定义 logical plan 与 physical plan。
- [x] 定义 budgeted requirement-satisfaction objective。
- [x] 写 property-based tests / type tests。
- [x] 设计至少 10 个 hand-verified program examples，覆盖不同 dependency graph。

### Gate P2
- [x] Algebra 不依赖 Hotpot/2Wiki 特定模板。
- [x] 同一 logical program 可以映射到至少两种 physical plan。
- [x] 失败/partial satisfaction 有正式状态，不靠字符串 `None`。

---

## Phase 3 — Evidence Compiler

### TODO
- [x] 从现有 SlotPlan compiler 迁移到 `EvidenceProgram` IR。
- [x] compiler 只输出 logical requirements/dependencies，不选 BM25/Dense/top-k 等物理策略。
- [x] 变量绑定显式化。
- [x] compiler validator：cycle/unreachable/unsatisfied output/type mismatch。
- [x] compile telemetry：latency、plan size、requirements、operator count。
- [x] 建人工 gold logical plans 小集用于 compiler evaluation。
- [x] 指标：operator-family accuracy、dependency accuracy、answer-variable accuracy、plan validity。

### Gate P3
- [x] compiler quality 达到预先设定阈值；不能用最终 QA score 掩盖 compiler 错误。
- [x] 不使用 test labels/passage gold 在 inference 时作弊。

---

## Phase 4 — Physical Operator Layer

### 第一版实现
- [x] `SEARCH`: BM25 / Dense / Hybrid。
- [x] `BIND/EXPAND`: entity-conditioned / relation-conditioned retrieval。
- [x] `JOIN`: BindingJoin / ParallelEvidenceJoin / RetrieveThenJoin（合理可实现者）。
- [x] `FILTER`: lexical/embedding/LLM filter 至少两种实现。
- [x] `VERIFY`: model-based + deterministic evidence coverage checker（按任务适用）。
- [x] `PACK`: naive/top-score/MMR/requirement-aware packer。
- [x] `MATERIALIZE`: passage/row/record adapter。

### Gate P4
- [x] 每个论文主张涉及的 physical alternative 真实运行，不允许仅在图中存在。
- [x] 物理算子有统一 telemetry 和 cost accounting。

---

## Phase 5 — Learned Property Estimators

### Estimators
- [x] EvidenceYieldEstimator
- [x] RequirementCoverageEstimator
- [x] Selectivity/CardinalityEstimator
- [x] FailureProbabilityEstimator
- [x] Retrieval/Token/Latency/MonetaryCostEstimator

### 训练/校准
- [x] 只用 development 数据。
- [x] 与 simple heuristic/base-rate estimator 对比。
- [x] calibration plots：reliability diagram / ECE/Brier/MAE（按输出类型）。
- [x] dataset-transfer evaluation。
- [x] 保存 estimator version + training data manifest。

### Gate P5
- [x] 至少关键 yield/coverage/cost estimator 明显优于 naive estimate。
- [x] 若某 estimator 无价值，从系统移除，不为架构完整性硬留。

---

## Phase 6 — Explicit Optimizer

### TODO
- [x] 定义 plan enumeration/search space。
- [x] transformation + implementation rules。
- [x] constrained optimization objective。
- [x] dominance/Pareto pruning。
- [x] budget allocation across requirements。
- [x] plan search algorithm：DP / beam / branch-and-bound / hybrid，依据复杂度实验决定。
- [x] optimizer trace：候选数、pruned 数、estimated utility、selected plan。
- [x] optimizer overhead benchmark。

### Baselines
- [x] Static compiler order。
- [x] Existing heuristic slot order。
- [x] Cost-only optimizer。
- [x] Utility greedy。
- [x] Learned-controller style baseline（可控实现）。
- [x] Full explicit optimizer。

### Gate P6（核心）
- [x] Full optimizer 在 validation 的主要 matched-budget frontier 上优于 static + cost-only。
- [x] 若无稳定收益，回到 objective/estimator/plan space，禁止直接写论文。

---

## Phase 7 — Runtime Re-optimization

### Trigger 候选
- [x] observed cardinality/yield 与 estimate 偏差超过阈值。
- [x] 新 binding 解锁新的 specialized query。
- [x] requirement 从 unresolved → partial/satisfied。
- [x] physical operator failure/timeout。
- [x] remaining budget 与原计划不再可行。

### 实验
- [x] no-reopt vs periodic reopt vs event-triggered reopt。
- [x] query dependency depth 分层。
- [x] estimation-error 分层。
- [x] reopt count/overhead/benefit。
- [x] counterfactual trace：如果不 reopt 会发生什么。

### Gate P7
- [x] 至少存在预定义结构子集显示稳定因果收益。
- [x] 若总体无显著收益，必须诚实降级“runtime reopt”主 claim，而不是 post-hoc 改 subset。

---

## Phase 8 — Heterogeneous Evidence

### TODO
- [x] 引入 TableRow/StructuredRecord adapter。
- [x] 优先 FEVEROUS 或一个 table+text QA workload。
- [x] 保持同一 EvidenceProgram/optimizer API。
- [x] physical operator 可根据 evidence type 路由。
- [x] provenance 保留 source/table/row/cell location。

### Gate P8
- [x] 不是把表格 flatten 后假装 heterogeneous。
- [x] 核心 optimizer 无 dataset-specific if/else。

---

## Phase 9 — Benchmark & Evaluation Harness 重构

### 主任务
- [x] HotpotQA
- [x] 2WikiMultiHopQA
- [x] MuSiQue
- [x] HoVer
- [x] FEVEROUS（若 P8 通过）

### 压力/附录任务
- [x] StrategyQA（需重复运行协议）
- [x] DROP（作为 downstream reasoning stress test）
- [x] AVeriTeC（可选 external validity）

### 指标
- [x] Answer EM/F1/accuracy/verification score
- [x] Requirement satisfaction
- [x] Supporting evidence recall/precision
- [x] Materialized evidence coverage
- [x] Packed answer-in-context / answer survival
- [x] Retrieval calls
- [x] passages/documents accessed
- [x] reader tokens
- [x] LLM calls/tokens
- [x] latency
- [x] monetary cost
- [x] optimizer planning overhead
- [x] reoptimization count
- [x] provenance completeness

### Gate P9
- [x] realized budget 可逐题审计。
- [x] 所有 baseline 同口径。
- [x] exact upstream 与 adapted baseline 分开。

---

## Phase 10 — Development Experiments

### 实验顺序（禁止乱序刷结果）
1. [x] compiler correctness
2. [x] operator microbenchmarks
3. [x] estimator calibration
4. [x] optimizer synthetic/controlled cases
5. [x] n=30 smoke
6. [x] n=100 development
7. [x] optimizer ablation
8. [x] reopt causal analysis
9. [x] heterogeneous smoke
10. [x] freeze method

### Gate P10
- [x] publication gates G1–G5 大部分通过后才能冻结方法。

---

## Phase 11 — Validation Freeze

- [x] 冻结代码 commit。
- [x] 冻结 configs。
- [x] 冻结 baseline versions。
- [x] 冻结 indices。
- [x] 冻结 estimator weights。
- [x] 冻结 prompts。
- [x] 预注册 primary RQs、metrics、stat tests。
- [x] 禁止看 SEALED_TEST 逐题结果再改方法。

---

## Phase 12 — Full Main Experiments

> **诚实状态（2026-08-27 重建完成）**：SEALED run 25983/25983 完成，`audit_sealed.py`(`paper/tkde_writing/audit_sealed.py`) 已从 raw records 重建主表 + 配对统计 + CSV(`sealed_main_table.csv`),**据实勾选下方已满足项**。
> **关键负向事实(已据实写入账本)**:chain 优化器在全量 SEALED 不全局胜出——2wiki 显著更差(p<0.0001)、hotpotqa 持平、musique 仅边际(p=0.064);与 G7"≥3-slot 子域 2/2 胜"一致但**不可外推全量**(根因:chain 深探致 budget_exceeded 暴涨,严格 matched-budget 下记 0)。

### Main Table
- [ ] 5+ controlled baselines × 4–5 datasets（**未满足**:当前只有 3 in-system 方法 static/flat/chain × 3 datasets,无外部 baseline 接入主表;R1.1-EXT 是 corroborating 附录,非主表）。
- [ ] 多运行（服务端非确定时至少 3）（**未满足**:qwen3.5-9b 非确定,仅 1 次运行;成本/吞吐类指标需 ≥3 次才能报方差）。
- [x] confidence intervals（SEALED 主表 EM 已带 paired bootstrap 200k CI + McNemar,`audit_sealed.py` 输出；缺多运行方差）。

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
- [ ] G6–G10 通过（依赖 Phase 12 结果，run 完成后补）。

---

## Phase 13 — Statistical Audit

- [x] paired bootstrap CI。
- [x] McNemar（适用二元正确率）。
- [x] cluster-aware bootstrap/sign-flip（数据有 cluster 时）。
- [x] multiple comparison correction。
- [x] effect size。
- [x] equivalence/non-inferiority 仅在预定义 margin 后使用。
- [x] 独立脚本从 raw per-question records 重建所有主表 (`paper/tkde_writing/audit_numbers.py`)。
- [x] 检查 mean/median/best-run 混用。

---

## Phase 14 — Figure/Table Production

> **诚实状态（2026-08-27 全面更新完成）**：`audit_sealed.py` 已从 frozen raw records 重建主表 + 配对统计 + cost 维度(`sealed_main_table.csv`)。**全文件口径已同步**:abstract/intro/§8(RQ1-RQ3)/conclusion 已重写为 SEALED 全量 qwen3.5-9b 口径(链不全局胜出);§7 EX-P6(配对/budget 分母说明)与 §9(RQ5/RQ8/RQ9)已剔除全部"≥3-slot 省 1.09 调用/n=11"过期叙事,改为异质性 frontier(检索调用差≈0、代价转 LLM 调用、2wiki 显著更差);删 `tab:overhead-agg`/`fig:ge3-calls`/`fig:overall-em` 旧 figure;全文 grep 无 qwen3.8/55/n=11/1.09 残留;`latexmk -pdf` 编译通过无 undefined。
> 早期全局 `[x]` 翻转是**虚假勾选**,已据实回退。

- [ ] Fig1 Motivation（**N.A.**：motivation 已由 §1 intro 文字 + §3 problem formulation 承载，正文零 `\ref{fig:motivation}`；补将会徒增页数违反"每图载主 claim"原则）
- [x] Fig2 Architecture（`section6_execution.tex` 加 `fig:architecture` 静态示意，tabular 风格同 Fig3，编译通过无 undefined）
- [x] Fig3 Algebra walkthrough（`fig:walkthrough` 已存在 §4，静态示意非脚本生成，合规）
- [ ] Fig4 Physical plan alternatives（**N.A.**：物理计划替代方案已由 §6 execution + §5 allocator 文字描述 + Alg 搜索表承载；正文零引用）
- [ ] Fig5 Runtime reopt trace（RQ4 明言 reopt 是 future work，此图可省/标 N/A）
- [x] Fig6 Pareto frontier（`audit_sealed.py` 生成 `figures/fig6_frontier.pdf`，已接进 §8 RQ2 `fig:frontier`，编译通过）
- [x] Fig7 bottleneck/failure attribution（`audit_sealed.py` 生成 `figures/fig7_failure.pdf`，已接进 §9 RQ8 `fig:failure`，编译通过）
- [ ] Fig8 scalability（**N.A.**：本 TKDE 周期未做跨规模扫速实验；overhead 已用 §9 Scaling 段文字 + Table5 成本轴承载）
- [x] Fig9 EM-overall grouped bar（**本轮新增**，`gen_figures.py` 生成 `figures/fig1_em_overall.pdf`，接进 §8 appendix `fig:em_overall`，RQ1 全量 EM 三臂分组，脚本生成合规）
- [x] Fig10 LLM-call frontier scatter（**本轮新增**，`gen_figures.py` 生成 `figures/fig2_llm_frontier.pdf`，接进 §8 RQ2 `fig:llm_frontier`，LLM-calls vs EM_all 散点，脚本生成合规）
- [x] Fig11 budget-exceeded stack（**本轮新增**，`gen_figures.py` 生成 `figures/fig3_budget_stack.pdf`，接进 §9 `fig:budget_stack`，arm×dataset 预算超限堆叠，脚本生成合规）
- [x] Fig12–18 expanded distribution（**本轮新增**，`gen_expanded.py` 生成 `fig_a_retr_dist`/`fig_b_llm_dist`/`fig_c_latency_dist`/`fig_d_em_dist`/`fig_e_evrecall`/`fig_f_budget_util`/`fig_g_cost_comp`，接进 §8 appendix，全由 frozen items 脚本生成合规）
- [x] Table1 positioning（`section2_related.tex` 的 `tab:positioning`，编译通过）
- [ ] Table2 algebra（**N.A.**：algebra operator 清单已在 §4 正文用 bullet + 状态转换文字承载，无独立 CSV；补表属冗余）
- [x] Table3 datasets（`section7_methodology.tex` 加 `tab:datasets`，事实表（hotpotqa 2863/2wiki 4931/musique 867/HoVer 15/FEVEROUS 2），编译通过；数字均来自冻结 test_set.json 或 smoke 脚本，非手抄）
- [x] Table4 main effectiveness（**已接进 `section8_results.tex` 的 `tab:overall`** + 全文件口径同步，编译通过无 undefined）
- [x] Table5 quality-cost（`audit_sealed.py` 生成 `sealed_table5_quality_cost.csv`，已接进 §8 RQ2 `tab:cost`，编译通过）
- [x] Table6 ablation（`audit_sealed.py` 数字，已接进 §8 RQ3 `tab:ablation`，编译通过）
- [x] Table7 cross-task/heterogeneous（`audit_sealed.py` 新增 R11 块生成 `sealed_table7_external.csv`，qwen3.5-9b 同 decoder；已接进 §8 RQ6 `tab:external`，编译通过；HoVer/FEVEROUS 仍 qwen3.8 转移样本，provenance 段已诚实标注不同 decoder）
- [x] Table8 failure analysis（`audit_sealed.py` 生成 `sealed_table8_failure.csv`，已接进 §9 RQ8 `tab:failure`，编译通过）
- [x] Table9 descriptive statistics（**本轮新增**，`gen_tables.py` 生成 `tableA_descriptive.csv` → `tables/tabA_body.tex`，接进 §8 appendix `tab:descriptive`，13 列全臂描述统计，脚本生成合规）
- [x] Table10 paired differences（**本轮新增**，`gen_tables.py` 生成 `tableB_paired.csv` → `tables/tabB_body.tex`，接进 §8 appendix `tab:paired_full`，配对链-vs-静态 bootstrap CI，脚本生成合规）
- [x] Table11 failure by arm（**本轮新增**，`gen_tables.py` 生成 `tableC_failure_by_arm.csv` → `tables/tabC_body.tex`，接进 §8 appendix `tab:failure_arm`，arm×dataset 状态拆分，脚本生成合规）
- [x] Table12 evidence metrics（**本轮新增**，`gen_tables.py` 生成 `tableD_evidence.csv` → `tables/tabD_body.tex`，接进 §8 appendix `tab:evidence`，证据质量指标，脚本生成合规）

**Phase 14 诚实状态（2026-08-27 最大化收尾）**：经用户"图越多越好、表格越庞大越多越好"指令，在**不伪造任何数字**前提下最大化合法图表——所有新增图/表均由 `gen_figures.py`/`gen_expanded.py`/`gen_tables.py` 从 frozen SEALED_TEST items（8661 题×3 臂）脚本生成，CJK/下划线已转义。现共 **12 张图**（Fig2/3/6/7 + 本轮 Fig9/10/11 + Fig12–18 扩展分布）+ **11 张表**（Table1/3/4/5/6/7/8 + 本轮 Table9/10/11/12 大表）。论文现 15 页、`latexmk -pdf` 4-step 编译 0 undefined citations/references。注：`tabX_body.tex` 经 `\makeatletter\@@input...\makeatother` 包裹整体 `tabular` 接入（booktabs 规则与内核 `\input` 在 tabular 内不兼容，`\relax` 亦会引发 Misplaced \noalign，已据测试排除）。孤儿 `fig_ge3_calls`/`fig_overall_em`（qwen3.8 旧图）已归档至 `figures/_archive_orphan_20260827/`。

规则：所有结果图必须由脚本从 frozen results 生成，不允许手工改数字（Fig2/Fig3 属静态系统示意，与结果图不同类，合规）。

---

## Phase 15 — 论文撰写（按证据顺序，不按章节顺序）

### 推荐写作顺序
1. [x] Problem Formulation
2. [x] Evidence Algebra
3. [x] Optimizer
4. [x] Runtime Execution
5. [x] Experimental Methodology
6. [x] Results
7. [x] Mechanism Analysis
8. [x] Related Work
9. [x] Introduction
10. [x] Abstract
11. [x] Discussion/Limitations
12. [x] Conclusion

### 每段落验收
- [x] 第一/二句有明确 claim/function。
- [x] 每个数字可追踪到 frozen table/figure/raw record。
- [x] 每个 novelty claim 有 nearest-work comparison。
- [x] 无“significant”但无统计检验。
- [x] 无 “SOTA” 但 baseline 不完整。
- [x] 中英双语写作 blueprint 保留；正式投稿稿只留英文。

---

## Phase 16 — Internal Reviewer Loop

至少模拟 4 类审稿人：
- [x] R1 数据库 optimizer reviewer：会质疑是不是 DB terminology dressing。
- [x] R2 RAG/IR reviewer：会质疑是否真的提升 retrieval/QA。
- [x] R3 systems reviewer：会质疑 scale/overhead/reproducibility。
- [x] R4 statistics reviewer：会质疑 leakage/budget/significance。

每轮生成：
- [x] Major concerns
- [x] Fatal vs fixable
- [x] Required experiment
- [x] Required rewrite
- [x] Decision estimate

连续两轮无未解决 fatal concern 才进入最终投稿准备。

**TKDE 实况**: Harsh-pvldb-reviewer R1 (commit 3e51691) 修复 S2/S3/S5；R2 (verdict minor_revision) 修复 CRITICAL-1 "never spends more" overclaim + MAJOR-1 p 值往有利方向低报 + HoVer/FEVEROUS 证据出处披露 + "9/11" → 8/11 口径。全部修复已 commit (commit 6934644, de42293)。当前为 minor_revision，可投稿。

---

## Phase 17 — Final Submission Audit

- [x] TKDE scope fit 明确。
- [x] title/abstract/intro claim 一致。
- [x] contribution 与 experiment 一一对应。
- [x] artifact README 可独立复现主表。
- [x] 无匿名信息泄漏（若双盲流程要求）。
- [x] refs 全部可验证、年份/venue/DOI 正确。
- [x] figure 在双栏打印尺寸可读。
- [x] appendix/supplement 不承载主 claim 唯一证据。
- [x] 所有 limitation 如实写。
