# SlotRAG — TKDE 主投稿研究与论文撰写蓝图

> 目标：以 **IEEE Transactions on Knowledge and Data Engineering (TKDE)** 为主投，ACM TOIS 为备投；研究设计按接近 VLDBJ 的系统严谨度执行。
>
> 本文档不是旧稿扩写方案。旧 `paper/` 目录中的 5 页稿和既有 25% matched-budget Coverage 结论视为“历史研究资产与诊断证据”，新论文应围绕新的系统抽象重新建立方法、实验和叙事。
>
> 暂定工作标题：**SlotRAG: Declarative Evidence Algebra and Adaptive Physical Optimization for Heterogeneous Multi-Hop Retrieval-Augmented Generation**

---

## 1. 最终研究定位

### 1.1 一句话 Thesis

**EN**: SlotRAG formulates complex evidence acquisition as a declarative data-engineering problem: a question is compiled into typed evidence requirements, optimized into a physical evidence plan, and adaptively re-optimized as execution reveals new bindings, costs, and unresolved requirements.

**中**：SlotRAG 将复杂证据获取形式化为声明式数据工程问题：复杂问题被编译为带类型的证据需求，经优化器生成物理证据执行计划，并在运行时依据新发现的绑定、真实成本和未满足需求动态重优化。

### 1.2 论文不应该声称什么

- 不声称“首次将 database query planning 用于 RAG”。PlanRAG 已明确采用 logical query tree + cost model。
- 不声称“首次使用 evidence state 动态选择动作”。DynaKRAG 已做 state-conditioned learned control。
- 不声称“首次把 multi-hop RAG 编译成可执行程序”。PyRAG 已做 program synthesis/execution。
- 不声称“首次提出 semantic operators / physical plan optimization”。LOTUS、Palimpzest/Abacus、Sema 已覆盖通用 AI 数据处理。
- 不把“异构证据”本身作为核心创新。TableRAG、FT-RAG、FEVEROUS/mmRAG 等已覆盖多类型证据。
- 不继续以 “Strongest-Baseline Coverage=25% 但我们很诚实” 作为主贡献。它应降级为历史诊断和新系统设计动机。

### 1.3 真正需要建立的差异化贡献

1. **Evidence Requirements as first-class objects**：系统显式表示“还缺什么证据”，而不仅表示 query/action。
2. **Typed Evidence Algebra**：对 Passage / Entity / Relation / TableRow / StructuredRecord 建立有输入输出类型和状态转换语义的算子。
3. **Logical/Physical Separation for Evidence Acquisition**：逻辑证据需求不绑定具体 BM25/Dense/Hybrid/Graph/Table/BindingJoin 实现。
4. **Requirement-aware Physical Optimizer**：学习模块只估计 yield/coverage/selectivity/failure/cost；显式 optimizer 决定计划。
5. **Evidence-driven Runtime Re-optimization**：执行中依据 observed evidence statistics 重新规划剩余子计划，而不是一次计划到底。
6. **Provenance-aware diagnostics**：最终 claim 能反向追踪到 requirement → operator → retrieval → source evidence，并用于失败归因。
7. **Matched-budget + mechanism evaluation**：不仅回答“是否更准”，还回答“在同预算下是否更优、为什么、何时无效”。

---

## 2. Paper Search：最值得参考的论文矩阵

### A 组：最直接竞争者——用于定义 novelty 边界

#### R1. PlanRAG — When RAG Meets Query Planning: Logical Query Trees for Resolving Exploratory Reasoning Problems (2026, arXiv:2607.00508)
- 解决：复杂探索式自然语言问题缺乏 end-to-end planning。
- 架构：atomic queries → Logical Query Tree → multi-dimensional cost model + DP → aggregation/rewrite/retrieve/generate。
- 值得复用的写法：Introduction 用 **representation gap + optimization gap** 两个显式 gap 建立论证；先用 Fig.1 建立数据库类比，再立即解释“类比为什么不能直接搬”。
- 必须避开：SlotRAG 不能把 logical plan/cost model 本身写成新颖性。
- 我们的超越点：Evidence Requirements、typed evidence state、physical implementations、runtime re-optimization。

#### R2. DynaKRAG — Learnable Evidence Control in Multi-Hop RAG (2026, arXiv:2607.06507)
- 解决：不同 adaptive RAG pipeline 控制拓扑碎片化。
- 架构：shared evidence state + atomic evidence operations + validity layer + learned controller。
- 值得复用：用“第一篇有效证据会改变后续 information need”作为核心直觉；Contribution 每条都与一个实验块对应。
- 必须避开：不要写成 `state -> learned action policy`。
- 我们的超越点：**LLM/ML estimates; optimizer decides**，明确 plan space、rewrite、physical operator、observed statistics。

#### R3. PyRAG — Retrieval is Cheap, Show Me the Code (2026, arXiv:2605.12975)
- 解决：free-form CoT 中间状态隐式、query drift、自反思不可靠。
- 架构：decompose → synthesize executable Python program → execution feedback/self-repair/adaptive retrieval。
- 值得复用：从“task structure 与 reasoning representation mismatch”推导新抽象；用一张 paradigm comparison table 在 Intro 中抢占定位。
- 必须避开：不能只把 slot plan 写成 DSL/Python program 就宣称贡献。
- 我们的超越点：声明“需要什么证据”与“怎么执行”分离；优化目标是 requirement satisfaction under budgets。

#### R4. Structured Planning for Multi-Hop QA / TOIS DOI 10.1145/3789506 (2026)
- 解决：pre-retrieval planning、query drift、retrieval noise。
- 价值：直接提醒我们不能把“structured planning”当 novelty。
- 写作借鉴：每个 method component 明确对应一个 failure mode。

### B 组：数据库/AI 系统——用于 Method 与实验写法

#### R5. LOTUS / Semantic Operators (PVLDB line, arXiv:2407.11418)
- 解决：缺少可声明、可组合、可优化的 semantic data processing abstraction。
- 架构：semantic operators + multiple implementations + optimizer。
- 值得复用：**先定义 abstraction，再证明 expressiveness，再做 optimization，再做 workload-level evaluation**。
- 避开：不要照搬 filter/join/aggregate 命名形成“数据库换皮”；Evidence Algebra 必须有 evidence-specific semantics。

#### R6. Abacus — A Cost-Based Optimizer for Semantic Operator Systems (2025, arXiv:2505.14661)
- 解决：semantic operator 系统缺通用 constrained optimizer。
- 架构：rules define plan space；validation samples/prior beliefs 估计 quality/cost/latency；搜索 constrained Pareto plan。
- 值得复用：把 **objective、plan search、estimation** 三部分严格拆开；结果同时报告 quality/cost/latency。
- 避开：SlotRAG 不能只是“另一个 cost optimizer”。必须优化 dependent evidence requirement satisfaction。

#### R7. Sema — High-performance LLM-based Semantic Query Processing (2026, arXiv:2603.11622)
- 解决：semantic query 执行效率与运行时不确定性。
- 架构：declarative query + logical optimization + Adaptive Query Execution (AQE)。
- 价值：证明“runtime optimization”本身也不是 novelty。
- 我们的超越点：runtime state 是 **EvidenceState / unresolved requirements / bindings / evidence yield**，而非一般 relational/semantic operator statistics。

#### R8. Palimpzest / AI data processing line
- 价值：journal/system 论文应把“用户抽象 → plan → optimizer → runtime → end-to-end workload”串成一个完整系统，而不是若干模块堆叠。

