# SlotRAG-TKDE — Paragraph Plan (中英对照)

> 用途: 正式写作段落级施工图。每段只承担一个论证功能; 真实数值/显著性/成本结果只能在冻结实验后填入。
> 规则 (LOOP_PROMPT): 先写 section/paragraph id + 中文论证目的 + English claim + supporting citations, 再草拟正文。
> 代码对齐锚点: `src/slotrag/models.py`, `evidence_algebra.py`, `optimizer.py`, `qo.py`, `planner.py`, `benchmarking/statistics.py`。
> 诚实性裁定 (裁决12s/12t/12y/12z): **runtime re-optimization (G4) FALSIFIED — 降级为 future work, 不在正文当主贡献**; estimator = 确定性链律 τ=2·depth−1 (G5 SUPPORTED); 主贡献 = requirement-aware budgeted physical-plan search (G7 SUPPORTED, matched budget)。

---

## Section 4 — Declarative Evidence Algebra (Evidence Algebra)

### EA-P1 — Design goals
- **section/para id**: S4-P1
- **中文论证目的**: 列 3 原则: 声明式 (程序表达"要满足什么证据目标"而非"执行什么检索过程")、有类型且可组合、优化器可见 (供物理优化用的算子属性显式暴露而非藏在 prompt)。不先堆 operator 表。
- **English claim sentence**: The algebra is designed around three requirements: programs specify evidence goals rather than retrieval procedures; operator inputs and outputs are typed and composable; and operator properties relevant to physical optimization remain explicit rather than hidden inside prompts.
- **supporting citations**: (blueprint EA-P1) + code: `models.py` EvidenceRequirement/EvidenceType/RequirementStatus; `evidence_algebra.py`.
- **证据锚点 (code)**: `EvidenceRequirement` (models.py:555) — first-class typed evidence need (status/evidence_type/importance/variables/depends_on); `EvidenceType` (models.py:535); `RequirementStatus` (models.py:541).
- **禁止**: 不写 "existing methods cannot plan"; 不把 EvidenceState 说成 reopt 触发器的唯一来源 (G4 falsified).

### EA-P2 — Requirement and acquisition operators
- **section/para id**: S4-P2
- **中文论证目的**: 介绍 REQUIRE、SEARCH、EXPAND, 用同一 multi-hop 例贯穿。REQUIRE 引入一个未满足的证据条件; SEARCH/EXPAND 从 source 或既有 binding 获取候选证据。区分声明式条件与一种可能的获取机制。
- **English claim sentence**: REQUIRE introduces an unresolved evidence condition, while SEARCH and EXPAND acquire candidate evidence from a source or from an existing binding. These operators distinguish the declarative condition to be met from one possible acquisition mechanism.
- **supporting citations**: (blueprint EA-P2) + code: `evidence_algebra.py apply_observation` (transition unresolved→partial→satisfied); `planner.py SlotMaterializer` (per-slot retrieval); `qo.py`.
- **证据锚点 (code)**: `apply_observation` (evidence_algebra.py:87) — 状态转换算子, 单调格 `_RANK` (unresolved<partial<satisfied).

### EA-P3 — Binding and composition operators
- **section/para id**: S4-P3
- **中文论证目的**: BIND 把证据转为可复用变量; JOIN 通过共享 binding/语义约束组合证据; FILTER 按 typed predicate 减少候选。显式 binding 使下游获取"条件于已观测值"而非"生成子问题"。
- **English claim sentence**: BIND converts evidence into reusable variables; JOIN composes evidence through shared bindings or semantic constraints; FILTER reduces candidates according to typed predicates. Explicit bindings make downstream acquisition conditional on observed values rather than merely on generated subquestions.
- **supporting citations**: (blueprint EA-P3) + code: `models.py BindingRow`; `binding.py AdaptiveBindingBeam`; `planner.py join` (shared-variable joins); `RelationalOperator` (models.py).
- **证据锚点 (code)**: `SlotPlan.joins` + `JoinSpec` — shared-variable join edges; `BindingRow` bindings dict.

