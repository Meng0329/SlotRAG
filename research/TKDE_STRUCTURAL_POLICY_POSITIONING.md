# TKDE_STRUCTURAL_POLICY_POSITIONING.md — Differentiation Statement

> **Date:** 2026-09-03 (H-STRUCT-3 后更新)
> **Purpose:** Position the structure-gated physical planning contribution against related adaptive/topology-aware RAG work
> **Rules (§14):** 不使用 "first adaptive RAG" / "first budget-aware RAG" / "first query planner for RAG" / "first structure-aware RAG"。gate 主题词 = budget-aware **flat** 物理优化器（非 chain），chain 已降级 ablation。

---

## 1. Core Thesis

> "Universal budget-aware allocation is not uniformly beneficial. Its treatment effect is conditioned by the structural depth of the compiled evidence plan. A deterministic structural-depth gate (structural_hops ≥ 2) confines the budget-aware flat optimizer to the regime where its physical assumptions are useful, protecting shallow plans from quality harm while eliminating budget_exceeded on deep plans — without learned routing."

**实证摘要 (H-STRUCT-3, n=8,632 offline replay + n=350 confirmatory):**
- 浅层 flat 显著伤害质量：ΔEM −0.0210, CI[−0.0273,−0.0146], p<0.001（2wiki hops0 主导）
- A′ vs always-flat：ΔEM +0.0197, CI[+0.0138,+0.0256], p<0.001；Δretrieval −0.0144 显著；ΔLLM +0.86 n.s.
- Confirmatory matched-budget：BE 146/350→0（人口级 −22.48 BE/1000 自然题，相对 100%）
- Population-level A′ effect：+0.004158 EM/题, CI[+0.002464,+0.005852]

---

## 2. Differentiation from Related Work

### 2.1 Adaptive-RAG (Ma et al., 2024)

**他们做:** 用 LLM classifier 把 query 路由到不同 RAG pipeline（retrieve-only / retrieve-then-read / no-retrieval）。

**我们做:** 对**已编译证据计划**选物理分配策略（budget-aware flat vs static），基于该计划的**结构深度**。

**关键差异:**
- Adaptive-RAG 作用于 **raw query → pipeline 选择**
- SlotRAG 作用于 **compiled plan → 分配策略（同一 pipeline 内）**
- 我们的 gate 是**确定性**的（structural_hops ≥ 2），不是 learned classifier
- **我们不声称 "first adaptive RAG"** — Adaptive-RAG predates us 且 decision point 不同

### 2.2 RAG-on-a-Diet (Chen et al., 2024)

**他们做:** RL 驱动 per-hop 资源路由（per-hop 决定检索多少、用小模型、跳过检索），优化 cost-quality tradeoff。

**我们做:** 一个**per-plan 二值 gate**，在编译后一次性决定整个计划的分配策略。

**关键差异:**
- RAG-on-a-Diet: learned, per-hop, continuous resource allocation
- SlotRAG: deterministic, per-plan, binary allocation gate
- **我们不声称 "first cost-aware RAG"** — RAG-on-a-Diet 做连续资源优化；我们做结构资格判据

### 2.3 PlanRAG (Baek et al., 2023)

**他们做:** 构造逻辑 query tree，用 cost-based planning 选每节点的检索策略。

**我们做:** slot compiler 已产生逻辑 plan；我们的贡献是**编译后 gate**，决定 budget-aware 分配在该 plan 结构下是否适用。

**关键差异:**
- PlanRAG: planning 阶段（树构造 + 检索策略选择）
- SlotRAG: 执行阶段（对已编译 plan 的物理分配 gate）
- **我们不声称 "first query planning"** — PlanRAG 的 planning 更复杂且 decision point 不同

### 2.4 GraphRAG / TopoRAG (various)

**他们做:** 利用知识图谱的实体/文档级拓扑做检索（遍历实体链接、community detection）。

**我们做:** 分析**编译证据计划**的拓扑（join 结构 + operator 连通性），不是知识图谱拓扑。

**关键差异:**
- GraphRAG: knowledge substrate 的拓扑（documents/entities/relations）
- SlotRAG: compiled evidence plan 的拓扑（slots/joins/operators）
- 正交：graph-RAG retrieval 可与 structure-gated allocation 组合
- **我们不声称 "first structure-aware RAG"** — graph-RAG 作用于完全不同的图

### 2.5 PAGE-RAG (2024/2025, 页面级 RAG)

**他们做:** 以 PDF 页面为检索单元做页面级 retrieval（page relevance routing + hierarchical page content extraction），优化文档问答中的检索粒度。

**我们做:** 以**计划结构**而非页面为单元；检索粒度决策由 slot plan 决定，不是页面边界。

**关键差异:**
- PAGE-RAG: page-level retrieval granularity（面向长文档）
- SlotRAG: slot-level evidence materialization（面向多跳问答计划）
- PAGE-RAG 的 "routing" 是页面筛选；我们的 gate 是物理分配策略筛选
- **我们不声称 "first page-aware / granularity-aware RAG"**

---

## 3. What SlotRAG Actually Contributes

1. **C1 — Declarative Evidence Planning**: 编译式 typed slot plan + 结构证据图（structural_hops 确定性可算）
2. **C2 — Structural Budget-Feasibility Diagnosis**: 编译期离线判定计划的可完成性（Σ allocation ≤ B）；混淆矩阵 precision 1.0
3. **C3 — Structure-Gated Budget-Feasible Physical Planning**: 确定性结构深度 gate 把 budget-aware flat 限制在 ≥2-hop 计划，同时保护浅层质量并消除 matched-budget BE

（详见 `PAPER_CONTRIBUTIONS_V3.md`；chain-rule importance = ablation/falsified，非贡献。）

---

## 4. Prohibited Claims

- ❌ "First adaptive RAG system"
- ❌ "First topology-aware / structure-aware RAG"
- ❌ "First query-planning RAG"
- ❌ "First cost-aware / budget-aware RAG"
- ❌ "Policy A eliminates star-plan harm"（A′ 的 gate 是 structural_hops≥2，不读 topology_full 字符串）
- ❌ "Chain allocation is universally beneficial"（H-STRUCT-2 CASE B：flat→chain ΔEM +0.0086, p=0.743）
- ❌ "Chain importance improves accuracy"（仅 exploratory 效率优势，非准确率）
- ❌ "The gate eliminates all budget_exceeded"（confirmatory 350 内 146→0；population 仅 eligible 域，非全体）

## 5. Approved Claims

- ✅ "Structural depth of the compiled evidence plan moderates the effect of uniform budget-aware allocation"（H-STRUCT-3: 浅层 flat ΔEM −0.0210 显著；深层 hotpotqa +0.1654）
- ✅ "A deterministic depth gate confines budget-aware allocation to the regime where it pays"（A′ ΔEM +0.0197 vs always-flat, p<0.001）
- ✅ "The gate operates on plan structure, not query complexity or knowledge topology"
- ✅ "The gate is deterministic and requires no learned classifier or resource router"
- ✅ "The budget-feasibility diagnosis is computable at compile time (precision 1.0)"
- ✅ "Improving the quality-cost frontier in the eligible stratum; eliminating matched-budget budget_exceeded on deep plans"
- ✅ "Population-level effect is small and honestly bounded (+0.004 EM/题, CI 不含 0)"