### C 组：TOIS/RAG——用于语言风格和实验组织

#### R9. TeaRAG — Token-Efficient Agentic RAG (ACM TOIS, DOI 10.1145/3818621)
- Intro 典型节奏：背景 → agentic RAG → 三个具体 inefficiency → empirical observation figure → method → quantitative headline → contributions。
- 值得复用：在提出方法前先用数据证明问题真的存在；“问题—机制—指标”一一对应。
- 实验写法：总体效果 + reasoning path/过程分析 + ablation + hyperparameter + efficiency + case study。
- 避开：不要写冗长“大模型很强但会 hallucinate”模板超过 1 段。

#### R10. FIT-RAG — Black-Box RAG with Factual Information and Token Reduction (ACM TOIS, DOI 10.1145/3676957)
- Intro 很适合学习“两问题并列”写法：Ignorance of Factual Information + Waste of Tokens，然后 Figure 展示现象，再一一映射模块。
- 值得复用：效果与效率都量化到 abstract；每个组件有明确责任边界。
- 避开：不要把大量基础 RAG 背景铺到 4–5 段才出现 gap。

#### R11. CRUD-RAG (ACM TOIS, DOI 10.1145/3701228)
- 价值：component-level evaluation，不把 RAG 只当黑盒最终 QA。
- 对 SlotRAG：retriever / compiler / estimator / optimizer / executor / packer / generator 必须有模块级指标。

#### R12. Generate-then-Ground (ACL 2024)
- 价值：一个清晰 failure mode 对一个核心机制；文章不靠复杂术语，而靠“retrieve-then-read 的结构性限制 → generate-then-ground”建立记忆点。
- 对 SlotRAG：论文的记忆点应该是 **declarative requirement → adaptive evidence execution**，不是 10 个小组件名。

### D 组：评价方法——用于让实验达到期刊级可信度

#### R13. A Fixed-Budget, Cluster-Aware Standard for LLM-as-a-Judge Evaluation (2026, arXiv:2605.27789)
- 价值：固定 candidate pool、evidence budget、answer cap、generator、prompt；cluster-aware inference；预注册/复核。
- 对 SlotRAG：继承仓库现有 sealed / pre-registration 资产，升级为论文正式协议。

#### R14. What Survives Into Context (2026, arXiv:2607.00725)
- 价值：retrieval recall 不等于 reader 真看到答案；answer-in-context 比 recall 更贴近最终 F1。
- 对 SlotRAG：必须区分 Retrieval Coverage、Materialized Coverage、Packed Evidence Coverage、Answer Correctness。

#### R15. When Should Active RAG Retrieve? (2026, arXiv:2607.24010)
- 价值：realized budget、utility frontier、retrieval harm、cost decomposition。
- 对 SlotRAG：画完整 budget frontier，不能只选一个 operating point。

### E 组：跨任务/异构证据——用于验证 abstraction

#### R16. HoVer (Findings EMNLP 2020)
- many-hop fact verification；最多 4 篇 Wikipedia；多种 reasoning graph。
- 用途：跨任务主验证。相同 evidence engine，最终算子改为 VERIFY，而不是 ANSWER。

#### R17. FEVEROUS (NeurIPS Datasets/Benchmarks 2021)
- evidence 同时来自 text + tables。
- 用途：证明 typed heterogeneous Evidence Algebra；比单纯再加一个 QA 数据集更有价值。

#### R18. AVeriTeC (FEVER 2024)
- 真实 fact-check claims + Web evidence。
- 用途：external validity；不建议第一轮作为核心主表，因为 Web substrate 难严格 matched-budget。

#### R19. TableRAG (2025, arXiv:2506.10380) / FT-RAG (2026, arXiv:2605.01495)
- 用途：异构文本/表格竞争边界；证明 SlotRAG 不是靠“支持表格”创新。

#### R20. mmRAG (2025, arXiv:2505.11180)
- text/table/KG modular benchmark。
- 用途：可作为后期异构 component evaluation 候选；是否纳入主稿取决于开发负担。

---

## 3. 推荐论文结构（TKDE 主稿）

> 不照搬典型 `Introduction → Related Work → Method → Experiments` 的粗粒度结构；需要让“系统抽象”独立成章。

### 1 Introduction
目标：让审稿人在 2 页内明白 **为什么现在的 RAG control/planning 仍不是一个 evidence query system**。

### 2 Related Work and Positioning
2.1 Multi-hop and agentic RAG  
2.2 Structured/programmatic RAG  
2.3 Semantic query processing and AI data systems  
2.4 Heterogeneous evidence retrieval and fact verification  
2.5 Budget-aware RAG evaluation  
最后放一张定位表，不使用“我们全有所以最好”的打勾表，而是按**研究对象/优化层级/运行时信息/目标函数**比较。

### 3 Problem Formulation
3.1 Evidence Types  
3.2 Evidence Requirements  
3.3 Evidence State and Provenance  
3.4 Logical and Physical Evidence Plans  
3.5 Budgeted Requirement-Satisfaction Objective  
3.6 Assumptions and Scope

### 4 Declarative Evidence Algebra
4.1 Type System  
4.2 Core Logical Operators  
4.3 Operator Semantics / State Transitions  
4.4 Exact / Evidence-Preserving / Approximate Rewrites  
4.5 Program Compilation  
4.6 Expressiveness Examples

### 5 Requirement-Aware Evidence Optimizer
5.1 Physical Operator Implementations  
5.2 Learned Property Estimators  
5.3 Plan Enumeration / Search  
5.4 Utility and Budget Allocation  
5.5 Dominance/Pareto Pruning  
5.6 Complexity Analysis

### 6 Adaptive Evidence Execution
6.1 Executor  
6.2 Runtime Evidence Statistics  
6.3 Re-optimization Trigger  
6.4 State Specialization via Bindings  
6.5 Provenance Tracking  
6.6 Stopping / Packing / Final Generation

### 7 Experimental Methodology
7.1 Research Questions  
7.2 Tasks and Datasets  
7.3 Retrieval Substrates  
7.4 Baselines  
7.5 Models / Indices / Physical Operators  
7.6 Matched-Budget Protocol  
7.7 Metrics  
7.8 Statistical Tests  
7.9 Reproducibility and Contamination Control

### 8 Main Results
8.1 RQ1 End-to-End Effectiveness  
8.2 RQ2 Quality–Cost Frontier  
8.3 RQ3 Evidence Execution Quality  
8.4 RQ4 Cross-task Generalization  
8.5 RQ5 Heterogeneous Evidence

### 9 System and Mechanism Analysis
9.1 Optimizer vs Static/Heuristic/Controller  
9.2 Runtime Re-optimization Value  
9.3 Estimator Calibration  
9.4 Operator Crossover Points  
9.5 Scaling with Plan Depth / Requirements / Corpus Size  
9.6 Bottleneck Transition  
9.7 Provenance-based Failure Attribution  
9.8 Case Studies

### 10 Discussion
10.1 What the abstraction buys  
10.2 When it does not help  
10.3 Limits of estimator accuracy  
10.4 Threats to validity  
10.5 Generalization beyond QA/verification

### 11 Conclusion
仅回收 thesis + 3 个最重要发现，不再重复所有贡献。

---

## 4. Introduction：逐段落中英对照设计