### EA-P4 — Verification/materialization/packing operators
- **section/para id**: S4-P4
- **中文论证目的**: VERIFY 检查候选是否支持 requirement; MATERIALIZE 提交选中证据到持久 evidence state; PACK 构建给 answer model 的有界上下文。强调 retrieved ≠ materialized ≠ packed。
- **English claim sentence**: VERIFY checks whether candidate evidence supports a requirement, MATERIALIZE commits selected evidence to the persistent evidence state, and PACK constructs the bounded context delivered to the answer model. The separation is intentional: evidence can be retrieved yet rejected before materialization, or materialized yet omitted from the final context under a tighter reader budget.
- **supporting citations**: (blueprint EA-P4) + code: `planner.py materialize`; `evidence_bundle.py EvidenceBundle`; `sufficiency.py` (verdict); `generation.py`.
- **证据锚点 (code)**: `EvidenceRecord` (models.py) — provenance-clean materialized evidence; `MaterializationTrace`; `SlotExecutionTrace.sufficiency_status` (SUFFICIENT/PARTIAL/INSUFFICIENT → satisfied/partial/unresolved via `_status_from_sufficiency`).

### EA-P5 — Type semantics
- **section/para id**: S4-P5
- **中文论证目的**: operator signatures 显式 evidence-type compatibility; 覆盖 Passage/Entity/Relation/TableRow/StructuredRecord; 良定义程序的 type-preservation。
- **English claim sentence**: Operator signatures make evidence-type compatibility explicit. We define admissible transformations across passage, entity, relation, table-row, and structured-record types and establish type-preservation conditions for well-formed programs.
- **supporting citations**: (blueprint EA-P5) + code: `EvidenceType` (models.py:535) 五类; `derive_evidence_state` 当前固定 passage (G9 异构待扩展 — 诚实边界)。
- **证据锚点 (code)**: `EvidenceType = Literal["passage","entity","relation","table_row","structured_record"]`. **诚实边界**: 当前后端只实现 passage (derive_evidence_state 注释 "text-only backend today; extended by G9 heterogeneous").

### EA-P6 — Rewrite rules
- **section/para id**: S4-P6
- **中文论证目的**: 三类 rewrite: exact / evidence-preserving / approximate; approximate 必须把风险暴露给 optimizer。
- **English claim sentence**: Rewrites fall into three classes. Exact rewrites preserve operator semantics; evidence-preserving rewrites may alter intermediate candidates while preserving the evidence requirement under stated conditions; approximate rewrites trade recall or verification risk for cost and therefore expose an estimated loss term to the optimizer.
- **supporting citations**: (blueprint EA-P6) + code: `qo.py compile_physical_plan` (logical→physical); `optimizer.py` (strategy variants hybrid/bm25 cost prior 0.5×).
- **证据锚点 (code)**: `PhysicalPlan.retrieval_strategy` (G2 后活字段); bm25 0.5× cost prior (optimizer.py, "declared cost prior, G5 to calibrate" → 现为确定性链律)。

### EA-P7 — End-to-end walkthrough
- **section/para id**: S4-P7
- **中文论证目的**: 配 Fig.3, 从一个问题编译成 requirements, 经 rewrite, 强调同一 logical program 可有多个 physical executions。
- **English claim sentence**: Figure 3 traces a single query from natural-language input to a typed evidence program. The example illustrates that the logical program fixes what evidence dependencies must be satisfied, while leaving open whether they are realized by sparse, dense, hybrid, conditioned, or structured access paths.
- **supporting citations**: (blueprint EA-P7) + code: `planner.py SlotCompiler` (LLM compile → SlotPlan); `qo.py` (LogicalPlan→PhysicalPlan); `tools/run_g3_optimizer_smoke.py`.
- **证据锚点 (code)**: `SlotCompiler` — LLM 编译 question → SlotPlan (logical); `compile_physical_plan` — 确定性初始物理计划; `search_physical_plans` — 枚举混合物理实现。

---

## Section 5 — Requirement-Aware Evidence Optimizer

### OP-P1 — Logical/physical separation
- **section/para id**: S5-P1
- **中文论证目的**: 正式定义 logical operator ↔ physical implementation 映射; SEARCH/JOIN 各给多实现。
- **English claim sentence**: SlotRAG separates a logical evidence operator from its physical implementations. For example, SEARCH may be instantiated by sparse, dense, hybrid, entity-conditioned, or iterative retrieval; JOIN may be instantiated by binding-driven retrieval or by materialize-then-join execution.
- **supporting citations**: (blueprint OP-P1) + code: `qo.py` LogicalPlan/PhysicalPlan; G2 (`retrieval_strategy` hybrid vs bm25 活字段); `search_physical_plans` (optimizer.py).
- **证据锚点 (code)**: `PhysicalPlan.retrieval_strategy` 每 slot `hybrid`(dense+sparse RRF) vs `bm25`(sparse-only batch); G2 `allow_retrieval_strategy_variants`.

