# SlotRAG：面向 VLDB 2027 的轻量新型 RAG 方法

## 1. 方法名称

**SlotRAG: Cost-Aware Query-Specific Evidence Materialization for Multi-Hop Retrieval-Augmented Generation**

中文：

**SlotRAG：面向多跳问答的代价感知查询特定证据物化方法**

一句话定义：

> SlotRAG 将复杂问题编译为少量带变量的证据槽位，从非结构化语料中按需物化槽位记录，并通过代价感知的连接顺序，以尽可能少的检索和语义调用获得完整答案。

它仍然是标准意义上的 RAG 方法：

```text
问题
→ 检索外部知识
→ 组织证据
→ LLM 生成答案
```

但它不再直接根据完整问题检索 Top-K 文本，而是根据问题需要的数据结构进行检索。

---

# 2. 为什么需要 SlotRAG

传统 RAG 将问题视为一个整体检索请求：

```text
Query
→ Top-K Passages
→ Generator
```

这对单跳事实问题有效，但多跳问题通常包含多个关系约束和连接变量。

例如：

> 哪位 OpenAI 创始人后来又创办了一家人工智能公司？

这个问题实际需要满足：

```text
Founder(person, OpenAI)
Founded(person, company)
Industry(company, ArtificialIntelligence)
```

传统检索可能直接搜索整句话，但真正需要执行的是一个三关系连接。

QO-Bench 的近期研究已经表明，很多自然语言问题本质上是潜藏于文本记录中的数据库式查询；仅检索语义相关文本不能保证保留连接、交集和计数等操作所需的字段。即便给出正确证据，长上下文模型在执行这些查询操作时仍可能失败。

因此，SlotRAG 的基本判断是：

> 多跳 RAG 的主要问题不只是“没有检索到相关文本”，而是检索结果没有围绕查询变量和连接条件进行组织。

---

# 3. 最终架构

SlotRAG 在线阶段只有三个核心模块：

```text
Query
  ↓
Slot Compiler
  ↓
Adaptive Slot Materializer
  ↓
Generator
  ↓
Answer
```

其中 Adaptive Slot Materializer 内部负责检索、事实抽取和增量连接，不再拆成多个 Agent。

明确删除：

```text
全局知识图谱
Proof DAG
Evidence Database
多智能体
生成后验证 Agent
复杂多轮反思
新 Benchmark
全局 Schema
预先抽取全部关系
```

---

# 4. 核心概念：Evidence Slot

一个 Evidence Slot 是针对当前问题临时生成的虚拟关系：

[
S_i=P_i(X_i,Y_i,C_i)
]

其中：

* (P_i)：关系或属性；
* (X_i)：已经绑定的实体；
* (Y_i)：需要发现的变量；
* (C_i)：类型、时间或条件约束。

前述问题被编译为：

```text
S1 = Founder(person, OpenAI)
S2 = Founded(person, company)
S3 = Industry(company, ArtificialIntelligence)
```

变量连接关系为：

```text
S1.person = S2.person
S2.company = S3.company
```

每个槽位物化后形成查询局部表：

| person     | organization | source     |
| ---------- | ------------ | ---------- |
| Elon Musk  | OpenAI       | passage-17 |
| Sam Altman | OpenAI       | passage-22 |

Slot 并不是全局本体，也不是预先存在的数据库表。

它只在当前问题生命周期内存在。

---

# 5. 查询执行过程

## 第一步：Slot Compilation

LLM 将问题转换成一个小型 Slot Plan：

```json
{
  "slots": [
    {
      "id": "S1",
      "predicate": "Founder",
      "arguments": ["?person", "OpenAI"]
    },
    {
      "id": "S2",
      "predicate": "Founded",
      "arguments": ["?person", "?company"]
    },
    {
      "id": "S3",
      "predicate": "Industry",
      "arguments": ["?company", "Artificial Intelligence"]
    }
  ],
  "joins": [
    ["S1.person", "S2.person"],
    ["S2.company", "S3.company"]
  ],
  "outputs": ["person", "company"]
}
```