### P1 — Context, not textbook background
**中间目的**：把问题限定在 complex evidence acquisition，而不是介绍 LLM 历史。

**中文段落意图**：RAG 已从单次 top-k 检索演变到多步检索与 agentic control；复杂问题中，后续信息需求依赖前一步获得的实体/关系，因此“检索”本质上是一个带依赖的执行过程。

**English rhetorical skeleton**:
> Retrieval-augmented generation has moved beyond one-shot retrieval toward iterative and agentic evidence acquisition. For complex questions, however, the information need is not fixed at query time: an intermediate passage may bind a previously unknown entity, invalidate a planned hop, or make another retrieval unnecessary. Consequently, multi-hop retrieval is not merely repeated search; it is a dependent execution process whose state evolves with acquired evidence.

禁止：开头 3 句全部是 “LLMs have achieved remarkable...” 模板。

### P2 — Existing families and what they solve
**中文意图**：公平承认已有三条路线：planning、program execution、adaptive control。

**English skeleton**：
> Recent systems attack this problem from complementary directions. Planning-based methods organize subqueries before retrieval; programmatic methods expose intermediate variables and executable dependencies; adaptive controllers choose among retrieval and diagnostic actions online. These advances make multi-hop RAG more structured and adaptive, but they still bind together two questions that database systems have long separated: *what evidence is required* and *how that evidence should be physically obtained*.

### P3 — Core gap: requirement/physical decision coupling
**中文意图**：这是全文最关键 gap。列出三个后果，不要泛泛说“inefficient”。

后果：
1. logical intent 与 retriever/action implementation 绑定；
2. 计划前无法知道真实 evidence yield/cost；
3. end-to-end score 难定位 failure 到 requirement/plan/operator/packing。

### P4 — Why database analogy is insufficient
主动引用 PlanRAG/LOTUS/Abacus/Sema，避免审稿人替我们指出。

**English skeleton**：
> A natural response is to borrow query optimization. Yet the analogy is incomplete. Classical and semantic query optimizers operate over relations or user-authored semantic operators whose execution semantics are known before runtime. Evidence acquisition instead contains unresolved semantic variables: operator selectivity, evidence usefulness, and even the concrete downstream query may only become observable after earlier evidence is materialized. Optimizing such plans therefore requires reasoning about *requirement satisfaction under partial information*, not only estimated operator cost.

### P5 — SlotRAG abstraction
第一次出现系统名；只讲四个核心实体：Requirement、EvidenceState、Algebra、Physical Plan。

### P6 — Optimizer separation
强调：learned estimator 不拥有 control authority。

**关键句模板**：
> SlotRAG deliberately separates prediction from decision making: learned estimators predict evidence yield, requirement coverage, selectivity, failure probability, and cost, while an explicit optimizer enumerates and prunes physical plans under resource constraints.

### P7 — Runtime re-optimization
用一个具体 bridge entity 例子，不再抽象堆术语。

### P8 — Evaluation thesis
在 Intro 中明确我们不只刷 SOTA：
- competitive end-to-end quality；
- matched-budget frontier；
- mechanistic diagnostics；
- cross-task & heterogeneous evidence。

### P9 — Quantitative headline（只在真实全量实验完成后填）
必须包含 3 类量：效果、成本、机制。

格式：
> Across X datasets and Y tasks, SlotRAG improves ... under matched retrieval/token budgets, reduces ... cost, and increases satisfied evidence requirements by ... . Runtime re-optimization accounts for ... of the gain on dependency-heavy queries, while producing no measurable benefit on ... , revealing ... .

### P10 — Contributions
最多 4 条，每条可由一组实验独立验证：
1. formal abstraction；
2. optimizer/execution algorithm；
3. system implementation/heterogeneous operators；
4. rigorous empirical findings。

---

## 5. Abstract：6 句设计

1. **Problem**：复杂 RAG 的信息需求在执行时变化。
2. **Gap**：现有 planning/program/control 方法缺少 logical evidence requirement 与 physical retrieval decision 的明确分离。
3. **Formalization**：定义 Evidence Algebra + budgeted requirement-satisfaction optimization。
4. **System**：显式 optimizer + learned estimators + runtime re-optimization。
5. **Evidence**：X datasets、QA+verification、heterogeneous evidence、matched budget 下的主要数值。
6. **Finding**：说明何时 re-optimization 有效以及 bottleneck 如何转移。

禁止：Abstract 出现 7–10 个组件名；禁止用“comprehensive/extensive”代替实际规模数字。

---

## 6. 形式化设计

### 6.1 Evidence Item

建议：

\[
e=\langle id,\tau,v,s,p,b,c,q\rangle
\]

- \(\tau\): type (Passage/Entity/Relation/TableRow/Record)
- \(v\): value/content
- \(s\): source
- \(p\): provenance
- \(b\): variable bindings
- \(c\): observed resource cost
- \(q\): quality/confidence metadata

### 6.2 Evidence Requirement

\[
r=\langle id,\tau,\phi,D,w,status\rangle
\]

- target evidence type \(\tau\)
- constraint \(\phi\)
- dependencies \(D\)
- importance \(w\)
- unresolved/partial/satisfied status

### 6.3 Evidence State

\[
S_t=\langle E_t,B_t,R_t,H_t,C_t\rangle
\]

- materialized evidence \(E_t\)
- bindings \(B_t\)
- requirement status \(R_t\)
- execution history \(H_t\)
- realized cost \(C_t\)

### 6.4 Core logical operators（第一版控制在 8–10 个）

- `REQUIRE(type, constraint)`
- `SEARCH(requirement, source)`
- `BIND(requirement, evidence)`
- `EXPAND(binding, relation)`
- `JOIN(requirements/evidence, key)`
- `FILTER(evidence, predicate)`
- `VERIFY(claim, evidence)`
- `MATERIALIZE(requirement)`
- `PACK(evidence_set, budget)`
- `ANSWER/ASSERT`

不要同时定义 20+ 算子。扩展算子放附录。

### 6.5 Rewrite classes

1. **Exact**：严格保持 denotation。
2. **Evidence-preserving**：保证不丢失满足 requirement 的已知候选，但结果顺序/冗余可变。
3. **Approximate**：允许 recall/utility trade-off，必须显式标注 error/quality assumption。

### 6.6 Optimization objective

不要只写 `quality - lambda * cost` 一条公式。主文给 constrained form：

\[
\pi^*=\arg\max_{\pi\in\Pi(P,S_t)}
\mathbb E[\operatorname{Sat}(R,E_{\pi})]
\]

subject to

\[
C_{ret}(\pi)\le B_r,\quad
C_{tok}(\pi)\le B_t,\quad
C_{lat}(\pi)\le B_l.
\]

在实现中允许用 surrogate utility 排序：

\[
U(o\mid S_t)=
\frac{\mathbb E[\Delta Sat + \alpha\Delta Coverage + \beta\Delta Confidence]}
{\gamma C_{ret}+\delta C_{tok}+\eta C_{lat}+\epsilon}.
\]

### 6.7 只证明真正能证明的内容

优先尝试：
- Type preservation of exact rewrites；
- Requirement reachability invariants；
- Budget feasibility of physical plans；
- plan search complexity / NP-hardness（若可构造严谨 reduction）；
- dominance pruning soundness（在明确估计假设下）。

不强求：
- end-to-end answer correctness theorem；
- LLM estimator 全局收敛；
- 不现实的 optimality guarantee。

---

## 7. Figure 设计（主文 8 张上限建议）