### OP-P2 — Estimator architecture
- **section/para id**: S5-P2
- **中文论证目的**: 定义 estimator 预测 optimizer-visible 属性而非动作; G5 锚定为确定性链律。
- **English claim sentence**: The optimizer relies on estimators that predict optimizer-visible properties rather than actions. Given an operator, implementation, and current evidence state, an estimator predicts evidence yield, marginal requirement coverage, selectivity, failure probability, and resource cost.
- **supporting citations**: (blueprint OP-P2, 但**核心改写**: G5 = 确定性链律 τ=2·depth−1 按构造恒等, 非 learned) + code: G5 main `09e1515`; `optimizer.py _estimate_plan_utility`; §27.
- **证据锚点 (code)**: `_estimate_plan_utility` — 显式 objective utility = Σ imp·saturating_marginal(calls) − cost; 确定性链律 importance ≡ τ=2·depth−1 (Spearman ≡ 1, 反事实扫描发现的确定性规律, 非 learned estimator).

### OP-P3 — Calibration/training data
- **section/para id**: S5-P3
- **中文论证目的**: 训练只用 development registry; sealed test 禁止参与; 无训练则明确 fallback 是 deterministic estimator。
- **English claim sentence**: Property estimators are fitted and calibrated exclusively on development executions. Sealed evaluation instances are never used for model selection, threshold tuning, or property calibration.
- **supporting citations**: (blueprint OP-P3, 改写为确定性 estimator) + code: `benchmark/` DEVEL/VALIDATION/TEST split; seed 2027 registry.
- **证据锚点 (code)**: 确定性链律 importance = τ=2·depth−1 不依赖训练 (按构造); 预注册 + frozen plan replay (frozen_plan_source=static) 保证无泄漏。

### OP-P4 — Plan enumeration
- **section/para id**: S5-P4
- **中文论证目的**: 候选物理计划构造: 依赖序 × operator 实现 × budget allocation; 枚举有界。
- **English claim sentence**: The optimizer enumerates candidate physical plans by combining legal operator orderings, compatible implementations, and budget allocations subject to the requirement dependency graph. Enumeration is bounded to prevent exponential blow-up.
- **supporting citations**: (blueprint OP-P4) + code: `optimizer.py _dependency_respecting_orders` (Kahn + backtrack, cap 256); `_allocate_budget_between`.
- **证据锚点 (code)**: `_dependency_respecting_orders` — 严格链只有 1 合法序 (G4 结构性无收益根因); 分支 DAG >1 序 cardinality 才移动 allocation。

### OP-P5 — Dominance/Pareto pruning
- **section/para id**: S5-P5
- **中文论证目的**: 定义 plan A 支配 B; 不能只按 estimated cost 排序。
- **English claim sentence**: Candidate plans are pruned by dominance over expected requirement utility and constrained resource dimensions. A cheaper plan does not dominate a more expensive plan if the latter is expected to satisfy materially different or higher-weight requirements.
- **supporting citations**: (blueprint OP-P5) + code: `optimizer.py` dominance pruning (utility ≥ and cost ≤).
- **证据锚点 (code)**: `PlanSearchTelemetry.candidates_pruned` — Pareto 剪枝计数诚实记录。

### OP-P6 — Utility-aware selection
- **section/para id**: S5-P6
- **中文论证目的**: 边际 utility 只对 unresolved requirements 计; 已满足证据重复检索降值。
- **English claim sentence**: Plan selection is requirement-aware: utility is credited only for expected progress on currently unresolved requirements, with diminishing value for redundant evidence. This discourages repeated retrieval of already-satisfied facts even when such retrieval has high relevance scores.
- **supporting citations**: (blueprint OP-P6) + code: `optimizer.py _estimate_plan_utility` saturating marginal; §29 G7 frontier.
- **证据锚点 (code)**: utility = Σ imp·(1 − exp(−calls/base)); base ∝ estimated_cardinality (rarer evidence needs more calls); **主 claim C5 (G0 SUPPORTED)** — utility 只对 unresolved-requirement 边际计, 非通用 cost optimizer (对 Abacus/Sema/PlanRAG 无硬伤)。