编译器只输出：

* 槽位；
* 变量；
* 类型；
* 连接键；
* 最终输出字段。

不生成完整推理链，也不生成检索文本。

## 第二步：选择第一个槽位

系统不一定按照问题中的自然语言顺序执行。

假设估算结果为：

| Slot                       | 预计候选数量 | 单次成本 |
| -------------------------- | -----: | ---: |
| Founder(?person, OpenAI)   |      6 |    1 |
| Founded(?person, ?company) |     很大 |    4 |
| Industry(?company, AI)     |     很大 |    3 |

系统优先物化 `Founder`，因为它能够快速得到少量 `person` 绑定。

## 第三步：绑定传播

得到：

```text
person = Elon Musk
person = Sam Altman
...
```

然后将下一槽位从：

```text
Founded(?person, ?company)
```

改写为多个有界检索：

```text
Founded(Elon Musk, ?company)
Founded(Sam Altman, ?company)
```

检索范围因此显著缩小。

## 第四步：增量连接

每个槽位物化后立即进行连接：

```text
S1 ⋈ S2
```

无法与当前候选连接的记录被立即删除，不传入后续步骤。

## 第五步：运行时重新规划

如果某个槽位返回的记录数量远高于估计值，SlotRAG 根据实际基数重新选择后续物化顺序。

## 第六步：生成答案

生成模型只接收：

```text
连接结果
+ 每个记录对应的原始证据段落
+ 用户问题
```

而不是接收所有检索到的候选文本。

---

# 6. 核心算法

设查询包含槽位集合：

[
\mathcal S={S_1,S_2,\ldots,S_n}
]

当前已绑定变量集合为 (B_t)。

对尚未物化的槽位 (S_i)，估计：

* (C_i(B_t))：在当前绑定下物化槽位的成本；
* (N_i(B_t))：预计返回记录数；
* (R_i(B_t))：预计能够删除的无效候选比例；
* (H_i)：该槽位距离最终输出的结构重要性。

选择：

[
S_i^*
=====

\arg\max_{S_i}
\frac{
R_i(B_t)\cdot H_i
}{
C_i(B_t)
}
]

直观含义：

> 优先执行单位成本下，最可能减少候选连接空间的槽位。

每次物化后更新：

```text
变量绑定
实际基数
槽位选择率
剩余连接图
```

然后重新规划。

这比静态 Query Decomposition 多了一项关键能力：

> 检索顺序由运行时返回的数据决定，而不是在开始时一次性固定。

---

# 7. Slot 的物理实现

槽位是逻辑关系，其物理实现可以是：

```text
BM25 检索
Dense Retrieval
Hybrid Retrieval
元数据过滤
LLM 关系抽取
已有结构化数据库查询
```

SlotRAG 不提出新的 Embedding 或 Retriever。

例如：

```text
Founder(Elon Musk, OpenAI)
```

可执行为：

```text
1. 使用实体和关系模板检索候选段落；
2. 在候选段落中抽取 Founder 记录；
3. 保存原始 source span；
4. 返回结构化行。
```

统一返回格式：

```json
{
  "slot_id": "S1",
  "bindings": {
    "person": "Elon Musk",
    "organization": "OpenAI"
  },
  "source_id": "doc-17",
  "source_span": "...",
  "confidence": 0.94
}
```

---

# 8. 与现有工作的区别

## 与 PlanRAG 的区别

PlanRAG 将复杂问题组织为逻辑查询树，并通过动态规划优化树结构，再执行聚合、改写、检索和生成。

SlotRAG 不强调新的分解树，而强调：

```text
虚拟证据关系
运行时变量绑定
槽位选择率
连接顺序
增量连接
```

PlanRAG 的节点通常是子问题；SlotRAG 的节点是可以物化并连接的关系槽位。

## 与 SRAG 的区别

SRAG 将从多篇文档中抽取的信息组织成关系表，再进行表格推理。

SlotRAG 不提前构建完整关系表：