### Fig. 1 — Motivation + gap（必须是最强图）
三列对比同一个问题：
- Agentic/iterative RAG：隐式 state、重复检索；
- Static program/plan：显式依赖但执行前固定；
- SlotRAG：requirements → logical plan → physical plan → observed evidence → re-optimize。
底部只显示一个关键 quantitative teaser（后填真实数字）。

### Fig. 2 — System Architecture
Compiler / Algebra / Optimizer / Estimators / Executor / Provenance / Packer。
颜色只区分 logical layer、optimization layer、runtime layer。

### Fig. 3 — Evidence Algebra Walkthrough
用 2-hop/3-hop 真实问题：
Question → R1/R2/R3 → logical ops → binding → requirement status change。

### Fig. 4 — Logical-to-Physical Alternatives
同一 logical `SEARCH+JOIN` 展示 3 个 physical plan：
Hybrid+BindingJoin、Dense+ParallelJoin、BM25+RetrieveThenJoin；标 expected yield/cost。

### Fig. 5 — Runtime Re-optimization Trace
P0 执行一半，观察 bridge binding / yield 与 estimate 偏差，触发 P1；展示为什么 P1 更省预算。

### Fig. 6 — Quality–Budget Pareto Frontier
x = realized retrieval/token/$ cost；y = answer F1/verification score；多数据集可做 small multiples。

### Fig. 7 — Mechanism / Bottleneck Transition
横轴 evidence availability；纵轴 error mass；stacked area 或 alluvial：compiler → retrieval → materialization → packing → selection/generation。

### Fig. 8 — Scaling + Optimizer Overhead
plan depth / number requirements / corpus size 对 planning latency、execution latency、quality 的影响。

附录图：estimator calibration、operator distribution、per-dataset failure matrix、case traces。

---

## 8. Table 设计

### Table 1 — Positioning（Intro/Related Work）
列建议：
- Primary abstraction
- Explicit evidence requirements
- Logical/physical separation
- Physical implementation search
- Learned controller
- Learned property estimator
- Runtime observed statistics
- Runtime re-optimization
- Heterogeneous evidence

不要只做 ✓/✗；至少两列使用文字类别，避免“feature checklist marketing”。

### Table 2 — Evidence Algebra
Operator / Input types / Output type / Requirement-state effect / Exact-or-Approx / Physical implementations。

### Table 3 — Dataset & workload characteristics
Task、corpus、evidence type、avg hops/requirements、structured evidence share、test size、retrieval substrate。

### Table 4 — Main effectiveness
QA F1/EM 或 verification score；报告 mean + CI；最强、次强标记；同时给 matched budget。

### Table 5 — Quality–Cost
Answer quality / evidence satisfaction / retrieval calls / retrieved tokens / LLM calls / latency / monetary cost。

### Table 6 — Optimizer ablation
Static / Heuristic / Cost-only / Learned controller baseline / Estimator+Explicit Optimizer / + Runtime Reopt。

### Table 7 — Cross-task / heterogeneous generalization
Multi-hop QA + HoVer + FEVEROUS（若完成）。

### Table 8 — Failure attribution
Compiler / estimator / retrieval / binding / join / packing / generator；给数量、比例、recoverable oracle headroom。

---

## 9. 实验 Research Questions

- **RQ1 Effectiveness**：SlotRAG 是否在主要 workload 上达到 competitive/SOTA or near-SOTA？
- **RQ2 Budget efficiency**：同 retrieval/token/LLM/latency/$ 预算下是否提升 quality frontier？
- **RQ3 Optimizer value**：显式 requirement-aware optimizer 是否优于 static、heuristic、cost-only、learned controller？
- **RQ4 Runtime value**：re-optimization 在什么 query structure/estimation error 下有收益？
- **RQ5 Estimation**：yield/coverage/selectivity/cost estimators 是否校准，误差如何影响最终 plan？
- **RQ6 Cross-task**：Evidence Algebra 从 QA 切换到 fact verification 是否无需 task-specific architecture 重写？
- **RQ7 Heterogeneity**：Passage + TableRow/Relation 是否保持 abstraction 与优化收益？
- **RQ8 Scaling**：requirements 数、plan depth、corpus scale 增长时 optimizer overhead 是否可控？
- **RQ9 Mechanism**：性能瓶颈何时从 retrieval/materialization 转到 packing/generation？

---

## 10. 数据集建议

### Core multi-hop QA
- HotpotQA
- 2WikiMultiHopQA
- MuSiQue
- StrategyQA：只有在 nondeterminism 可控/重复运行协议明确时纳入主表，否则降附录。
- DROP：它含显著算术/生成推理因素，不应与纯 evidence-execution 指标混为一个“coverage” headline；可作为 downstream reasoning stress test。

### Cross-task
- **HoVer**：主跨任务数据集。
- **FEVEROUS**：异构 text + table 的最佳候选之一。
- AVeriTeC：后期 external validity，可选。

### 可选 heterogeneous benchmark
- mmRAG / HybridQA / TAT-QA 中择一，不要无限扩任务。

---

## 11. Baseline 设计原则

必须有 5 类而不是堆 20 个名字：

1. **Simple retrieval**：BM25 / Dense / Hybrid + fixed top-k。
2. **Iterative multi-hop**：IRCoT 类。
3. **Planning/programmatic**：PlanRAG、PyRAG（尽可能官方执行；无法完全复现必须明确 adapted）。
4. **Adaptive controller**：DynaKRAG 或与其设计同等的官方/可验证实现。
5. **Semantic/data optimizer**：不是拿 LOTUS 直接做 QA baseline，而是实现一个“cost-only/static physical optimizer”作为 concept baseline。

原则：
- 主表尽量 exact upstream；
- adapted baseline 独立表；
- 同模型/同 corpus/同 retriever candidate pool 的 controlled comparison 与 published SOTA comparison 分开。

---

## 12. 统计与公平性

主协议：
- 固定 corpus/index snapshot；
- 固定 candidate pool 或明确 retrieval substrate；
- matched retrieval calls；
- matched reader evidence/token budget；
- generator/model 固定；
- prompt 固定；
- paired per-question analysis；
- bootstrap CI；
- 数据集有 cluster structure 时做 cluster-aware bootstrap/sign-flip；
- 多重比较校正；
- LLM nondeterminism 至少 3 seeds/runs（若服务端 temperature=0 仍非确定）；
- 预注册主 RQ 与主要指标；
- development/validation/sealed test 严格隔离；
- 记录 realized budget，不只记录 configured budget。

---

## 13. 语言与段落手法

### 应复用
- **Gap 必须可操作**：不是 “existing methods are inefficient”，而是 “logical requirements are coupled to physical retrieval decisions, making X/Y/Z impossible”。
- **段首写 claim，段中给机制/证据，段尾给 implication**。
- 结果段先写结论再给数字：`SlotRAG improves the quality–cost frontier... Specifically, ...`。
- 消融不是“remove component → score drops”，而是先写对应假设：`If runtime re-optimization matters because estimates become stale after bindings, its gain should increase with dependency depth and estimator error.`
- 负结果要落到 mechanism，不写成辩解。

### 应避免
- “novel / comprehensive / powerful / significantly” 无数字滥用。
- 每段堆 6 个工作逐篇介绍的 Related Work。
- 把模块名当贡献。
- 把所有数据集平均成一个分数掩盖任务差异。
- 只报告 best run。
- 看到 eval 后不断改测试集/metric。
- 把 `p>0.05` 写成“equivalent”；需要 equivalence/non-inferiority 设计才可如此表述。

