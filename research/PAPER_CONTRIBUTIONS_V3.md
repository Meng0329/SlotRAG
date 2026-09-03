# PAPER_CONTRIBUTIONS_V3.md — SlotRAG-X: 3 项贡献

> **Date**: 2026-09-03
> **Status**: FINAL（H-STRUCT-3 完成后定稿）
> **约束**: chain-rule importance **不是贡献**（H-STRUCT-2 falsified, ΔEM +0.0086, p=0.743）；去掉所有 "first adaptive / budget-aware / query-planner / structure-aware RAG" 声称。

---

## C1 — Declarative Evidence Planning via Typed Slot Plans

> SlotRAG 将复杂问题**声明性地编译为 typed slot plan**——每个 slot 指定一个谓词（查询意图）、约束条件、绑定变量，通过 join 边连接形成**结构证据图**。该计划在执行前即暴露了完整的证据依赖关系（哪些 slot 需要前置绑定，哪些 slot 可并行物化），为后续的预算感知物理分配提供了结构信息。

**关键特性**：
- Slot 计划是**声明式逻辑 plan**（LLM 编译，确定性语法校验），非逐步执行的启发式轨迹
- 结构证据图的 `structural_hops` = 最长 join/operator 路径，直接可计算（LLM-free，planner 内确定性度量）
- 计划的可执行性（`executable`）与物理可完成性（`Σ allocation ≤ B`）在编译阶段即可离线判定（§12 混淆矩阵：precision 1.0，recall 0.53）

**与现有工作的边界**：
- 不是 query planner（PlanRAG）：PlanRAG 的 planning 是检索策略选择；SlotRAG 的 plan 是**证据物化逻辑**——decision point 不同
- 不是路由分类器（Adaptive-RAG）：我们不分类 query 复杂度，而是直接**从计划结构**派生执行策略
- 不是知识图谱拓扑（GraphRAG）：结构证据图的 topology 是**计划的 join 结构**，不是知识库的实体关系

---

## C2 — Structural Budget-Feasibility Diagnosis

> 静态预算分配策略（每个 slot 预分配固定份额）在结构化深度计划上**结构性不可完成**（executable 但 sum-of-allocations > B）。该 diagnosis 通过离线 feasibility 分析**精确识别**哪类计划会 BE（precision 1.0），为 gate 的触发条件提供了机制性解释，而非黑箱 learned routing。

**核心证据**：
- 350 个冻结 plan 中，76 个 Feasible（Σ≤8）且**零 BE**（TN），146 个 Infeasible（Σ>8）且**全部 BE**（TP），FP=0（§12）
- H-STRUCT-1 confirmatory validation：static 41.7% BE 全部集中于 depth≥2 计划（n=350 matched-budget 8-call 体制）
- Chain importance 能绕过此 BE（chain importances={sid:2*(idx+1)-1} 把高依赖 slot 分配更多份额），但 flat（全 1.0）更简单且**同样有效**（H-STRUCT-2 CASE B）

**论文叙事**：
> The failure of static allocation is structural: it is precisely predictable from the plan's topology at compile time, before any LLM or retrieval call is made. This diagnosis motivates a gate that operates on the plan's structure, not on the query's surface features.

---

## C3 — Structure-Gated Budget-Feasible Physical Planning（Policy A′）

> 最终系统在结构证据图的 `structural_hops >= 2` 时应用 budget-aware flat 物理分配器，否则回退到静态分配。该 gate **从计划结构派生**（LLM-free、确定性、无需 learned classifier），将 flat 优化器的收益**限制在能受益的深度计划**上，同时**保护浅层计划**免受 flat 在其上的质量伤害。

**核心证据**（H-STRUCT-3）：
- **Gate 必要性（CASE G1）**：浅层（hops<2）flat vs static ΔEM = −0.0210, CI [−0.0273, −0.0146], p<0.001；always-flat 在 93.6% 的计划上造成净质量伤害（以 2wiki 为主导）
- **A′ 优于 always-flat**：ΔEM +0.0197, CI [+0.0138, +0.0256], p<0.001；ΔF1 +0.0073; Δretrieval −0.0144（A′ 更少检索且质量更好）
- **A′ 保留 flat 的 BE 消除**：confirmatory matched-budget BE 146/350 → 0；人口级 −22.48 BE per 1000 natural questions（相对 100% 削减）
- **人口级 A′ 效应**：ATE_population = 0.05390 × +0.0771 = +0.004158 EM/题，CI [+0.002464, +0.005852]（不含 0，显著；效应小，诚实定位为"深度计划的预算内自适应降级"而非全局增益）

**方法名**：**Structure-Gated Budget-Feasible Physical Planning**

**与现有工作的边界**：
- 不是自适应路由（Adaptive-RAG）：我们不在 query 或 pipeline 级别路由；gate 作用于**已编译计划**的结构
- 不是资源路由（RAG-on-a-Diet）：RAG-on-a-Diet 做 per-hop 连续资源分配；我们做 per-plan 离散 gate
- 不是 cost-aware 检索策略选择（PlanRAG）：我们不选择检索策略；我们选择**物理分配策略**（在检索/物化之后的执行器层面）

---

## 不是贡献

### Chain-rule importance（falsified hypothesis）

依赖敏感 chain importance（importance={sid:2*(idx+1)-1}）是 H-STRUCT-1 的初始策略，但它**不构成独立的准确率贡献**：

> 「The chain-specific importance law did not yield a detectable accuracy gain over a uniform budget-aware optimizer (paired ΔEM = +0.0086, 95% CI [−0.026, +0.043], exact McNemar p = 0.743). This falsification motivated the simpler uniform flat physical policy used in our final system.」

论文中 chain importance 仅出现在 ablation 中（"Exploratory Efficiency Audit" §11：chain 比 flat 省 LLM 0.986 次/retrieval 0.759 次，perm-p<0.001，但这是效率不是准确率，不可称为"confirmed"）。最终系统用 flat，不用 chain。

### Structure-aware RAG 声称

- ❌ 不使用 "first adaptive RAG"（Adaptive-RAG 2024 预存）
- ❌ 不使用 "first budget-aware RAG"（RAG-on-a-Diet 2024 预存）
- ❌ 不使用 "first query planner for RAG"（PlanRAG 2023 预存）
- ❌ 不使用 "first structure-aware RAG"（GraphRAG / TopoRAG 运行于知识图谱拓扑，与计划拓扑不同）
- ❌ 不使用 "first physical optimizer for RAG"（该声称缺乏领域内可比基线）

**Approved positioning**：
- 「SlotRAG operates on the compiled evidence plan, not on raw queries or knowledge graphs — a fundamentally different decision point.」
- 「The gate is deterministic and plan-structural, not a learned classifier or continuous resource router.」
- 「The budget-feasibility diagnosis is computed at compile time, enabling efficient offline analysis of plan executability.」