```text
SRAG：
先抽取和构造结构化表
→ 再回答问题

SlotRAG：
先看到问题
→ 只物化当前问题所需的关系行
```

## 与 LOTUS、Abacus 的区别

LOTUS 提供语义过滤、连接、聚合等语义算子；Abacus 进一步对这些语义操作的质量、成本和延迟进行全局优化。

这些系统通常从用户或程序员已经给出的语义程序开始。

SlotRAG 解决的是：

```text
如何从一个自然语言问答请求，
自动生成查询特定的虚拟关系，
并通过检索动态物化这些关系。
```

## 与 GraphRAG 的区别

SlotRAG 不构建全局图，也不要求语料中预先存在完整路径。

只有当前问题所需的连接关系被临时物化。

## 与 QO-Bench 的关系

QO-Bench 已经明确提出，未来系统可以推断查询操作结构、为查询特定 Schema 物化字段，并执行关系操作。

因此，“查询特定 Schema”本身不能作为 SlotRAG 的全部创新。

SlotRAG 真正需要证明的新贡献是：

1. 将槽位定义为可检索的虚拟关系；
2. 利用运行时绑定和基数决定物化顺序；
3. 在每轮检索后进行增量连接和候选剪枝；
4. 联合优化问答质量、语义调用和中间结果规模。

---

# 9. VLDB 论文贡献

最终只保留三项贡献。

## Contribution 1：Slot-Based RAG Model

提出一种查询特定虚拟关系表示，把多跳 RAG 从文本相关性检索转化为槽位物化和连接执行。

## Contribution 2：Adaptive Slot Join Optimizer

提出基于：

```text
槽位选择率
物化成本
变量绑定
运行时基数
连接图
```

的自适应槽位执行算法。

## Contribution 3：SlotRAG System

实现一个轻量系统，并证明它能在多跳和数据库式自然语言查询中：

```text
减少无效文档访问
减少 LLM 语义调用
缩小中间结果
提升或维持回答准确率
保留证据溯源
```

PVLDB 2027 将机器学习、AI 与数据库、查询处理、文本及半结构化数据、数据溯源等列为研究范围，但要求论文仍然以核心数据管理问题为中心，并与数据库研究形成实质联系。

SlotRAG 的数据库核心应明确落在：

```text
虚拟关系
自适应查询处理
连接顺序优化
惰性物化
选择率估计
增量执行
数据溯源
```

---

# 10. 实验设计

不建立新 Benchmark。

## 数据集

主实验：

```text
HotpotQA
2WikiMultiHopQA
MuSiQue
StrategyQA
DROP
```

前三个数据集测试多跳证据连接；StrategyQA 测试需要组合事实的布尔判断，DROP 测试数值抽取、计数、比较和算术操作。实验不再使用 QO-Bench。HotpotQA 与 2WikiMultiHopQA 提供可用于证据质量评估的金标；其余数据集没有同等粒度金标时，证据质量指标严格报告为 `N/A`，不以零值代替。

数据划分与调优协议：

```text
Diagnostic:训练集分层抽样 10 题，仅用于系统与成本诊断，不作显著性结论
Tune:      训练集分层抽样 50 题，仅用于逐步调参
Validation:训练集独立分层抽样 200 题，用于冻结配置前验证
Final:     官方评估划分分层抽样 500 题，只在配置冻结后运行
```

主方法在每个阶段使用固定种子运行一次；随机顺序消融使用 5 个预注册种子，并同时报告均值、标准差、最小值和最大值。每次执行保存不可变 attempt 记录，失败重试不会覆盖历史。

## Baseline

```text
Hybrid RAG
IRCoT
ReAct RAG
PlanRAG
SRAG
强多跳 GraphRAG
```

条件允许时增加 LOTUS 实现的等价语义查询流程。

## 指标

回答质量：

```text
EM
F1
Accuracy
DROP EM / DROP F1
```

检索和执行：