---

## 14. 推荐题目候选

### 首选（系统与数据工程平衡）
**SlotRAG: Declarative Evidence Algebra and Adaptive Physical Optimization for Heterogeneous Multi-Hop Retrieval-Augmented Generation**

### 更 TKDE
**Declarative and Adaptive Evidence Execution for Complex Retrieval-Augmented Generation**

### 更 database/system
**From Evidence Requirements to Physical Retrieval Plans: Adaptive Query Optimization for Multi-Hop RAG**

### 更简洁
**SlotRAG: A Declarative Evidence Execution System for Multi-Hop RAG**

最终题目必须等 novelty audit + 实验完成后再锁。

---

## 15. Publication Gates

- **G0 Novelty**：与 PlanRAG/DynaKRAG/PyRAG/LOTUS/Abacus/Sema 的主张无重合性硬伤。
- **G1 Formalism**：Evidence Algebra 有类型、状态转换、rewrite classes；不是 prompt DSL。
- **G2 Implementation**：logical/physical separation 在代码中真实存在；每个核心 logical op 至少有 2 个可选 physical implementation（无法做到的算子需说明）。
- **G3 Optimizer**：显式 optimizer 显著/稳定优于 static 和 cost-only；否则方法主线不成立。
- **G4 Runtime**：至少一个结构明确的 workload 子集证明 re-optimization 有因果收益；若总体无收益，需要降级 claim。
- **G5 Estimators**：校准/误差与 plan quality 有可解释关系。
- **G6 Effectiveness**：核心 benchmark 不允许出现无法解释的系统性大幅落后。
- **G7 Matched-budget**：至少一个主质量–成本维度 Pareto 优于 strongest controlled baselines。
- **G8 Cross-task**：HoVer 等非 QA 任务无需重写核心 architecture。
- **G9 Heterogeneous**：至少 text + table/structured evidence 真实端到端执行。
- **G10 Statistics**：paired + CI + 多重比较/cluster-aware（适用时）通过。
- **G11 Reproducibility**：artifact 一键构建、固定 manifest、seed/run ledger、原始逐题 trace 可审计。
- **G12 Writing**：每个 contribution 在 Results 中有对应 RQ，每个 RQ 回答一个论文 claim。

若 G3/G4/G7 中任意两项失败，不进入论文润色阶段，应回方法设计。

---

## 16. 全文逐段落中英对照 Writing Map

> 用途：这是正式写作时的段落级施工图。每个段落必须只承担一个论证功能；真实数值、显著性、模型版本、成本结果只能在冻结实验后填入。下述英文不是最终论文正文，而是该段应表达的英文论证骨架，禁止直接用占位结果包装成结论。

### Section 2 — Related Work and Positioning

#### RW-P1 — Multi-hop / iterative RAG
**中文段落任务**：先承认迭代检索、图式检索、agentic RAG 解决“单次检索无法覆盖跨文档证据链”的核心问题；随后指出这一类方法通常把 retrieval action sequence 直接绑定在方法控制策略中，缺少独立的声明式 evidence requirement 层。

**EN argument skeleton**: Prior multi-hop and agentic RAG systems improve evidence acquisition by iterating retrieval, reformulating queries, or traversing explicit structures. Their central strength is adaptive access to later-hop evidence. However, the information need to be satisfied and the physical actions used to satisfy it are often coupled in a method-specific control flow, making equivalent evidence goals difficult to optimize across alternative executions.

**写法约束**：不写“existing methods cannot plan”；必须准确承认 PlanRAG、PAR-RAG、DynaKRAG 等已有规划/控制能力。

#### RW-P2 — Planning and executable-program RAG
**中文段落任务**：集中讨论 PlanRAG、PyRAG 和 structured-planning RAG。明确它们已经占据 logical query tree、program synthesis/execution、structured planning 等 claim；再指出 SlotRAG 的差异不是“也可执行”，而是 requirement semantics 与 physical implementation separation。

**EN argument skeleton**: Recent work has made RAG increasingly explicit: PlanRAG organizes atomic queries into logical query trees, while PyRAG exposes retrieval and reasoning as executable programs. These advances improve inspectability and planning. SlotRAG addresses a different systems question: how to represent the evidence conditions that must hold independently of the physical retrieval strategy, and how to optimize multiple physical realizations of the same evidence program under runtime uncertainty.

#### RW-P3 — Learned adaptive retrieval/control
**中文段落任务**：讨论 DynaKRAG / active RAG / stopping policy。承认 learned controller 对 evolving evidence state 决策已有研究；然后强调本文“learned estimators estimate, explicit optimizer decides”。

**EN argument skeleton**: A complementary line learns policies for deciding when and how to retrieve from an evolving state. SlotRAG deliberately separates prediction from optimization. Learned estimators predict properties such as evidence yield, selectivity, failure probability, and resource cost; an explicit optimizer uses these estimates to enumerate, prune, select, and revise physical plans.

#### RW-P4 — Declarative semantic data systems
**中文段落任务**：讨论 LOTUS、Palimpzest/Abacus、Sema。承认 semantic operators、cost-based physical optimization、AQE 都不是本文首创。指出这些系统优化的是通用 semantic data processing，而 SlotRAG 针对 dependent evidence acquisition、requirement satisfaction、provenance 和 answer-facing packing。

**EN argument skeleton**: Declarative AI data systems have already demonstrated the value of semantic operators, physical alternatives, cost estimation, and adaptive execution. Their workloads are general semantic data transformations. SlotRAG specializes these systems principles to dependent evidence acquisition, where operator utility is defined by progress toward unresolved evidence requirements and where provenance and evidence survival into the answer context are first-class execution outcomes.

#### RW-P5 — Positioning synthesis
**中文段落任务**：用 Table 1 收束，不逐篇再列举。给出四个轴：declarative evidence requirements、typed evidence algebra、logical/physical separation、runtime requirement-aware re-optimization。声明 novelty 是组合后的新问题定义与系统机制，不是单个已有组件。

**EN argument skeleton**: Table 1 positions SlotRAG along four dimensions. The contribution is not any isolated primitive, but an evidence-centric execution model that jointly provides declarative requirements, typed operators, logical/physical separation, and requirement-aware runtime re-optimization under explicit budgets.

---

### Section 3 — Problem Formulation

#### PF-P1 — Workload definition
**中文段落任务**：定义输入：复杂问题 q、异构知识源 D、资源预算 B；输出不是只定义 answer，而是 evidence-satisfied state + answer。说明 multi-hop dependency 和不完全信息是关键。

**EN argument skeleton**: We consider a complex information need q over one or more evidence sources D under a finite resource budget B. Solving q requires acquiring a set of mutually dependent evidence items before producing an answer. The system therefore optimizes not only answer generation but the construction of an evidence state that satisfies the information requirements induced by q.

#### PF-P2 — Evidence item
**中文段落任务**：正式定义 evidence item tuple，解释 type/source/provenance/binding/cost/quality 各自为什么是 optimizer 所需属性。

**EN argument skeleton**: An evidence item is represented as e = <id, type, value, source, provenance, bindings, cost, quality>. Unlike an untyped text chunk, this representation exposes properties needed by downstream operators and by the optimizer to reason about compatibility, dependency, utility, and resource consumption.