### OP-P7 — Complexity and algorithm
- **section/para id**: S5-P7
- **中文论证目的**: Algorithm 1 (bounded physical-plan search); 只对真实实现给复杂度; search cap/beam/DP/Pareto pruning 边界。
- **English claim sentence**: Algorithm 1 presents bounded physical-plan search. We characterize the combinatorial factors introduced by implementation choice, partial ordering, and budget allocation, and then state the complexity of the actual bounded search procedure used in experiments.
- **supporting citations**: (blueprint OP-P7) + code: `search_physical_plans` (optimizer.py) 真实实现; `_dependency_respecting_orders` cap 256 + backstop 2M.
- **证据锚点 (code)**: 复杂度来自真实实现: order enumeration 最坏阶乘被 256 确定性子集截断; allocation 贪心确定性 (round-half-even by slot id)。

---

## Section 6 — Adaptive Evidence Execution (诚实改写)

> **核心裁定 (裁决12s)**: G4 (runtime re-optimization) FALSIFIED — 严格链 (executor 唯一可消费拓扑) allocation 是 importance+budget 纯函数, cardinality 注入不移动预算; 机制仅在 ≥2 序拓扑 (分支/星型) 存活但 executor 不消费。**本节的 re-optimization 内容全部改写为 future work**, 不当作主贡献。主执行贡献 = 确定性自适应执行 + 预算执行 + provenance 诊断。

### AE-P1 — Deterministic adaptive execution (取代 "why static plans fail/reopt")
- **section/para id**: S6-P1
- **中文论证目的**: 诚实重写 — 执行是确定性的: 同一 frozen logical plan + adaptive 策略下, 物理计划选择是 importance+budget 的确定性函数; runtime 观测 (binding/selectivity) 在**当前 chain-only executor** 上不改变分配。明确这是未来分支执行模型的工作。
- **English claim sentence**: Execution is deterministic under a frozen logical plan: physical-plan selection is a pure function of requirement importance and remaining budget. Runtime observations change bindings but, under the current chain-only execution topology, do not re-allocate the physical plan; re-optimization over branching topologies is future work.
- **supporting citations**: 裁决12s (G4 falsified), §28; code: `search_physical_plans` + `_dependency_respecting_orders` (严格链 1 合法序).
- **证据锚点 (code)**: G4 falsification probe — 严格链 cardinality {100,100,100}/{2,5,8}/{1,100,1} → alloc 恒 {S1:1,S2:3,S3:4}。

### AE-P2 — Executor state transition (不变)
- **section/para id**: S6-P2
- **中文论证目的**: operator execution 如何更新 S_t; 记录 telemetry/provenance。
- **English claim sentence**: Each physical operator transforms S_t into S_{t+1} while recording realized cost, candidate yield, verification outcome, bindings, and provenance.
- **supporting citations**: (blueprint AE-P2) + code: `planner.py AdaptiveExecutor.execute`; `derive_evidence_state`; `apply_observation`.
- **证据锚点 (code)**: `derive_evidence_state` — 快照 (Snapshot); `apply_observation` — 状态转换 (G1, 主贡献之一)。

### AE-P3 — Re-optimization triggers → future work
- **section/para id**: S6-P3
- **中文论证目的**: 诚实改写 — 明确 re-optimization 触发机制是**设计未实现的未来工作**, 不做成 claimed contribution。
- **English claim sentence**: Event-driven re-optimization over alternative physical plans is not part of the current system; the chain-only executor admits a single legal order, so re-optimization would be dead code. We identify trigger design as future work under a branching execution model.
- **supporting citations**: 裁决12s; §28.
- **证据锚点 (code)**: G4 falsification — "Executor-embedded reopt would be dead code — NOT to be implemented."

### AE-P4 — Partial-plan preservation → future work
- **section/para id**: S6-P4
- **中文论证目的**: 改写为 future work 描述 (保留已执行结果的可复用性, 若未来支持分支)。
- **English claim sentence**: In a branching execution model, re-optimization would preserve valid materialized evidence and completed bindings, reconsidering only the unexecuted suffix. We leave this to future work because the current executor's single-order topology makes the suffix trivial.
- **supporting citations**: 裁决12s.

### AE-P5 — Provenance and diagnostics (主贡献, 保留)
- **section/para id**: S6-P5
- **中文论证目的**: provenance 作为系统属性, claim → evidence → materialization → physical action → source 反向追踪; operator-level failure attribution。
- **English claim sentence**: SlotRAG maintains provenance across compilation, acquisition, verification, materialization, and packing, enabling answer-level traceability and operator-level failure attribution.
- **supporting citations**: (blueprint AE-P5) + code: `models.py` (EvidenceRecord.source_id, RetrievalSearchTrace, SlotExecutionTrace, MaterializationTrace); `derive_evidence_state` (unsatisfied_reason).
- **证据锚点 (code)**: `EvidenceRecord` provenance-clean; `derive_evidence_state` unsatisfied_reason (slot never materialized / no binding context / insufficient evidence / partial coverage)。