```text
Evidence Recall@1/5/10
Evidence Precision@1/5/10
Evidence Hit@1/5/10
Evidence MRR
Evidence NDCG@10
Documents Accessed
Passages Processed
Retrieved Documents / Evidence Count
LLM Calls
Embedding / Reranker / Retrieval Calls
Prompt / Completion / Total Tokens（成本代理，不换算货币）
End-to-End Latency
Provider / Compilation / Execution / Materialization / Generation Latency
P50 / P95 / P99 Latency
Peak RSS / Index Bytes / Index Build Latency
```

数据库指标：

```text
Intermediate Binding Size
Slot Selectivity Estimation Error
Number of Re-optimizations
Planner Regret against Oracle Order
Materialization Reuse Rate
Cache Hit Rate
Plan Slots / Joins / Variables / Outputs / Operators / Complexity
Steps Executed
LLM / Retrieval / Step Budget Utilization
```

所有结果同时输出逐题、数据集×方法、题型分层和跨数据集宏平均视图。显著性分析采用逐题配对 bootstrap 95% 置信区间、双侧检验、Holm 多重比较校正，并报告中位差、胜/平/负、胜率和 Cliff's delta。失败报告基于全部 attempts，而不是只看最终成功快照。

---

# 11. 关键消融

必须包含：

```text
SlotRAG
vs. 原始完整问题检索

自适应槽位顺序
vs. 原问题顺序
vs. 固定顺序
vs. 随机顺序
vs. Oracle 顺序

运行时重新规划
vs. 静态规划

增量连接
vs. 所有槽位完成后统一连接

查询特定物化
vs. 急切结构化抽取

绑定传播
vs. 无绑定的独立子查询

类型化算子
vs. 禁用类型化算子（依赖算子的计划显式记为 unsupported，不允许最终 LLM 代算）
```

---

# 12. 内部 Go / No-Go 门槛

这不是 VLDB 官方录用阈值，而是建议的内部标准。

建议继续投稿的条件：

```text
回答质量达到或超过 PlanRAG 等强基线；

在质量下降不超过约 1 个百分点时，
文档访问或语义调用减少至少约 30%；

自适应执行顺序明显优于固定顺序；

运行时重新规划在数据分布变化下仍然有效；

在 DROP 的数值操作题与多跳数据集的连接型问题上取得明确优势；

能够清楚证明性能来自连接式执行，
而不是更强 Prompt 或更强基础模型。
```

应终止或更换方向的情况：

```text
Slot Compiler 错误成为主要瓶颈；

固定顺序与自适应顺序几乎没有差别；

绑定传播已被现有 PlanRAG 或 GraphRAG 完整覆盖；

只在个别多跳数据集上有效；

只能减少 Token，无法体现查询处理贡献。
```

---

# 13. 最终架构图

```text
Natural-Language Query
          ↓
┌──────────────────────┐
│ Slot Compiler        │
│ slots + joins + vars │
└──────────┬───────────┘
           ↓
┌──────────────────────────────┐
│ Adaptive Slot Materializer   │
│                              │
│ Select Slot                  │
│      ↓                       │
│ Retrieve + Extract Tuples    │
│      ↓                       │
│ Incremental Join             │
│      ↓                       │
│ Update Bindings/Cardinality  │
│      ↺                       │
└──────────────┬───────────────┘
               ↓
      Joined Evidence Table
               ↓
┌──────────────────────┐
│ Generator            │
└──────────┬───────────┘
           ↓
        Answer
```

---

# 14. 最终判断

这个版本比 QED 合适，原因是：

```text
仍然是一种清晰的 XXX-RAG 方法；
只有三个在线模块；
没有全局知识图谱；
没有新数据库语言；
没有 Proof 系统；
没有新 Benchmark；
没有多智能体；
数据库贡献集中在连接与自适应物化；
工作量能够控制在 VLDB Research Paper 范围。
```

最终核心表述：

> **SlotRAG does not retrieve passages for the whole question. It lazily materializes query-specific evidence slots and adaptively joins them using runtime bindings and cardinalities.**

中文：

> **SlotRAG 不围绕完整问题盲目检索文本，而是按需物化查询所需的证据槽位，并根据运行时变量绑定和基数自适应地完成证据连接。**