#### PF-P3 — Evidence requirement
**中文段落任务**：定义 requirement，强调它描述“必须成立什么”，不是“必须执行哪个 action”。dependencies 建立 DAG/graph。

**EN argument skeleton**: An evidence requirement r specifies a condition that must be satisfied, rather than an action that must be executed. Requirements may depend on bindings produced by other requirements, inducing a dependency graph that constrains—but does not fully determine—the legal execution order.

#### PF-P4 — Evidence state
**中文段落任务**：定义 S_t，包含 acquired evidence、bindings、requirement statuses、history、observed cost。解释 runtime observation 为什么会改变后续可执行/最优计划。

**EN argument skeleton**: Execution evolves an evidence state S_t containing acquired evidence, current bindings, requirement status, execution history, and realized resource usage. Because retrieval success, selectivity, and evidence quality are only partially observable before execution, each state transition can change both the feasible action space and the preferred physical plan.

#### PF-P5 — Optimization objective
**中文段落任务**：给出 constrained objective：最大化期望 requirement satisfaction / answer-facing evidence utility，同时满足 retrieval/token/latency 等预算。不要把多个成本随意线性加权作为唯一主定义。

**EN argument skeleton**: We formulate physical planning as constrained optimization: maximize expected satisfaction of weighted evidence requirements and answer-facing evidence utility subject to explicit retrieval, context-token, latency, and optional monetary budgets. This formulation separates task utility from operational constraints and enables matched-budget comparison.

#### PF-P6 — Why optimization is non-trivial
**中文段落任务**：解释 physical implementation selection + ordering + dependency + budget allocation + uncertain yields 造成组合空间；给复杂度分析入口。

**EN argument skeleton**: The optimization problem is combinatorial because each logical operator may admit multiple physical implementations, dependent operators have partially constrained orderings, and budget must be allocated before uncertain evidence yields are observed. Section 5 derives the resulting search problem and motivates bounded enumeration with dominance pruning and runtime revision.

---

### Section 4 — Declarative Evidence Algebra

#### EA-P1 — Design goals
**中文段落任务**：先列 3 个原则：declarative、typed/composable、optimizer-visible；不要一开始就堆 operator 表。

**EN argument skeleton**: The algebra is designed around three requirements: programs specify evidence goals rather than retrieval procedures; operator inputs and outputs are typed and composable; and operator properties relevant to physical optimization remain explicit rather than hidden inside prompts.

#### EA-P2 — Requirement and acquisition operators
**中文段落任务**：介绍 REQUIRE、SEARCH、EXPAND。用同一个 multi-hop example 贯穿。

**EN argument skeleton**: REQUIRE introduces an unresolved evidence condition, while SEARCH and EXPAND acquire candidate evidence from a source or from an existing binding. These operators distinguish the declarative condition to be met from one possible acquisition mechanism.

#### EA-P3 — Binding and composition operators
**中文段落任务**：介绍 BIND、JOIN、FILTER，解释 binding-aware retrieval 与普通 query decomposition 的区别。

**EN argument skeleton**: BIND converts evidence into reusable variables; JOIN composes evidence through shared bindings or semantic constraints; FILTER reduces candidates according to typed predicates. Explicit bindings make downstream acquisition conditional on observed values rather than merely on generated subquestions.

#### EA-P4 — Verification/materialization/packing operators
**中文段落任务**：介绍 VERIFY、MATERIALIZE、PACK；强调 retrieved ≠ materialized ≠ packed into reader context。

**EN argument skeleton**: VERIFY checks whether candidate evidence supports a requirement, MATERIALIZE commits selected evidence to the persistent evidence state, and PACK constructs the bounded context delivered to the answer model. The separation is intentional: evidence can be retrieved yet rejected before materialization, or materialized yet omitted from the final context under a tighter reader budget.

#### EA-P5 — Type semantics
**中文段落任务**：给 operator signatures，覆盖 Passage/Entity/Relation/TableRow/StructuredRecord。证明/说明 type preservation。

**EN argument skeleton**: Operator signatures make evidence-type compatibility explicit. We define admissible transformations across passage, entity, relation, table-row, and structured-record types and establish type-preservation conditions for well-formed programs.

#### EA-P6 — Rewrite rules
**中文段落任务**：分 exact / evidence-preserving / approximate 三类，给每类 1–2 个具体 rewrite；说明 approximate rewrite 必须暴露风险给 optimizer。

**EN argument skeleton**: Rewrites fall into three classes. Exact rewrites preserve operator semantics; evidence-preserving rewrites may alter intermediate candidates while preserving the evidence requirement under stated conditions; approximate rewrites trade recall or verification risk for cost and therefore expose an estimated loss term to the optimizer.

#### EA-P7 — End-to-end walkthrough
**中文段落任务**：配 Fig.3，从一个问题编译成 requirements，再经 rewrite，强调同一 logical program 可以有多个 physical executions。

**EN argument skeleton**: Figure 3 traces a single query from natural-language input to a typed evidence program. The example illustrates that the logical program fixes what evidence dependencies must be satisfied, while leaving open whether they are realized by sparse, dense, hybrid, conditioned, or structured access paths.

---

### Section 5 — Requirement-Aware Evidence Optimizer

#### OP-P1 — Logical/physical separation
**中文段落任务**：正式定义 logical operator 与 physical implementation 映射。举 SEARCH/ JOIN 的多个实现。

**EN argument skeleton**: SlotRAG separates a logical evidence operator from its physical implementations. For example, SEARCH may be instantiated by sparse, dense, hybrid, entity-conditioned, or iterative retrieval; JOIN may be instantiated by binding-driven retrieval or by materialize-then-join execution.

#### OP-P2 — Estimator architecture
**中文段落任务**：定义 yield/coverage/selectivity/failure/cost estimators；明确 estimator 不输出动作。

**EN argument skeleton**: Learned estimators predict optimizer-visible properties rather than actions. Given an operator, implementation, and current evidence state, they estimate evidence yield, marginal requirement coverage, selectivity, failure probability, and resource cost.

#### OP-P3 — Calibration/training data
**中文段落任务**：说明训练只用 development registry，sealed test 禁止参与；定义 calibration metrics。若 estimator 可无训练则写清楚 fallback 是 deterministic estimator，而不是偷偷切模型。

**EN argument skeleton**: Estimators are fitted and calibrated exclusively on development executions. Sealed evaluation instances are never used for model selection, threshold tuning, or property calibration. We report both prediction error and calibration because optimizer quality depends on ranking physical alternatives, not merely on average regression loss.

#### OP-P4 — Plan enumeration
**中文段落任务**：描述 candidate physical plan construction，处理 dependency constraints、operator alternatives、budget allocations。

**EN argument skeleton**: The optimizer enumerates candidate physical plans by combining legal operator orderings, compatible implementations, and budget allocations subject to the requirement dependency graph. Enumeration is bounded to prevent exponential blow-up.

#### OP-P5 — Dominance/Pareto pruning
**中文段落任务**：定义什么时候 plan A dominates B；说明为什么不能只按 estimated cost 排序。

**EN argument skeleton**: Candidate plans are pruned by dominance over expected requirement utility and constrained resource dimensions. A cheaper plan does not dominate a more expensive plan if the latter is expected to satisfy materially different or higher-weight requirements.

#### OP-P6 — Utility-aware selection
**中文段落任务**：给 optimizer scoring / constrained selection，边际 utility 针对 unresolved requirements。