### AE-P6 — Budget enforcement and stopping (主贡献, 保留)
- **section/para id**: S6-P6
- **中文论证目的**: 硬预算、reservation、stop condition; 确定性, 非 learned stopping controller。
- **English claim sentence**: Budget enforcement is deterministic. The executor reserves resources for unresolved high-priority requirements, rejects plans that would violate hard constraints, and terminates when requirements are sufficiently satisfied or no admissible plan can improve utility within the remaining budget.
- **supporting citations**: (blueprint AE-P6) + code: `action_policy.py PhysicalActionPolicy`; `benchmarking/runner.py` matched budget (max_retrieval_calls → retrieval_budget); G6/G7 实证。
- **证据锚点 (code)**: `RunMetrics.retrieval_calls`; matched-budget 线程化 (optimizer `retrieval_budget`); G6 retrieval_calls 显著降。

---

## Section 3 — Problem Formulation (骨架; 冻结数字后填)

### PF-P1..PF-P6 (来自 blueprint, 代码锚定)
- S3-P1 Workload: `EvidenceRequirement` 独立 evidence 需求; `SlotPlan`。
- S3-P2 Evidence item: `EvidenceRecord` (id/type/value/source/provenance/bindings/cost/quality)。
- S3-P3 Evidence requirement: `EvidenceRequirement` (variables/depends_on/evidence_type/importance)。
- S3-P4 Evidence state: `EvidenceState` (requirements/bound_evidence/bindings/budget)。
- S3-P5 Objective: constrained utility (PF-P5) = Σ imp·saturating_marginal − cost (matched budget)。
- S3-P6 Why non-trivial: implementation choice × partial ordering × budget allocation × uncertain yields (combining); 复杂度入口 = §5 Algorithm 1。

---

## Section 2 — Related Work (写作顺序靠后, 骨架暂列)

### RW-P1..RW-P5 (来自 blueprint §16)
- 约束: 必须承认 PlanRAG/PyRAG/LOTUS/Abacus/Sema 已有规划/语义算子/成本优化; novelty = 组合后的 evidence-centric execution model。
- C5 差异化锚定 (裁决12z): utility 只对 unresolved-requirement 边际计 → 非通用 cost optimizer。

---

## Section 7 — Experimental Methodology (骨架)

### EX-P1..EX-P8 (来自 blueprint §16)
- RQ1-RQ9 逻辑链; datasets/tasks (MHQA/HoVer/FEVEROUS); controlled substrate; baselines family; 3-layer metrics; matched-budget protocol; statistics (paired bootstrap/Cohen's d/McNemar/cluster bootstrap — G10 工具); reproducibility (registries/manifest/nondeterminism — G11)。

---

## Section 8 — Main Results (冻结后填)

### MR-P1..MR-P5 (来自 blueprint §16)
- MR-P1 总表 (Table 4); MR-P2 matched-budget frontier (Fig 6); MR-P3 optimizer ablation (static/cost-only/chain — G6/G7 实跑); MR-P4 runtime re-optimization **改写为 "runtime observations and determinism" 或省略** (G4 falsified); MR-P5 cross-task (HoVer/FEVEROUS — G8/G9 数据可达待方法)。

---

## Section 9 — Mechanism Analysis (骨架)

### MA-P1..MA-P6
- MA-P1 estimator validity: 确定性链律 (G5, Spearman ≡ 1)。
- MA-P2 logical-to-physical crossover: 链律收益域 = ≥3-slot 良定义链 (G7 2/6)。
- MA-P3 bottleneck: 旧稿 failure map 升级 (selection ceiling 泛化至 musique — Phase5 记忆)。
- MA-P4 runtime trace: 成功+失败 paired (G6 5add695a)。
- MA-P5 scaling/overhead: optimizer 枚举/剪枝 (telemetry 已记录)。
- MA-P6 robustness: 确定性 → estimator error 无 (结构性不敏感)。

---

## Section 10 — Discussion / Section 11 — Conclusion (骨架)

- DS-P1..DS-P4, CO-P1..CO-P2 (blueprint §16): evidence-centric execution abstraction; benefit conditions (dependent requirements + multiple impls + constrained budget + informative runtime observations); honest limitations; generality scoped to evidence-intensive workloads.
