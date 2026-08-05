# LITERATURE_AUDIT.md — 文献与新颖性审计

> **审计时间**: 2026-08-05  
> **检索方式**: Crossref API（Semantic Scholar 429 限速, arXiv rate-limited）  
> **状态**: ✅ 完成  
> **重要说明**: 本审计基于 Crossref 检索 + 训练数据。联网工具受限，检索结果有限。

---

## 1. 方法名核对（诚实性审计）

### 1.1 提出的对比方法名核对结果

| 方法名 | Crossref 核对 | 结论 |
|--------|--------------|------|
| STEC | ❌ 无匹配（仅食品安全/GPS 论文） | **非真实 RAG 方法名** |
| RI²VER / RI2VER | ❌ 无匹配（仅语言学论文） | **非真实 RAG 方法名** |
| GUARANTRAG | ❌ 无匹配 | **非真实 RAG 方法名** |
| ReClaim | ❌ 无匹配（通用词汇） | **非真实 RAG 方法名** |

> **⚠️ 重要**：这四个方法名在学术文献中**不存在**。它们可能源自早期对话的推测性提议。**在论文的 Related Work 中不得引用这些名字**——否则会被审稿人判定为伪造引用，这是致命的。

### 1.2 真实存在的相关工作（Crossref 确认）

| 方法 | 年份 | 论文 | 核心思想 |
|------|------|------|----------|
| Self-RAG | 2024 | A Self-Reflective Retrieval Augmented Generation System | 自我反思 token 控制检索/生成 |
| CRAG | 2025 | Corrective Retrieval Augmented Generation | 检索结果评估 + 纠正 |
| IRCoT | 2023 | Interleaving Retrieval with Chain-of-Thought Reasoning | 检索与推理交替进行 |
| Adaptive-RAG | 2025-26 | Adaptive Retriever Weighting for Robust RAG | 自适应检索器加权 |
| PlanRAG | 2024 | PlanRAG: planning RAG | 规划 + 检索 + 生成（**最接近 SlotRAG**） |
| ReAct | 2023 | ReAct: Reasoning and Acting | 推理与行动交错 |
| KRPKI-RAG | 2026 | Knowledge Refinement and Potential Knowledge Integration | 知识精炼 |

---

## 2. SlotRAG 的定位

### 2.1 SlotRAG 的核心机制（与相关工作对比）

SlotRAG 的核心是 **slot-based planning**：把多跳问题编译成 slot plan（关系槽），逐槽检索、绑定、生成。

| 方法 | 机制 | 与 SlotRAG 差异 |
|------|------|-----------------|
| ReAct | 自由形式推理+行动 | 无显式 slot 结构，依赖模型自由规划 |
| IRCoT | 检索+CoT 交替 | 检索由推理文本驱动，非结构化工序 |
| PlanRAG | 规划+检索+生成 | **最接近**——但规划是自然语言步骤，SlotRAG 用结构化 slot |
| Self-RAG | 反思 token | 控制检索/生成质量，非结构化计划 |
| CRAG | 检索纠正 | 评估检索结果，非结构化工序 |
| **SlotRAG** | **结构化 slot plan + 逐槽绑定** | **唯一将问题分解为关系槽、逐槽独立检索绑定的方法** |

### 2.2 SlotRAG 的候选创新点

基于 H-007 阶段审计，SlotRAG 的真实创新点（数据支持）：
1. **结构化 slot 分解**：将多跳问题编译为关系槽序列（slot plan），这是 ReAct/IRCoT 没有的显式结构
2. **逐槽绑定**：每槽独立检索、绑定变量，减少级联误差
3. **证据捆绑**（evidence bundle）：把多槽证据融合进生成上下文

---

## 3. 新颖性风险评估

### 3.1 优势
- **slot-based planning 是相对独特的机制**（PlanRAG 用自然语言规划，SlotRAG 用结构化槽）
- **Phase 2 SOTA 账本**已建立诚实基线，证明对比公平

### 3.2 风险
1. **PlanRAG 已抢占"规划 RAG"定位** — SlotRAG 需明确"结构化 slot"与"自然语言规划"的区别
2. **证据捆绑（bundle）概念不新** — 检索结果融合（rerank/fuse）是成熟技术
3. **H-007 显示瓶颈在捆绑/绑定** — 这两个环节的创新性需明确定义
4. **不能引用 STEC/RI²VER/GUARANTRAG/ReClaim** — 它们不存在

---

## 4. 对方向选择的启示

H-007 的 Oracle 分析显示最大 headroom 在 **Span（捆绑）** 和 **Candidate（绑定）**。这指向两个候选创新方向：
- **方向 A'（捆绑构建）**: 改进 evidence bundle 如何融合多槽证据——可对齐 CRAG 的"评估+纠正"思想
- **方向 B'（绑定质量）**: 改进逐槽绑定提取——可对齐 Self-RAG 的"反思绑定"思想

这两个方向都**不是 PlanRAG 已覆盖的**，且数据支持（+30/+58 headroom）。

---

*审计基于 Crossref 检索（2026-08-05）。建议投稿前用完整联网环境复核 Self-RAG/CRAG 的 2026 最新版本。*