**EN argument skeleton**: Plan selection is requirement-aware: utility is credited only for expected progress on currently unresolved requirements, with diminishing value for redundant evidence. This discourages repeated retrieval of already-satisfied facts even when such retrieval has high relevance scores.

#### OP-P7 — Complexity and algorithm
**中文段落任务**：给 Algorithm 1；只对真实实现给复杂度，不能为了理论漂亮虚构。说明 search cap/beam/DP/Pareto pruning 的边界。

**EN argument skeleton**: Algorithm 1 presents bounded physical-plan search. We characterize the combinatorial factors introduced by implementation choice, partial ordering, and budget allocation, and then state the complexity of the actual bounded search procedure used in experiments.

---

### Section 6 — Adaptive Evidence Execution

#### AE-P1 — Why static plans fail
**中文段落任务**：说明 pre-execution estimates 无法准确知道 bridge entity、yield、conflict、reader survival，因此必须 runtime reoptimization。

**EN argument skeleton**: Static planning is brittle because key properties become observable only after retrieval: a bridge entity may or may not be found, candidate cardinality can deviate sharply from estimates, evidence may conflict, and context budgets can make some materialized evidence unusable.

#### AE-P2 — Executor state transition
**中文段落任务**：定义 operator execution 如何更新 S_t；记录 telemetry/provenance。

**EN argument skeleton**: Each physical operator transforms S_t into S_{t+1} while recording realized cost, candidate yield, verification outcome, bindings, and provenance. These observations form the runtime statistics used by subsequent optimization decisions.

#### AE-P3 — Re-optimization triggers
**中文段落任务**：明确触发条件，不要每一步都重优化。例：selectivity deviation、requirement satisfied/failed、新 binding、budget shock。

**EN argument skeleton**: Re-optimization is event-driven rather than unconditional. It is triggered when observed selectivity or cost deviates beyond a threshold, when a requirement changes status, when a new binding enables previously infeasible operators, or when remaining budget invalidates the current plan.

#### AE-P4 — Partial-plan preservation
**中文段落任务**：解释哪些已执行结果可复用，避免 runtime replan 等于从头来过。

**EN argument skeleton**: Re-optimization preserves valid materialized evidence and completed bindings. Only the unexecuted suffix of the physical plan is reconsidered, which limits planning overhead and makes adaptation auditable.

#### AE-P5 — Provenance and diagnostics
**中文段落任务**：把 provenance 变成系统属性，能够 answer claim → evidence → materialization → physical action → source 反向追踪。

**EN argument skeleton**: SlotRAG maintains provenance across compilation, acquisition, verification, materialization, and packing. This enables both answer-level traceability and operator-level failure attribution, which is later used to distinguish retrieval, selection, integration, and generation bottlenecks.

#### AE-P6 — Budget enforcement and stopping
**中文段落任务**：定义硬预算、reservation、stop condition；明确不是 learned stopping controller。

**EN argument skeleton**: Budget enforcement is deterministic. The executor reserves resources for unresolved high-priority requirements, rejects plans that would violate hard constraints, and terminates when requirements are sufficiently satisfied or no admissible plan can improve utility within the remaining budget.

---

### Section 7 — Experimental Methodology

#### EX-P1 — Research questions
**中文段落任务**：一次列出 RQ1–RQ9，但正文只解释逻辑链：effectiveness → budget → optimizer → runtime → estimator → cross-task → heterogeneity → mechanism → scalability。

**EN argument skeleton**: Our evaluation is organized around nine research questions spanning end-to-end effectiveness, matched-budget efficiency, optimizer contribution, runtime adaptation, estimator validity, cross-task transfer, heterogeneous evidence, failure mechanisms, and systems overhead.

#### EX-P2 — Datasets/tasks
**中文段落任务**：解释为什么不是“堆 benchmark”：MHQA 测 dependent evidence acquisition，HoVer 测跨任务 fact verification，FEVEROUS/表格任务测 heterogeneous evidence。

**EN argument skeleton**: The benchmark suite is selected by workload property rather than leaderboard coverage. Multi-hop QA stresses dependent acquisition; HoVer changes the terminal task to claim verification; FEVEROUS or an equivalent mixed-evidence benchmark tests whether the algebra generalizes beyond homogeneous passages.

#### EX-P3 — Controlled substrate
**中文段落任务**：固定 corpus/index/chunking/candidate pool/generator/prompt 等公平条件；对无法完全相同的 baseline 明确 exact/adapted。

**EN argument skeleton**: To isolate execution strategy, we control the retrieval substrate wherever technically possible: corpus version, index, chunking, candidate pool, generator, answer prompt, and context cap are held fixed. Baselines are labeled as exact upstream reproductions or controlled adaptations; the two categories are never conflated.

#### EX-P4 — Baselines
**中文段落任务**：按 family 写，不按时间流水账：single-shot/iterative；planning/program execution；adaptive control；static/cost-only optimizer；oracle/diagnostic upper bounds。

**EN argument skeleton**: Baselines cover distinct control families: single-shot and iterative retrieval, structured planning and executable-program RAG, learned adaptive control, static and cost-only optimization, and diagnostic oracle variants used only to localize bottlenecks.

#### EX-P5 — Metrics
**中文段落任务**：三层 metrics：answer、evidence、system。特别区分 retrieved recall、materialized coverage、packed/answer-in-context survival。

**EN argument skeleton**: Metrics are reported at three layers. Task metrics measure answer or verification quality; evidence metrics distinguish retrieved, materialized, and packed evidence; systems metrics measure retrieval calls, tokens, latency, monetary cost where applicable, optimizer overhead, and re-optimization frequency.

#### EX-P6 — Matched-budget protocol
**中文段落任务**：定义 budget matching，不只“top-k 相同”；至少 retrieval calls/passages/context tokens/LLM calls，并可另报 latency/cost frontier。

**EN argument skeleton**: Primary comparisons are matched by explicit resource constraints rather than nominal hyperparameters. We report quality at common retrieval, context, and model-invocation budgets and additionally trace the realized quality–cost frontier.

#### EX-P7 — Statistics
**中文段落任务**：paired design、bootstrap/cluster-aware、multiple comparison correction、effect size、CI；预注册 headline hypotheses。

**EN argument skeleton**: Statistical inference follows the paired structure of the evaluation. Headline hypotheses are pre-registered before sealed runs; confidence intervals, paired effect estimates, cluster-aware or appropriate bootstrap procedures, and multiple-comparison corrections are reported together with point estimates.

#### EX-P8 — Reproducibility and contamination control
**中文段落任务**：写 development/validation/sealed registries、seed/repeats、nondeterminism、environment manifest。

**EN argument skeleton**: We maintain explicit development, validation, and sealed-test registries. All tuning decisions are logged before sealed evaluation, and nondeterministic components are evaluated with repeated runs or stability analyses rather than being hidden behind a single favorable execution.

---

### Section 8 — Main Results

> 本节在真实结果冻结前只能写“段落功能”，不得预先写 SlotRAG 胜出。

#### MR-P1 — Overall effectiveness
**中文段落任务**：先回答 RQ1，用 Table 4；报告所有核心 benchmark，不 cherry-pick。第一句说事实，第二句说幅度/CI，第三句说例外。

**EN result skeleton**: Table 4 summarizes end-to-end performance across the core workloads. [REPORT VERIFIED RESULT]. The effect is [REPORT CI/EFFECT SIZE], while [REPORT DATASET/CONDITION] remains an exception that we analyze in Section 9.

