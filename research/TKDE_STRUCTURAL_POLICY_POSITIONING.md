# TKDE_STRUCTURAL_POLICY_POSITIONING.md — Differentiation Statement

> **Date:** 2026-08-31
> **Purpose:** Position the structural-depth-gate contribution against related adaptive/topology-aware RAG work

---

## 1. Core Thesis (Provisional)

> "Universal dependency-aware allocation is not uniformly beneficial. Its treatment effect is conditioned by the structural depth of the compiled evidence plan. A simple structural-depth gate restricts chain allocation to the regime in which its physical assumptions are useful, improving the quality-cost frontier without learned routing."

---

## 2. Differentiation from Related Work

### 2.1 Adaptive-RAG (Ma et al., 2024)

**What they do:** Route queries to different RAG pipelines (retrieve-only, retrieve-then-read, no-retrieval) based on query complexity estimated by an LLM classifier.

**What we do:** Select a physical allocation policy (static vs chain) for a **compiled evidence plan**, based on the structural depth of that plan.

**Key difference:**
- Adaptive-RAG operates on the **raw query** → pipeline selection
- SlotRAG operates on the **compiled plan** → allocation policy within a fixed pipeline
- Our gate is **deterministic** (structural_hops ≥ 2), not a learned classifier
- We do NOT claim "first adaptive RAG" — Adaptive-RAG predates us and addresses a different decision point

### 2.2 RAG-on-a-Diet (Chen et al., 2024)

**What they do:** RL-based hop-level resource routing — decide per-hop whether to retrieve more, use a smaller model, or skip retrieval, optimizing a cost-quality tradeoff.

**What we do:** A binary gate on the **entire plan's** structural depth, applied once before execution.

**Key difference:**
- RAG-on-a-Diet: learned, per-hop, continuous resource allocation
- SlotRAG: deterministic, per-plan, binary allocation gate
- We do NOT claim "first cost-aware RAG" — RAG-on-a-Diet addresses continuous resource optimization; we address a structural eligibility criterion

### 2.3 PlanRAG (Baek et al., 2023)

**What they do:** Construct a logical query tree, then use cost-based planning to select among retrieval strategies for each node.

**What we do:** The slot compiler already produces a logical plan. Our contribution is the **post-compilation gate** that decides whether chain allocation's physical assumptions hold for this plan structure.

**Key difference:**
- PlanRAG: planning phase (tree construction + strategy selection)
- SlotRAG: execution phase (allocation gate on already-compiled plan)
- PlanRAG's cost model is about retrieval strategy; ours is about physical allocation of evidence materialization
- We do NOT claim "first query planning" — PlanRAG's planning is more sophisticated

### 2.4 TopoRAG / Graph-RAG (various)

**What they do:** Exploit document-level or entity-level graph topology for retrieval — traverse knowledge graphs, follow entity links, use community detection.

**What we do:** Analyze the **compiled plan's** topology (join structure + operator connectivity), not the knowledge graph's topology.

**Key difference:**
- Graph-RAG: topology of the knowledge substrate (documents, entities, relations)
- SlotRAG: topology of the compiled evidence plan (slots, joins, operators)
- These are orthogonal: you could combine graph-RAG retrieval with structural-depth-gated allocation
- We do NOT claim "first topology-aware RAG" — graph-RAG operates on a fundamentally different graph

---

## 3. What SlotRAG Actually Contributes

1. **Compiled evidence-plan structure** as the input to an adaptive decision (not raw queries, not knowledge graphs)
2. **Physical allocation treatment** (static vs chain) as the decision variable (not pipeline selection, not resource routing, not retrieval strategy)
3. **Structural-depth gate** as the mechanism (deterministic, not learned; single gate, not per-hop; eligibility criterion, not continuous optimization)
4. **Honest scope:** the gate eliminates harm from universal chain allocation on shallow/star plans, with a small but real quality improvement (macro EM +0.49pt) and meaningful cost reduction (-8% LLM calls)

---

## 4. Prohibited Claims

- ❌ "First adaptive RAG system"
- ❌ "First topology-aware RAG"
- ❌ "First query-planning RAG"
- ❌ "First cost-aware RAG"
- ❌ "Policy A eliminates star-plan harm" (Policy A does not read topology)
- ❌ "Chain allocation is universally beneficial" (it is not — this is the whole point)

## 5. Approved Claims

- ✅ "Structural depth of the compiled plan moderates the effect of chain allocation"
- ✅ "A simple depth gate attenuates the aggregate harm of universal chain allocation"
- ✅ "The depth gate operates on plan structure, not query complexity or knowledge topology"
- ✅ "The gate is deterministic and requires no learned classifier"
- ✅ "Improving the quality-cost frontier in the eligible stratum"