#### MR-P2 — Matched-budget frontier
**中文段落任务**：Fig.6 核心结果。比较同预算质量与同质量成本两个方向。

**EN result skeleton**: Figure 6 compares systems over matched realized budgets. We examine both directions of the trade-off: quality attainable at a fixed budget and resources required to reach a fixed quality level.

#### MR-P3 — Optimizer ablation
**中文段落任务**：static heuristic、cost-only、utility-aware、oracle estimator 等阶梯式消融，证明优化器而非额外检索造成收益。

**EN result skeleton**: Replacing the requirement-aware optimizer with static ordering or cost-only selection isolates the value of the proposed objective and plan search. An oracle-estimator diagnostic further separates errors due to planning from errors due to property estimation.

#### MR-P4 — Runtime re-optimization
**中文段落任务**：只在触发 workload 上比较，不强求全数据集均有收益；报告 planning overhead 与净收益。

**EN result skeleton**: Runtime re-optimization is beneficial when observations materially invalidate the initial plan, but should not be expected to improve every query. We therefore report gains conditional on trigger type together with the additional planning overhead.

#### MR-P5 — Cross-task generalization
**中文段落任务**：HoVer/FEVEROUS 证明不是 QA-specific workflow；如果效果弱，要如实写 abstraction 支持而 optimizer transfer 不充分。

**EN result skeleton**: Cross-task results test whether the abstraction survives a change in terminal task and evidence type. We distinguish structural portability of the evidence program from empirical transfer of learned estimators, since the latter may require workload-specific calibration.

---

### Section 9 — System and Mechanism Analysis

#### MA-P1 — Estimator validity
**中文段落任务**：预测 vs observed，calibration curve / rank correlation / error by operator type。

**EN argument skeleton**: We first ask whether the optimizer is making decisions from usable estimates. Calibration and ranking analyses compare predicted and realized evidence yield, requirement coverage, selectivity, failure probability, and cost across operator types.

#### MA-P2 — Logical-to-physical crossover
**中文段落任务**：展示 sparse/dense/hybrid/entity-conditioned/Table lookup 等 physical operator 在不同 query/evidence condition 下的 crossover points。

**EN argument skeleton**: No physical implementation dominates universally. We identify crossover regions in which different retrieval or join strategies become preferable as requirement type, selectivity, dependency depth, and remaining budget change.

#### MA-P3 — Bottleneck transition
**中文段落任务**：把旧稿 valuable failure map 升级进来；区分 acquisition-limited → materialization/packing-limited → integration/generation-limited。

**EN argument skeleton**: Execution traces reveal where additional retrieval ceases to translate into answer gains. We decompose failures into acquisition, verification/materialization, packing, integration, and generation stages and examine how the dominant bottleneck changes as evidence coverage improves.

#### MA-P4 — Runtime trace cases
**中文段落任务**：选成功+失败案例，不只 cherry-pick 成功。逐步展示 requirement status / estimated vs realized stats / replan reason。

**EN argument skeleton**: Figure 5 presents paired successful and failed traces. Each trace shows requirement status, the selected physical operator, predicted and realized statistics, the trigger for any re-optimization, and the final effect on evidence survival and answer correctness.

#### MA-P5 — Scaling and overhead
**中文段落任务**：Fig.8；requirements 数、physical alternatives 数、dependency depth、corpus/source type 增大时 optimizer time/memory/execution overhead。

**EN argument skeleton**: We quantify optimizer overhead as plan complexity increases. The analysis separates compile time, estimator inference, plan enumeration/pruning, re-optimization, and evidence execution so that systems cost is not hidden inside end-to-end latency.

#### MA-P6 — Robustness to estimator error
**中文段落任务**：人工扰动 estimator，画 performance degradation；说明 optimizer 对 calibration error 的敏感性。

**EN argument skeleton**: To determine whether the optimizer is fragile to imperfect learned properties, we perturb estimator outputs and measure plan stability and downstream quality. This analysis identifies which estimates require accurate calibration and which are tolerant to noise.

---

### Section 10 — Discussion

#### DS-P1 — What is genuinely new
**中文段落任务**：重新对照 PlanRAG/DynaKRAG/PyRAG/semantic data systems，谨慎总结 novelty，不夸 first。

**EN argument skeleton**: The central contribution is an evidence-centric execution abstraction, not the isolated use of planning, programs, learned estimates, or adaptive execution. SlotRAG makes evidence requirements and their satisfaction state explicit and uses them as the interface between declarative programs and physical optimization.

#### DS-P2 — When SlotRAG should help
**中文段落任务**：列条件：多依赖、多物理实现、预算受限、runtime statistics 信息量高。简单 single-hop 不一定值得。

**EN argument skeleton**: SlotRAG is most useful when evidence requirements are dependent, multiple physical access paths are available, resources are constrained, and runtime observations are informative. For simple single-hop workloads, optimizer overhead may outweigh the benefit of adaptive planning.

#### DS-P3 — Limitations
**中文段落任务**：真实写 estimator transfer、LLM nondeterminism、source coverage、heterogeneous scope、optimizer search cap 等。

**EN argument skeleton**: The current system remains limited by estimator transfer across domains, nondeterministic neural components, finite physical-operator coverage, and bounded search. These limitations constrain claims of universality and motivate future work on broader source types and more robust property estimation.

#### DS-P4 — Generality beyond QA
**中文段落任务**：只根据 cross-task 证据决定 claim 强度。若只 HoVer/FEVEROUS，写“evidence-intensive tasks”而不是“general-purpose data engine”。

**EN argument skeleton**: The cross-task experiments support generalization to the evaluated evidence-intensive workloads; they do not by themselves establish SlotRAG as a universal semantic data engine. We therefore scope the claim to complex evidence acquisition with explicit dependency and budget constraints.

---

### Section 11 — Conclusion

#### CO-P1 — Problem + solution + evidence
**中文段落任务**：一段完成：重新定义问题 → 三个核心机制 → 三层实验结论。不要重复摘要数字列表。

**EN argument skeleton**: We formulated complex RAG as declarative evidence execution, introduced a typed evidence algebra with requirement-aware physical optimization and runtime re-optimization, and evaluated the resulting system across effectiveness, matched-budget efficiency, and execution mechanisms. The results establish [ONLY VERIFIED CLAIM] while also identifying the conditions under which evidence acquisition is no longer the dominant bottleneck.

#### CO-P2 — Final boundary
**中文段落任务**：最后一句落在系统研究问题，不写 marketing slogan。

**EN argument skeleton**: More broadly, the study suggests that complex retrieval can be treated as an execution problem in which evidence goals remain stable while physical acquisition strategies adapt to observed state and resource constraints.

---

## 17. 正式写作顺序建议（不是论文阅读顺序）

1. 先冻结 Section 3–6 的术语、符号、算法与代码实现映射。
2. 再写 Section 7 Experimental Methodology，把所有公平性规则提前锁死。
3. 全量 sealed results 完成后写 Section 8–9；任何 headline 数字必须可追溯到冻结 artifact。
4. 再写 Section 2 Related Work，确保 novelty wording 与最终实现一致。
5. 最后写 Introduction、Abstract、Conclusion。
6. 最后一次 reviewer-mode 检查：Abstract/Intro 中每个 claim 能否指向 Method definition + Experiment evidence；不能则删弱。
