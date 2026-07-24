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

## 持续实验与架构演进账本

本节是方法、实现和实验的唯一同步账本。后续每次架构或配置变更都必须先写明假设和预期指标，再使用新的源码指纹和运行目录执行；不覆盖旧 attempt，不删除负结果，不在 Validation 或 Final 上调参。详细逐题表、分层表、失败表和 bootstrap 表以对应 `runs/<run-id>/summaries/<stage>/` 为准，本节保留可审计的关键结论和决策。

可比性规则：

```text
Diagnostic n=10 只用于发现故障、成本瓶颈和候选调优方向，不作显著性或论文主结论。
schema v4 之前的运行不用于阶段 token、唯一访问量或索引/在线延迟的正式比较。
单次 temperature=0 运行仍可能存在提供方非确定性；冻结配置前必须补运行间稳定性试验。
证据无金标时严格记为 N/A，失败、空结果和 unsupported 均进入分母。
```

### 已完成诊断的架构与测量版本（2026-07-21）

`schema v4` 对应源码指纹 `99469d81eb4984cb113a86b6c0abeef78a5cd084518b9b9eed9fcd9ef6f73308`，当前使用默认 `materialization_top_k=5`。该版本包含以下方法和实验基础设施变更：

1. Slot Compiler 先进行结构化编译；当且仅当共享变量唯一明确时，允许本地修复缺失或错误的 join key，避免可确定修复的额外 LLM 调用。
2. 自适应执行器记录编译、抽取、规划、推理和生成各阶段调用/token/延迟，并分开“累计候选访问量”与“唯一文档/段落访问量”。
3. 语料向量构建放到在线问题计时之外，单独报告索引延迟、embedding 调用和缓存命中；查询向量仍计入在线成本。
4. 单输出列且只有一个非空唯一值时允许确定性返回，以省略生成调用。该优化仍在诊断中：结构化值和错误抽取可能导致直接输出质量下降，冻结前需加入标量类型约束并做配对重复实验。
5. `slotrag-no-operators` 遇到依赖类型化算子的计划时显式返回 `unsupported_operation`，不允许最终 LLM 代算。
6. 每次执行写入不可变 attempt，统计同时保留逐题、分层、宏平均、P50/P95/P99、失败分类、种子方差和配对 bootstrap。

### 实验记录

| 运行 | 数据/规模 | 关键设置 | SlotRAG 结果 | 对照结果 | 决策 |
| --- | --- | --- | --- | --- | --- |
| `vldb2027-diagnostic-v1` | HotpotQA train，10 题/方法 | schema v3，top-k=5，指纹 `72733e...b9ce` | F1 0.714，R@5 0.900，NDCG@10 0.892，9.2 候选文档，4.5 LLM calls，8,886 tokens，72.81 s | Hybrid F1 0.642，R@5 0.900，NDCG@10 0.905，9.2 文档，1.1 calls，2,276 tokens，15.11 s | 仅作历史诊断；schema v3 缺少可信的阶段和唯一访问指标。 |
| `vldb2027-tune-topk3-v1` | HotpotQA train，10 题 | schema v4 过渡版，top-k=3，指纹 `4541f8...cce3` | F1 0.542，R@5 0.800，NDCG@10 0.823，4.7 候选/3.6 唯一文档，3.8 calls，7,419 tokens，65.23 s | 未同轮重跑 Hybrid | 暂不采用 top-k=3；虽降低成本，但单次运行显示证据覆盖下降。该轮抽取阶段埋点有缺陷，不用于阶段指标比较。 |
| `vldb2027-diagnostic-v2` | HotpotQA train，10 题/方法 | schema v4，top-k=5，指纹 `99469d...3088` | F1 0.450，R@5 0.850，NDCG@10 0.823，9.2 候选/6.3 唯一文档，4.8 calls，9,226 tokens，100.29 s，P95 144.60 s | Hybrid F1 0.592，R@5 0.900，NDCG@10 0.905，9.2 文档，1.1 calls，2,372 tokens，22.90 s，P95 37.79 s | 20/20 成功，阶段 token 覆盖 100%。当前质量、调用和延迟均未达门槛，不形成正面结论。 |
| `vldb2027-diagnostic-v2` | 2WikiMultiHopQA train，10 题/方法 | 与上行完全相同 | F1 0.644，R@5 0.850，NDCG@10 0.893，7.7 候选/5.8 唯一文档，5.1 calls，10,474 tokens，101.79 s，P95 153.93 s | Hybrid F1 0.652，R@5 0.925，NDCG@10 0.938，9.8 文档，1.1 calls，1,866 tokens，15.74 s，P95 21.30 s | 最终 20/20 成功；共 21 attempts，1 次 `provider_connect` 失败后重试恢复。文档访问降低 40.8%，但质量略低且语义调用和延迟显著更高。 |
| `vldb2027-diagnostic-v2` | MuSiQue train，10 题/方法 | 与上行完全相同；证据质量 N/A | F1 0.750，12.2 累计候选/8.7 唯一文档，5.6 calls，9,225 tokens，84.79 s，P95 127.15 s | Hybrid F1 0.756，9.8 累计/唯一文档，1.2 calls，3,452 tokens，19.19 s，P95 39.48 s | 20/20 成功。SlotRAG 的 2-hop F1 为 0.917（Hybrid 0.759），3-hop 为 0.333（Hybrid 0.667），4-hop 双方均为 1.000 但仅 1 题。暂无跨跳数可扩展优势，且累计访问和语义成本更高。 |
| `vldb2027-diagnostic-v2` | StrategyQA train，10 题/方法 | 与上行完全相同；主指标 Accuracy，证据质量 N/A | Accuracy 1.000，2.7 累计/唯一文档，2.1 calls，3,281 tokens，55.09 s，P95 84.70 s | Hybrid Accuracy 1.000，2.7 文档，1.2 calls，1,096 tokens，23.88 s，P95 54.56 s | 最终 20/20 成功；共 21 attempts，1 次 `provider_connect` 失败后重试恢复。true/false 各 5 题，双方均全对；布尔路径可用，但 SlotRAG 无质量或访问量优势，成本更高。 |
| `vldb2027-diagnostic-v2` | DROP train，10 题/方法 | 与上行完全相同；主指标 DROP EM/F1，证据质量 N/A | EM 0.600，F1 0.734，1.5 累计/1.0 唯一文档，4.1 calls，7,387 tokens，74.23 s，P95 147.87 s | Hybrid EM 0.700，F1 0.767，1.0 文档，1.0 call，1,156 tokens，16.85 s，P95 26.91 s | 20/20 成功。counting 的双方 F1 均为 0.500；SlotRAG 仅 2/4 题实际执行类型化算子，这 2 题均正确，未执行算子的 2 题均错误。算子覆盖是优先故障。 |

`vldb2027-diagnostic-v2` 完整性：5 个数据集、2 个方法、每个数据集 10 题，共 100/100 个最终记录；总计 102 attempts，其中 2 次 Agnes `provider_connect` 失败均在保留原 attempt 后重试成功。全部最终记录为 schema v4，阶段 token 覆盖率 100%；HotpotQA 和 2WikiMultiHopQA 共 40 条记录有证据金标，其余 60 条的证据质量为 N/A。

跨数据集等权宏平均（仅作 Diagnostic 方向判断）：

| 指标 | SlotRAG | Hybrid | 诊断 |
| --- | ---: | ---: | --- |
| 数据集主指标宏平均 | 0.716 | 0.753 | SlotRAG 低 3.8 个百分点。 |
| Evidence Recall@5（仅 2 个有金标数据集） | 0.850 | 0.913 | SlotRAG 证据覆盖较低。 |
| Evidence NDCG@10（仅 2 个有金标数据集） | 0.858 | 0.922 | SlotRAG 排序质量较低。 |
| 唯一文档访问数 | 4.90 | 6.50 | SlotRAG 下降 24.6%，但未达 30% 门槛。 |
| 累计候选文档访问数 | 6.66 | 6.50 | SlotRAG 的重复物化抵消了唯一访问节省。 |
| LLM calls | 4.34 | 1.12 | SlotRAG 约为 3.9 倍。 |
| Total tokens | 7,919 | 1,988 | SlotRAG 约为 4.0 倍。 |
| 在线延迟 | 83.24 s | 19.71 s | SlotRAG 约为 4.2 倍。 |

逐数据集配对 bootstrap 的样本量均仅为 10；所有 95% 置信区间都包含 0，Holm 校正后 `p=1.0`。因此这些数字只能用于诊断，不能支持任何显著优势声明。当前版本同时未达到质量、唯一访问降幅和语义成本门槛；在 F1/F2 修复通过同样本配对验证前，不进入 Tune50。

HotpotQA 两次相同样本运行间，SlotRAG F1 从 0.714 变为 0.450，Hybrid 从 0.642 变为 0.592。该差异不能归因于样本变化，说明在 `temperature=0` 下仍存在运行间波动，而 SlotRAG 的多阶段链路放大了该波动。因此，当前优先级不是继续扩大样本，而是：

1. 完成五数据集 Diagnostic，定位错误是否集中在编译、检索、抽取、连接或答案规范化。
2. 对确定性返回增加标量类型安全检查，并与强制生成进行配对比较。
3. 在相同样本上运行多次重复，报告运行间均值、方差和答案一致率；若提供方支持可复现 seed，将 seed 写入 manifest 和逐题记录。
4. 优先减少编译/抽取调用与结构化修复，再评估自适应 top-k；不使用只降低证据覆盖的成本优化。
5. 只有在 Tune50 和独立 Validation200 上同时满足质量与成本门槛，才冻结架构并进入 Final500。

### 已定位的架构故障与待验证修改

| 编号 | 证据 | 归因 | 拟议修改 | 验收方式 | 状态 |
| --- | --- | --- | --- | --- | --- |
| F1 | HotpotQA `5a7b9b8a554299294a54aa1c`：金答案 `Holy Avenger`，Evidence Recall@5=1.0，但执行顺序为 `S2 -> S1`，最终确定性输出 `Senninha`。`S1` 的来源段落是 Erica Awano，抽取绑定却是段落中不存在的 `Rogério Martins`/`Ridaut Dias Jr.`。 | 绑定传播将上游候选注入抽取上下文后，LLM 回显了绑定而非从证据抽取；错误 join 再被确定性返回放大。这是抽取/连接正确性故障，不是检索未命中。 | 已增加 provenance-grounded binding validator：传播值必须与抽取行一致，且规范化形式必须出现在 `source_span` 或文档标题；否则拒绝该行并记录 `grounding_rejections`。合法的文档标题锚定可通过校验。 | v3 故障题走了不同的编译/检索轨迹，`grounding_rejections=0`、R@5=0、F1=0，因此未隔离验证该修改。DROP 另一题触发 2 次拒绝后转证据生成并答对，但显示它可能增加空行和调用。需要冻结计划重放才能评估因果。 | 已实现，在线因果未建立 |
| F2 | DROP `drop_train_11251`：问题要求计算 1906-09-18 到 1906-12-02 的月份差，金答案为 3。计划将 `DateDiffInMonths(?startDate, ?endDate, ?months)` 编译成普通 slot，`operators=[]`，LLM 抽取 `months=2`，最终 DROP EM/F1=0。 | 衍生数值被伪装成可检索语义关系，绕过了类型化算子和 `slotrag-no-operators` 的干净对照；结果依赖 LLM 心算，不具备数据库执行语义。 | v3 的事后安全改写依赖 LLM 先产生有效计划，在线三次编译失败后无法触发。schema v6 已对严格匹配的“How many months after ...”问题直接生成 `MonthDifferenceDates(?startDate, ?endDate)` 与 `date_diff_months` 算子，跳过 LLM 计划结构生成；其他月份、天数、年份和 `before` 问法仍走原编译路径。 | v4 目标题输出 3，`typed_plan_templates=1`、`compilation_llm_calls=0`、`operators_executed=1`、`plan_fallbacks=0`，DROP EM/F1=1.0；同批只有该题触发模板。 | schema v6 在线通过 |
| F3 | DROP v4 虽升至 F1 0.834，但平均仍需 3.5 LLM calls、7,078 tokens 和 74.76 s；仅编译就占 1.9 calls、4,747 tokens 和 42.29 s，10 题中 4 题三次编译失败后退化为单槽证据回答。 | DROP 每题只有一个唯一文档，不存在跨文档连接顺序或绑定传播收益；仍调用结构 Slot Compiler 是与数据拓扑不匹配的固定成本。 | 在类型算子模板之后增加退化单文档计划：当可见语料拓扑只有一个唯一文档时，直接物化 `EvidenceAnsweringQuestion(?answer)`，跳过结构编译；多文档问题保持原路径。新增 `direct_plan_templates`，并加入禁用该路由的消融。 | v5 精确产生 1 个 typed + 9 个 direct 计划，编译调用和 fallback 均为 0；calls/tokens/延迟为 1.1/1,417/15.26 s，但 F1 0.796，较 v4 低 0.038。 | H7/H9 通过，H8 失败 |
| F4 | v5 `drop_train_41439` 的直接槽位抽取为 `families (20,154 families compared to 74,563 people)`；它是唯一非空字符串，因而被确定性输出，DROP F1 从 1.0 降到 0.29。 | 直接计划把“答案 + 括号内证据说明”当作合法标量；结构类型正确，但答案投影不满足最短答案跨度契约。 | 只对 direct plan 的答案行做可审计规范化：若结尾括号体以数值开头且再次原样包含括号外答案，则去掉括号说明；`Mercury (planet)`、`Washington (Washington state)` 等消歧括号保持不变，EvidenceRecord 保留原始绑定。新增 `answer_span_normalizations`。 | v6 在线抽取自行返回 `families`，因此规范化计数为 0；冻结重放 v5 原始结果后输出 `families`、计数 1，且原始 EvidenceRecord 不变。总体 F1 0.867。 | 冻结重放通过，在线触发未观察 |
| F5 | v6 2Wiki `55b23a90084c11ebbd56ac1f6bf848b6`：问题问 `Find Me Guilty` 与 `Tear Gas Squad` 哪部电影的导演出生更早。编译器生成四个事实抽取槽和第五个 `Compare(?bd1, ?bd2)` 槽；首次 attempt 因 `5 > max_steps=4` 返回 `budget_exceeded`，重试又在 embedding 端点超时。 | `Compare` 是对已抽取字段的确定性运算，却被错误物化为语义检索槽；两个独立事实分支也缺少由字段算子声明的关系连接，执行器只能处理等值 join。 | 将严格可证明的字段比较槽规范化为 `field_argmin`/`field_argmax` 类型算子；答案候选标签必须来自问题中已落地的计划常量，算子显式连接两个事实分支，执行器只对这些算子连接的分支做受控笛卡尔组合。保持 `max_steps=4`，不以放宽预算掩盖错误建模。 | 冻结重放从 5 槽改写为 4 槽并正确输出；但 v7 在线编译三轮均未形成可校验的输入计划，最终回退为单槽，`operator_rewrites=operators_executed=0`、F1=0。预算失败消失不等于算子修复生效。 | schema v9 离线通过、在线未通过 |
| F6 | v6 2Wiki 的三个 `comparison` 样本金答案均为 `no`；SlotRAG 分别输出语义正确的 `No, ...` 解释，单题 F1 仅 0.143/0.143/0.083。另一个 `bridge_comparison` 同样正确回答 `No. ...`，F1 为 0.095。Hybrid 也受同一评分契约影响。 | Hotpot/SQuAD token-F1 奖励最短答案，但生成器没有对一般数据集的极性问题强制 canonical `yes/no`；这会把正确解释误计为低质量，并混淆方法质量与输出格式。 | schema v10 增加无金标泄漏的统一极性规范化：仅当问题是白名单助动词开头且以问号结束、最终答案首 token 为 yes/no/true/false 时，映射为 `yes`/`no`；对所有方法在 `run_method` 出口一致应用，并记录可审计计数。 | v8 在线双方各且仅改变同 4 题，每条计数 1，非极性题为 0；SlotRAG/Hybrid EM=F1 为 0.900/1.000，检索、证据与提供方调用逻辑不变。 | schema v10 在线通过 |
| F7 | v6 的 31 个 SlotRAG attempts 共记录 25 次计划校验错误；v7 的 10 个最终记录又产生 22 次结构失败、15 次修复调用和 5 次单槽 fallback。可提取的 16 条校验错误中有断图 6、缺工具调用 3、旧比较/argmin 表达 3、嵌套 JSON 1、错误 join field 1、同实体变量不一致 1、无变量槽 1；5 个 fallback 全部属于 `comparison` 或 `bridge_comparison`。 | 大量成本来自可分类的结构协议不一致，而不是查询本身需要多轮规划；F5 还证明“有效计划之后才执行的改写”无法覆盖入口校验失败。不过缺工具调用、未落地常量等错误不能安全本地猜测。 | 先实现全方法统一的 F6 出口规范化，再独立预注册编译入口修复：对白名单别名和双重 JSON 做无损规范化；字段极值问题采用严格句法和问题内常量约束的类型化入口，其他断图、缺工具调用和未落地字段仍重试或 fallback。 | 冻结重放逐类报告成功修复率和误修复率；在线同样本必须记录触发范围、编译 calls/tokens/延迟、F5 答案和全部异常，不得吞掉 ValidationError。 | v7 再现，待独立 schema 验证 |

### schema v5 候选架构与预注册复验（2026-07-21）

schema v5 对应源码指纹 `c11171dd1ade4088bf0a030e44a145293cb3f02680b5433b44fe1f744c693fce`，使用与 v2 相同的数据、样本、提供方、预算和 `materialization_top_k=5`，只改变以下方法逻辑：

1. 引入来源感知的传播绑定校验，新增 `grounding_rejections` 指标。
2. 引入安全的功能谓词规范化入口和 `date_diff_months` 确定性算子，新增 `operator_rewrites` 指标。当前只启用已有失败证据且可安全证明的月份差改写，不在未验证的 `Count`/`ArgMax` 上扩大规则。
3. 确定性答案路径拒绝序列化对象/数组；普通实体、数值和布尔标量仍可以零生成调用返回。
4. 记录 schema 升级到 v5；schema v4 及以前的两个新指标报告为 N/A，不回填为 0。

离线验证已通过 `57 passed, 1 skipped`，Python 编译检查通过。在线复验使用新目录 `runs/vldb2027-diagnostic-v3`，先运行 HotpotQA 和 DROP，预注册判定如下：

数据审计在 manifest 首次创建后补生成为 `runs/vldb2027-diagnostic-v3/dataset-audit.json`：10 个数据集划分、共 378,888 条记录、0 invalid，SHA-256 为 `a24ad382ed92fe32949d050c282a366eaf6a16085ad8df27dfc9f12b7c00c67e`，与 v2 完全一致。因初始化顺序问题，v3 manifest 内嵌审计字段为空，该限制保留在账本中，不对生成后的 manifest 进行静默改写。

```text
H1（绑定正确性）：HotpotQA 故障题不再产生无来源绑定；整体 F1 和失败率不低于 v2。
H2（算子正确性）：DROP 月份差故障题输出 3，计划记录 operator_rewrites=1 且实际执行算子。
H3（无隐性回退）：HotpotQA 的 Evidence Recall@5/NDCG@10 和 DROP 的总体 F1 不低于 v2；新增拒绝不得导致系统性 empty/budget_exceeded。
```

| v3 复验 | 状态 | SlotRAG | Hybrid | 判定 |
| --- | --- | --- | --- | --- |
| HotpotQA train，10 题/方法 | 20/20 完成，0 失败 | F1 0.700，R@5 0.750，NDCG@10 0.775，9.2 累计/5.9 唯一文档，5.1 calls，9,981 tokens，101.93 s，P95 190.84 s | F1 0.594，R@5 0.900，NDCG@10 0.905，9.2 文档，1.1 calls，2,356 tokens，17.04 s，P95 25.46 s | SlotRAG 对 Hybrid 的配对差为 +0.106，95% CI [-0.317, 0.505]，`p=0.6162`。v2→v3 为 3 胜/7 平/0 负，但 `grounding_rejections=0`，改善不能归因于 F1 修改；故障题仍为 0 分且本轮未召回金证据。H1 未建立，R@5/NDCG 回退使 H3 不通过。 |
| DROP train，10 题/方法 | 20/20 完成，0 失败 | EM 0.500，F1 0.634，1.2 累计/1.0 唯一文档，4.3 calls，8,486 tokens，88.55 s，P95 138.26 s；平均 0.4 plan fallbacks | EM 0.700，F1 0.767，1.0 文档，1.1 calls，1,059 tokens，14.34 s，P95 25.25 s | SlotRAG 对 Hybrid 配对差 -0.133，95% CI [-0.333, 0]，`p=0.2154`。v2→v3 为 0 胜/9 平/1 负，F1 从 0.734 降至 0.634；`operator_rewrites=0`，目标题仍为 0 分。H2/H3 均不通过。 |

v3 只完成预注册的 HotpotQA/DROP 配对复验，共 40/40 个最终记录、0 失败、0 重试，全部为 schema v5。由于 H1 无法隔离建立且 H2/H3 失败，不扩展到其余三个数据集，不进入 Tune50。

### schema v6 确定性月份差计划与 v4 预注册（2026-07-21）

v3 说明“生成计划后再修复”的入口仍受上游结构化编译失败支配。schema v6 因此增加一个刻意收窄的类型计划模板：仅当答案类型为数值且问题严格匹配 `How many month(s) after` 时，编译器直接生成一个日期抽取槽位和一个 `date_diff_months` 算子。模板不覆盖 `before`、天数、年份、一般时长或非数值问题，避免把未经验证的规则扩展成新的启发式系统。

实现与测量变更：

1. 生成 `MonthDifferenceDates(?startDate, ?endDate)`，保留完整问题作为检索约束，输出 `?months`。
2. 省略结构计划 LLM 调用；证据日期仍由原有检索与带来源结构抽取获得，随后按日历月份边界确定性计算。
3. 新增 `typed_plan_templates`；schema v5 及以前严格报告 N/A，不回填 0。逐题记录升级为 schema v6。
4. 离线覆盖包括目标题端到端执行、日期格式解析、模板范围负例、schema 兼容和 benchmark runner，共 `60 passed, 1 skipped`；Python 编译检查通过。

在线复验固定使用与 v2/v3 完全相同的 DROP diagnostic 10 题和两种方法，运行目录为 `runs/vldb2027-diagnostic-v4`。先生成数据审计，再创建 manifest；源码指纹为 `4eb4b1f067537651f3ca323e84a5242cd11774837f3676a3695cb8ff7987d7d5`。预注册判定如下：

```text
H4（目标正确性）：drop_train_11251 输出 3，typed_plan_templates=1、compilation_llm_calls=0、operators_executed=1、plan_fallbacks=0。
H5（范围约束）：同批其余题 typed_plan_templates=0，不因模板出现新增 failed/empty/unsupported。
H6（总体无回退）：DROP 总体 EM/F1 不低于 v3；调用、token 和延迟按完整同批结果报告，不以单题成功替代总体判断。
```

v4 最终完整性：20/20 个最终记录、20 个不可变 attempts、0 benchmark 重试、0 failed/empty/unsupported，全部为 schema v6；提供方内部重试平均为 SlotRAG 0.1、Hybrid 0.2。manifest 正确内嵌 378,888 条、0 invalid 的数据审计及 SHA-256 `a24ad382ed92fe32949d050c282a366eaf6a16085ad8df27dfc9f12b7c00c67e`；DROP 样本文件与 v3 SHA-256 均为 `cc937926ba09a0e6b4dabca8897236100c56a82691b3dd2e4230366e8096f9c4`。

| v4 DROP diagnostic | SlotRAG | Hybrid | 判定 |
| --- | ---: | ---: | --- |
| EM / F1 | 0.700 / 0.834 | 0.700 / 0.767 | 配对 F1 差 +0.067，95% CI [-0.099, 0.300]，`p=p_holm=0.7108`；1 胜/8 平/1 负，不能声称显著优势。 |
| 累计/唯一文档访问 | 1.2 / 1.0 | 1.0 / 1.0 | 唯一访问无优势，累计访问高 20%。 |
| LLM calls | 3.5 | 1.2 | SlotRAG 为 2.9 倍；编译/抽取/生成为 1.9/1.3/0.2。 |
| Prompt / completion / total tokens | 4,708 / 2,369 / 7,078 | 762 / 422 / 1,185 | SlotRAG 总 token 为 6.0 倍。 |
| 在线延迟 mean / P50 / P95 / P99 | 74.76 / 71.41 / 127.45 / 139.56 s | 18.62 / 18.52 / 25.49 / 26.27 s | SlotRAG 平均延迟为 4.0 倍；编译/执行/生成为 42.29/26.28/6.20 s。 |
| 模板/算子/回退 | 0.1 / 0.2 / 0.4 | 0 / 0 / 0 | 10 题中 1 题走新模板、2 题执行算子、4 题发生 plan fallback。 |

H4、H5、H6 均通过：目标题输出 3，只用 1 次调用、1,290 tokens、19.43 s；同批其余 9 题的 `typed_plan_templates=0`，且没有新增异常状态。v3→v4 的 SlotRAG 为 2 胜/8 平/0 负、平均 F1 +0.200，其中目标题的 +1.0 有明确架构触发证据；`drop_train_26165` 的另一个 +1.0 没有触发新模板，保守归为提供方波动。总体 calls/tokens/延迟相对 v3 分别下降 18.6%/16.6%/15.6%，但与 Hybrid 的成本差距仍远超内部门槛。因此不进入 Tune50，转入预注册的 F3 单文档退化计划验证。

### schema v7 单文档退化计划预注册（2026-07-21）

该路由只读取运行时已经可见的语料拓扑，不使用金答案、金证据或题型标签。编译优先级固定为“已验证类型模板 → 单文档退化计划 → 原 Slot Compiler”，因此 v4 的月份差修复不会被直接回答路径覆盖，多文档数据集的连接式执行也不变。v5 继续使用同一 DROP 样本，并预注册：

离线实现已完成：`direct_plan_templates` 只在 schema v7 有定义，schema v6 及以前报告 N/A；同一 `doc_id` 的多个 chunk 计为一个文档；新增 `slotrag-no-direct`，并纳入 ablation gate、smoke 和正式 ablations。测试覆盖路由、类型模板优先级、多文档隔离、消融开关、schema 兼容和 runner 版本，共 `64 passed, 1 skipped`；Python 编译和实验 YAML 校验通过。

```text
H7（路由可审计）：1 题 typed_plan_templates=1，其余 9 题 direct_plan_templates=1；全部 compilation_llm_calls=0、plan_fallbacks=0。
H8（质量非劣）：DROP F1 相对 v4 下降不超过 0.01，目标题继续输出 3；失败、空结果和 unsupported 均为 0。
H9（成本门槛）：平均 LLM calls ≤1.5、total tokens ≤2,500、在线延迟 ≤40 s，并完整报告相对 Hybrid 的差异。
```

v5 使用运行目录 `runs/vldb2027-diagnostic-v5`，源码指纹为 `82f49bf3da06f8897cc16186c83370a27f6d10dfe8c47a5ccd13092fae91724d`。数据审计和 DROP 样本 SHA 分别与 v4 相同。20/20 个最终记录、20 attempts、0 benchmark 重试、0 failed/empty/unsupported，全部为 schema v7。

| v5 DROP diagnostic | SlotRAG | Hybrid | 判定 |
| --- | ---: | ---: | --- |
| EM / F1 | 0.700 / 0.796 | 0.700 / 0.714 | 配对差 +0.082，95% CI [-0.160, 0.353]，`p=p_holm=0.5728`；2 胜/7 平/1 负，仍不显著。Hybrid 自身相对 v4 有波动，跨运行只作诊断。 |
| 累计/唯一文档访问 | 1.0 / 1.0 | 1.0 / 1.0 | 访问量持平；SlotRAG 累计访问相对 v4 从 1.2 降到 1.0。 |
| LLM calls | 1.1 | 1.0 | SlotRAG 相对 v4 下降 68.6%，仅高于本轮 Hybrid 0.1；编译/抽取/生成为 0/1.0/0。 |
| Prompt / completion / total tokens | 1,093 / 325 / 1,417 | 762 / 339 / 1,101 | SlotRAG 相对 v4 总 token 下降 80.0%，仍比本轮 Hybrid 高 28.7%。 |
| 在线延迟 mean / P50 / P95 / P99 | 15.26 / 12.57 / 26.46 / 27.49 s | 17.17 / 16.42 / 27.57 / 31.23 s | SlotRAG 相对 v4 平均延迟下降 79.6%，且本轮比 Hybrid 低 11.1%。 |
| typed / direct / fallback | 0.1 / 0.9 / 0 | 0 / 0 / 0 | H7 精确通过；10 题均无编译调用，只有目标题执行类型算子。 |

H7、H9 通过，H8 失败。v4→v5 为 1 胜/8 平/1 负：`drop_train_24769` 从 0.67 升至 1.0，但 `drop_train_41439` 从 1.0 降至 0.29，净变化 -0.038。后者输出带括号解释，是唯一有明确、局部且可测的路由质量回退。F3 的成本目标已经建立，因此保留单文档路由，不进入 Tune50，先验证 F4 答案跨度规范化。

### schema v8 直接答案跨度规范化预注册（2026-07-21）

规范化只作用于 `direct_plan_templates=1` 的投影行，不修改检索、抽取、原始 EvidenceRecord 或类型算子结果。规则要求完整字符串形如 `head (body)`、`body` 以数值开头，且规范化后的非空 `head` 在 `body` 中原样出现；否则不变。新增 `answer_span_normalizations`，schema v7 及以前报告 N/A。预注册：

离线实现已完成：规范化只修改最终投影行，保留原始 EvidenceRecord；测试覆盖目标题、非重复消歧、重复但非数值消歧、非 direct 隔离、schema 兼容和 runner 版本，共 `66 passed, 1 skipped`。Python 编译和实验 YAML 校验通过。

```text
H10（局部修复）：drop_train_41439 输出 families、answer_span_normalizations=1、F1=1；其余 9 题该指标为 0。
H11（质量恢复）：DROP F1 ≥0.824，目标题继续输出 3，且无 failed/empty/unsupported。
H12（成本保持）：平均 LLM calls ≤1.5、total tokens ≤2,500、在线延迟 ≤40 s。
```

即使 schema v8 在 DROP 通过，也必须在多文档数据上验证路由不改变原执行路径，并通过 `slotrag-no-direct` 消融证明收益来自拓扑感知退化，而不是隐式更换基线。

v6 DROP 使用运行目录 `runs/vldb2027-diagnostic-v6`，源码指纹为 `7fef6c1d36fdec3273b55e7202c3faf818da3ac757ca886119db4736be0bb8aa`，审计和样本 SHA 与 v5 相同。20/20 个最终记录、20 attempts、0 benchmark 重试、0 failed/empty/unsupported，全部为 schema v8。

| v6 DROP diagnostic | SlotRAG | Hybrid | 判定 |
| --- | ---: | ---: | --- |
| EM / F1 | 0.800 / 0.867 | 0.700 / 0.722 | 配对差 +0.145，95% CI [0, 0.345]，`p=p_holm=0.2182`；2 胜/8 平/0 负，n=10 仍不能声称显著优势。 |
| 累计/唯一文档访问 | 1.0 / 1.0 | 1.0 / 1.0 | 访问量持平，证据指标因 DROP 无金标而为 N/A。 |
| LLM calls | 1.0 | 1.0 | 完全持平；SlotRAG 为 1.0 次抽取，Hybrid 为 1.0 次生成。 |
| Prompt / completion / total tokens | 1,093 / 281 / 1,373 | 762 / 342 / 1,104 | SlotRAG 高 24.4%，但远低于 v4。 |
| 在线延迟 mean / P50 / P95 / P99 | 11.52 / 10.65 / 16.84 / 19.18 s | 12.37 / 12.60 / 16.02 / 16.68 s | SlotRAG 平均低 6.9%，P95/P99 略高。 |
| typed / direct / normalization / fallback | 0.1 / 0.9 / 0 / 0 | 0 / 0 / 0 / 0 | 路由保持稳定；本轮提供方直接给出简洁答案，未触发新规则。 |

H11、H12 通过。H10 的在线输出目标通过，但触发计数目标未通过，不能把 v5→v6 的唯一 F1 变化（`drop_train_41439` +0.71）直接归因于 schema v8。对 v5 不可变结果执行冻结重放后，答案从 `families (20,154 families compared to 74,563 people)` 变为 `families`，`answer_span_normalizations=1`，原始 EvidenceRecord 绑定不变；因此功能因果在冻结输入上成立，在线频率仍未知。

在不改源码、配置或测试的前提下，v6 随后扩展同一 diagnostic 的 HotpotQA 与 2WikiMultiHopQA。HotpotQA、2Wiki 样本 SHA-256 分别为 `b16d710e995dd7385ce2da389b3f61d714089c024a29c4362ce3d1cb1b4ccbe3`、`5bcc2298686f2c3d1e0e570bcfa6197454f32660009d6cf3e9599dae63f1c1a4`。最终共有 60/60 个样本快照、62 个不可变 attempts、2 次 benchmark 重试，schema 全部为 v8；最终状态为 58 `ok`、2 `failed`，40 条多文档记录具有证据金标。失败不会从分母删除。

质量与完整证据指标如下；DROP 已在上表报告且无证据金标，因此本表只列多文档数据集。

| 数据集/方法 | ok/总数 | EM / F1 | Recall@1/5/10 | Precision@1/5/10 | Hit@1/5/10 | MRR / NDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| HotpotQA / SlotRAG | 10/10 | 0.800 / 0.800 | 0.450 / 0.850 / 0.850 | 0.900 / 0.340 / 0.170 | 0.900 / 1.000 / 1.000 | 0.933 / 0.853 |
| HotpotQA / Hybrid | 9/10 | 0.700 / 0.717 | 0.450 / 0.850 / 0.900 | 0.900 / 0.340 / 0.180 | 0.900 / 0.900 / 0.900 | 0.900 / 0.860 |
| 2Wiki / SlotRAG | 9/10 | 0.500 / 0.546 | 0.425 / 0.875 / 0.875 | 0.900 / 0.380 / 0.190 | 0.900 / 0.900 / 0.900 | 0.900 / 0.883 |
| 2Wiki / Hybrid | 10/10 | 0.600 / 0.648 | 0.450 / 0.925 / 1.000 | 1.000 / 0.440 / 0.240 | 1.000 / 1.000 / 1.000 | 1.000 / 0.938 |

访问、调用、token 与端到端延迟如下。`候选/唯一` 同时给出累计工作量和去重后的实际覆盖；provider calls 包含在线 LLM、embedding 和 reranker，请勿与 LLM calls 混用。

| 数据集/方法 | 检索证据/文档/字符 | 文档候选/唯一 | 段落候选/唯一 | LLM/retrieval/embed/rerank calls | provider calls（含索引） | prompt/completion/total tokens | 在线 mean/P50/P95/P99 | 索引/含索引总延迟 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HotpotQA / SlotRAG | 3.2 / 3.0 / 1,509 | 7.7 / 5.9 | 7.7 / 5.9 | 3.8 / 1.6 / 1.6 / 1.6 | 7.0（8.0） | 5,498 / 2,840 / 8,338 | 55.45 / 52.88 / 90.67 / 101.07 s | 0.51 / 55.96 s |
| HotpotQA / Hybrid | 8.2 / 8.2 / 4,153 | 8.2 / 8.2 | 8.2 / 8.2 | 0.9 / 0.9 / 1.2 / 0.9 | 3.0（3.0） | 1,655 / 327 / 1,982 | 27.38 / 10.63 / 105.72 / 165.89 s | <0.01 / 27.38 s |
| 2Wiki / SlotRAG | 2.4 / 2.4 / 827 | 6.9 / 5.5 | 7.0 / 5.5 | 4.3 / 1.4 / 1.7 / 1.4 | 7.4（8.3） | 5,228 / 3,195 / 8,423 | 89.02 / 82.95 / 191.56 / 232.82 s | 0.21 / 89.23 s |
| 2Wiki / Hybrid | 9.9 / 9.8 / 2,906 | 9.8 / 9.8 | 9.9 / 9.9 | 1.0 / 1.0 / 1.0 / 1.0 | 3.0（3.0） | 1,549 / 327 / 1,876 | 10.91 / 9.88 / 15.49 / 15.95 s | <0.01 / 10.92 s |

SlotRAG 的阶段和机制指标进一步定位了成本来源：

| 数据集 | 编译/抽取/生成 calls | 编译/抽取/生成 tokens | 编译/执行/物化/生成延迟 | slots/joins/variables/outputs/operators/complexity | structured fail/repair | grounding/local repair/fallback | deterministic/evidence fallback | replan/selectivity error/regret |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HotpotQA | 1.9 / 1.8 / 0.1 | 4,532 / 3,669 / 137 | 30.71 / 23.40 / 23.40 / 1.34 s | 1.5 / 0.5 / 1.5 / 1.0 / 0 / 4.5 | 1.5 / 1.2 | 0.2 / 0.1 / 0.2 | 0.9 / 0.1 | 0.5 / 1.773 / 0.014 |
| 2Wiki | 1.8 / 1.7 / 0.4 | 4,107 / 3,837 / 479 | 30.47 / 27.94 / 27.94 / 6.30 s | 1.4 / 0.5 / 1.4 / 0.9 / 0 / 4.2 | 1.6 / 1.2 | 0 / 0 / 0.3 | 0.5 / 0.2 | 0.5 / 2.609 / 0 |

两组 SlotRAG 的 `typed_plan_templates`、`direct_plan_templates` 和 `answer_span_normalizations` 均为 0，故单文档路由隔离通过。运行时 cache hit/miss 均为 0、materialization reuse 为 0；HotpotQA/2Wiki 的平均最大中间绑定分别为 2.1/0.9。LLM/retrieval/step 预算利用率分别为 0.059/0.400/0.375 与 0.067/0.350/0.350；峰值 RSS 增量为 0.121/0.150 MB。索引 embedding calls 为 1.0/0.9，索引 cache hit/miss 为 9.2/9.2 与 12.3/7.9，命中率 0.500/0.605，索引大小为 80,040/85,697 bytes。阶段 token 覆盖率均为 1.0。上述所有原始字段还保存在 `runs/vldb2027-diagnostic-v6/summaries/diagnostic/metrics.csv`、`retrieval_metrics.csv`、`per_question.csv`、`stratified_metrics.csv` 和 `summary.json`，避免论文表格舍入导致信息丢失。

失败报告严格基于 62 个不可变 attempts：HotpotQA Hybrid `5ab6e42a554299710c8d1f9a` 首次为 `Agnes returned an empty answer twice`，重试为 embedding `ReadTimeout`；2Wiki SlotRAG `55b23a90084c11ebbd56ac1f6bf848b6` 首次为 5 槽计划超过 4 步预算，重试同样为 embedding `ReadTimeout`。因此重试后成功率没有提升，不能把 60/60 完成率误写成 100% 方法成功率。

配对 bootstrap（n=10）中，SlotRAG-Hybrid 的 F1 差分别为：DROP `+0.145`，95% CI `[0, 0.380]`，2 胜/8 平/0 负，`p=0.2094`、Holm `p=0.6282`；HotpotQA `+0.083`，CI `[-0.217, 0.383]`，2/7/1，`p=p_holm=0.7812`；2Wiki `-0.102`，CI `[-0.303, 0.002]`，1/7/2，`p=0.2244`、Holm `p=0.6282`。所有区间仍包含 0。HotpotQA 的均值还被 Hybrid 最终失败样本压低，不能解释为 SlotRAG 架构优势；2Wiki 则同时暴露质量、稳定性和约 8.2 倍在线延迟问题。因此 v6 只通过多文档路由隔离，不达到 Tune50 或 VLDB 论文结论门槛。

分层指标进一步说明当前优势与故障并不均匀：

| 数据集/分层（n） | 方法 | F1 | R@5 / NDCG@10 | 唯一文档 | LLM calls / tokens | 在线延迟 | 诊断 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 2Wiki bridge_comparison (2) | SlotRAG / Hybrid | 0.048 / 0.543 | 0.375/0.416 / 0.875/0.977 | 2.5 / 9.5 | 4.5/8,135 / 1.0/1,971 | 185.83 / 13.01 s | SlotRAG 含 F5 最终失败；另一题为正确 `No` 加解释，F1 0.095。 |
| 2Wiki comparison (3) | SlotRAG / Hybrid | 0.123 / 0.132 | 1.000/1.000 / 1.000/1.000 | 4.67 / 9.67 | 5.33/10,635 / 1.0/1,747 | 89.43 / 11.66 s | 三题双方均主要受极性答案冗长影响；证据已满召回。 |
| 2Wiki compositional (4) | SlotRAG / Hybrid | 1.000 / 1.000 | 1.000/1.000 / 1.000/0.908 | 7.25 / 10.0 | 3.5/5,883 / 1.0/1,512 | 39.61 / 9.07 s | 质量与证据均通过，但 SlotRAG 成本仍约 4 倍。 |
| 2Wiki inference (1) | SlotRAG / Hybrid | 1.000 / 1.000 | 1.000/1.000 / 0.500/0.798 | 7.0 / 10.0 | 4.0/12,527 / 1.0/3,532 | 91.82 / 11.88 s | 单题不作泛化结论；SlotRAG 证据更好但成本过高。 |
| HotpotQA bridge (7) | SlotRAG / Hybrid | 0.714 / 0.857 | 0.786/0.790 / 0.786/0.801 | 6.0 / 8.57 | 3.57/7,644 / 0.86/2,060 | 46.22 / 34.26 s | Hybrid 含 1 个最终失败，均值仍更高；SlotRAG 的访问节省未转化为质量。 |
| HotpotQA comparison (3) | SlotRAG / Hybrid | 1.000 / 0.391 | 1.000/1.000 / 1.000/1.000 | 5.67 / 7.33 | 4.33/9,958 / 1.0/1,799 | 76.99 / 11.31 s | SlotRAG 三题全对，但 n=3 且成本约 6.8 倍，暂不形成优势声明。 |

上述分层均来自现有 `stratified_metrics.csv`，未排除失败；样本最小仅 1--4 题，作用是确定调优方向而非支持统计结论。当前顺序固定为：先完成 schema v9 对 F5 的因果验证，再单独处理 F6 评测契约，最后才评估多跳成本优化。

F6 冻结重评分使用纯句法触发，不读取 gold：仅对以 `Do/Does/Did/Is/Are/Was/Were/Can/Could/Would/Will/Has/Have/Had` 起始的问题，且答案首 token 为 `yes/no/true/false` 时规范化。双方恰好各改变同 4 题，非极性答案改变 0 条；SlotRAG/Hybrid F1 变为 0.900/1.000。规范化后的配对差为 -0.100，0 胜/9 平/1 负，95% CI `[-0.300, 0]`，`p=0.7114`；唯一负例就是 F5 最终失败。因此协议修正不会制造 SlotRAG 优势，只会移除双方共同的格式惩罚。完整结果保存于 `runs/vldb2027-diagnostic-v7/frozen-polar-answer-replay.json`。

### schema v9 字段极值算子预注册（2026-07-21）

schema v9 只修复 F5 已观察到的“已抽取字段间比较被编译成语义槽”故障，不放宽步数、检索或 LLM 预算。候选架构增加 `field_argmin`/`field_argmax`：算子接收字段列表、与字段一一对应且来自问题常量的答案标签，并在字段值可同类型解析且极值唯一时返回对应标签。多个无等值连接的事实分支只有在同一类型算子显式引用它们时才允许受控组合；普通不连通计划仍拒绝。

```text
H13（冻结计划改写）：F5 的 5 槽计划改写为 4 槽 + field_argmin，输出字段为 ?answer，labels 精确为两个问题内电影名，operator_rewrites=1。
H14（确定性执行）：冻结证据日期 1924-06-25 与 1906-01-30 输出 Tear Gas Squad，operators_executed=1，计划不再触发 max_steps=4。
H15（边界与无回退）：只匹配 Compare/DateCompare、两个已物化变量、两个唯一可追溯且问题内落地的标签，以及明确的 born first/earlier/earliest 或 born later/latest 问法；缺标签、平局、混合类型和非极值比较保持原路径或返回空，不猜测答案。
```

离线实现已完成：`RelationalOperator` 增加字段内 `field_argmin`/`field_argmax`，`SlotPlan` 只把被同一字段极值算子引用的事实分支视为逻辑连通，执行器对这些分支执行受控组合；无算子的普通不连通计划仍被拒绝。测试覆盖编译改写、歧义负例、日期选择、平局、混合类型、`born later` 对称路径、增量 join、late join、普通断图和 runner schema，共 `74 passed, 1 skipped`；Python 编译、实验 YAML 和 `git diff --check` 均通过。

对 v6 attempt-0001 中保存的真实 5 槽 plan 做冻结重放，得到 4 个事实槽、输出 `?answer`、`normalize_S5: field_argmin(fields=[bd1,bd2], labels=[Find Me Guilty,Tear Gas Squad])`，`operator_rewrites=1`；输入冻结日期 `June 25, 1924` 与 `January 30, 1906` 后输出 `Tear Gas Squad`。因此 H13、H14 的离线部分通过；`operators_executed` 和预算状态仍需在线端到端记录确认。

同样对 v6 2Wiki 的全部 10 个 SlotRAG `attempt-0001` 计划做冻结范围审计：恰有 F5 目标题从 5 槽改写为 4 槽并触发一次 `field_argmin`，其余 9 题的槽数、算子和 `operator_rewrites=0` 均保持不变。结果保存在 `runs/vldb2027-diagnostic-v7/frozen-plan-replay.json`。H15 的同样本冻结触发范围通过，但在线编译器可能产生不同计划，仍需在 v7 逐题记录中复核。

离线门槛通过后，在新的源码指纹和运行目录上重跑相同 2Wiki diagnostic 10 题；必须同时报告目标题、总体 F1/证据、异常状态、算子触发范围及相对 Hybrid 的全部成本。若只是消除预算失败却继续显著劣于 Hybrid，仍不得进入 Tune50。

首次在线启动门槛检查于 `2026-07-21T20:06:05+08:00` 执行：Agnes 为 `HTTP 200`，但 embedding 与 reranker 均在 60 秒后 `ReadTimeout`。补齐 `field_argmax` 对称测试并冻结最终候选源码后，于 `2026-07-21T21:52:10+08:00` 再次执行相同探针；最终源码指纹 `be5b59803d2b84dbfd59c4b8fa6ff74efb3c53a4d0bf4a85d5e8c26185e5068d` 下结果仍为 Agnes `HTTP 200`、embedding/reranker `ReadTimeout`。两次检查分别保存在无密钥的 `service-doctor.json` 与 `service-doctor-history.json`，后者保留完整时间序列；没有创建 manifest、样本或逐题结果，也没有产生 v7 在线 attempt。

截至第二次检查，`runs/vldb2027-diagnostic-v7/` 仅有离线与服务探针文件；这段基础设施阻塞不作为方法失败或重试样本计入统计。服务于 `2026-07-22T10:31:29+08:00` 恢复，三项探针均为 `HTTP 200`，恢复记录已追加到 `service-doctor-history.json`；随后才在同一冻结指纹下创建 manifest 并启动 v7。

### schema v9 在线同样本复验（v7，2026-07-22）

v7 manifest 源码指纹为 `be5b59803d2b84dbfd59c4b8fa6ff74efb3c53a4d0bf4a85d5e8c26185e5068d`，数据审计 SHA-256 为 `a24ad382ed92fe32949d050c282a366eaf6a16085ad8df27dfc9f12b7c00c67e`，2Wiki 样本 SHA-256 为 `5bcc2298686f2c3d1e0e570bcfa6197454f32660009d6cf3e9599dae63f1c1a4`，均与预注册值一致。20/20 个最终记录、20 个不可变 attempts、0 重试、0 failed/empty/unsupported，全部为 schema v9；流程完成率为 1.0，但答案质量仍单独计分。

| v7 2Wiki diagnostic（10 题/方法） | SlotRAG | Hybrid |
| --- | ---: | ---: |
| EM / F1 | 0.600 / 0.636 | 0.600 / 0.652 |
| Evidence Recall@1 / @5 / @10 | 0.450 / 0.900 / 0.950 | 0.450 / 0.925 / 1.000 |
| Evidence Precision@1 / @5 / @10 | 1.000 / 0.420 / 0.220 | 1.000 / 0.440 / 0.240 |
| Evidence Hit@1 / @5 / @10 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 |
| Evidence MRR / NDCG@10 | 1.000 / 0.950 | 1.000 / 0.938 |
| 检索证据数 / 文档数 / 文本字符 | 3.4 / 2.9 / 2,054 | 9.9 / 9.8 / 2,906 |
| 累计文档 / 唯一文档 / 累计 passage / 唯一 passage | 7.3 / 5.8 / 7.5 / 5.9 | 9.8 / 9.8 / 9.9 / 9.9 |
| LLM / retrieval / embedding / reranker calls | 4.7 / 1.5 / 1.5 / 1.5 | 1.1 / 1.0 / 1.0 / 1.0 |
| Total tokens / provider calls / 含索引 calls | 10,736 / 7.7 / 8.7 | 1,841 / 3.1 / 3.1 |
| 在线延迟 mean / P50 / P95 / P99 | 94.35 / 79.40 / 185.31 / 187.14 s | 22.38 / 15.72 / 55.13 / 68.62 s |
| 编译 / 执行 / 物化 / 生成延迟 | 46.77 / 40.57 / 40.57 / 7.00 s | 0 / 0 / 0 / 21.51 s |
| 结构失败 / 修复 / plan fallback / evidence fallback | 2.2 / 1.5 / 0.5 / 0.3 | 0 / 0 / 0 / 0 |
| 确定性答案 / operator rewrite / operator executed | 0.6 / 0 / 0 | 0 / 0 / 0 |
| slots / joins / variables / outputs / operators / complexity | 1.5 / 0.5 / 1.5 / 1.0 / 0 / 4.5 | 0 / 0 / 0 / 0 / 0 / 0 |
| steps / LLM预算 / 检索预算 / step预算 | 1.5 / 0.073 / 0.375 / 0.375 | 0 / 0.017 / 0.250 / 0 |
| 峰值 RSS 增量 / 最大中间绑定 / reoptimization | 0.502 MB / 1.1 / 0.5 | 0 / 0 / 0 |
| 平均 selectivity error / planner regret | 1.189 / 0 | N/A / N/A |
| 索引构建延迟 / embedding calls / cache hit rate | 0.359 s / 1.0 / 0.555 | 0.001 s / 0 / 1.000 |
| 索引大小 / phase token coverage | 85,697 bytes / 1.0 | 85,697 bytes / 1.0 |

Hybrid 在方法顺序中复用 SlotRAG 已建立的 passage embedding cache，因此索引构建差异不解释为方法优势；主表在线延迟不含索引构建，`total_latency_with_index` 分别为 94.70/22.38 s。SlotRAG 相对 Hybrid 减少 40.8% 唯一文档和 29.3% 证据文本字符，但 LLM calls、tokens 和在线延迟分别为 4.27、5.83 和 4.22 倍，同时 Evidence Recall@5/@10 更低。

配对 bootstrap 的 SlotRAG-Hybrid F1 差为 `-0.0164`，2 胜/7 平/1 负，Cliff's delta `-0.06`，95% CI `[-0.2982, 0.2455]`，`p=p_holm=0.9276`。分层结果如下；每层只有 1--4 题，仅用于定位故障：

| 分层（n） | SlotRAG / Hybrid F1 | R@5 | NDCG@10 | 唯一文档 | LLM calls / tokens | 在线延迟 | 诊断 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| bridge_comparison (2) | 0.053 / 0.543 | 0.750 / 0.875 | 0.832 / 0.977 | 4.5 / 9.5 | 6.0/17,957 / 1.5/1,971 | 120.66 / 40.31 s | 两题均 fallback；F5 是唯一配对负例。 |
| comparison (3) | 0.417 / 0.144 | 1.000 / 1.000 | 1.000 / 1.000 | 4.67 / 9.67 | 5.33/10,584 / 1.0/1,747 | 108.53 / 21.99 s | SlotRAG 一题返回 canonical `No`，形成两项配对胜例之一；另两题仍受格式惩罚。 |
| compositional (4) | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 0.908 | 7.25 / 10.0 | 3.25/5,694 / 1.0/1,506 | 48.50 / 16.70 s | 质量持平、证据排序略高，但成本仍约 2.9 倍。 |
| inference (1) | 1.000 / 1.000 | 0.500 / 0.500 | 0.832 / 0.798 | 6.0 / 10.0 | 6.0/16,916 / 1.0/3,206 | 182.52 / 10.38 s | 单题持平，无法支持泛化结论。 |

F5 在线 attempt-0001 的三轮候选依次因断图、旧式 `argmin`/`<` 和双重 JSON 结构校验失败，最终回退到 1 槽；输出“证据不足”，EM/F1=0，`operator_rewrites=operators_executed=0`。因此 H13/H14 只在冻结计划成立，在线端到端不通过；H15 的“同样本仅目标题触发”也未成立，因为 10 题全部 0 次触发。v7 证明算子本身与事后改写正确，但编译入口仍是瓶颈，不能把 0 流程失败误写为 F5 修复成功。

v7 的无 gold 极性冻结重评分仍只改变双方相同 4 题：SlotRAG/Hybrid F1 变为 0.900/1.000，0 胜/9 平/1 负，差值 `-0.100`，95% CI `[-0.300, 0]`，`p=0.7114`；唯一负例为 F5。结果保存在 `polar-answer-replay-v7.json`。全部原始指标见 `runs/vldb2027-diagnostic-v7/summaries/diagnostic/{metrics,retrieval_metrics,per_question,stratified_metrics,paired_bootstrap}.csv` 与 `summary.json`。v7 不进入 Tune50：下一步先独立实现 F6 统一出口协议，再预注册 F7/F5 编译入口修复。

### schema v10 统一极性答案协议预注册（2026-07-22）

schema v10 只修改所有方法共享的 `run_method` 出口，不改变检索、计划、执行、证据或提供方调用。触发条件不读取 gold：问题去除尾部空白后必须以 `?` 结束，首词必须是 `Do/Does/Did/Is/Are/Was/Were/Can/Could/Would/Will/Has/Have/Had` 之一，成功结果的答案首 token 必须是 `yes/no/true/false`；随后统一映射为小写 `yes/no`。已经是小写 canonical 答案时保持不变且不重复计数，祈使句、WH 问句、非首 token 和异常状态不改。新增 `polar_answer_normalizations`，schema v9 及以前报告 N/A。

```text
H16（触发精度）：冻结 v7 只改变双方相同 4 个极性题，非极性题改变 0；问题或答案边界不满足时不触发。
H17（方法对称与不变性）：规范化位于共享出口，对 SlotRAG、Hybrid 和其他基线采用同一规则；rows、EvidenceRecord、状态、检索指标、provider calls/tokens/latency 全部不变。
H18（可审计与幂等）：每个实际改变的结果计数 1，已经 canonical 的结果计数 0；schema 10 汇总报告该字段，schema 9 不回填 0。
```

离线实现已完成。聚焦测试先后观察到 verbose `No` 未压缩、祈使句误触发、旧 schema 不报告新字段和 canonical `no` 重复计数四个 RED，再分别修至 GREEN；全仓为 `78 passed, 1 skipped`，Python 编译、pilot YAML 和 `git diff --check` 均通过。候选源码指纹为 `df8bf7e53fd84c317eca08934b2caa3374d0251bfa56d57f0eff91c8a63a5fb5`。

冻结 v7 原始结果调用实际 schema v10 出口后，SlotRAG/Hybrid 都恰好改变相同 4 个 question IDs，F1 精确为 0.900/1.000，非极性题改变 0；因此 H16-H18 的离线部分通过。验证记录保存在 `runs/vldb2027-diagnostic-v8/offline-validation.json`。在线复验使用独立 v8 目录、相同 2Wiki 样本、预算与两方法；三项 service doctor 全部通过且 manifest 指纹匹配后才启动。在线仅验证协议触发和运行时不变性，不将提供方随机波动误归因于规范化，也不混入 F7 编译入口修改。

#### schema v10 在线结果（v8）

三项服务于 `2026-07-22T11:05:59+08:00` 全部返回 `HTTP 200` 后才创建 manifest。manifest 指纹、审计 SHA-256 和样本 SHA-256 均与预注册值一致；20/20 条记录和 20 attempts 全部为 schema 10，0 重试、0 failed/empty/unsupported。

| v8 2Wiki diagnostic（10 题/方法） | SlotRAG | Hybrid |
| --- | ---: | ---: |
| EM / F1 | 0.900 / 0.900 | 1.000 / 1.000 |
| Polar normalization | 0.4（4/10） | 0.4（4/10） |
| Evidence Recall@1 / @5 / @10 | 0.450 / 0.875 / 0.925 | 0.450 / 0.925 / 1.000 |
| Evidence Precision@1 / @5 / @10 | 1.000 / 0.400 / 0.210 | 1.000 / 0.440 / 0.240 |
| Evidence Hit@1 / @5 / @10 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 |
| Evidence MRR / NDCG@10 | 1.000 / 0.930 | 1.000 / 0.938 |
| 检索证据数 / 文档数 / 文本字符 | 3.1 / 2.7 / 1,739 | 9.9 / 9.8 / 2,906 |
| 累计文档 / 唯一文档 / 累计 passage / 唯一 passage | 7.3 / 5.8 / 7.5 / 5.9 | 9.8 / 9.8 / 9.9 / 9.9 |
| LLM / retrieval / embedding / reranker calls | 4.6 / 1.5 / 1.5 / 1.5 | 1.1 / 1.0 / 1.0 / 1.0 |
| Total tokens / provider calls / 含索引 calls | 10,197 / 7.6 / 8.6 | 1,961 / 3.1 / 3.1 |
| 在线延迟 mean / P50 / P95 / P99 | 110.96 / 93.62 / 218.09 / 259.99 s | 19.82 / 17.06 / 35.33 / 41.40 s |
| 编译 / 执行 / 物化 / 生成延迟 | 62.23 / 40.52 / 40.52 / 8.21 s | 0 / 0 / 0 / 18.92 s |
| 结构失败 / 修复 / local repair / plan fallback | 2.2 / 1.5 / 0.1 / 0.5 | 0 / 0 / 0 / 0 |
| evidence fallback / deterministic / operator rewrite / executed | 0.2 / 0.7 / 0 / 0 | 0 / 0 / 0 / 0 |
| slots / joins / variables / outputs / operators / complexity | 1.5 / 0.5 / 1.5 / 1.0 / 0 / 4.5 | 0 / 0 / 0 / 0 / 0 / 0 |
| steps / LLM预算 / 检索预算 / step预算 | 1.5 / 0.072 / 0.375 / 0.375 | 0 / 0.017 / 0.250 / 0 |
| 峰值 RSS 增量 / 最大中间绑定 / reoptimization | 0.461 MB / 1.3 / 0.5 | 0 / 0 / 0 |
| 平均 selectivity error / planner regret | 2.060 / 0 | N/A / N/A |
| 索引构建延迟 / embedding calls / cache hit rate | 0.410 s / 1.0 / 0.555 | 0.001 s / 0 / 1.000 |
| 索引大小 / phase token coverage | 85,697 bytes / 1.0 | 85,697 bytes / 1.0 |

双方触发的 question IDs 精确相同：`49b5...`、`904a...`、`d6a...`、`fce9...`；每条 `polar_answer_normalizations=1`，其余 12 个方法-题记录为 0，没有计数大于 1。H16-H18 的在线部分通过，完整判定保存在 `runs/vldb2027-diagnostic-v8/online-validation.json`。这项协议修复消除了格式假负例，但没有制造 SlotRAG 优势。

配对 bootstrap 中 SlotRAG-Hybrid F1 差为 `-0.100`，0 胜/9 平/1 负，Cliff's delta `-0.10`，95% CI `[-0.300, 0]`，`p=p_holm=0.7008`。`comparison`、`compositional` 和 `inference` 分层双方 F1 均为 1.0；`bridge_comparison` 为 0.5/1.0，唯一差异仍是 F5。F5 本轮产生 5 次结构失败和 3 次修复，最终单槽 fallback；8 次 LLM 调用、23,241 tokens、270.46 s，`operator_rewrites=operators_executed=0`，EM/F1=0。故 schema v10 通过自身协议门槛，但 v8 仍不进入 Tune50；后续 F7 必须独立修复类型化编译入口及其长尾成本。全部原始指标保存在 v8 `summaries/diagnostic/` 的 CSV、REPORT 和 `summary.json`。

### schema v11 字段极值类型化入口预注册（2026-07-22）

v7/v8 连续证明 schema v9 的事后改写无法覆盖 LLM 输出在 `SlotPlan` 入口前就失败的情形。schema v11 因此把已经冻结验证的字段极值查询类前移到编译器确定性入口，优先级为“月份差类型模板 → 字段极值类型模板 → 单文档/原 LLM 编译路径”。本轮不加入通用断图猜测、缺工具调用恢复或任意 comparator 修补，避免把多类机制混成一次实验。

白名单语法完整锚定为 `Which film/movie has the director who was born {first|earlier|earliest|later|latest}, A or B?`，忽略大小写和边界空白。只允许两个非空、规范化后不同、内部不再含候选分隔词的显式标签；标签直接来自问题，不读取数据集类型、gold answer 或 gold evidence。入口生成两个 `DirectorOf`、两个 `BirthDate` 事实槽，两条实体 join，以及一个 `field_argmin` 或 `field_argmax`，输出 `?answer`；计划仍受 `max_steps=4`、字段类型一致、唯一极值和平局拒绝约束。新增 `field_extremum_templates`，并增加只关闭该入口的 `slotrag-no-extremum-template` 消融；后者仍保留原 LLM 编译及安全事后改写。

```text
H19（入口确定性）：F5 不调用编译 LLM，生成 4 slots/2 joins/1 field_argmin，labels 精确为 Find Me Guilty/Tear Gas Squad；typed_plan_templates=field_extremum_templates=1，operator_rewrites=0。
H20（对称与边界）：later/latest 生成 field_argmax；同名候选、三个候选、非电影关系、非完整锚定语法均不触发并走原路径。
H21（端到端执行）：F5 在 4 步预算内执行一次算子，输出 Tear Gas Squad，EM/F1=1，plan_fallbacks=0；不得通过放宽预算或读取 gold 达成。
H22（同样本范围与成本）：2Wiki 10 题中只 F5 的 field_extremum_templates=1，其余 9 题为 0；相对 v8 的 F5 编译 calls/tokens/延迟和总成本下降，并完整报告证据指标与异常状态。
```

离线实现已完成。新增编译入口、独立 `slotrag-no-extremum-template` 消融开关、schema 11 统计门控及端到端四步执行测试；旧的 LLM 计划后校验用例显式关闭新入口，继续独立覆盖 schema v9 路径。聚焦测试为 `64 passed`，全仓为 `90 passed, 1 skipped`；Python 编译、pilot YAML/消融注册和 `git diff --check` 均通过。冻结源码/配置/测试指纹为 `3b5f4572c2dc15b90003590fbf9a77be02acbee05cca44f67cccf312b7f07b84`。

冻结范围审计复用 v8 的 2Wiki 10 题快照，审计 SHA-256 仍为 `a24ad382ed92fe32949d050c282a366eaf6a16085ad8df27dfc9f12b7c00c67e`，样本 SHA-256 仍为 `5bcc2298686f2c3d1e0e570bcfa6197454f32660009d6cf3e9599dae63f1c1a4`。静态入口扫描只命中 F5 `55b23a90084c11ebbd56ac1f6bf848b6`，其余 9 题不命中；目标计划为 4 slots/2 joins/1 `field_argmin`，编译 LLM calls=0。基于冻结事实绑定的执行顺序为 `S1→S2→S3→S4`，4 次检索、1 次算子执行，输出 `Tear Gas Squad`。重复候选、三个候选、非电影关系和缺少完整问号边界均拒绝，`latest` 映射为 `field_argmax`。因此 H19、H20 与 H21 的冻结执行部分通过，H22 仅范围部分通过、在线成本部分待测；机器可读记录为 `runs/vldb2027-diagnostic-v9/offline-validation.json`。

在线因果验证继续使用相同 2Wiki 样本；只有离线测试、冻结执行和负例范围全部通过后才创建新 manifest。若在线 F5 因检索/抽取未获得两个可解析日期而失败，必须保留空结果或证据 fallback，不允许类型算子猜测标签。

#### schema v11 在线结果（v9）

三项服务于 `2026-07-22T11:48:52+08:00` 均返回 `HTTP 200` 后创建 manifest；源码指纹、审计 SHA-256 与样本 SHA-256 均与预注册值一致。首次运行最先两条 SlotRAG 成功，随后 Agnes 在 `11:57:04--12:01:59+08:00` 之间发生连接中断：SlotRAG 8 条、Hybrid 10 条共 18 个 `attempt-0001` 以同一 `provider_connect/ConnectError` 失败。失败 attempts 未删除；`12:22:52+08:00` 三项 doctor 再次通过后，在同一目录续跑并为这 18 条追加成功的 `attempt-0002`。最终为 20/20 条 schema 11 `ok` 记录、38 个不可变 attempts、18 个 benchmark retries、0 个最终 failed/empty/unsupported；故障时间线保存在 `service-doctor-history.json`，汇总失败率仍以 attempts 为分母。

| v9 2Wiki diagnostic（10 题/方法） | SlotRAG | Hybrid |
| --- | ---: | ---: |
| EM / F1 | 1.000 / 1.000 | 1.000 / 1.000 |
| Evidence Recall / MRR | 0.975 / 1.000 | 1.000 / 1.000 |
| Evidence Recall@1 / @5 / @10 | 0.450 / 0.975 / 0.975 | 0.450 / 0.925 / 1.000 |
| Evidence Precision@1 / @5 / @10 | 1.000 / 0.460 / 0.230 | 1.000 / 0.440 / 0.240 |
| Evidence Hit@1 / @5 / @10 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 |
| Evidence NDCG@10 | 0.983 | 0.938 |
| 检索证据数 / 文档数 / 文本字符 | 2.5 / 2.5 / 1,099 | 9.9 / 9.8 / 2,906 |
| 累计文档 / 唯一文档 / 累计 passage / 唯一 passage | 8.7 / 6.0 / 9.0 / 6.1 | 9.8 / 9.8 / 9.9 / 9.9 |
| LLM / retrieval / embedding / reranker calls | 4.3 / 1.8 / 1.8 / 1.8 | 1.0 / 1.0 / 1.0 / 1.0 |
| Prompt / completion / total tokens | 5,886 / 2,793 / 8,679 | 1,549 / 319 / 1,868 |
| 编译 / 抽取 / 生成 LLM calls | 2.0 / 1.9 / 0.2 | 0 / 0 / 1.0 |
| 编译 prompt/completion tokens | 3,148 / 1,380 | 0 / 0 |
| 抽取 prompt/completion tokens | 2,596 / 1,236 | 0 / 0 |
| 生成 prompt/completion tokens | 141 / 177 | 1,549 / 319 |
| Provider calls / 含索引 provider calls | 7.9 / 8.1 | 3.0 / 3.0 |
| 在线延迟 mean / P50 / P95 / P99 | 69.90 / 47.02 / 160.02 / 175.65 s | 10.91 / 10.14 / 14.80 / 15.76 s |
| Provider latency / 含索引总延迟 | 69.83 / 69.93 s | 10.90 / 10.91 s |
| 编译 / 执行 / 物化 / 生成延迟 | 34.78 / 31.84 / 31.83 / 3.29 s | 0 / 0 / 0 / 10.45 s |
| 内部 provider retry / benchmark 失败 attempts | 0.2 / 8 | 0 / 10 |
| 结构失败 / 修复 / grounding / local repair | 1.8 / 1.3 / 0 / 0.1 | 0 / 0 / 0 / 0 |
| plan fallback / evidence fallback / deterministic | 0.4 / 0.1 / 0.8 | 0 / 0 / 0 |
| operator rewrite / executed | 0 / 0.1 | 0 / 0 |
| heuristic / typed / field-extremum / direct templates | 0.1 / 0.1 / 0.1 / 0 | 0 / 0 / 0 / 0 |
| polar / span normalization / reconciliation | 0.4 / 0 / 0 | 0.4 / 0 / 0 |
| join input / output rows | 1.6 / 0.8 | 0 / 0 |
| slots / joins / variables / outputs / operators / complexity | 1.8 / 0.7 / 1.8 / 1.0 / 0.1 / 5.4 | 0 / 0 / 0 / 0 / 0 / 0 |
| steps / LLM预算 / 检索预算 / step预算 | 1.8 / 0.067 / 0.450 / 0.450 | 0 / 0.016 / 0.250 / 0 |
| 峰值 RSS 增量 / 最大中间绑定 / reoptimization | 1.750 MB / 1.2 / 0.8 | 0 / 0 / 0 |
| 平均 selectivity error / planner regret | 1.956 / 0 | N/A / N/A |
| 物化请求 / 物化 cache hit / reuse rate | 1.8 / 0 / 0 | 0 / 0 / N/A |
| 运行时 cache hit/miss / binding prune / early stop | 0/0 / 0 / 0 | 0/0 / 0 / 0 |
| 索引构建 / provider 延迟 / embedding calls | 31.97 / 25.95 ms / 0.2 | 1.40 / 0 ms / 0 |
| 索引 cache hit/miss/rate | 18.4 / 1.8 / 0.910 | 20.2 / 0 / 1.000 |
| 索引大小 / phase token coverage | 85,697 bytes / 1.0 | 85,697 bytes / 1.0 |

`accuracy` 与 DROP 专用 EM/F1 在 2Wiki 上均为 N/A。分层结果没有隐藏失败：`bridge_comparison`（2 题）双方 F1=1，SlotRAG/Hybrid Evidence Recall=0.875/1.000、wall=88.98/13.27 s；`comparison`（3 题）双方 F1=1、Evidence Recall=1、wall=56.58/9.44 s；`compositional`（4 题）双方 F1=1、Evidence Recall=1、wall=76.00/10.33 s；`inference`（1 题）双方 F1=1、Evidence Recall=1、wall=47.29/12.91 s。配对 bootstrap 为 0 胜/10 平/0 负，均值与中位差均为 0，Cliff's delta=0，95% CI `[0,0]`，`p=p_holm=1.0`。

| F5 同题因果比较 | v8 schema 10 | v9 schema 11 |
| --- | ---: | ---: |
| EM / F1 | 0 / 0 | 1 / 1 |
| Evidence Recall / NDCG@10 | 0.750 / 0.832 | 1.000 / 1.000 |
| 编译 LLM calls / tokens / latency | 3 / 9,068 / 166.98 s | 0 / 0 / 0.00062 s |
| 总 LLM calls / tokens | 8 / 23,241 | 4 / 7,413 |
| retrieval / embedding / reranker calls | 1 / 1 / 1 | 4 / 4 / 4 |
| 总 provider calls | 10 | 12 |
| wall latency | 270.46 s | 41.82 s |
| 结构失败 / fallback / executed operator | 5 / 1 / 0 | 0 / 0 / 1 |
| steps / slots / joins / operators | 1 / 1 / 0 / 0 | 4 / 4 / 2 / 1 |
| 累计/唯一文档，累计/唯一 passage | 4/4，5/5 | 18/8，20/9 |

F5 的答案变为 `Tear Gas Squad`；`field_extremum_templates=typed_plan_templates=heuristic_plans=1`、`operator_rewrites=0`，同样本其余 9 条 SlotRAG 和全部 Hybrid 均为 0。相对 v8，F5 总 LLM calls 减少 50%，总 tokens 减少 68.1%，wall latency 减少 84.5%（6.47 倍加速），同时 retrieval/embedding/reranker calls 各增加 300%、总 provider calls 增加 20%。因此 H19、H20、H21 在线通过；H22 的触发范围、编译成本、总 token 和延迟部分通过，但 provider 调用成本维度未通过，只能判为部分通过。未配置提供方价格，不能宣称货币成本下降。

v9 修复了 F5 并消除 10 题答案差距，但 SlotRAG 全样本平均仍比 Hybrid 使用 4.65 倍 tokens、2.63 倍 provider calls 和 6.41 倍 wall time；当前证据量更小、NDCG 更高，但尚不满足“质量持平时成本下降”的内部 Go 门槛。因此 v9 不直接进入 Tune50，下一轮必须独立预注册编译/抽取调用削减，而不能把本轮单题修复外推为整体效率优势。完整指标、分层、逐题、bootstrap 与 attempts 失败分母见 `runs/vldb2027-diagnostic-v9/summaries/diagnostic/`，在线判定见 `online-validation.json`。

### schema v12 极性比较拓扑路由预注册（2026-07-22）

v9 的 4 个极性比较题均先经历三轮 LLM 编译失败，再回退为同一个 `EvidenceAnsweringQuestion(?answer)` 单槽计划；四题合计浪费 12 次编译调用、28,508 个编译 tokens、180.86 s 编译延迟，产生 14 次结构失败和 4 次 plan fallback。最终答案均为 `no` 且 F1=1，说明答案路径不需要改变，瓶颈是数据集级 `answer_kind=short` 未识别封闭比较问句的拓扑。

schema v12 增加无 gold 的极性比较路由：仅在 `answer_kind=short` 时，问题必须以白名单助动词 `Do/Does/Did/Is/Are/Was/Were/Has/Have/Had/Can/Could/Would/Will` 开头、以 `?` 完整结束、含独立词 `same` 或 `both`，且不含 WH 词；`Can/Could/Would/Will you ...` 请求式问句显式排除。触发后生成与 v9 fallback 完全相同的单槽计划和 `estimated_cardinality=5`，不读取答案、证据、数据集 stratum 或实体；检索、抽取、共享极性规范化及最终判分均不改变。优先级为“月份差 → 字段极值 → 极性比较 → 显式 boolean/单文档/LLM 编译”。新增 `polar_comparison_templates` 和只关闭该入口的 `slotrag-no-polar-template`，schema 11 及以前报告 N/A。

冻结 v9 反事实直接复用四题的同构 fallback 计划，仅去除其编译阶段：全 10 题 SlotRAG 平均 LLM calls 从 4.3 降至 3.1、tokens 从 8,679 降至 5,828、wall 下界估计从 69.90 降至 51.81 s、provider calls 从 7.9 降至 6.7；该估计不重写答案、rows 或 EvidenceRecord，也不当作在线观测值。

```text
H23（计划同一性）：4 个冻结极性比较题均零编译 LLM 调用，polar_comparison_templates=heuristic_plans=1；生成计划与各自 v9 fallback 计划完全相同，plan_fallbacks=structured_output_failures=0。
H24（触发边界）：同样本恰好命中上述 4 题；Can you name both...、嵌套 WH、WH 首问、无 same/both 线索和缺少问号均不触发；StrategyQA 的显式 boolean 路由不改。
H25（质量与路径）：同样本最终 20 条仍全部 ok，SlotRAG/Hybrid EM=F1=1；四题检索/抽取/规范化路径除随机提供方输出外与 v9 同构，不以 gold 或基线结果选择路由。
H26（成本）：四题 compilation calls/tokens 均为 0；SlotRAG 聚合 compilation calls≤0.8、structured failures≤0.4、plan fallbacks=0，LLM calls≤3.3、tokens≤6,500。延迟完整报告但不设跨时段硬阈值。
```

只有 H23/H24 的离线计划同一性和边界测试全部通过后才启动独立 v10 目录。若任一极性题的候选计划与 v9 fallback 不同，或非目标题触发，必须停止在线实验而不是扩大正则范围。

离线实现与门槛检查已完成。开发过程先观察正例继续调用编译 LLM 的 RED，再实现最小路由；方法消融、schema 12 统计与 runner 版本也分别经过 RED/GREEN。相关测试为 `74 passed`，全仓为 `100 passed, 1 skipped`；Python 编译、三阶段消融配置、YAML 校验和 `git diff --check` 均通过。冻结源码/配置/测试指纹为 `0acf3536f92a9fa242930b3735b16c7d96388bd268ac8a2dfdd3efb7c6d6e2e4`。

对冻结 v9 样本和实际最终计划执行同一性审计后，候选入口恰好命中预注册的 4 个 question IDs，4 个候选计划都与对应 v9 fallback `SlotPlan` 完全相同，其余 6 题触发 0。请求式 modal-you、嵌套 WH、WH 首问、缺少 same/both 和缺少问号五类边界均拒绝，显式 boolean 路由保持原 `estimated_cardinality=2` 且新计数为 0。H23/H24 离线通过，H25/H26 待在线验证；机器记录为 `runs/vldb2027-diagnostic-v10/offline-validation.json`。

#### schema v12 在线结果（v10）

`2026-07-22T12:47:09+08:00` 三项 service doctor 全部为 `HTTP 200` 后创建 v10 manifest；源码指纹、数据审计和样本哈希均与预注册值一致。运行一次完成 20/20 条 schema 12 记录，20 attempts、0 benchmark retry、0 final failed/empty/unsupported，证据金标覆盖 20/20。

| v10 2Wiki diagnostic（10 题/方法） | SlotRAG | Hybrid |
| --- | ---: | ---: |
| EM / F1 | 1.000 / 1.000 | 1.000 / 1.000 |
| Evidence Recall / MRR | 0.975 / 1.000 | 1.000 / 1.000 |
| Evidence Recall@1 / @5 / @10 | 0.450 / 0.925 / 0.975 | 0.450 / 0.925 / 1.000 |
| Evidence Precision@1 / @5 / @10 | 1.000 / 0.440 / 0.230 | 1.000 / 0.440 / 0.240 |
| Evidence Hit@1 / @5 / @10 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 |
| Evidence NDCG@10 | 0.966 | 0.938 |
| 检索证据数 / 文档数 / 文本字符 | 3.1 / 2.7 / 2,010 | 9.9 / 9.8 / 2,906 |
| 累计文档 / 唯一文档 / 累计 passage / 唯一 passage | 8.7 / 6.1 / 9.0 / 6.2 | 9.8 / 9.8 / 9.9 / 9.9 |
| LLM / retrieval / embedding / reranker calls | 2.9 / 1.8 / 1.8 / 1.8 | 1.0 / 1.0 / 1.0 / 1.0 |
| Prompt / completion / total tokens | 4,052 / 1,740 / 5,792 | 1,549 / 341 / 1,891 |
| 编译 / 抽取 / 生成 LLM calls | 0.6 / 1.9 / 0.4 | 0 / 0 / 1.0 |
| 编译 prompt/completion tokens | 845 / 241 | 0 / 0 |
| 抽取 prompt/completion tokens | 2,680 / 1,296 | 0 / 0 |
| 生成 prompt/completion tokens | 527 / 203 | 1,549 / 341 |
| Provider calls / 含索引 provider calls | 6.5 / 7.5 | 3.0 / 3.0 |
| 在线延迟 mean / P50 / P95 / P99 | 40.53 / 40.33 / 58.34 / 63.68 s | 9.77 / 9.54 / 12.02 / 12.19 s |
| Provider latency / 含索引总延迟 | 40.52 / 40.90 s | 9.77 / 9.78 s |
| 编译 / 执行 / 物化 / 生成延迟 | 6.62 / 29.92 / 29.92 / 3.98 s | 0 / 0 / 0 / 9.08 s |
| 内部 provider retry / benchmark retry attempts | 0 / 0 | 0 / 0 |
| 结构失败 / 修复 / grounding / local repair | 0.3 / 0.2 / 0 / 0 | 0 / 0 / 0 / 0 |
| plan fallback / evidence fallback / deterministic | 0 / 0.1 / 0.6 | 0 / 0 / 0 |
| operator rewrite / executed | 0 / 0.1 | 0 / 0 |
| heuristic / typed / field / polar / direct templates | 0.5 / 0.1 / 0.1 / 0.4 / 0 | 0 / 0 / 0 / 0 / 0 |
| polar / span normalization / reconciliation | 0.4 / 0 / 0 | 0.4 / 0 / 0 |
| join input / output rows | 1.4 / 0.7 | 0 / 0 |
| slots / joins / variables / outputs / operators / complexity | 1.8 / 0.7 / 1.8 / 1.0 / 0.1 / 5.4 | 0 / 0 / 0 / 0 / 0 / 0 |
| steps / LLM预算 / 检索预算 / step预算 | 1.8 / 0.045 / 0.450 / 0.450 | 0 / 0.016 / 0.250 / 0 |
| 峰值 RSS 增量 / 最大中间绑定 / reoptimization | 0.186 MB / 1.5 / 0.8 | 0 / 0 / 0 |
| 平均 selectivity error / planner regret | 1.264 / 0 | N/A / N/A |
| 物化请求 / cache hit / reuse rate | 1.8 / 0 / 0 | 0 / 0 / N/A |
| 运行时 cache hit/miss / binding prune / early stop | 0/0 / 0 / 0 | 0/0 / 0 / 0 |
| 索引构建 / provider 延迟 / embedding calls | 372.96 / 262.57 ms / 1.0 | 1.27 / 0 ms / 0 |
| 索引 cache hit/miss/rate | 11.2 / 9.0 / 0.555 | 20.2 / 0 / 1.000 |
| 索引大小 / phase token coverage | 85,697 bytes / 1.0 | 85,697 bytes / 1.0 |

`accuracy` 与 DROP 专用指标在本数据集为 N/A。v10 使用独立冷 embedding cache 且方法顺序为 SlotRAG 后 Hybrid，因此共享索引 embedding calls 被记在 SlotRAG，Hybrid 复用热 cache；主 `wall_latency` 按既定协议排除共享索引，`with-index` 指标完整保留但具有顺序依赖，不能作为方法优势或劣势的因果证据。

分层 F1 均为 1：`bridge_comparison`（2 题）SlotRAG/Hybrid Evidence Recall=0.875/1.000、tokens=5,265/2,033、wall=33.45/10.53 s；`comparison`（3 题）Evidence Recall=1/1、tokens=3,008/1,790、wall=37.47/8.71 s，三题均触发极性路由；`compositional`（4 题）Evidence Recall=1/1、tokens=5,490/1,550、wall=40.24/10.31 s；`inference`（1 题）Evidence Recall=1/1、tokens=16,405/3,273、wall=65.01/9.33 s。配对 bootstrap 仍为 0 胜/10 平/0 负、均值/中位差 0、Cliff's delta=0、95% CI `[0,0]`、`p=p_holm=1.0`。

| 4 个极性比较题合计 | v9 schema 11 | v10 schema 12 |
| --- | ---: | ---: |
| 每题答案 / F1 / Evidence 指标 | 全部不变 | 全部不变 |
| 编译 LLM calls / tokens | 12 / 28,508 | 0 / 0 |
| 总 LLM calls / tokens | 20 / 43,573 | 7 / 11,664 |
| wall latency | 305.89 s | 134.36 s |
| 结构失败 / plan fallback | 14 / 4 | 0 / 0 |
| polar comparison template | 0 | 4 |

四个触发 ID 与预注册集合完全相同，非目标题触发 0，`polar_answer_normalizations=1` 仍逐题成立；F5 独立保持 `field_extremum_templates=1`、F1=1，两种路由没有混淆。相对 v9 全样本，SlotRAG 平均 LLM calls 减少 32.6%、tokens 减少 33.3%、provider calls 减少 17.7%、wall 减少 42.0%、编译 calls 减少 70.0%、结构失败减少 83.3%，plan fallback 从 0.4 降为 0。因此 H23-H26 全部在线通过，机器判定见 `runs/vldb2027-diagnostic-v10/online-validation.json`。

schema v12 证明了基于计划同一性的拓扑路由可以无质量变化地删除冗余编译阶段，但尚未达到全面效率优势：相对 Hybrid，SlotRAG 检索文档数减少 72.4%、唯一访问文档减少 37.8%，同时 tokens、provider calls 和 wall 仍高 3.06、2.17 和 4.15 倍。v10 仍不进入 Tune50；下一步应针对占 SlotRAG tokens 68.7% 的抽取阶段和 4 个生成 calls 做机制级削减，并先用冻结 rows/evidence 证明不改变答案路径，而不是继续增加数据集短语模板。完整 122 列逐题指标及所有汇总保存在 v10 `summaries/diagnostic/`。

### schema v13 行级极性共识投影预注册（2026-07-22）

v10 有 4 个生成 calls，其中 3 个来自极性比较题。进一步检查 rows 后只能安全删除 2 个：`904a...` 和 `fce9...` 各有多条字符串不同的 `answer`，但每条都显式以同一 `No` token 开头；现有确定性出口按完整字符串去重，误把一致解释当作多个答案。`d6a...` 的两条 rows 只陈述不同地点，没有显式 yes/no，仍需生成器完成比较，不能因 gold 为 `no` 而确定化。

schema v13 在执行完成后、最终生成前增加保守共识投影。仅当结果为 `ok`、计划只有一个输出、问题满足现有助动词开头与问号边界、至少有两个不同非空输出字符串、且每个字符串首 token 都属于 `yes/no/true/false` 并规范化到同一极性时，返回 `Yes` 或 `No`；rows、EvidenceRecord 和计划保持原样，随后仍经过共享出口映射为小写 canonical 答案。任一行缺 token、出现 yes/no 冲突、非极性问题或原字符串本就唯一时均不触发。新增 `polar_row_consensus`、`slotrag-no-polar-consensus` 消融和 schema 13 门控；原 `polar_answer_normalizations` 应继续计数，证明共享输出协议未被绕过。

冻结 v10 重放恰好命中 `904a637d08e611ebbda5ac1f6bf848b6` 与 `fce934db085b11ebbd5cac1f6bf848b6`，两题共可删除 2 个 generation calls、2,239 tokens 和 26.60 s generation latency；全样本反事实为 LLM calls 2.7、tokens 5,567.9、wall 37.87 s。该反事实只从已记录指标减去被证明冗余的生成阶段，不把它当作在线时延观测。

```text
H27（共识安全性）：同极性多解释触发；yes/no 冲突、缺少极性 token、单一原始值、非极性问题均不触发，且 rows/evidence/plan 不变。
H28（冻结范围）：同样本只命中上述 2 题，答案仍为 no，d6a... 与其余 7 题触发 0；polar_answer_normalizations 在 4 个极性题上仍各为 1。
H29（方法隔离）：完整方法记录 polar_row_consensus=2/10；slotrag-no-polar-consensus 只关闭该投影，不改变两个编译模板、类型算子或共享规范化。
H30（质量与成本）：20 条最终记录全部 ok，双方 EM=F1=1；两题 generation calls=0，SlotRAG 聚合 generation calls≤0.2、LLM calls≤2.8、tokens≤6,000，延迟完整报告不设硬阈值。
```

只有冻结 rows 重放、冲突/缺 token 负例和消融隔离全部通过后才启动独立 v11 目录。不得从地点、日期、国籍等事实值自行推断极性；这类推断仍属于生成器职责。

离线实现已完成。共识投影端到端 RED/GREEN、4 类拒绝边界、消融隔离及 schema 13 统计门控均通过；相关测试 `81 passed`，全仓 `107 passed, 1 skipped`，Python 编译、YAML/消融注册和 diff 检查通过。冻结指纹为 `76a81af851133941d125309dda9860f4c27a022b1c4eae5957c26daa0d1c2add`。对 v10 实际 rows 重放恰好命中 `904a...`、`fce9...` 两题，答案、rows、evidence 完全不变，输出经共享出口仍为 `no`；H27-H29 离线通过，H30 待在线验证，机器记录为 `runs/vldb2027-diagnostic-v11/offline-validation.json`。

#### schema v13 在线结果（v11）

`2026-07-22T13:08:11+08:00` 三项 service doctor 全部为 `HTTP 200`，随后在冻结指纹、数据审计和样本哈希下启动 v11。运行一次完成 20/20 条 schema 13 记录，20 attempts、0 benchmark retry、0 final failed/empty/unsupported，证据金标覆盖 20/20。源码指纹为 `76a81a...2add`，数据审计与样本哈希仍分别为 `a24ad3...67e`、`5bcc22...1a4`。

| v11 2Wiki diagnostic（10 题/方法） | SlotRAG | Hybrid |
| --- | ---: | ---: |
| EM / F1 | 1.000 / 1.000 | 1.000 / 1.000 |
| Evidence Recall / MRR | 0.925 / 1.000 | 1.000 / 1.000 |
| Evidence Recall@1 / @5 / @10 | 0.450 / 0.925 / 0.925 | 0.450 / 0.925 / 1.000 |
| Evidence Precision@1 / @5 / @10 | 1.000 / 0.420 / 0.210 | 1.000 / 0.440 / 0.240 |
| Evidence Hit@1 / @5 / @10 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 |
| Evidence NDCG@10 | 0.939 | 0.938 |
| 检索证据数 / 文档数 / 文本字符 | 2.1 / 2.1 / 971 | 9.9 / 9.8 / 2,906 |
| 累计文档 / 唯一文档 / 累计 passage / 唯一 passage | 8.7 / 6.2 / 9.0 / 6.3 | 9.8 / 9.8 / 9.9 / 9.9 |
| LLM / retrieval / embedding / reranker calls | 2.9 / 1.8 / 1.8 / 1.8 | 1.1 / 1.0 / 1.0 / 1.0 |
| Prompt / completion / total tokens | 3,630 / 1,793 / 5,423 | 1,549 / 516 / 2,066 |
| 编译 / 抽取 / 生成 LLM calls | 0.7 / 1.9 / 0.1 | 0 / 0 / 1.0 |
| 编译 prompt/completion tokens | 1,004 / 357 | 0 / 0 |
| 抽取 prompt/completion tokens | 2,572 / 1,378 | 0 / 0 |
| 生成 prompt/completion tokens | 53 / 59 | 1,549 / 516 |
| Provider calls / 含索引 provider calls | 6.5 / 7.5 | 3.1 / 3.1 |
| 在线延迟 mean / P50 / P95 / P99 | 41.56 / 42.93 / 70.45 / 74.46 s | 14.41 / 12.94 / 28.54 / 32.17 s |
| Provider latency / 含索引总延迟 | 41.50 / 42.16 s | 14.38 / 14.41 s |
| 编译 / 执行 / 物化 / 生成延迟 | 10.50 / 29.98 / 29.98 / 1.09 s | 0 / 0 / 0 / 13.14 s |
| 内部 provider retry / benchmark retry attempts | 0.2 / 0 | 0.1 / 0 |
| 结构失败 / 修复 / grounding / local repair | 0.5 / 0.5 / 0 / 0.2 | 0 / 0 / 0 / 0 |
| plan fallback / evidence fallback / deterministic | 0 / 0 / 0.9 | 0 / 0 / 0 |
| polar row consensus / polar normalization | 0 / 0.4 | 0 / 0.4 |
| operator rewrite / executed | 0 / 0.1 | 0 / 0 |
| heuristic / typed / field / polar / direct templates | 0.5 / 0.1 / 0.1 / 0.4 / 0 | 0 / 0 / 0 / 0 / 0 |
| span normalization / reconciliation | 0 / 0 | 0 / 0 |
| join input / output rows | 1.6 / 0.8 | 0 / 0 |
| slots / joins / variables / outputs / operators / complexity | 1.8 / 0.7 / 1.8 / 1.0 / 0.1 / 5.4 | 0 / 0 / 0 / 0 / 0 / 0 |
| steps / LLM预算 / 检索预算 / step预算 | 1.8 / 0.045 / 0.450 / 0.450 | 0 / 0.017 / 0.250 / 0 |
| 峰值 RSS 增量 / 最大中间绑定 / reoptimization | 0.207 MB / 1.3 / 0.8 | 0 / 0 / 0 |
| 平均 selectivity error / planner regret | 1.887 / 0 | N/A / N/A |
| 物化请求 / cache hit / reuse rate | 1.8 / 0 / 0 | 0 / 0 / N/A |
| 运行时 cache hit/miss / binding prune / early stop | 0/0 / 0 / 0 | 0/0 / 0 / 0 |
| 索引构建 / provider 延迟 / embedding calls | 593.79 / 545.76 ms / 1.0 | 1.35 / 0 ms / 0 |
| 索引 cache hit/miss/rate | 11.2 / 9.0 / 0.555 | 20.2 / 0 / 1.000 |
| 索引大小 / phase token coverage | 85,697 bytes / 1.0 | 85,697 bytes / 1.0 |

`accuracy` 与 DROP 专用指标在本数据集为 N/A。冷索引与方法顺序限制同 v10：SlotRAG 先运行并承担共享索引 embedding，Hybrid 复用热 cache；主 wall 延迟排除索引构建，含索引指标仅用于完整核算。分层 F1 均为 1：`bridge_comparison`（2 题）SlotRAG/Hybrid Evidence Recall=0.625/1.000、tokens=6,679/2,211、wall=39.74/11.01 s；`comparison`（3 题）为 1/1、2,457/2,117、20.61/23.77 s；`compositional`（4 题）为 1/1、6,284/1,601、56.41/9.25 s；`inference`（1 题）为 1/1、8,369/3,478、48.67/13.75 s。配对 bootstrap 为 0 胜/10 平/0 负、Cliff's delta=0、95% CI `[0,0]`、`p=p_holm=1.0`。

在线 `polar_row_consensus` 实际为 **0/10**，不是预注册的 2/10。`904a...` 的两行变成不含显式极性 token 的事实句，安全规则正确拒绝且保留 1 次生成；`fce9...` 的两行都精确等于 `No`，因只有一个唯一原始值而被共识规则拒绝，随后由已有确定性出口直接回答。`d6a...` 也生成两条完全相同的显式 `No` 解释并由旧出口确定化，`49b5...` 只有一行 `No`。因此极性题 generation calls 从 v10 的 3 次降到 v11 的 1 次、全样本 generation calls 从 0.4 降到 0.1，均是抽取输出随机变化触发现有路径，**不能归因于 schema v13**。

| 预注册假设 | 在线判定 | 依据 |
| --- | --- | --- |
| H27 共识安全性 | 通过 | 离线冲突/缺 token/单值/非极性负例全部通过，在线 0 次误触发。 |
| H28 冻结范围 | 失败 | 冻结 v10 rows 命中 2 题，但新在线 rows 命中 0 题，触发范围不可复现。 |
| H29 方法隔离与计数 | 失败 | 计数为 0/10，而非预注册的 2/10；消融接口正确但没有在线处理效应。 |
| H30 质量与成本 | 整体失败 | 20/20 ok、双方 EM=F1=1、tokens=5,423、generation calls=0.1 通过；但 `904a...` 未删除生成，且 LLM calls=2.9 高于 2.8 门槛。 |

v10→v11 的 SlotRAG 观测变化为：LLM/provider calls 均不变（2.9/6.5），tokens 降 6.4%（5,792→5,423），wall 反升 2.6%（40.53→41.56 s），Evidence Recall 从 0.975 降到 0.925；其中 `49b5...` Evidence Recall 从 0.75 降到 0.25。相对同轮 Hybrid，SlotRAG 检索文档少 78.6%、唯一访问文档少 36.7%、证据字符少 66.6%，但 LLM calls、tokens、provider calls、wall 分别为 2.64、2.63、2.10、2.89 倍。v11 不进入 Tune50，schema v13 只保留为安全但未获在线支持的候选，不应写成有效贡献。机器判定见 `runs/vldb2027-diagnostic-v11/online-validation.json`，完整逐题与分层结果见 v11 `summaries/diagnostic/`。

失败原因不是判断规则过严，而是自由文本抽取没有稳定的极性表示契约。下一轮应把极性变成抽取 schema 中受约束的 `yes/no/unknown`，只在返回 `yes/no` 时确定化，`unknown` 继续交给生成器；不得放宽为从地点、国籍、日期等事实值推断答案。该改变需要新的预注册、独立计数和只关闭契约的消融。

### schema v14 类型化变量域与抽取期弃权预注册（2026-07-22）

schema v13 的失败表明，执行层不能把自由文本措辞当作稳定接口。schema v14 将类型信息前移到 `Slot`：新增可选 `variable_types`，键必须属于该槽位变量，首个支持域为 `boolean`。极性比较拓扑模板把 `answer` 标为 boolean；普通槽位、字段极值模板和 LLM 编译计划不自动获得该类型，因此检索查询、连接、算子和非目标题执行路径保持不变。

启用类型化抽取契约时，boolean 字段的工具 schema 只接受小写 `yes/no/unknown`。若抽取返回非空且所有行都是同一 `yes` 或同一 `no`，保留具有效 source attribution 的 canonical rows，已有确定性出口直接作答；若 rows 为空、任一行为 `unknown`、或同时出现 yes/no，则计为一次 abstention、向执行器返回空 rows，并由现有 evidence-only 生成器兜底。字段缺失、非法枚举或未知 source ID 仍进入既有一次结构修复；禁止根据地点、国籍、日期等事实字符串自行计算极性。

新增三项独立计数：`typed_extraction_contracts`、`typed_extraction_answers`、`typed_extraction_abstentions`。消融 `slotrag-no-typed-extraction` 仅让物化器忽略 `variable_types` 并使用原自由文本抽取工具；计划、极性拓扑模板、类型化算子、共识安全检查和最终规范化全部保留。在线门使用新阶段 `polar_contract_gate`，冻结同一 2Wiki train 10 题，方法为 SlotRAG、Hybrid、该消融，共 30 条最终记录。

```text
H31（契约安全）：boolean 工具域严格为 yes/no/unknown；同极性有效来源可确定化，空/unknown/冲突均弃权并调用生成器；非法值和未知来源进入结构修复；普通槽位工具不变。
H32（范围与隔离）：冻结样本仅 4 个极性模板计划带 answer:boolean，另外 6 题为 0；完整方法 contract=4，消融 contract=0，双方计划拓扑与检索查询相同。
H33（在线稳定性）：完整方法 4 个 contract outcome 均被 answers 或 abstentions 覆盖，typed_extraction_answers>=3，所有非弃权 rows 只含 canonical yes/no，4 题最终 polar normalization 均为 1。
H34（质量与成本）：30/30 final ok；SlotRAG、Hybrid、消融均 EM=F1=1，4 个极性题的完整方法与消融答案/F1一致；完整方法极性题 generation calls<=1、聚合 generation calls<=0.1、LLM calls<=2.9、tokens<=6,000，且 generation calls 不高于消融。延迟完整报告但不设硬阈值。
```

schema v14 仍只是对核心按需物化框架的接口收紧，不作为独立论文贡献。只有 H31-H34 均通过并在独立重复运行中保持触发稳定，才考虑把类型化抽取写入最终方法；否则回滚该候选，转向削减非极性题的通用编译/抽取成本。

离线实现与范围审计已完成。新增类型键校验、boolean 工具枚举、canonical rows、空/unknown/冲突弃权、非法值修复、自由文本消融及 schema14 统计门控；全仓 `117 passed, 1 skipped`，Python 编译、YAML 和 diff 检查通过。冻结样本恰好只有 `49b5...`、`904a...`、`d6a...`、`fce9...` 四个计划携带 `answer:boolean`，其余 6 题为 0；消融恢复普通 string schema 而保留同一计划。冻结源码指纹为 `e9c00b0280cd3e2e05a23548d9de80a8f8deab39dfef58354306d55225eed795`，H31/H32 离线通过，H33/H34 待在线，机器记录为 `runs/vldb2027-diagnostic-v12/offline-validation.json`。

#### schema v14 在线结果（v12）

`2026-07-22T13:35:02+08:00` 三项 service doctor 全部为 `HTTP 200` 后，在冻结指纹 `e9c00b...d795` 下启动 `polar_contract_gate`；新阶段样本哈希精确复现 `5bcc22...1a4`。运行中 Agnes 再次进入 `ReadTimeout`，主方法 1 条、Hybrid 2 条 immutable attempts 失败；进程暂停、两次 doctor 恢复后在同一目录续跑，最终 30/30 条 schema14 记录均为 `ok`。总计 33 attempts、3 benchmark retry attempts、0 final failed/empty/unsupported，故障时间线见 `service-doctor-history.json`。下表均为最终成功记录的每题均值，attempt 级故障率另行保留。

| v12 2Wiki polar contract gate（10 题/方法） | SlotRAG | Hybrid | No typed extraction |
| --- | ---: | ---: | ---: |
| EM / F1 | 1.000 / 1.000 | 1.000 / 1.000 | 0.900 / 0.900 |
| Evidence Recall / MRR | 0.975 / 1.000 | 1.000 / 1.000 | 0.875 / 1.000 |
| Evidence Recall@1 / @5 / @10 | 0.450 / 0.975 / 0.975 | 0.450 / 0.925 / 1.000 | 0.450 / 0.875 / 0.875 |
| Evidence Precision@1 / @5 / @10 | 1.000 / 0.460 / 0.230 | 1.000 / 0.440 / 0.240 | 1.000 / 0.400 / 0.200 |
| Evidence Hit@1 / @5 / @10 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 |
| Evidence NDCG@10 | 0.983 | 0.938 | 0.900 |
| 检索证据数 / 文档数 / 文本字符 | 2.5 / 2.5 / 1,099 | 9.9 / 9.8 / 2,906 | 2.4 / 2.4 / 1,418 |
| 累计文档 / 唯一文档 / 累计 passage / 唯一 passage | 8.7 / 6.4 / 9.0 / 6.5 | 9.8 / 9.8 / 9.9 / 9.9 | 8.2 / 5.9 / 8.5 / 6.0 |
| LLM / retrieval / embedding / reranker calls | 2.9 / 1.8 / 1.8 / 1.8 | 1.4 / 1.0 / 1.0 / 1.0 | 2.8 / 1.7 / 1.7 / 1.7 |
| Prompt / completion / total tokens | 3,991 / 1,954 / 5,945 | 1,549 / 730 / 2,279 | 3,842 / 3,327 / 7,168 |
| 编译 / 抽取 / 生成 LLM calls | 0.8 / 2.0 / 0.1 | 0 / 0 / 1.0 | 0.7 / 1.9 / 0.2 |
| 编译 prompt/completion tokens | 1,235 / 373 | 0 / 0 | 1,007 / 1,156 |
| 抽取 prompt/completion tokens | 2,668 / 1,387 | 0 / 0 | 2,593 / 1,849 |
| 生成 prompt/completion tokens | 88 / 195 | 1,549 / 730 | 241 / 322 |
| Provider calls / 含索引 provider calls | 6.5 / 7.4 | 3.4 / 3.4 | 6.2 / 6.2 |
| 在线延迟 mean / P50 / P95 / P99 | 48.84 / 38.07 / 106.79 / 126.67 s | 47.56 / 26.54 / 137.08 / 137.99 s | 51.58 / 42.34 / 109.02 / 134.47 s |
| Provider latency / 含索引总延迟 | 48.83 / 49.18 s | 47.40 / 47.56 s | 51.57 / 51.58 s |
| 编译 / 执行 / 物化 / 生成延迟 | 12.12 / 34.71 / 34.70 / 2.01 s | 0 / 0 / 0 / 45.88 s | 15.01 / 33.30 / 33.30 / 3.27 s |
| 内部 provider retry / benchmark retry attempts | 0 / 1 | 0.4 / 2 | 0 / 0 |
| 结构失败 / 修复 / grounding / local repair | 0.6 / 0.5 / 0 / 0 | 0 / 0 / 0 / 0 | 0.6 / 0.4 / 0 / 0 |
| plan fallback / evidence fallback / deterministic | 0 / 0.1 / 0.9 | 0 / 0 / 0 | 0.1 / 0.1 / 0.8 |
| typed contract / answer / abstention | 0.4 / 0.3 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| polar consensus / polar normalization | 0 / 0.1 | 0 / 0.4 | 0 / 0.4 |
| operator rewrite / executed | 0 / 0.1 | 0 / 0 | 0 / 0.1 |
| heuristic / typed / field / polar / direct templates | 0.5 / 0.1 / 0.1 / 0.4 / 0 | 0 / 0 / 0 / 0 / 0 | 0.5 / 0.1 / 0.1 / 0.4 / 0 |
| reconciliation / span normalization / early stop / binding prune | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| join input / output rows | 1.6 / 0.8 | 0 / 0 | 1.4 / 0.7 |
| slots / joins / variables / outputs / operators / complexity | 1.8 / 0.7 / 2.0 / 1.0 / 0.1 / 5.6 | 0 / 0 / 0 / 0 / 0 / 0 | 1.7 / 0.6 / 1.7 / 1.0 / 0.1 / 5.1 |
| steps / LLM预算 / 检索预算 / step预算 | 1.8 / 0.045 / 0.450 / 0.450 | 0 / 0.022 / 0.250 / 0 | 1.7 / 0.044 / 0.425 / 0.425 |
| 峰值 RSS 增量 / 最大中间绑定 / reoptimization | 1.085 MB / 1.2 / 0.8 | 0.739 MB / 0 / 0 | 0.100 MB / 1.2 / 0.7 |
| 平均 selectivity error / planner regret | 1.956 / 0 | N/A / N/A | 2.066 / 0 |
| 物化请求 / cache hit / reuse rate | 1.8 / 0 / 0 | 0 / 0 / N/A | 1.7 / 0 / 0 |
| 运行时 cache hit/miss | 0/0 | 0/0 | 0/0 |
| 索引构建 / provider 延迟 / embedding calls | 340.75 / 300.60 ms / 0.9 | 1.27 / 0 ms / 0 | 1.46 / 0 ms / 0 |
| 索引 cache hit/miss/rate | 12.2 / 8.0 / 0.605 | 20.2 / 0 / 1.000 | 20.2 / 0 / 1.000 |
| 索引大小 / phase token coverage | 85,697 bytes / 1.0 | 85,697 bytes / 1.0 | 85,697 bytes / 1.0 |

`accuracy` 与 DROP 专用指标为 N/A。主方法先运行并承担大部分冷索引成本，后续两方法复用热 cache；同时本轮跨越 Agnes 故障、退化与恢复三个服务时段，因此绝对延迟和方法间 wall 比值仅作完整记录，不作因果结论。attempt 级故障为 SlotRAG 1/11、Hybrid 2/12、消融 0/10，三条失败均为 `provider_connect/ReadTimeout`，最终记录已通过续跑恢复。

四个极性目标题提供了干净的计划级消融：两方法 4/4 计划完全相同、答案和 F1 均为 1。完整方法得到 contract=4、typed answer=3、abstention=0；`49b5...` 两次结构校验均失败，安全回退生成器。目标题合计如下：

| 4 个极性题合计 | SlotRAG typed contract | No typed extraction |
| --- | ---: | ---: |
| EM / F1 | 1.000 / 1.000 | 1.000 / 1.000 |
| extraction / generation / total LLM calls | 6 / 1 / 7 | 5 / 1 / 6 |
| total tokens | 17,896 | 14,295 |
| structured failure / repair | 3 / 2 | 1 / 1 |
| wall latency | 144.23 s | 101.83 s |

契约在 `904a...` 上删除了消融的 1 次生成，却在 `49b5...` 上因结构耗尽增加了 1 次生成，净 generation saving 为 0；同时 LLM calls、tokens 和 wall 分别高 16.7%、25.2%、41.6%。`d6a...`、`fce9...` 两边都被原确定性出口处理。因此 schema14 没有证明效率收益。完整方法的 `polar_answer_normalizations=1` 而非预注册的 4，不是输出错误：3 个 typed answer 已经是小写 canonical `no`，共享规范化函数无需改写便不会增加“发生变化”计数；但按预注册计数条件仍判失败。

全样本消融 F1=0.9 的唯一错误来自非目标题 `574...`。完整方法独立 LLM 编译得到正确两跳 `MotherOf→MotherOf` 计划并回答 `Isabel Marshal`；消融的独立编译连续结构失败后退化为单槽 evidence plan，最终回答证据不足。10 题中只有 6 对计划相同，4 个非目标题计划不同。因此 SlotRAG 对消融的配对结果（1 胜/9 平、均值差 0.1、Cliff's delta=0.1、95% CI `[0,0.3]`、`p=0.7108, p_holm=1`）**不能解释为类型契约的质量贡献**。SlotRAG 对 Hybrid 仍为 0 胜/10 平/0 负、差值/Cliff's delta=0、CI `[0,0]`、`p=p_holm=1`。

| 预注册假设 | 在线判定 | 依据 |
| --- | --- | --- |
| H31 契约安全 | 通过 | 3 个 canonical `no` 直接回答；结构耗尽题安全回退生成器，4 题答案均正确。 |
| H32 范围与隔离 | 目标题通过、协议有缺口 | 完整方法 contract=4、消融=0，4 个目标题计划相同；但 4/6 个非目标题因独立 LLM 编译而计划不同。 |
| H33 在线稳定性 | 失败 | typed answer=3 达标，但 answer+abstention 只覆盖 3/4，结构耗尽未归类；normalization 变更计数仅 1/4。 |
| H34 质量与成本 | 失败 | 30/30 final ok、主方法/Hybrid F1=1、主方法 calls/tokens 门槛通过；但消融 F1=0.9，且目标题没有生成净节省并增加 calls/tokens。 |

schema v14 候选拒绝，不纳入默认方法贡献。相对 Hybrid，主方法仍少检索 74.5% 文档、少访问 34.7% 唯一文档、少处理 62.2% 证据字符，但 LLM calls、tokens、provider calls 仍为 2.07、2.61、1.91 倍；本轮 wall 仅为 1.03 倍是服务时段污染，不能视为效率突破。机器判定见 `runs/vldb2027-diagnostic-v12/online-validation.json`，完整逐题、分层与 attempt 汇总见 v12 `summaries/polar_contract_gate/`。

本轮还暴露了比继续做极性优化更优先的实验协议问题：执行型消融必须复用完全相同的编译计划，否则 LLM compiler 随机性会制造伪质量差。下一步先实现“冻结计划配对消融”协议，将计划生成成本作为共享前置成本单列；随后在相同 plan/evidence 下研究非极性题的通用抽取成本。不得再从全样本独立编译的消融差值主张因果贡献。

在线判定后已立即回滚默认架构：`slotrag` 的 `typed_extraction_contracts` 默认为关闭，候选改名为显式实验方法 `slotrag-typed-extraction`；原 `slotrag-no-typed-extraction` 仅为读取 v12 历史 manifest 保留，不再进入后续消融清单。schema14 统计字段和运行解析保持兼容，故 v12 机器记录不受回滚影响。回滚审计还发现并修复了通用 CLI 直接构造物化器时仍默认开启契约的缺口；现在方法注册、`SlotMaterializer` 和 `extraction_tool` 三层默认均为关闭，仅候选方法显式开启。离线验证为 `117 passed, 1 skipped`，`compileall` 与 `git diff --check` 均通过；回滚后、schema15 改造前的源码指纹为 `d6c3922a3380e30f7a384dab1746b4dcb7d2c3da5942e90394173e9d0fa68f77`。当前方法默认不包含 schema13 行级共识以外的新类型契约贡献；下一次在线运行必须使用新的源码指纹和独立目录。

### schema v15 固定计划成对消融协议预注册（2026-07-22）

schema v15 只修复实验设计，不改变 SlotRAG 答案逻辑，也不作为论文方法贡献。新阶段可指定 `frozen_plan_source`；runner 对每个问题只调用一次该来源方法的 Slot Compiler，将 `SlotPlan`、编译指标、provider delta 和时延原子化保存，随后所有编译兼容的 SlotRAG 方法绕过编译器并重放该计划。配置层比较 `direct_single_document`、`field_extremum_templates` 和 `polar_comparison_templates`；任一开关不同的方法不得伪装成执行期成对消融。

快照有两层完整性约束。输入哈希覆盖 stage、dataset、question ID/文本、source method 和实际 compiler options；计划哈希是规范 JSON `SlotPlan` 的 SHA-256。同一输出目录中问题或编译选项改变时直接拒绝旧快照，计划内容与哈希不同时也直接失败。共享编译失败写入独立 `plan_attempts/` 且不覆盖；恢复后追加 attempt 并且最终只产生一个成功快照。

成本同时报告两种口径：

```text
执行期因果口径：每个重放方法的 result.metrics 不包含共享编译，frozen_plan_replays=1；
独立部署口径：llm_calls/total_tokens/provider_calls/wall_latency_with_shared_compile 为执行成本加回一次共享编译；
共享编译审计：独立报告 calls、prompt/completion/total tokens、provider attempts/retries/latency、wall P50/P95/P99、结构失败/修复/fallback 和计划复杂度。
```

汇总新增 `frozen_plan_audit.json` 和 `frozen_plan_metrics.csv`，必须报告 snapshot/attempt/replay 数、无 provenance 记录、result-plan 哈希不匹配、未知快照哈希和同题多计划对数。冻结阶段仍输出原有全部答案、证据、调用、token、分阶段、时延分位数、索引、cache、绑定/连接、计划和异常指标，不用新协议取代端到端基线。

v13 在线门固定为 `runs/vldb2027-diagnostic-v13`，阶段 `frozen_polar_contract_gate`，仅使用 2Wiki train 原 10 题，样本 SHA-256 预期仍为 `5bcc2298686f2c3d1e0e570bcfa6197454f32660009d6cf3e9599dae63f1c1a4`。方法为 `slotrag`、`slotrag-typed-extraction` 和 Hybrid；前两者共享由 `slotrag` 生成的计划，Hybrid 仍按原协议端到端运行，只作质量与整体成本参考。该门是对已拒绝 schema14 候选的因果复核，不因一次通过而自动恢复默认开关。

```text
H35（计划同一性）：10 个有效快照、20 个 SlotRAG 重放记录；两方每题 plan_sha256 相同，mismatch/inconsistent/missing provenance 全为 0，每条 frozen_plan_replays=1。
H36（成本隔离与可恢复性）：每题共享编译成本只记一次，执行期 compilation calls/tokens/latency=0；共享和加回后口径均完整，失败 plan attempts 不被覆盖。
H37（消融隔离）：typed 方法 contract=4、默认方法=0，另 6 题均为 0；两方全 10 题 EM/F1 逐题一致，不再出现 v12 非目标编译差异。
H38（候选保留门）：30/30 final ok，SlotRAG/typed/Hybrid 均 EM=F1=1；4 个目标题 typed answers+abstentions=4、非弃权值均为 canonical yes/no；typed 目标题 generation calls 不高于默认方法，且执行期 LLM calls 和 total tokens 均不高于默认方法。
```

H35/H36 是协议验收，H37/H38 才是候选因果判定。任一哈希审计失败时 H37/H38 不予解释；H38 任一成本或覆盖条件失败时继续拒绝类型契约，不通过修改阈值追认。时延受共享服务时段影响，完整报告但不设跨时段硬门；calls/tokens 为主成本判定。

离线 TDD 验证已完成：覆盖编译兼容配置拒绝、重放路径不构造编译器、单次共享编译、同哈希续跑、失败 attempt 恢复、过期输入拒绝、schema15 向后兼容和汇总审计。全仓为 `123 passed, 1 skipped`，Python `compileall`、pilot YAML 解析和 `git diff --check` 通过；冻结源码/配置/测试指纹为 `1ef387ec7d9d3836cbf6606bf094ff6abae752d9c52284a71034e0f8516d2044`。机器离线记录为 `runs/vldb2027-diagnostic-v13/offline-validation.json`；只有样本与数据审计哈希复现、三项服务 doctor 通过后才创建 v13 manifest。

#### schema v15 在线结果（v13）

`2026-07-22T14:57:49+08:00` 三项 service doctor 全部为 `HTTP 200`，随后在指纹 `1ef387...d2044`、数据审计 `a24ad3...67e` 和样本 `5bcc22...1a4` 下创建 v13 manifest。一次运行完成 30/30 条 schema15 最终记录，30 个执行 attempts、0 benchmark retry、0 final failed/empty/unsupported，30/30 都有证据金标。

固定计划审计先于方法效果判定且全部通过：

| schema15 协议审计 | 在线值 |
| --- | ---: |
| snapshot / valid / invalid | 10 / 10 / 0 |
| plan attempts / failed plan attempts | 10 / 0 |
| replay records / replay questions | 20 / 10 |
| missing provenance / missing result plan | 0 / 0 |
| plan hash mismatch / unknown snapshot hash / inconsistent pair | 0 / 0 / 0 |
| 共享编译 LLM calls（total / mean） | 7 / 0.7 |
| 共享编译 prompt / completion / total tokens | 10,037 / 11,843 / 21,880 |
| 共享编译 token mean / P95 | 2,188 / 6,477 |
| 共享编译时延 mean / P50 / P95 / P99 | 20.39 / 10.82 / 57.26 / 63.28 s |
| 共享编译 provider attempts / retries | 7 / 0 |
| 共享编译结构失败 / 修复 / fallback | 2 / 2 / 0 |
| 共享 heuristic / typed / field / polar / direct templates | 5 / 1 / 1 / 4 / 0 |
| 共享 slots / joins / complexity mean | 1.9 / 0.8 / 5.7 |

下表中 SlotRAG 两列的主 calls/tokens/wall 是执行期因果口径，不含上表共享编译；`+共享编译` 行则是每个方法独立部署时加回一次编译的估计。Hybrid 本身为端到端口径。

| v13 2Wiki frozen gate（10 题/方法） | SlotRAG | Typed candidate | Hybrid |
| --- | ---: | ---: | ---: |
| EM / F1 | 0.900 / 0.900 | 0.900 / 0.900 | 1.000 / 1.000 |
| Evidence Recall / MRR | 0.825 / 1.000 | 0.725 / 1.000 | 1.000 / 1.000 |
| Evidence Recall@1 / @5 / @10 | 0.450 / 0.825 / 0.825 | 0.450 / 0.725 / 0.725 | 0.450 / 0.925 / 1.000 |
| Evidence Precision@1 / @5 / @10 | 1.000 / 0.380 / 0.190 | 1.000 / 0.340 / 0.170 | 1.000 / 0.440 / 0.240 |
| Evidence Hit@1 / @5 / @10 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 |
| Evidence NDCG@10 | 0.862 | 0.784 | 0.938 |
| 检索证据数 / 文档数 / 文本字符 | 2.1 / 2.0 / 974 | 2.1 / 2.1 / 1,260 | 9.9 / 9.8 / 2,906 |
| 累计文档 / 唯一文档 / 累计 passage / 唯一 passage | 9.2 / 6.1 / 9.5 / 6.2 | 8.2 / 5.9 / 8.5 / 6.0 | 9.8 / 9.8 / 9.9 / 9.9 |
| LLM / retrieval / embedding / reranker calls | 2.3 / 1.9 / 1.9 / 1.9 | 2.4 / 1.7 / 1.7 / 1.7 | 1.0 / 1.0 / 1.0 / 1.0 |
| Prompt / completion / total tokens | 2,766 / 2,014 / 4,780 | 2,876 / 2,421 / 5,297 | 1,549 / 879 / 2,429 |
| 编译 / 抽取 / 生成 LLM calls | 0 / 2.0 / 0 | 0 / 2.0 / 0.1 | 0 / 0 / 1.0 |
| 抽取 prompt / completion tokens | 2,766 / 2,014 | 2,701 / 2,217 | 0 / 0 |
| 生成 prompt / completion tokens | 0 / 0 | 175 / 204 | 1,549 / 879 |
| 执行期 provider calls | 6.1 | 5.8 | 3.0 |
| +共享编译 LLM calls / tokens / provider calls | 3.0 / 6,968 / 6.8 | 3.1 / 7,485 / 6.5 | N/A |
| 执行期 wall mean / P50 / P95 / P99 | 37.02 / 40.46 / 55.63 / 58.50 s | 46.86 / 38.00 / 108.81 / 120.64 s | 16.70 / 18.12 / 23.47 / 25.50 s |
| +共享编译 wall mean / P95 | 57.41 / 101.27 s | 67.25 / 137.72 s | N/A |
| Provider latency mean / P95 | 36.93 / 55.59 s | 46.77 / 108.66 s | 16.69 / 23.46 s |
| 执行 / 物化 / 生成时延 | 37.02 / 37.02 / 0 s | 44.71 / 44.71 / 2.15 s | 0 / 0 / 16.33 s |
| 内部 provider retry / benchmark retry | 0.3 / 0 | 0.3 / 0 | 0 / 0 |
| 结构失败 / 修复 / grounding / local repair | 0.1 / 0.1 / 0 / 0 | 0.4 / 0.3 / 0 / 0 | 0 / 0 / 0 / 0 |
| plan fallback / evidence fallback / deterministic | 0 / 0 / 1.0 | 0 / 0.1 / 0.9 | 0 / 0 / 0 |
| polar / span normalization / reconciliation / row consensus | 0.4 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0.4 / 0 / 0 / 0 |
| typed contract / answer / abstention / frozen replay | 0 / 0 / 0 / 1.0 | 0.4 / 0.4 / 0 / 1.0 | 0 / 0 / 0 / 0 |
| operators executed / rewrite | 0.1 / 0 | 0.1 / 0 | 0 / 0 |
| join input / output rows | 1.8 / 0.9 | 1.4 / 0.7 | 0 / 0 |
| slots / joins / variables / outputs / operators / complexity | 1.9 / 0.8 / 1.9 / 1.0 / 0.1 / 5.7 | 1.9 / 0.8 / 1.9 / 1.0 / 0.1 / 5.7 | 0 / 0 / 0 / 0 / 0 / 0 |
| steps / LLM预算 / 检索预算 / step预算 | 1.9 / 0.0359 / 0.475 / 0.475 | 1.7 / 0.0375 / 0.425 / 0.425 | 0 / 0.0156 / 0.250 / 0 |
| 峰值 RSS 增量 / 最大中间绑定 / reoptimization | 1.104 MB / 1.2 / 0.9 | 0 / 0.9 / 0.7 | 0 / 0 / 0 |
| 平均 selectivity error / planner regret | 2.319 / 0 | 2.470 / 0 | N/A / N/A |
| 物化请求 / 物化 cache hit / reuse rate | 1.9 / 0 / 0 | 1.7 / 0 / 0 | 0 / 0 / N/A |
| 运行时 cache hit/miss / binding prune / early stop | 0/0 / 0 / 0 | 0/0 / 0 / 0 | 0/0 / 0 / 0 |
| 索引构建 / provider 时延 / embedding calls | 420.68 / 343.47 ms / 1.0 | 1.36 / 0 ms / 0 | 1.34 / 0 ms / 0 |
| 索引 cache hit/miss/rate | 11.2 / 9.0 / 0.555 | 20.2 / 0 / 1.000 | 20.2 / 0 / 1.000 |
| 索引大小 / phase token coverage | 85,697 bytes / 1.0 | 85,697 bytes / 1.0 | 85,697 bytes / 1.0 |

`accuracy` 和 DROP 专用指标在 2Wiki 上为 N/A。SlotRAG 先运行并承担冷语料索引，后两种方法复用热索引；在线 `wall_latency` 按既定协议排除索引构建，`with-index` 指标保留顺序影响。因此 H38 以成对 calls/tokens 和质量为主，延迟只完整报告。

四个类型契约目标题的计划哈希 4/4 相同，双方答案均为 canonical `no`、EM/F1 均为 1；候选 contract=4、typed answer=4、abstention=0，默认方法三项均为 0，另外 6 题也没有误触发。

| 4 个目标题合计 | SlotRAG | Typed candidate |
| --- | ---: | ---: |
| EM / F1 | 1.000 / 1.000 | 1.000 / 1.000 |
| Evidence Recall | 0.688 | 0.438 |
| extraction / generation / total LLM calls | 5 / 0 / 7 | 6 / 0 / 8 |
| prompt / completion / total tokens | 5,849 / 7,057 / 12,906 | 7,285 / 8,827 / 16,112 |
| retrieval / embedding / reranker calls | 4 / 4 / 4 | 4 / 4 / 4 |
| provider calls | 15 | 16 |
| structured failure / repair | 1 / 1 | 2 / 2 |
| deterministic answers | 4 | 4 |
| wall latency | 105.28 s | 121.55 s |

候选相对默认方法的目标题 generation saving 为 0，LLM calls、tokens、provider calls、wall 分别增加 14.3%、24.8%、6.7%、15.5%，Evidence Recall 下降 36.4%。`49b5...` 和 `904a...` 上候选各多一次结构失败/修复；虽然契约覆盖稳定为 4/4，但没有成本收益。

全样本两种 SlotRAG 逐题 F1 10/10 一致，bootstrap 为 0 胜/10 平/0 负、均值差/Cliff's delta=0、CI `[0,0]`、`p=p_holm=1`；文本答案只有 9/10 一致。唯一不同的 `574...` 两者都 F1=0：共享计划把问题已给定的人物拆成冗余 `Person(Baldwin De Redvers, 7Th Earl Of Devon, ?baldwin)` 身份槽，再连接两层 `MotherOf`。默认方法错答 `Baldwin de Redvers, 6th Earl of Devon`，候选因抽取随机性回答证据不足；Hybrid 答对 `Isabel Marshal`。这是一个共享的语义计划错误，不是类型契约处理效应。SlotRAG 对 Hybrid 为 0 胜/9 平/1 负、均值差 -0.1、Cliff's delta=-0.1、CI `[-0.3,0]`、`p=0.7128, p_holm=1`。

| 预注册假设 | 在线判定 | 依据 |
| --- | --- | --- |
| H35 计划同一性 | 通过 | 10 快照、20 重放，所有 provenance/内容/成对哈希检查均为 0 错误。 |
| H36 成本隔离与恢复 | 通过 | 每题共享编译只保存一次，重放编译指标为 0，共享和加回成本均可查，0 失败 plan attempts。 |
| H37 消融隔离 | 通过 | contract 严格 4 vs 0、非目标为 0；相同计划下全 10 题 F1 一致。 |
| H38 候选保留门 | 失败 | 30/30 ok、4 目标题质量/覆盖通过；但两种 SlotRAG 总 F1=0.9，候选目标 calls/tokens 高于默认方法。 |

schema15 协议保留，后续所有执行型消融必须使用它或等价的同计划机制。schema14 类型契约则再次明确拒绝：保持 `slotrag-typed-extraction` 显式实验方法且默认关闭，不得纳入论文贡献。机器判定见 `runs/vldb2027-diagnostic-v13/online-validation.json`，完整逐题、分层、bootstrap、失败分母和 130+ 指标见 `runs/vldb2027-diagnostic-v13/summaries/frozen_polar_contract_gate/`。下一候选应针对 `574...` 暴露的通用冗余实体锚定槽做语义计划修复，而不是再增加极性短语规则。

#### schema v16：grounded entity anchor folding 与 v14 预注册

v13 唯一失败题揭示的是一个可泛化但必须保守处理的计划缺陷：编译器把问题已经给出的实体拆成身份槽，再让下游关系槽重新检索该身份。schema16 增加默认关闭的 `slotrag-anchor-folding` 候选，它不重新编译、不调用 LLM，也不改变原始快照；它只在执行前把安全的实体身份叶子折叠为唯一消费者的绑定约束。论文方法候选暂称 **Grounded Entity Anchor Folding (GEAF)**。

安全契约同时要求：predicate 只能是 `Person/Entity/Item/Place`；锚槽恰有一个变量和至少一个常量；常量按槽内顺序在原问题中连续出现，中间只允许空白或标点；锚变量不是最终输出且不被 operator 引用；锚槽无额外 constraint/type；变量只有一个下游消费者；锚槽只有一条同字段叶子 join；消费者不存在冲突约束。变换后必须重新通过完整 `SlotPlan` 校验，否则返回原计划并记 0 次折叠。原有“单常量、多消费者”保守消除逻辑不变，GEAF 是独立开关。

以 v13 原始计划为例：

```text
source:
  S1 Person(Baldwin De Redvers, 7Th Earl Of Devon, ?baldwin)
  S2 MotherOf(?mother, ?baldwin)
  S3 MotherOf(?grandmother, ?mother)
  joins: S1.baldwin=S2.baldwin, S2.mother=S3.mother

effective candidate:
  S2 MotherOf(?mother, ?baldwin), constraint baldwin="Baldwin De Redvers, 7Th Earl Of Devon"
  S3 MotherOf(?grandmother, ?mother)
  join: S2.mother=S3.mother
```

schema16 同时扩展冻结计划协议。`frozen_plan_import_dir` 允许新运行导入旧运行的不可变快照；runner 验证来源 stage 输入哈希、dataset、question ID/文本、source method、compiler options 和 plan hash，任一不一致直接拒绝，绝不静默重编译。新运行仍生成本地 immutable plan attempt 与原子 snapshot，并保留来源共享编译成本。每条记录同时保存 `plan_sha256`（共同 source plan）和 `effective_plan_sha256`（方法实际执行计划）；审计用前者判断配对同一性、用后者校验 result plan，并单列有效计划发生分歧的问题数。

v14 固定为 `runs/vldb2027-diagnostic-v14`、阶段 `entity_anchor_gate`，仅运行 2Wiki train 同一批 10 题；样本 SHA-256 仍为 `5bcc2298686f2c3d1e0e570bcfa6197454f32660009d6cf3e9599dae63f1c1a4`。方法为默认 SlotRAG、`slotrag-anchor-folding` 和 Hybrid；两个 SlotRAG 方法导入 v13 的同一源计划，Hybrid 仅作端到端质量参照。

在线前离线作用域审计已冻结：10 个来源快照全部有效，只有 `5741415a0bb011ebab90acde48001122` 触发 1 次折叠，source/effective 分别为 3/2 slots、2/1 joins，传播值严格为问题中的 `Baldwin De Redvers, 7Th Earl Of Devon`；其余 9 题 fold=0 且 source/effective hash 完全相同。五个公开数据集各 10 条样本已生成，数据审计哈希 `a24ad3...67e` 与 v13 一致。离线全仓为 `132 passed, 1 skipped`，`compileall`、pilot YAML、`git diff --check` 均通过；指纹为 `7053cdae...e3c0`。机器记录见 `runs/vldb2027-diagnostic-v14/offline-validation.json` 和 `anchor-folding-scope-audit.json`。

```text
H39（导入与双哈希完整性）：10 个 imported snapshots、20 个 SlotRAG replay；source hash 每题一致，effective/result hash 校验、未知快照、缺失 provenance 和 source inconsistent 均为 0。
H40（保守作用域）：全 10 题恰好只在 574... 上 fold=1，其余 fold=0；审计报告恰好 1 个 effective-plan variant question。
H41（语义修复）：574... 上候选答案为 Isabel Marshal 且 F1=1，候选总体 EM/F1 不低于默认 SlotRAG；不得用 Hybrid 的正确结果替代该判定。
H42（候选保留门）：30/30 final ok；574... 候选 slots/joins/steps/retrieval calls 均低于默认方法，执行期 LLM calls 与 total tokens 也严格降低；非目标题无折叠且总体 calls/tokens 不恶化。
```

H39/H40 是协议与安全验收，H41/H42 是候选因果验收。任何哈希错误都使效果结果不可解释；目标质量通过但成本不降，或成本下降但答案仍错，都必须拒绝候选。时延完整报告但不作为单次小样本硬门。GEAF 在全部条件通过前维持显式实验方法、默认关闭，且不得追溯修改门槛。

#### schema v16 在线结果（v14）

`2026-07-22T16:00:22+08:00` 首次 doctor 三项均为 HTTP 200。运行中 embedding 出现“无可用上游实例/满载”HTTP 503，随后 Agnes 一次 `ConnectError`；进程被主动中止，失败 attempts 原样保留。`16:14:57` 和 `16:24:28` 两次三项 doctor 恢复后按同目录续跑，最终为 30/30 schema16 final `ok`、38 个 immutable attempts、8 个 benchmark retry。历史失败分母为候选 6 次 HTTP 5xx + 1 次 connect、Hybrid 1 次 HTTP 5xx；默认 SlotRAG 10/10 首次成功。服务历史见 `service-doctor-history.json`，不能只报告恢复后的最终状态。

双哈希协议完整通过：10/10 snapshots 均从 v13 导入且有效，10 个 plan attempts、0 plan preparation failure、20 条 SlotRAG replay；missing provenance/result/effective hash、payload mismatch、unknown snapshot hash、source inconsistent pair 均为 0，恰好 1 个问题具有不同 effective plan。共享编译指标与 v13 原快照一致：7 calls、10,037 prompt + 11,843 completion = 21,880 tokens、0 provider retry、2 次结构失败/修复、0 fallback。

下表主 calls/tokens/wall 均为执行期口径；两个 SlotRAG 方法的 `+共享编译` 指标按独立部署口径加回同一份原始编译成本。最终结果和历史 attempt 失败分别报告，避免把恢复能力混入方法质量。

| v14 2Wiki entity-anchor gate（10 题/方法） | SlotRAG | GEAF constraint | Hybrid |
| --- | ---: | ---: | ---: |
| EM / F1 | 0.900 / 0.900 | 1.000 / 1.000 | 1.000 / 1.000 |
| Evidence Recall / MRR | 0.875 / 1.000 | 0.925 / 1.000 | 1.000 / 1.000 |
| Evidence Recall@1 / @5 / @10 | 0.450 / 0.875 / 0.875 | 0.450 / 0.875 / 0.925 | 0.450 / 0.925 / 1.000 |
| Evidence Precision@1 / @5 / @10 | 1.000 / 0.400 / 0.200 | 1.000 / 0.400 / 0.210 | 1.000 / 0.440 / 0.240 |
| Evidence Hit@1 / @5 / @10 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 |
| Evidence NDCG@10 | 0.900 | 0.922 | 0.938 |
| 检索证据数 / 文档数 / 文本字符 | 2.2 / 2.1 / 1,031 | 3.2 / 2.9 / 1,938 | 9.9 / 9.8 / 2,906 |
| 累计文档 / 唯一文档 / 累计 passage / 唯一 passage | 9.2 / 6.1 / 9.5 / 6.2 | 8.7 / 6.1 / 9.0 / 6.2 | 9.8 / 9.8 / 9.9 / 9.9 |
| LLM / retrieval / embedding / reranker calls | 2.0 / 1.9 / 1.9 / 1.9 | 2.5 / 1.8 / 1.8 / 1.8 | 1.0 / 1.0 / 1.2 / 1.0 |
| Prompt / completion / total tokens | 2,786 / 2,318 / 5,104 | 3,329 / 2,688 / 6,017 | 1,549 / 901 / 2,450 |
| 编译 / 抽取 / 生成 LLM calls | 0 / 2.0 / 0 | 0 / 2.1 / 0.2 | 0 / 0 / 1.0 |
| 抽取 prompt / completion tokens | 2,786 / 2,318 | 2,917 / 2,489 | 0 / 0 |
| 生成 prompt / completion tokens | 0 / 0 | 412 / 200 | 1,549 / 901 |
| 执行期 provider calls | 5.8 | 6.1 | 3.2 |
| +共享编译 LLM calls / tokens / provider calls | 2.7 / 7,292 / 6.5 | 3.2 / 8,205 / 6.8 | N/A |
| 执行期 wall mean / P50 / P95 / P99 | 46.19 / 39.55 / 94.68 / 107.34 s | 43.31 / 38.55 / 80.91 / 93.26 s | 18.66 / 19.00 / 27.38 / 31.45 s |
| +共享编译 wall mean / P95 | 66.57 / 112.29 s | 63.70 / 115.33 s | N/A |
| Provider latency mean / P95 | 46.18 / 94.66 s | 43.25 / 80.75 s | 18.58 / 27.37 s |
| 执行 / 物化 / 生成时延 | 46.18 / 46.18 / 0 s | 38.55 / 38.55 / 4.75 s | 0 / 0 / 17.38 s |
| 内部 provider retry mean / benchmark retry count | 0 / 0 | 0.2 / 7 | 0.2 / 1 |
| 结构失败 / 修复 / grounding / local repair | 0.1 / 0.1 / 0 / 0 | 0.5 / 0.3 / 0 / 0 | 0 / 0 / 0 / 0 |
| plan fallback / evidence fallback / deterministic | 0 / 0 / 1.0 | 0 / 0.2 / 0.8 | 0 / 0 / 0 |
| polar / span normalization / reconciliation / row consensus | 0.4 / 0 / 0 / 0 | 0.4 / 0 / 0 / 0 | 0.4 / 0 / 0 / 0 |
| typed contract / answer / abstention / frozen replay / GEAF fold | 0 / 0 / 0 / 1.0 / 0 | 0 / 0 / 0 / 1.0 / 0.1 | 0 / 0 / 0 / 0 / 0 |
| operators executed / rewrite | 0.1 / 0 | 0.1 / 0 | 0 / 0 |
| join input / output rows | 1.8 / 0.9 | 1.4 / 0.7 | 0 / 0 |
| slots / joins / variables / outputs / operators / complexity | 1.9 / 0.8 / 1.9 / 1.0 / 0.1 / 5.7 | 1.8 / 0.7 / 1.9 / 1.0 / 0.1 / 5.5 | 0 / 0 / 0 / 0 / 0 / 0 |
| steps / LLM预算 / 检索预算 / step预算 | 1.9 / 0.0313 / 0.475 / 0.475 | 1.8 / 0.0391 / 0.450 / 0.450 | 0 / 0.0156 / 0.250 / 0 |
| 峰值 RSS 增量 / 最大中间绑定 / reoptimization | 0.993 MB / 1.3 / 0.9 | 3.443 MB / 1.1 / 0.8 | 0.200 MB / 0 / 0 |
| 平均 selectivity error / planner regret | 2.279 / 0 | 2.423 / 0 | N/A / N/A |
| 物化请求 / 物化 cache hit / reuse rate | 1.9 / 0 / 0 | 1.8 / 0 / 0 | 0 / 0 / N/A |
| 运行时 cache hit/miss / binding prune / early stop | 0/0 / 0 / 0 | 0/0 / 0 / 0 | 0/0 / 0 / 0 |
| 索引构建 / provider 时延 / embedding calls | 485.58 / 437.43 ms / 1.0 | 0.90 / 0 ms / 0 | 1.34 / 0 ms / 0 |
| 索引 cache hit/miss/rate | 11.2 / 9.0 / 0.555 | 20.2 / 0 / 1.000 | 20.2 / 0 / 1.000 |
| 索引大小 / phase token coverage | 85,697 bytes / 1.0 | 85,697 bytes / 1.0 | 85,697 bytes / 1.0 |

`accuracy` 和 DROP 指标在 2Wiki 上为 N/A。冷索引仍由第一个 SlotRAG 方法承担，在线 wall 排除索引；候选与 Hybrid 的 embedding calls 均包含最终成功记录中的 query 请求，历史失败请求另见 failure report。

唯一作用题给出清晰但不充分的收益：默认方法仍答错 `Baldwin de Redvers, 6th Earl of Devon`，候选答对 `Isabel Marshal`，EM/F1 从 0 升至 1，Evidence Recall 从 0.5 升至 1，NDCG 从 0.613 升至 0.832；slots/joins/steps/retrieval calls 从 `3/2/3/3` 降至 `2/1/2/2`。但是 constraint 版本仍要求抽取器输出已经绑定的 `baldwin` 字段，两次结构失败后 S2/S3 仅保留空 bindings，最终走 evidence-only fallback 和一次生成：目标 LLM calls 从 3 升至 5，tokens 从 10,558 升至 15,958，wall 从 75.35 升至 96.35 秒，provider calls 持平为 9。

另外 9 题 fold 全为 0，F1 与答案文本均 9/9 相同，说明语义作用域隔离成立；但随机结构失败使候选非目标题 calls `17→20`、tokens `40,479→44,212`、provider calls `49→52`，同样未满足“不恶化”门。全 10 题候选相对默认方法 retrieval calls `19→18`，但 LLM calls `20→25`、tokens `51,037→60,170`、provider calls `58→61`。成对 bootstrap 为默认对候选 0 胜/9 平/1 负，均值差与 Cliff's delta 均 -0.1，CI `[-0.3,0]`，`p=0.7108, p_holm=1`；小样本仅支持诊断，不支持显著性主张。

| 预注册假设 | 在线判定 | 依据 |
| --- | --- | --- |
| H39 导入与双哈希完整性 | 通过 | 10 imported snapshots、20 replay，所有 source/effective/provenance 审计为 0 错误。 |
| H40 保守作用域 | 通过 | 仅 `574...` fold=1，另外 9 题为 0；effective variant question 恰为 1。 |
| H41 语义修复 | 通过 | 目标题 F1 0→1，总体 F1 0.9→1.0，非目标题质量不变。 |
| H42 候选保留门 | 失败 | slots/joins/steps/retrieval 降低，但目标和非目标 calls/tokens 均增加，且目标触发 fallback + generation。 |

因此拒绝 schema16 的 **constraint-propagation** 实现，`slotrag-anchor-folding` 保持默认关闭，不把这次 0.1 F1 提升包装成已完成贡献。保留的是两点：同源计划下冗余实体锚确实是可修复的质量瓶颈；安全作用域和双哈希协议有效。下一候选必须把已知实体直接替换进消费者实参，使抽取 schema 不再要求返回该已知变量，而不是继续在 `constraints` 中保留它。完整机器判定见 `runs/vldb2027-diagnostic-v14/online-validation.json`。

#### schema v17：grounded entity constant substitution 与 v15 预注册

schema17 将表示从 `S2 MotherOf(?mother, ?baldwin), constraint baldwin=...` 改为 `S2 MotherOf(?mother, "Baldwin ...")`。新候选 `slotrag-anchor-substitution` 先复用 schema16 的全部安全判定，再把唯一消费者中的已知变量替换为问题原文常量，同时删除该变量的 constraint/type；若消费者因此没有任何未知变量或完整计划校验失败，则原样返回。该操作暂称 **Grounded Entity Constant Substitution (GECS)**，与已拒绝的 constraint GEAF 使用不同方法名和指标 `grounded_entity_anchor_substitutions`。

真实 v13 快照离线扫描仍只命中 `574...` 一题。source hash 为 `7a7816...efe8`，constraint effective hash 为 `2066a0...85d5`，constant-argument effective hash 为 `96c5b9...e5a`；后者把 slots/joins/variables/complexity 从 `3/2/3/9` 降为 `2/1/2/6`。另外 9 题 substitution=0 且 effective hash 与 source 完全相同。schema17 审计进一步报告 extra effective variants 与单题最大 variant 数；四路运行预期在目标上得到 2 个额外变体、最大 3 个有效计划。

v15 固定为 `runs/vldb2027-diagnostic-v15`、阶段 `entity_anchor_substitution_gate`，运行默认 SlotRAG、constraint GEAF、constant-argument GECS 和 Hybrid，各 10 题。三种 SlotRAG 方法共享导入的 v13 计划，因而能在同一服务时段直接比较“无变换 / 保留已知变量约束 / 删除已知变量并常量化”。样本与数据审计 SHA-256 分别仍为 `5bcc22...1a4` 和 `a24ad3...67e`；全仓 `138 passed, 1 skipped`，指纹 `cff52d76...ac20f`。机器离线记录见 v15 `offline-validation.json` 与 `anchor-substitution-scope-audit.json`。

```text
H43（四路同源完整性）：10 imported snapshots、30 SlotRAG replay；source hash 每题一致，所有 provenance/result/effective hash 错误为 0；目标恰有 2 个 extra effective variants、单题最大 3 variants。
H44（表示隔离）：constraint 与 substitution 都只在 574... 各触发 1 次，其余 9 题两项均为 0；substitution 目标 profile 必须为 2 slots、1 join、2 variables、complexity 6。
H45（无 fallback 的语义修复）：substitution 在 574... 答 Isabel Marshal、F1=1，产生非空 joined rows，deterministic_answers=1，evidence_only_fallbacks=0、generation calls=0；总体 F1 不低于默认方法。
H46（目标因果效率）：substitution 目标 steps/retrieval/extraction/total LLM calls 均为 2，结构失败/修复为 0，tokens 严格低于默认 SlotRAG 与 constraint GEAF；40/40 final ok。非目标题以 hash/触发隔离为硬门，随机 calls/tokens 完整报告但不再作为方法无作用时的硬门。
```

H46 对非目标题的处理在看结果前已明确：当 effective plan 完全相同时，在线 LLM 抽取的随机结构失败不是变换因果效应，不能用一次波动否定表示变换；但不得隐藏，仍需逐题和历史 attempt 报告。相反，目标题三种有效计划不同，必须以严格 calls/tokens、fallback 和 deterministic 条件判定。即使 H43-H46 全过，也只说明下一步值得扩展到 50 题调优与 200 题验证，不等于达到 VLDB 证据标准。

#### schema v17 在线结果（v15）

`2026-07-22T16:46:23+08:00` 与中断恢复后的 `16:57:46+08:00`，Agnes、embedding、reranker 三项 doctor 均为 HTTP 200。首次串行进程在 21 条结果落盘后被实验控制端中断，没有生成失败 attempt；随后按用户给定的并发 2 将剩余 GECS 与 Hybrid 分配到两个互斥方法 worker。允许上限为 30 RPM、运行上限为 20 RPM；本次 Agnes 75 次成功请求的平均时延为 18.88 秒，并发 2 对应估算 6.36 RPM，未触碰上限。两个 worker 错峰写入不同 method 目录，启动前 10 个冻结计划已全部存在，因此没有 plan、manifest 或 item 写竞争。

最终为 40/40 条 schema17 final `ok`、40 个 immutable attempts、0 个 benchmark retry、40/40 有证据金标。执行期 Agnes 共 81 attempts、75 successes、6 次提供方内部重试；这些 retry 已计入 calls、tokens 和时延，但没有用覆盖式重跑隐藏。双哈希审计为 10/10 imported valid snapshots、10 个成功 plan attempts、30 个 SlotRAG replay；missing provenance/result/effective hash、hash mismatch、unknown snapshot 与 inconsistent source pair 全为 0。恰好 1 个问题具有有效计划分歧、2 个 extra variants、单题最大 3 variants，符合四路预注册。共享编译仍为 7 calls、21,880 tokens、0 provider retry、2 次结构失败/修复、0 fallback。

下表执行期均值覆盖汇总器当前全部核心质量、证据、调用、token、时延、鲁棒性、计划、连接、资源和索引指标；完整 130+ 列逐题与聚合文件保存在 v15 `summaries/entity_anchor_substitution_gate/`。`accuracy` 与 DROP 指标在 2Wiki 上为 N/A。

| v15 2Wiki entity-anchor substitution gate（10 题/方法） | SlotRAG | GEAF constraint | GECS constant | Hybrid |
| --- | ---: | ---: | ---: | ---: |
| EM / F1 | 0.900 / 0.900 | 1.000 / 1.000 | 0.900 / 0.900 | 1.000 / 1.000 |
| Evidence Recall / MRR | 0.825 / 1.000 | 0.925 / 1.000 | 0.825 / 1.000 | 1.000 / 1.000 |
| Evidence Recall@1 / @5 / @10 | 0.450 / 0.825 / 0.825 | 0.450 / 0.875 / 0.925 | 0.450 / 0.825 / 0.825 | 0.450 / 0.925 / 1.000 |
| Evidence Precision@1 / @5 / @10 | 1.000 / 0.380 / 0.190 | 1.000 / 0.400 / 0.210 | 1.000 / 0.380 / 0.190 | 1.000 / 0.440 / 0.240 |
| Evidence Hit@1 / @5 / @10 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 |
| Evidence NDCG@10 | 0.862 | 0.922 | 0.862 | 0.938 |
| 检索证据数 / 文档数 / 文本字符 | 2.1 / 2.0 / 974 | 3.0 / 2.6 / 1,953 | 2.0 / 1.9 / 973 | 9.9 / 9.8 / 2,906 |
| 累计文档 / 唯一文档 / 累计 passage / 唯一 passage | 9.2 / 6.1 / 9.5 / 6.2 | 8.7 / 6.1 / 9.0 / 6.2 | 8.7 / 6.1 / 9.0 / 6.2 | 9.8 / 9.8 / 9.9 / 9.9 |
| LLM / retrieval / embedding / reranker calls | 2.5 / 1.9 / 1.9 / 1.9 | 2.3 / 1.8 / 1.8 / 1.8 | 2.2 / 1.8 / 1.8 / 1.8 | 1.1 / 1.0 / 1.0 / 1.0 |
| Prompt / completion / total tokens | 3,045 / 2,599 / 5,645 | 3,227 / 2,655 / 5,882 | 2,922 / 2,395 / 5,317 | 1,549 / 854 / 2,403 |
| 编译 / 抽取 / 生成 LLM calls | 0 / 2.1 / 0.1 | 0 / 2.0 / 0.2 | 0 / 2.1 / 0 | 0 / 0 / 1.0 |
| 抽取 prompt / completion tokens | 2,981 / 2,488 | 2,794 / 2,411 | 2,922 / 2,395 | 0 / 0 |
| 生成 prompt / completion tokens | 64 / 111 | 433 / 244 | 0 / 0 | 1,549 / 854 |
| 执行期 provider calls | 6.3 | 5.9 | 5.8 | 3.1 |
| +共享编译 LLM calls / tokens / provider calls | 3.2 / 7,833 / 7.0 | 3.0 / 8,070 / 6.6 | 2.9 / 7,505 / 6.5 | N/A |
| 执行期 wall mean / P50 / P95 / P99 | 47.64 / 38.73 / 92.32 / 112.79 s | 41.93 / 40.24 / 75.90 / 82.39 s | 39.69 / 41.56 / 62.28 / 64.81 s | 15.72 / 15.21 / 21.40 / 21.77 s |
| +共享编译 wall mean / P95 | 68.03 / 126.25 s | 62.32 / 113.25 s | 60.08 / 109.12 s | N/A |
| Provider latency mean / P95 | 47.53 / 92.30 s | 41.90 / 75.89 s | 39.66 / 62.27 s | 15.69 / 21.28 s |
| 执行 / 物化 / 生成时延 | 46.32 / 46.32 / 1.32 s | 38.59 / 38.59 / 3.34 s | 39.69 / 39.69 / 0 s | 0 / 0 / 15.39 s |
| 内部 provider retry mean / benchmark retry count | 0.3 / 0 | 0.1 / 0 | 0.1 / 0 | 0.1 / 0 |
| 结构失败 / 修复 / grounding / local repair | 0.2 / 0.2 / 0 / 0 | 0.3 / 0.2 / 0 / 0 | 0.3 / 0.3 / 0 / 0 | 0 / 0 / 0 / 0 |
| plan fallback / evidence fallback / deterministic | 0 / 0 / 0.9 | 0 / 0.1 / 0.8 | 0 / 0 / 1.0 | 0 / 0 / 0 |
| polar / span normalization / reconciliation / row consensus | 0.4 / 0 / 0 / 0 | 0.4 / 0 / 0 / 0.1 | 0.4 / 0 / 0 / 0 | 0.4 / 0 / 0 / 0 |
| typed contract / answer / abstention / frozen replay | 0 / 0 / 0 / 1.0 | 0 / 0 / 0 / 1.0 | 0 / 0 / 0 / 1.0 | 0 / 0 / 0 / 0 |
| GEAF fold / GECS substitution | 0 / 0 | 0.1 / 0 | 0 / 0.1 | 0 / 0 |
| operators executed / rewrite | 0.1 / 0 | 0.1 / 0 | 0.1 / 0 | 0 / 0 |
| join input / output rows | 1.8 / 0.9 | 1.5 / 0.8 | 1.6 / 0.8 | 0 / 0 |
| slots / joins / variables / outputs / operators / complexity | 1.9 / 0.8 / 1.9 / 1.0 / 0.1 / 5.7 | 1.8 / 0.7 / 1.9 / 1.0 / 0.1 / 5.5 | 1.8 / 0.7 / 1.8 / 1.0 / 0.1 / 5.4 | 0 / 0 / 0 / 0 / 0 / 0 |
| steps / LLM预算 / 检索预算 / step预算 | 1.9 / 0.0391 / 0.475 / 0.475 | 1.8 / 0.0359 / 0.450 / 0.450 | 1.8 / 0.0344 / 0.450 / 0.450 | 0 / 0.0172 / 0.250 / 0 |
| 峰值 RSS 增量 / 最大中间绑定 / reoptimization | 2.209 MB / 1.2 / 0.9 | 0.600 MB / 1.3 / 0.8 | 2.461 MB / 1.2 / 0.8 | 1.718 MB / 0 / 0 |
| 平均 selectivity error / planner regret | 2.319 / 0 | 2.293 / 0 | 2.319 / 0 | N/A / N/A |
| 物化请求 / 物化 cache hit / reuse rate | 1.9 / 0 / 0 | 1.8 / 0 / 0 | 1.8 / 0 / 0 | 0 / 0 / N/A |
| 运行时 cache hit/miss / binding prune / early stop | 0/0 / 0 / 0 | 0/0 / 0 / 0 | 0/0 / 0 / 0 | 0/0 / 0 / 0 |
| 索引构建 / provider 时延 / embedding calls | 518.00 / 476.37 ms / 0.9 | 1.28 / 0 ms / 0 | 1.23 / 0 ms / 0 | 1.19 / 0 ms / 0 |
| 索引 cache hit/miss/rate | 12.2 / 8.0 / 0.605 | 20.2 / 0 / 1.000 | 20.2 / 0 / 1.000 | 20.2 / 0 / 1.000 |
| 索引大小 / phase token coverage | 85,697 bytes / 1.0 | 85,697 bytes / 1.0 | 85,697 bytes / 1.0 | 85,697 bytes / 1.0 |

目标题 `574...` 将表示变化和语义失败分开了。默认方法错答 `Baldwin de Redvers, 6th Earl of Devon`；constraint GEAF 依靠 evidence fallback + generation 答对 `Isabel Marshal`；constant GECS 则在无 fallback、非空 joined rows 和 deterministic answer 的情况下错答 `Baldwin de Redvers, 7th Earl of Devon`。GECS 的 `S2 MotherOf(?mother, "Baldwin...")` 正确抽到 `Amice de Clare`，但 `S3 MotherOf(?grandmother, ?mother)` 把原始 Baldwin 锚回填成 grandmother。说明常量替换消除了已知字段 schema 冲突，却没有解决 predicate 参数的方向与角色约束。

| 目标题指标 | SlotRAG | GEAF constraint | GECS constant | Hybrid |
| --- | ---: | ---: | ---: | ---: |
| EM / F1 | 0 / 0 | 1 / 1 | 0 / 0 | 1 / 1 |
| Evidence Recall / NDCG@10 | 0.5 / 0.613 | 1.0 / 0.832 | 0.5 / 0.613 | 1.0 / 0.798 |
| slots / joins / variables / complexity | 3 / 2 / 3 / 9 | 2 / 1 / 3 / 7 | 2 / 1 / 2 / 6 | 0 / 0 / 0 / 0 |
| steps / retrieval / extraction / generation / total LLM | 3 / 3 / 4 / 0 / 4 | 2 / 2 / 3 / 1 / 4 | 2 / 2 / 3 / 0 / 3 | 0 / 1 / 0 / 1 / 1 |
| prompt / completion / total tokens | 8,505 / 7,552 / 16,057 | 9,991 / 6,481 / 16,472 | 6,682 / 5,023 / 11,705 | 2,975 / 875 / 3,850 |
| provider calls / wall | 10 / 117.90 s | 8 / 84.01 s | 7 / 65.44 s | 3 / 11.89 s |
| structured failure / repair | 1 / 1 | 2 / 1 | 1 / 1 | 0 / 0 |
| evidence fallback / deterministic / joined rows | 0 / 1 / 2 | 1 / 0 / 0 | 0 / 1 / 1 | 0 / 0 / 0 |
| fold / substitution | 0 / 0 | 1 / 0 | 0 / 1 | 0 / 0 |

GECS 目标结构成本确有局部改善：相对默认方法少 1 step、1 retrieval、1 LLM call、4,352 tokens，且相对 GEAF 少 1 LLM call、4,767 tokens并消除生成；但未达到“恰好 2 次抽取/总 LLM、0 结构失败”的门，更重要的是答案仍错。其余 9 题三种 SlotRAG 的 effective/source hash 完全相同、fold/substitution 均为 0、F1 与答案文本均 9/9 一致。对应执行波动完整保留：默认 / GEAF / GECS 的非目标 LLM calls 为 `21/19/19`，tokens 为 `40,388/42,345/41,462`，provider calls 为 `53/51/51`。

全样本 SlotRAG 对 GECS 为 0 胜/10 平/0 负、均值差与 Cliff's delta 为 0、CI `[0,0]`、`p=p_holm=1`；GECS 没有质量增益。默认方法对 GEAF 仍为 0 胜/9 平/1 负、均值差 -0.1、CI `[-0.3,0]`、`p=0.7108, p_holm=1`；对 Hybrid 为相同胜负与区间，`p=0.7128, p_holm=1`。10 题诊断不支持显著性主张。

| 预注册假设 | 在线判定 | 依据 |
| --- | --- | --- |
| H43 四路同源完整性 | 通过 | 10 imported snapshots、30 replay，所有双哈希/provenance 检查为 0 错误，extra/max variants 为 2/3。 |
| H44 表示隔离 | 通过 | 两候选都只改变 `574...`；GECS 目标 profile 精确为 2 slots、1 join、2 variables、complexity 6。 |
| H45 无 fallback 的语义修复 | 失败 | 虽有非空 joined row、deterministic=1、fallback/generation=0，但错答 Baldwin 7th，目标 F1 仍为 0，总体 F1 仍为 0.9。 |
| H46 目标因果效率 | 失败 | 40/40 ok 且 tokens 下降，但目标 extraction/total LLM=3 而非 2，结构失败/修复为 1/1。 |

因此拒绝 schema17 **GECS** 作为保留方法，`slotrag-anchor-substitution` 继续默认关闭。保留的是安全常量替换、有效计划多变体审计和“无 fallback 的确定性错误”这一诊断证据；下一候选必须显式验证关系 predicate 的参数角色与当前问题实体，防止下游槽把已知锚复制到输出字段。机器判定见 `runs/vldb2027-diagnostic-v15/online-validation.json`，完整汇总见同运行的 `summaries/entity_anchor_substitution_gate/`。

#### schema v18：role-projected grounded extraction 与 v16 预注册

schema17 的错误不是 GECS 计划形状错误，而是 materializer 的抽取契约过浅。旧工具对 `MotherOf(?grandmother, ?mother)` 只声明两个无描述字符串字段；即使 `?mother=Amice de Clare` 已由上一跳传播，仍要求模型重复输出 `mother`。同时，它没有说明 `grandmother` 是有序关系的第一个参数，也不知道被替换的 Baldwin 是上游输入而不是下游答案。因此 schema18 增加默认关闭的 `slotrag-role-projected-substitution`，暂称 **Role-Projected Grounded Extraction (RPGE)**。

RPGE 先执行与 GECS 完全相同的安全常量替换，并额外保留精确的上游锚值。只有替换实际发生时才启用角色契约；否则构造 materializer 的参数与默认方法一致，保证非目标题完全惰性。启用后的每个槽执行三项局部操作：

```text
1. bound-field projection
   工具 schema 只请求尚未绑定的变量；已传播字段由执行器验证证据后合并，不再要求 LLM 回显。

2. ordered-role annotation
   每个未知字段携带完整签名和参数位置，例如：
   grandmother = argument 1 of MotherOf(?grandmother, ?mother)。

3. protected-anchor validation
   被 GECS 替换的上游锚不得赋给下游未知字段；若发生则拒绝该行，并在一次修复提示中给出有序签名、已知绑定和受保护锚。
```

候选还要求所有新抽取值与传播值都在所声明的 source title/span 中落地。新增审计指标为 `role_projected_extraction_contracts`、`known_binding_fields_projected` 和 `protected_anchor_rejections`。保护规则只覆盖安全锚替换触发的链式查询；可能合法回到起始实体的环查询不在当前候选适用域，不能据此泛化。

该设计形成两个干净对照：GECS 与 RPGE 的 effective plan hash 完全相同，二者差异只来自抽取契约；默认 / GEAF / GECS 则继续分离不变计划、constraint 表示与 constant 表示。v16 固定为 `runs/vldb2027-diagnostic-v16`、阶段 `entity_anchor_role_gate`，运行默认 SlotRAG、GEAF、GECS、RPGE 和 Hybrid，各 10 题，共 50 条最终记录。四种 SlotRAG 导入 v13 的同一源计划，预期 10 个 imported snapshots、40 个 replay。

离线扫描 10 个快照仅在 `574...` 启用 RPGE，保护值精确为 `Baldwin De Redvers, 7Th Earl Of Devon`；RPGE 与 GECS 的 effective hash 均为 `96c5b9...e5a`，目标 profile 均为 2 slots、1 join、2 variables、complexity 6。目标预期执行 2 个 role contracts，第二槽投影 1 个已知 `mother` 字段；其余 9 题 RPGE 完全关闭，source/effective hash 相同。数据审计与样本哈希仍为 `a24ad3...67e` 和 `5bcc22...1a4`。

全仓为 `144 passed, 1 skipped`；`compileall`、pilot YAML 与 `git diff --check` 通过，冻结源码指纹为 `01f720e3...bb89`。机器离线记录见 v16 `offline-validation.json` 与 `role-projection-scope-audit.json`。在线仍采用并发 2、允许 30 RPM、运行上限 20 RPM；worker 必须按互斥方法分区，禁止多个 worker 抢同一 method/question。

```text
H47（五路同源完整性）：10 imported snapshots、40 SlotRAG replay；所有 source/effective/result/provenance 错误为 0。目标的有效计划集合只能是 source、constraint、substitution 三种，GECS 与 RPGE 必须同 hash；extra/max variants 为 2/3。

H48（RPGE 作用域与审计）：只在 574... 上 substitution=1 且 role contracts=2、known fields projected=1；保护值精确为问题锚。其余 9 题 RPGE 三项指标均为 0，source/effective hash 相同，GECS/RPGE 的 F1 与答案文本均逐题一致。

H49（角色语义修复）：RPGE 在 574... 答 Isabel Marshal、F1=1，产生非空 joined rows，deterministic=1、evidence fallback=0、generation calls=0；最终 grandmother 不得等于受保护锚，S3 证据必须来自明确包含 Isabel Marshal 的 source。

H50（受控效率与完整性）：50/50 final ok；RPGE 目标 steps/retrieval 均为 2，extraction/total LLM calls 不超过 3，结构失败/修复和 protected-anchor rejection 各不超过 1；total tokens 严格低于同次默认 SlotRAG 与 GEAF，且总体 F1 不低于默认方法。时延和非目标题随机成本完整报告但不作硬门。
```

H50 在在线前允许最多一次角色拒绝修复，因为 protected-anchor validation 的价值正是把“确定性错误行”变成可审计拒绝；若第一跳即正确则 rejection 可以为 0，但不得要求为了满足指标而人为触发。若 H49 失败，即使 token 更低也拒绝；若 H49 通过但 H50 失败，同样不保留。即使四项全部通过，也只进入 50 题调优，不作 VLDB 级有效性结论。

#### schema v18 在线结果（v16）：语义通过，遥测门失败

v16 在冻结指纹 `01f720...bb89` 下先离线导入 10 个计划，再以两个互斥 worker 执行五种方法。最终 50/50 schema18 final `ok`、50 immutable attempts、0 benchmark retry；Agnes 为 99 attempts / 95 successes / 4 internal retries，平均请求时延 16.36 秒，并发 2 估算 7.33 RPM。冻结审计为 10 imported valid snapshots、40 replay、所有哈希/provenance 错误为 0，extra/max effective variants 为 2/3。

| v16 2Wiki role gate（10 题/方法） | SlotRAG | GEAF | GECS | RPGE | Hybrid |
| --- | ---: | ---: | ---: | ---: | ---: |
| EM / F1 | 0.900 / 0.900 | 0.900 / 0.900 | 0.900 / 0.900 | 1.000 / 1.000 | 1.000 / 1.000 |
| Evidence Recall / NDCG@10 | 0.825 / 0.862 | 0.825 / 0.862 | 0.825 / 0.862 | 0.875 / 0.900 | 1.000 / 0.938 |
| LLM / retrieval / embedding / reranker calls | 2.4 / 1.9 / 1.9 / 1.9 | 2.2 / 1.8 / 1.8 / 1.8 | 2.1 / 1.8 / 1.8 / 1.8 | 2.1 / 1.8 / 1.8 / 1.8 | 1.1 / 1.0 / 1.0 / 1.0 |
| Prompt / completion / total tokens | 3,318 / 2,698 / 6,015 | 2,818 / 2,654 / 5,472 | 2,909 / 2,435 / 5,344 | 2,713 / 2,240 / 4,954 | 1,549 / 902 / 2,451 |
| 抽取 / 生成 LLM calls | 2.2 / 0.1 | 2.1 / 0 | 2.1 / 0 | 2.0 / 0 | 0 / 1.0 |
| 执行期 provider calls | 6.2 | 5.8 | 5.7 | 5.7 | 3.1 |
| wall mean / P50 / P95 | 36.96 / 30.93 / 71.61 s | 34.43 / 35.30 / 53.33 s | 32.67 / 27.24 / 58.27 s | 36.97 / 38.18 / 54.40 s | 19.62 / 16.94 / 33.21 s |
| 结构失败 / 修复 / evidence fallback / deterministic | 0.3 / 0.3 / 0 / 0.9 | 0.3 / 0.3 / 0 / 1.0 | 0.3 / 0.3 / 0 / 1.0 | 0.2 / 0.2 / 0 / 1.0 | 0 / 0 / 0 / 0 |
| fold / substitution | 0 / 0 | 0.1 / 0 | 0 / 0.1 | 0 / 0.1 | 0 / 0 |
| role contracts / projected fields / protected rejection（记录值） | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | **0 / 0 / 0** | 0 / 0 / 0 |
| join input / output | 1.9 / 1.0 | 1.6 / 0.8 | 1.6 / 0.8 | 1.6 / 0.8 | 0 / 0 |
| slots / joins / variables / complexity | 1.9 / 0.8 / 1.9 / 5.7 | 1.8 / 0.7 / 1.9 / 5.5 | 1.8 / 0.7 / 1.8 / 5.4 | 1.8 / 0.7 / 1.8 / 5.4 | 0 / 0 / 0 / 0 |
| steps | 1.9 | 1.8 | 1.8 | 1.8 | 0 |

完整 130+ 指标、时延分位数、索引/缓存、资源、分层与逐题数据仍保存在 v16 summary 目录。目标题上，默认 / GEAF / GECS 都错答 Baldwin 7th；RPGE 与 Hybrid 答对 Isabel Marshal。GECS 与 RPGE effective hash 相同，前者为 3 calls、11,667 tokens、1 次结构失败/修复，后者为 2 calls、7,109 tokens、0 失败/修复，且 S3 证据来自 `Amice de Clare#0`，joined row=1、deterministic=1、fallback/generation=0。RPGE tokens 同时低于本次 SlotRAG 的 20,224 和 GEAF 的 7,881。

但是 RPGE final record 的 `role_projected_extraction_contracts / known_binding_fields_projected / protected_anchor_rejections` 为 `0/0/0`。代码审计确认 materializer 已执行角色契约，但 `AdaptiveExecutor.execute` 的显式指标合并列表遗漏了三项字段，导致它们没有进入最终 record。这不是可以事后回填的展示问题，而是 H48 所要求的可审计证据缺失。

| 预注册假设 | 在线判定 | 依据 |
| --- | --- | --- |
| H47 五路同源完整性 | 通过 | 10 imported、40 replay、双哈希与 provenance 全部无错误，variants=2/3。 |
| H48 RPGE 作用域与审计 | **失败** | 目标记录值为 contracts/projected=`0/0`，不满足预注册 `2/1`；历史记录不修改。 |
| H49 角色语义修复 | 通过 | Isabel Marshal、F1=1、joined/deterministic=1、无 fallback/generation，S3 证据正确。 |
| H50 受控效率与完整性 | 通过 | 50/50 ok；目标 2 calls、0 repair、7,109 tokens，低于默认与 GEAF。 |

因此 v16 不足以保留 RPGE，尽管语义与效率信号同时通过。下一步只修复 executor 的指标传播，增加 materializer→executor→record 集成测试并提升记录 schema；不修改 RPGE prompt、保护规则或 H49/H50 阈值。机器判定见 `runs/vldb2027-diagnostic-v16/online-validation.json`。

#### schema v19：RPGE 遥测闭环与 v17 预注册

schema19 只修复 `AdaptiveExecutor.execute` 的指标传播：把 materializer 已产生的 `role_projected_extraction_contracts`、`known_binding_fields_projected`、`protected_anchor_rejections` 纳入逐槽累计。新增集成测试从假 materializer 注入 `2/1/1` 并验证 executor 原样保留；runner 记录版本升为 19。RPGE 的计划变换、抽取 prompt、保护规则、答案出口和预算阈值均未修改，v16 的 50 条 schema18 记录也不回填。

v17 固定为 `runs/vldb2027-diagnostic-v17`、阶段 `entity_anchor_role_telemetry_gate`，只运行默认 SlotRAG、GECS 与 RPGE，各 10 题，共 30 条最终记录。三路均导入 v13 的同一冻结计划；预期 10 个 imported snapshots、30 个 replay。这样同时保留无变换对照、同 effective-plan 的语义对照与同次成本基线，不重复运行与遥测闭环无关的 GEAF/Hybrid。

公开数据审计哈希仍为 `a24ad382...67e`，2Wiki 样本与 v16 逐字节一致，哈希仍为 `5bcc229...1a4`。离线作用域仍只有 `574...` 启用 RPGE，GECS/RPGE 目标 effective hash 均为 `96c5b9...e5a`，保护锚为 `Baldwin De Redvers, 7Th Earl Of Devon`，计划 profile 为 2 slots、1 join、2 variables、complexity 6。全仓为 `145 passed, 1 skipped`，`compileall`、pilot YAML 和 `git diff --check` 通过；冻结源码指纹为 `ef9fb958...c96c`。机器记录见 v17 `offline-validation.json` 与 `role-projection-scope-audit.json`。

```text
H51（三路同源与 schema 完整性）：30/30 final ok 且全部为 schema19；10 imported snapshots、30 replay，所有 source/effective/result/provenance 检查为 0。只有目标题出现第二个 effective-plan variant，GECS 与 RPGE 必须同 hash。

H52（遥测传播与作用域）：目标题 RPGE 必须记录 role contracts=2、known fields projected=1、protected-anchor rejection∈{0,1}；其余 9 个 RPGE 记录及全部默认/GECS 记录三项均为 0。拒绝次数允许为 0，因为正确首答不应被人为改坏以制造计数。

H53（语义与成本复现）：RPGE 在 574... 答 Isabel Marshal、F1=1、joined rows>0、deterministic=1、fallback/generation=0，最终证据来自包含 Isabel Marshal 的 source；steps/retrieval=2、extraction/total LLM≤3，tokens 严格低于同次默认 SlotRAG 与 GECS。RPGE 总体 F1 不低于默认方法。
```

在线调度固定为两个互斥 worker：worker A 只跑默认方法 10 条，worker B 跑 GECS+RPGE 20 条；任务并发数为 2。服务许可上限记为 30 RPM，但运行硬上限按 20 RPM，若按观测时延估算将超过 20 RPM 则主动降速。任何失败只通过 immutable attempt 续跑，不覆盖旧 attempt，也不启动第三 worker。H51-H53 全部通过才把 RPGE 作为下一轮 50 题调优候选；本次仍不构成 VLDB 级结论。

#### schema v19 在线结果（v17）：遥测闭环通过

v17 最终得到 30/30 schema19 final `ok`，共保留 33 个 immutable attempts。首轮有 1 次默认方法空答案失败和 2 次 RPGE `provider_connect` 失败；第二次 doctor 三服务均为 HTTP 200 后，以单 worker 逐项生成 attempt 2，三条均恢复，原 attempt 1 未删除。冻结计划审计为 10 imported valid snapshots、30 replay，所有 source/effective/result/provenance 错误为 0；只有 `574...` 出现额外 effective variant，GECS 与 RPGE 的目标 hash 同为 `96c5b9...e5a`。

| v17 2Wiki telemetry gate（10 题/方法） | SlotRAG | GECS | RPGE |
| --- | ---: | ---: | ---: |
| EM / F1 | 0.900 / 0.900 | 0.900 / 0.900 | **1.000 / 1.000** |
| Evidence Recall / NDCG@10 | 0.875 / 0.900 | 0.875 / 0.900 | 0.875 / 0.900 |
| LLM / retrieval / embedding / reranker calls | 2.5 / 1.7 / 1.7 / 1.7 | 2.1 / 1.8 / 1.8 / 1.8 | **2.0 / 1.8 / 1.8 / 1.8** |
| Prompt / completion / total tokens | 2,924 / 2,718 / 5,642 | 2,905 / 2,507 / 5,412 | **2,590 / 1,846 / 4,436** |
| Extraction / generation LLM calls | 2.0 / 0.2 | 2.1 / 0 | **1.9 / 0** |
| 执行期 provider calls | 5.9 | 5.7 | **5.6** |
| wall mean / P50 / P95 | 35.82 / 26.46 / 66.83 s | 29.84 / 19.22 / 60.51 s | 30.22 / 25.90 / **50.87 s** |
| 结构失败 / 修复 / evidence fallback / deterministic | 0.5 / 0.3 / 0.2 / 0.8 | 0.3 / 0.3 / 0 / 1.0 | **0.1 / 0.1 / 0 / 1.0** |
| substitution / role contracts / projected / rejection | 0 / 0 / 0 / 0 | 0.1 / 0 / 0 / 0 | **0.1 / 0.2 / 0.1 / 0** |
| join input / output | 1.4 / 0.7 | 1.6 / 0.8 | 1.6 / 0.8 |
| slots / joins / variables / complexity | 1.9 / 0.8 / 1.9 / 5.7 | 1.8 / 0.7 / 1.8 / 5.4 | 1.8 / 0.7 / 1.8 / 5.4 |
| steps | 1.7 | 1.8 | 1.8 |
| index build mean / cache-hit rate | 237.39 ms / 0.605 | 260.67 ms / 0.645 | 1.26 ms / 1.000 |

RPGE 的 aggregate role contracts/projected 为 `0.2/0.1`，恰好对应唯一目标题的 `2/1` 除以 10；protected rejection 为 0，说明本次两跳均首答正确而没有人为触发拒绝。其余 9 个 RPGE 记录和全部 20 个控制记录的三项 role 指标均为 0。RPGE 后运行而命中共享 embedding cache，因此 index build/cache 数字不作为方法优势；质量、抽取 token 和执行期 LLM 指标才用于本门判定。完整 130+ 指标、分层、逐题、失败 attempt、配对 bootstrap 与冻结计划审计保存在 v17 `summaries/entity_anchor_role_telemetry_gate/`。

| `574...` 目标题 | SlotRAG | GECS | RPGE |
| --- | ---: | ---: | ---: |
| answer / F1 | evidence insufficient / 0 | Baldwin 7th / 0 | **Isabel Marshal / 1** |
| Evidence Recall / NDCG@10 | 0.5 / 0.613 | 0.5 / 0.613 | **1.0 / 1.0** |
| steps / retrieval / extraction / total LLM | 1 / 1 / 2 / 5 | 2 / 2 / 3 / 3 | **2 / 2 / 2 / 2** |
| prompt / completion / total tokens | 6,023 / 5,833 / 11,856 | 6,592 / 4,651 / 11,243 | **4,591 / 2,300 / 6,891** |
| provider calls / wall | 7 / 70.80 s | 7 / 51.92 s | **6 / 44.86 s** |
| structured failure / repair | 2 / 1 | 1 / 1 | **0 / 0** |
| fallback / generation / deterministic / joined rows | 1 / 1 / 0 / 0 | 0 / 0 / 1 / 1 | **0 / 0 / 1 / 1** |
| role contracts / projected / protected rejection | 0 / 0 / 0 | 0 / 0 / 0 | **2 / 1 / 0** |

RPGE 的第二条证据为 `Amice de Clare#0`，span 明确包含 “daughter of ... Isabel Marshal”；最终 grandmother 不等于受保护 Baldwin 锚。RPGE 相对同次默认方法少 3 个执行期 LLM calls、4,965 tokens，相对同 effective-plan 的 GECS 少 1 call、4,352 tokens，同时把目标题 F1 从 0 提升到 1。默认方法的最终记录来自 attempt 2；其 attempt 1 的空答案失败仍计入 failure report，不能把最终 30/30 ok 误写成无失败运行。

实际在线窗口共记录 Agnes 77 attempts / 67 successes / 8 internal retries，平均 attempt 时延 14.39 秒；按首末 attempt 完成时间观测为 4.93 RPM，按并发 2 与平均时延反推为 8.34 RPM，均低于 20 RPM 运行硬上限和 30 RPM 服务许可。连接失败发生后续跑主动降为并发 1。

| 预注册假设 | 在线判定 | 依据 |
| --- | --- | --- |
| H51 三路同源与 schema 完整性 | **通过** | 30/30 final ok、全为 schema19；10 imported、30 replay，所有哈希/provenance 错误为 0，variants=1/2。 |
| H52 遥测传播与作用域 | **通过** | 目标 RPGE 精确记录 `2/1/0`；其余 RPGE 与全部控制记录均为 `0/0/0`。 |
| H53 语义与成本复现 | **通过** | Isabel Marshal、F1=1、正确 evidence、2 calls、6,891 tokens，低于同次 SlotRAG 与 GECS。 |

默认 SlotRAG 对 RPGE 的配对结果为 0 胜/9 平/1 负，均值差 -0.1、Cliff's delta -0.1、CI `[-0.3,0]`、`p=0.7108, p_holm=1`；10 题仅支持因果诊断，不能主张统计显著。schema19 关闭了 v16 的遥测缺口，因此 RPGE 作为**默认关闭**候选进入预注册的 50 题调优阶段；保留结论不等于默认启用，更不等于达到 VLDB 2027 的最终有效性标准。机器判定见 v17 `online-validation.json`。

#### schema v19：v18 随机 50 题自然作用域预注册

v18 固定为 `runs/vldb2027-diagnostic-v18`、阶段 `entity_anchor_role_tune`。2Wiki train 的 seed-2027 分层样本为 50 题，哈希 `4f8f91f...d42c`，其中 bridge-comparison/comparison/compositional/inference 为 `11/15/22/2`。采样器的 50 题集合完整包含 v17 的 10 题，故本轮含 40 个新增问题，也含已知 `574...`；它是调优和自然作用域发现集，不是独立验证集，所有范围门必须同时报告“总触发”和“新增 40 题触发”。

本轮先只获取 50 个默认 SlotRAG 共享计划，不执行检索与回答。计划按确定性 sample index mod 2 分给两个 worker，并发 2；许可 30 RPM、运行硬上限 20 RPM。每题只有一个 source snapshot，失败 attempt 保留，只有 doctor 通过后才续跑。计划全部冻结后，离线对每题同时运行 GECS 常量替换和 RPGE 带保护值替换，审计 source/effective hash、计划 profile、保护锚和触发作用域。

为避免看到触发率后任意决定是否花费 150 条执行，本轮在计划调用前固定条件门：新增 40 题中至少 2 题触发、总触发至少 3 题，才运行默认/GECS/RPGE 三路各 50 条；若新增触发为 0–1，则在范围审计后停止，将“自然覆盖不足”作为结果，并构造单独标注的 relation-anchor stress set，不用大量惰性记录稀释已知目标题。

```text
H54（计划获取完整性）：50/50 source snapshots 有效；每题恰好一个 final snapshot，所有 input/plan hash、source method 与 compiler options 一致。失败与续跑只增加 immutable plan attempts，不覆盖历史。

H55（自然作用域门）：activation 定义为安全常量替换返回至少一个精确 protected anchor。新增触发数≥2 且总触发数≥3 才通过执行门；非触发题的 GECS/RPGE effective hash 必须等于 source hash。

H56（条件语义门，仅 H55 通过后）：非触发题 GECS/RPGE 的答案、F1 与 role metrics 必须逐题一致；触发题 RPGE F1 不低于 GECS，且所有确定性输出都有 grounded source。总体 RPGE F1 不低于默认方法。

H57（条件效率门，仅 H55 通过后）：触发题 RPGE 平均 extraction/total LLM 与 tokens 不高于 GECS，结构失败/修复不增加；150/150 final ok，完整报告 bootstrap、effect size、时延、缓存与 immutable failures，但调优集不用于最终显著性结论。
```

离线全仓为 `145 passed, 1 skipped`，`compileall`、pilot YAML、`git diff --check` 通过；源码指纹为 `d1fba3fa...f436`，数据审计仍为 `a24ad382...67e`。机器预注册见 v18 `offline-validation.json`。在 H55 判定前不得启动三路执行。

#### schema v19 v18 计划结果：自然作用域门失败，停止执行

两个 plan worker 分别完成 25/25，最终 50/50 snapshot `ok`、全部为 attempt 1，input/source method/compiler options/plan hash 验证错误为 0，H54 通过。计划获取只调用 Agnes，不调用 embedding/reranker：59 attempts / 57 successes / 2 internal retries，平均 attempt 时延 18.87 秒；观测 4.83 RPM，按并发 2 反推 6.36 RPM，均低于 20 RPM 硬上限。编译层同时暴露 33 次结构失败、26 次修复、7 个 fallback 和 19 个 heuristic plans，不能把 snapshot 完整性误写成编译无故障。

离线作用域审计的结果为 RPGE 总触发 `0/50`、新增 40 题触发 `0/40`，低于预注册的总数 3、新增数 2；H55 失败。按照条件门，没有创建任何 execution item 或 attempt，H56/H57 标记 `not_run`，而不是事后放宽阈值运行 150 条惰性对照。

已知 10 题的 source plan hash 有 8 个与 v13 相同、2 个变化。关键 `574...` 在 v13 为三槽 `Person(constants,?baldwin) → MotherOf(?mother,?baldwin) → MotherOf(?grandmother,?mother)`，RPGE 通过删除 Person anchor 槽而触发；v18 新编译计划则直接为两槽 `MotherOf("Baldwin...",?mother) → MotherOf(?mother,?grandmother)`，profile 已是 2 slots、1 join、2 variables、complexity 6。它没有多余 anchor 槽可替换，因此 GECS/RPGE 都保持 source hash `261c0f...d05`，protected values 为空，角色投影随之关闭。

| 预注册假设 | 判定 | 依据 |
| --- | --- | --- |
| H54 计划获取完整性 | **通过** | 50 snapshots、50 attempt-1、0 validation error，未覆盖历史。 |
| H55 自然作用域门 | **失败** | total/new trigger=`0/0`，低于 `3/2`。 |
| H56 条件语义门 | 未运行 | H55 失败后协议禁止执行。 |
| H57 条件效率门 | 未运行 | H55 失败后协议禁止执行。 |

这个否定结果改变了架构判断：schema19 RPGE 修复了一个真实语义错误，但入口绑定在“编译器是否先生成身份 anchor 槽”这一偶然表示上，无法作为稳定框架组件。下一候选必须在不改计划的前提下，同时覆盖（1）安全 substitution 返回的精确锚和（2）已经直接出现在关系槽中的问题锚常量；两种入口都只启用 bound-field projection、ordered-role annotation 与 protected-anchor validation。直接常量入口必须有独立的保守范围规则和负例，不能把所有问题常量都设为保护锚。机器结果见 v18 `plan-acquisition-validation.json` 与 `anchor-role-tune-scope-audit.json`。

#### schema v20：Grounded Role-Projected Extraction 与 v19 预注册

schema20 新增默认关闭的 `slotrag-grounded-role-projection`，暂称 **Grounded Role-Projected Extraction (GRPE)**。它保留 schema19 RPGE 的全部语义：先尝试安全 anchor substitution；若 substitution 已返回保护值，直接沿用旧路径且 `direct_grounded_anchor_projections=0`。只有 substitution 未触发时，才在原计划上检测直接关系锚，并且不改任何 slot/join/operator/hash。

直接锚必须同时满足：计划至少 2 slots 且有 join；join 图是森林而非环；候选槽是 join 图叶节点；槽中至少一个未知变量参与 join，但不直接包含最终输出变量；常量以词边界在问题中原样落地，并在问题 span 中含大写或数字实体信号；`Person/Entity/Item/Place/EvidenceAnsweringQuestion` 等身份或自由文本槽排除。单槽、答案槽、未落地常量、小写通用词和 join cycle 均由测试拒绝。该范围有意牺牲召回，避免把每个问题常量都变成全局禁值。

触发后仍只做三件事：抽取 schema 删除已绑定字段、未知字段标注完整 predicate 签名和参数位置、保护锚不能被赋给抽取出的未知字段。保护仅约束抽取字段，不约束 typed operator 的最终标签，所以 comparison 题仍可合法输出某个受保护片名。新增计数 `direct_grounded_anchor_projections` 与原三项 role telemetry 分开；runner 升为 schema20，schema19 记录不回填。

全仓为 `155 passed, 1 skipped`；`compileall`、pilot YAML、`git diff --check` 通过，冻结指纹 `d920f538...73b0`。v19 固定为 `runs/vldb2027-diagnostic-v19`、阶段 `grounded_role_projection_gate`，样本仍是 v18 的同一 50 题（哈希 `4f8f91f...d42c`），离线导入 50 个 v18 snapshot，不重新编译。

离线范围为 GRPE 触发 24/50、新增触发 18/40、惰性 26/50；保护值共 26 个，因为两道 bridge-comparison 各有两个片名。触发分层为 compositional 20、bridge-comparison 2、inference 2；substitution route 为 0，direct route 为 24。所有 50 题上默认/GECS/GRPE effective plan hash 完全相同，因此线上差异只来自抽取契约，而非计划形状。目标题 `574...` 以直接锚 `Baldwin...` 触发，source/effective hash 均为 `261c0f...d05`。

```text
H58（三路同源完整性）：50 imported snapshots、150 replay、150 schema20 final；所有 source/effective/result/provenance 错误为 0，三路逐题 effective hash 完全相同。

H59（GRPE 作用域与遥测）：24 个候选记录的 direct projection 逐题等于离线保护值数量，总和精确为 26；其余 26 个候选与全部 100 个控制记录该指标为 0。触发题 role contracts 与 projected fields 必须为正，惰性题三项 role telemetry 为 0。

H60（质量与语义安全）：150/150 final ok；GRPE 总体 F1 不低于默认和 GECS，24 个触发题的 F1 不低于 GECS。目标题必须答 Isabel Marshal、F1=1、direct=1、role contracts≥2、projected≥1、joined/deterministic=1、无 fallback/generation，证据含 Amice de Clare。comparison 的最终片名不视为 protected-anchor 违规。

H61（触发子集效率）：在 24 个触发题上，GRPE 的平均 extraction/total LLM calls、total tokens、结构失败与修复均不高于 GECS；总体 total tokens 也不高于 GECS。完整报告 provider calls、时延分位数、缓存、grounding/protected rejection、bootstrap、effect size 和全部 immutable failures。
```

在线先以两个互斥 worker 运行：A 为默认 50 条，B 为 GECS+GRPE 100 条；最大并发 2、服务许可 30 RPM、运行硬上限 20 RPM。若有失败，保留 attempt、doctor 后以并发 1 续跑。H58-H61 全过才进入独立 200 题验证；v19 仍是已观察调优集，不能用于最终显著性主张。机器预注册见 v19 `offline-validation.json` 与 `grounded-role-projection-scope-audit.json`。

#### v19 在线结果：作用域成立，但当前执行策略不进入 200 题验证

v19 最终得到 150/150 条 schema20 final `ok`，三种方法各 50 条。首轮共 150 个 attempts，其中默认 SlotRAG 30 条、GECS 22 条在同一 embedding 容量窗口收到“无健康或可用上游实例”HTTP 503；GRPE 在服务恢复后运行，50 条首轮均成功。失败 attempt 完整保留；`2026-07-22T19:54:06+08:00` 三项 doctor 均为 HTTP 200 后，以单 worker 续跑 52 条失败项并全部生成成功的 `attempt-0002`。最终共有 202 个不可变 attempts，历史失败类别只有 `provider_http_5xx=52`，不能用最终 150/150 成功掩盖该故障。

运行控制遵守许可 30 RPM、运行硬上限 20 RPM。首轮并发 2、恢复并发 1；以每个 provider 的 attempts 除以首末落盘记录间隔计算，首轮 Agnes/embedding/reranker 分别为 4.93/9.41/3.98 RPM，恢复段为 5.17/4.44/4.44 RPM。该值是阶段平均而非一分钟瞬时峰值，但结合最大 worker 并发可确认本轮没有主动提高到 20 RPM 以上。

冻结计划审计通过：50 个 imported snapshots、50 个 plan attempts、150 个 replay，缺 provenance/result plan/effective hash、source hash 不一致、未知 snapshot、跨方法 plan 不一致和 effective variant 均为 0。GRPE 的在线作用域也精确复现离线预注册：24 个触发题、26 个直接保护锚；逐题 `direct_grounded_anchor_projections` 与预期完全一致，总和 26。其余 26 个候选记录和全部 100 个控制记录的 direct 指标为 0；触发题 role contracts/projected fields 全为正，惰性题与控制题的三项 role telemetry 全为 0。因此 H58、H59 通过。

总体质量与证据指标如下；数值均为 50 题最终成功记录的均值。

| 方法 | EM | F1 | Evidence Recall | R@1 | R@5 | R@10 | P@1 | P@5 | P@10 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SlotRAG | 0.8600 | 0.8848 | 0.8500 | 0.4450 | 0.8400 | 0.8500 | 1.0000 | 0.3840 | 0.1940 | 0.8785 |
| GECS | 0.8600 | 0.8848 | 0.8850 | 0.4450 | 0.8750 | 0.8850 | 1.0000 | 0.4040 | 0.2040 | 0.9062 |
| GRPE | 0.8800 | 0.9048 | 0.8300 | 0.4450 | 0.8200 | 0.8300 | 1.0000 | 0.3760 | 0.1900 | 0.8631 |

| 方法 | LLM calls | Extraction calls | Retrieval calls | Tokens | Wall mean / p50 / p95 (s) | Structured fail / repair | Deterministic | Evidence fallback |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SlotRAG | 2.000 | 1.840 | 1.600 | 4608.18 | 28.42 / 22.03 / 70.87 | 0.340 / 0.240 | 0.860 | 0.120 |
| GECS | 1.880 | 1.740 | 1.600 | 3880.84 | 24.32 / 20.51 / 55.73 | 0.240 / 0.140 | 0.880 | 0.100 |
| GRPE | 1.980 | 1.840 | 1.620 | 4970.94 | 31.05 / 28.28 / 57.27 | 0.320 / 0.220 | 0.880 | 0.120 |

GRPE 的总体 F1 比 GECS 高 0.02，但这个均值不能支持方法收益：以 GECS 为 reference 的 50 题 paired bootstrap 差值为 `GECS-GRPE=-0.0200`，95% CI `[-0.1000, 0.0600]`，`p=0.8224`、Holm `p=1.0`。两者仅 5 题答案得分不同；24 个预注册触发题中 GRPE 为 1 win/21 ties/2 losses，而 26 个惰性题贡献 2 个随机 win、0 loss。换言之，总体表面提升来自方法按设计不应改变的惰性区，不是直接投影的可信因果收益。

触发子集直接否定质量和效率门：GRPE/GECS 的 F1 为 0.8433/0.8849；`GECS-GRPE=0.0417`，95% CI `[-0.0833, 0.1667]`，`p=0.7784`。GRPE/GECS 的 extraction calls 为 2.375/2.292、total calls 为 2.542/2.417、tokens 为 6246.13/5378.96、structured failures 为 0.250/0.250、repairs 为 0.167/0.125、wall mean 为 38.03/31.47 秒。只有 structured failures 持平，其余预注册效率条件均未满足；总体 tokens 也高出 28.1%。

目标题 `574...` 回答 `Isabel Marshal`、F1=1，证据包含 `Amice de Clare`，并且 direct/role/projected=`1/2/1`，说明范围检测与契约入口实际生效。然而两步抽取产生 2 次 structured failure、1 次 repair，最终 `join_output_rows=0`、`deterministic_answers=0`，依赖 1 次 evidence fallback 与 1 次 generation；共 4 次 LLM 调用、16296 tokens。它通过了答案与证据条件，却明确失败于本方法最关键的确定性 join 条件。

| 预注册假设 | 判定 | 依据 |
| --- | --- | --- |
| H58 三路同源完整性 | **通过** | 50 snapshots、150 replay，全部 plan/provenance/hash 检查为 0 error。 |
| H59 作用域与遥测 | **通过** | 24 个触发、26 个直接投影逐题精确匹配；惰性与控制无泄漏。 |
| H60 质量与语义安全 | **失败** | 总体 F1 条件通过，但触发集 F1 低于 GECS；目标题仍走 fallback/generation 而非确定性 join。 |
| H61 触发子集效率 | **失败** | calls、tokens、repairs 和总体 tokens 均高于 GECS，仅 structured failures 持平。 |

结论不是放弃直接锚检测器：H58/H59 证明它是稳定、保守且不改计划的有效框架组件；被否定的是“只靠 prompt/schema role projection 就能让执行更准更省”的当前策略。GRPE 不提升为默认方法，也不进入独立 200 题验证。下一轮保留已验证的作用域检测器，先增加抽取失败原因的可审计遥测，并针对 relation-role validation/确定性 join 做更窄的执行修复；新门槛必须在再次联网前预注册，不能据 v19 结果放宽 H60/H61。完整机器记录为 v19 `online-validation.json`，全部指标、分层、bootstrap、逐题和不可变失败分别见 `summary.json`、`metrics.csv`、`stratified_metrics.csv`、`paired_bootstrap.csv`、`per_question.csv` 与 `failure_report.csv`。

#### schema v21：阶段自适应轻量抽取与 v20 诊断预注册

v19 的 GRPE 抽取平均每次产生约 1096 completion tokens，部分调用触及 2048 上限；目标题和两个最大成本题的额外开销主要来自结构化抽取而非计划或检索。Agnes 2.0 Flash 的本地 API 文档提供 `chat_template_kwargs.enable_thinking`。因此 schema21 不改变已验证的 direct-anchor 范围，而引入一个更轻的阶段策略：规划仍保留原模型行为，只有已触发 role projection 的结构化抽取调用可显式设置 `enable_thinking=false`。惰性题、GECS 和旧 GRPE 不发送该参数，避免把全局模型配置变化伪装成方法收益。

第二个独立组件是 **bound role signature**。旧工具描述只显示 `MotherOf(?mother, ?grandmother)`；新描述在执行时把已知绑定代入为 `MotherOf("Amice de Clare", ?grandmother)`，并明确已知实参的位置和值，但仍只要求 unresolved 字段。它不改 plan、query、retrieval、join 或保护锚，仅减少参数方向歧义。

为避免再次只看到笼统的 `structured_output_failures`，schema21 新增 `extraction_thinking_disabled`、`bound_role_signatures`、`extraction_length_finishes`、`extraction_finish_reasons` 和 `extraction_validation_errors`。finish reason 与经截断的验证错误逐次保存在 final record，三个计数可进入聚合；schema20 及更早记录不回填。方法消融固定为：原 GRPE、只关闭 extraction thinking、只代入 bound signature、两者组合的 Lean GRPE（LGRPE）。全仓验证为 `160 passed, 1 skipped`，`compileall`、pilot YAML 与 `git diff --check` 通过；冻结源码/配置/测试指纹为 `ba895b...f429`。

v20 使用 `runs/vldb2027-diagnostic-v20` 与 `lean_grounded_role_diagnostic`，不是随机或独立验证集。它固定 6 个已观察诊断题：`574...` 确定性 join 失败目标、`53f...` 最大 token 增量且质量下降、`05b...` 高成本双失败、`254...` 与 `c52...` 两个 nationality 形式漂移对照，以及 `49b...` 单槽惰性负例。样本 SHA-256 为 `1c6c1b...ae38`；5 个 direct 触发、1 个惰性题，每个 role 方法预期 direct 总数 5。6 个 v19 共享计划已离线导入，6 snapshots/6 plan attempts 均为 ok，五个执行方法逐题 effective hash 与 source hash 完全一致。

```text
H62（同源完整性）：6 imported snapshots、30 schema21 final replay；全部 source/effective/result/provenance 检查通过，五路逐题 effective hash 相同。

H63（组件与遥测隔离）：5 个触发题上四个 role 方法 direct=1，惰性题所有 role/phase telemetry=0。只关 thinking 的方法只计 thinking-disabled，只绑定签名的方法只计 bound-signature，组合方法两者都计，原 GRPE 两者都为 0。

H64（目标题确定性门）：组合方法在 574... 上答 Isabel Marshal、F1=1，direct/role/projected 为正，join/deterministic 为正，无 fallback/generation、无 extraction validation error，calls/tokens 不高于同时运行的 GECS 和 GRPE。

H65（六题联合门）：组合方法 6/6 final ok，F1 不低于 GECS 与 GRPE；平均 calls、tokens、structured failures、repairs、length finishes 均不高于二者。
```

在线运行五种执行方法共 30 条；`slotrag` 仅作为 frozen plan source，不执行。worker A 为 GECS+GRPE+只关 thinking 共 18 条，worker B 为只绑定签名+组合方法共 12 条；最大并发 2、许可 30 RPM、运行上限 20 RPM。为避免再次向不稳定的 embedding 上游重复提交同文本，五路等同导入 v19 同模型缓存，SHA-256 为 `314b8d...90cc`；共享索引成本仍从在线执行指标排除。有失败时仍保留 attempt、doctor 后并发 1 续跑。只有 H62-H65 全过才允许开启新的 50 题调优门；该 6 题诊断不能用于显著性或 held-out 结论。机器预注册为 v20 `offline-validation.json` 与 `lean-role-diagnostic-scope-audit.json`。

#### v20 在线结果：阶段控制隔离成立，但 LGRPE 拒绝晋级

v20 得到 30/30 条 schema21 final `ok`，五种执行方法各 6 条；30 个不可变 attempts 全为首次成功，没有失败、重试或补跑。在线前 `2026-07-22T20:39:41+08:00` 的 Agnes、embedding、reranker doctor 均为 HTTP 200。执行保持两 worker 并发，首末落盘间隔 364 秒；Agnes/embedding/reranker 共 73/56/56 次 provider attempts，对应阶段平均 12.03/9.23/9.23 RPM，低于实际运行上限 20 RPM，也没有把 30 RPM 服务许可当作目标吞吐。该计算仍是阶段平均而非一分钟瞬时峰值。

同源审计无污染：6 imported snapshots、6 plan attempts、30 replay 全部有效，缺 provenance、缺 result/effective hash、source hash 不一致、未知 snapshot、跨方法 plan 不一致与 effective variant 均为 0。组件遥测也逐项精确：四个 role 方法在 5 个触发题上均为 direct/role/known=`5/10/5`；只关 thinking 为 thinking/bound=`10/0`，只绑签名为 `0/10`，组合为 `10/10`，原 GRPE 为 `0/0`。惰性题所有 phase telemetry 为 0，五种方法的 `extraction_length_finishes` 全为 0。因此 H62、H63 通过。

六题质量、检索与效率均值如下。该表只用于已观察诊断集上的组件选择；完整 130+ 指标仍以 v20 `metrics.csv`、`retrieval_metrics.csv`、`stratified_metrics.csv` 和 `summary.json` 为准。

| 方法 | EM / F1 | Evidence Recall / MRR | R@1 / R@5 / R@10 | P@1 / P@5 / P@10 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| GECS | 0.6667 / 0.6667 | 0.9583 / 1.0000 | 0.4583 / 0.9583 / 0.9583 | 1.0000 / 0.4333 / 0.2167 | 0.9720 |
| GRPE | 0.8333 / 0.8333 | 0.9583 / 1.0000 | 0.4583 / 0.9583 / 0.9583 | 1.0000 / 0.4333 / 0.2167 | 0.9720 |
| 只关 extraction thinking | 0.6667 / 0.6667 | 0.9583 / 1.0000 | 0.4583 / 0.9583 / 0.9583 | 1.0000 / 0.4333 / 0.2167 | 0.9586 |
| 只绑 role signature | 0.5000 / 0.5000 | 0.9583 / 1.0000 | 0.4583 / 0.9583 / 0.9583 | 1.0000 / 0.4333 / 0.2167 | 0.9586 |
| LGRPE（组合） | 0.6667 / 0.6667 | 0.9583 / 1.0000 | 0.4583 / 0.9583 / 0.9583 | 1.0000 / 0.4333 / 0.2167 | 0.9586 |

| 方法 | LLM / extraction / generation calls | Tokens | Provider calls | Wall mean / p50 / p95 (s) | Fail / repair / grounding | Deterministic / fallback |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GECS | 2.500 / 2.000 / 0.167 | 3865.00 | 6.500 | 23.72 / 22.97 / 36.91 | 0.000 / 0.000 / 0.000 | 0.833 / 0.000 |
| GRPE | 2.167 / 2.000 / 0.000 | 3584.83 | 5.833 | 18.10 / 17.61 / 26.00 | 0.167 / 0.167 / 0.000 | 1.000 / 0.000 |
| 只关 extraction thinking | 2.500 / 2.333 / 0.167 | 4350.00 | 6.167 | 23.14 / 22.97 / 34.31 | 0.667 / 0.500 / 0.500 | 0.833 / 0.167 |
| 只绑 role signature | 2.333 / 2.000 / 0.333 | 3775.67 | 6.000 | 23.74 / 22.06 / 38.72 | 0.333 / 0.167 / 0.333 | 0.667 / 0.167 |
| LGRPE（组合） | 2.667 / 2.000 / 0.333 | 3751.67 | 6.333 | 31.32 / 33.58 / 46.71 | 0.333 / 0.167 / 0.333 | 0.667 / 0.167 |

目标题 `574...` 给出最直接的否定证据。LGRPE 回答 `Isabel Marshal`、F1=1，direct/role/known/thinking/bound=`1/2/1/2/2`，两次抽取 finish reason 均为 `tool_calls`，没有 validation error、结构失败、repair、grounding rejection、length finish 或 evidence fallback。但是它抽出两个 join rows，`deterministic_answers=0`，随后使用 1 次 generation；共 4 次 LLM 调用、5679 tokens，高于同期 GECS 的 3/4664 和 GRPE 的 2/4847。只绑定签名的方法更直接地输出错误答案 `Gilbert de Clare, 5th Earl of Hertford`：`MotherOf("Amice de Clare", ?grandmother)` 消除了格式/grounding 错误，却仍从“Amice 是 Gilbert 与 Isabel 的女儿”中同时接纳父亲和母亲，说明失败根因是 predicate-role 语义约束缺失，而不是参数是否显示为已绑定。

| 预注册假设 | 判定 | 依据 |
| --- | --- | --- |
| H62 同源完整性 | **通过** | 6 snapshots、30 replay，全部 plan/provenance/hash 检查为 0 error。 |
| H63 组件与遥测隔离 | **通过** | 四路 role telemetry 与 thinking/bound 消融逐项精确，惰性题无泄漏，length finish 全为 0。 |
| H64 目标题确定性 | **失败** | 答案与抽取协议条件通过，但 join rows=2、deterministic=0、generation=1，calls/tokens 高于 GECS 与 GRPE。 |
| H65 六题联合质量/效率 | **失败** | LGRPE F1 低于 GRPE；calls、tokens、failures 均高于 GRPE，且 calls/failures/repairs 高于 GECS。 |

因此拒绝 LGRPE，不开启新的 50 题门，也不进入 200 题 held-out。`enable_thinking=false` 在本组没有减少 tokens，反而增加结构失败与 repair；bound signature 有助于暴露已知参数，却不能独立承担关系语义验证。下一候选必须在已验证的 direct-anchor 作用域内加入通用的 predicate-role 语义约束，并先用离线反例覆盖父/母、国籍/国家等角色边界，再冻结新门槛；不得据本轮结果放宽 H64/H65。机器判定见 v20 `online-validation.json`，完整聚合、逐题、检索、分层、attempt 分母与计划审计见同运行 `summaries/lean_grounded_role_diagnostic/`。

#### schema v22：角色类型矛盾过滤与 v21 诊断预注册

v20 说明绑定 signature 能消除格式/grounding 错误，却不能阻止 `grandmother` 接纳带 `Earl` 头衔的 Gilbert。schema22 因此不再改 prompt，而在结构化行通过 source grounding 后增加 **Role-Type Contradiction Filter（RTCF）**。它从 unresolved 字段名读取封闭的性别化亲属角色；只有女性角色遇到明确男性头衔/亲属标记，或男性角色遇到明确女性标记时才拒绝。普通人名、未标性别实体和非性别字段全部保留；全部行冲突时记 semantic abstention 并返回空物化，不把语义拒绝误记为 schema failure，也不发起 repair。该候选不使用题目 ID、gold answer、gold evidence、外部知识或额外 LLM 调用。

schema22 新增 `semantic_role_type_contracts`、`semantic_role_type_rejections`、`semantic_role_type_abstentions`，旧记录不回填。全仓 `165 passed, 1 skipped`，`compileall`、pilot YAML 与 `git diff --check` 通过。50 个 v19 冻结计划的离线范围为 10 个性别角色题、17 个可能生效的槽，另外 40 题完全惰性；在 v20 已落盘 evidence 上只回溯命中 `574...` 的 3 条 Gilbert/Earl 错误行，没有命中正确行。该回溯只用于冻结作用域，不作为在线收益。

v21 复用 v20 完全相同的 6 个已观察题，样本 SHA-256 仍为 `1c6c1b...ae38`；6 个 v19 snapshots 已离线导入，6 plan attempts 全为 imported/ok，没有新增 provider 请求。在线仅执行 GECS、GRPE、RTCF 三路共 18 条。RTCF 预期 direct/role/known=`5/10/5`，semantic contracts 只出现在 `574...` 的 mother/grandmother 与 `05b...` 的 father/grandfather，总数严格为 4；其他题与两个控制方法的三项 semantic telemetry 必须为 0。

```text
H66（同源完整性）：6 imported snapshots、18 schema22 final replay；三路逐题 source/effective hash 相同且 provenance 完整。

H67（作用域隔离）：两种 role 方法 direct/role/known 均为 5/10/5；RTCF semantic contracts 精确为 4，只落在两个预注册亲属题，GECS/GRPE/其余题均为 0。

H68（目标题门）：RTCF 在 574... 上答 Isabel Marshal、F1=1、join=1、deterministic=1，无 Gilbert row、generation、fallback、结构失败、repair、grounding rejection、semantic abstention 或 length finish，calls/tokens 不高于同期 GECS 与 GRPE。

H69（六题联合门）：RTCF 6/6 final ok，F1 不低于 GECS 与 GRPE；平均 calls、tokens、结构失败、repairs、fallbacks、length finishes 均不高于 GRPE。
```

运行仍固定最大并发 2、服务许可 30 RPM、实际运行上限 20 RPM：worker A 为 GECS+GRPE 共 12 条，worker B 为 RTCF 6 条；使用相同 warm embedding cache `314b8d...90cc`。失败 attempt 必须保留，doctor 恢复后才允许并发 1 补跑。只有 H66-H69 全过才开启新 50 题门；本轮重复使用已观察诊断集，不能作显著性、held-out 或泛化主张。机器预注册为 v21 `offline-validation.json` 与 `role-type-filter-scope-audit.json`。

#### v21 在线结果：作用域精确，但 RTCF 没有产生可归因收益

首次 doctor 的 Agnes 为 `ConnectError`，embedding/reranker 为 HTTP 200，因此没有启动实验；第二次完整 doctor 三项均为 HTTP 200 后才运行。最终 18/18 条 schema22 final `ok`，三种方法各 6 条；18 个不可变 attempts 全是首次成功，无失败、retry 或补跑。首末落盘间隔 267 秒，Agnes/embedding/reranker attempts 为 43/34/34，阶段平均 9.66/7.64/7.64 RPM，低于实际 20 RPM 上限。

并发运行同时暴露一个记录层问题：两个 worker 创建 `manifest.json` 时发生末写覆盖，初始只保留 RTCF 的 6 条 request，使第一次 summary 误报 expected=6、observed=18。18 个 attempts/items 本身完整且未修改；补回预注册的 GECS+GRPE request 后重新汇总为 expected=observed=18、completion=1.0。6 snapshots、6 plan attempts、18 replay 全部通过 provenance/hash 审计，缺失、mismatch、unknown snapshot、inconsistent pair 与 effective variant 均为 0。因此该问题不改变方法结果，但下一 schema 必须先为 manifest/progress 写入增加跨进程锁，不能继续人工修复。

RTCF 作用域与预注册完全一致：GRPE 和 RTCF 的 direct/role/known 总数均为 `5/10/5`；RTCF semantic contracts 总数为 4，只落在 `574...` 与 `05b...`，其他 4 个候选题和两个控制方法均为 0。所有方法的 length finishes 为 0。RTCF 在线 `semantic_role_type_rejections=0`、abstentions=0，说明本次模型没有产出带显式性别矛盾标记的行；因此不能把任何答案差异归因于过滤器。H66、H67 通过。

| 方法 | EM / F1 | Evidence Recall / MRR | R@1 / R@5 / R@10 | P@1 / P@5 / P@10 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| GECS | 0.6667 / 0.6667 | 0.9583 / 1.0000 | 0.4583 / 0.9583 / 0.9583 | 1.0000 / 0.4333 / 0.2167 | 0.9720 |
| GRPE | 0.6667 / 0.6667 | 0.9583 / 1.0000 | 0.4583 / 0.9583 / 0.9583 | 1.0000 / 0.4333 / 0.2167 | 0.9586 |
| RTCF | 0.6667 / 0.6667 | 0.9583 / 1.0000 | 0.4583 / 0.9583 / 0.9583 | 1.0000 / 0.4333 / 0.2167 | 0.9586 |

| 方法 | LLM / extraction / generation calls | Tokens | Provider calls | Wall mean / p50 / p95 (s) | Fail / repair / grounding | Deterministic / fallback |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GECS | 2.333 / 2.000 / 0.167 | 3865.00 | 6.333 | 24.81 / 20.24 / 43.44 | 0.000 / 0.000 / 0.000 | 0.833 / 0.000 |
| GRPE | 2.333 / 2.167 / 0.167 | 3947.83 | 6.000 | 23.04 / 21.46 / 35.10 | 0.500 / 0.333 / 0.333 | 0.833 / 0.167 |
| RTCF | 2.500 / 2.333 / 0.167 | 4344.83 | 6.167 | 23.87 / 24.25 / 36.32 | 0.667 / 0.500 / 0.500 | 0.833 / 0.167 |

目标题三路都回答 `Isabel Marshal`、F1=1、join=1、deterministic=1，且无 generation/fallback。RTCF 的 contracts=2，但 rejections=0；它先把未在 `Baldwin...` source 中 grounded 的 grandmother 行作为原有 grounding failure 拒绝，再 repair 得到 Isabel，因此为 3 calls、7260 tokens、fail/repair/grounding=`1/1/1`。同期 GECS 与 GRPE 均为 2 calls，tokens 为 4664/4847，且三项失败计数均为 0。RTCF 通过答案与确定性条件，却明确失败于 H68 的无 repair 与成本条件，也没有形成过滤器的因果激活证据。

六题上三路 F1 均为 0.6667；`254...` 与 `c520...` 仍输出 `United States` 而 gold 为 `American`。RTCF/GRPE 的 calls 为 2.500/2.333、tokens 为 4344.83/3947.83、structured failures 为 0.667/0.500、repairs 为 0.500/0.333；fallback 均为 0.167、length finishes 均为 0。质量只持平，四个预注册效率条件均变差，因此 H69 失败。

| 预注册假设 | 判定 | 依据 |
| --- | --- | --- |
| H66 同源完整性 | **通过** | 6 snapshots、18 replay，全部 plan/provenance/hash 检查为 0 error。 |
| H67 作用域隔离 | **通过** | role 指标为 5/10/5；4 个 contracts 精确落在两个亲属题，控制与其余题无泄漏。 |
| H68 目标题语义/效率 | **失败** | 答案与 deterministic join 通过，但有 1 次 grounding repair，3 calls/7260 tokens 高于两基线，且 semantic rejection=0。 |
| H69 六题联合门 | **失败** | F1 持平；calls、tokens、failures、repairs 均高于 GRPE。 |

因此拒绝 RTCF，不开启 50 题或 200 题验证。它可作为“只拒绝强矛盾”的安全原型保留，但不能列为有效方法贡献：其触发依赖 extractor 是否恰好输出显式冲突，无法解决无标记的候选歧义，也没有处理 nationality/country 表面形式。下一轮先修复并发 manifest/progress 的原子聚合，再选择不依赖随机候选形态的架构方向；机器判定见 v21 `online-validation.json`，完整指标、逐题、检索、分层、失败分母与计划审计见同运行 `summaries/grounded_role_type_filter_diagnostic/`。

#### v21 后基础设施闭环：20 RPM 硬限流与并发 4

v20、v21 的两个 worker 虽然阶段平均 RPM 均低于 20，但执行器此前没有主动限流；同时，两个进程对 `manifest.json`、`progress.json` 和 embedding cache 的读改写不是事务。v20/v21 的 completed 计数末写覆盖以及 v21 manifest 丢失一条 run request，均属于该记录层缺陷，不能继续依赖人工修复。

本轮只修改实验基础设施，不改变 schema22 方法、prompt、计划、检索、答案或评分。所有 JSON 改为同目录唯一临时文件后原子替换；共享读改写使用持久 lock file 与 `flock`。manifest 在锁内合并去重 run request；progress 在锁内重新扫描该 stage 的全部 final items 与 immutable attempts，统一计算 completed、attempts、retried 及最终状态分母；两个并发加载的 embedding cache 在 flush 时合并磁盘最新值，避免末写丢键。

请求控制显式冻结为 `provider_rpm=30`、`operational_rpm=20`、`max_concurrency=4`，共享状态位于 `runs/.rate-limits/`。每个 provider 分别持有最多 4 个跨进程在途槽；取得槽后，每个 HTTP attempt 必须再取得最小间隔为 3 秒的发起配额，429/5xx/连接失败后的内部 retry 同样计入。这样服务许可 30 RPM 只作为配置合法性上界，20 RPM 才是执行硬上限；即使同时启动多个 run，也不能各自复制一套进程内配额。

并发 4 来自近期在线时延的容量估算，而不是把 30 RPM 当吞吐目标：v21 并发 2 的 Agnes 阶段平均 9.66 RPM，线性外推并发 4 约为 19.32 RPM；v20 的对应外推为 24.06 RPM，因此必须由硬限流削平而不能只凭并发估算。后续正常运行最大并发设为 4，失败恢复仍降为 1；不同 worker 必须继续使用互斥 method/question 分片。

本地真实时钟烟雾测试让 4 个线程同时竞争 Agnes 的 20 RPM 配额，实际取得时刻为 `0.0043/3.0053/6.0059/9.0066s`，相邻最小间隔 `3.0006s`。并发 manifest、全局 progress、cache merge、每次 retry 取配额及在途槽上限均有回归测试；全仓 `174 passed, 1 skipped`，`compileall`、YAML 解析与 `git diff --check` 通过，源码指纹为 `761b5d9a...ae5f`。机器记录见 `runs/vldb2027-infrastructure-v22/concurrency-validation.json`。下一方法实验只能在该控制层上新建 run，既有 v21 frozen artifacts 保持不变。

#### schema v23：锚点中心属性抽取窗与 v22 诊断预注册

v21 的两个 nationality/country 错误不能只解释为评分别名。`254...` 的 Andy Warhol 文档首句明确写 `American`，但第 13 句另有与国籍关系无关的 `United States`；原 GRPE 只要候选值在整篇任意位置出现就视为 grounded，因此错误接纳远处词。`c520...` 的 Marshall Neilan 文档只写 `American`，GRPE 两次拒绝 `United States` 后没有结构行，最终生成器再次输出 `United States`。这说明错误同时来自整篇 grounding 过宽和抽取失败后的生成式表面改写，不应通过改 gold、放宽 F1 或手工 country/demonym alias 掩盖。

schema23 新增 **Anchor-Centered Extraction Window（ACEW）**。它只在已验证 direct-anchor + role-projection 作用域内、且 predicate 为 `CountryOf/CountryOfOrigin/CountryOfCitizenship/Nationality` 时激活；用当前 binding entity 的文档标题匹配或最早正文提及作为中心，只把前后两句交给结构化抽取器，并在同一局部窗内验证 unresolved value。找不到锚点时保守回退完整 passages。原始检索 top-k 仍写入 evidence ranking，窗口只改变 extraction payload 与局部 grounding；不增加检索、LLM 调用、外部知识、gold 或题目 ID 分支。

新增遥测为 `anchor_window_contracts`、selected/dropped passages、input/output chars、char reduction rate 与 fallbacks，runner record 升为 schema23，旧记录不回填。全仓 `179 passed, 1 skipped`，`compileall`、YAML 与 `git diff --check` 通过；源码指纹为 `8593826c...f8b6`。并发基础设施测试仍包含在同一全仓分母内。

离线审计覆盖 v19 的 250 个训练计划，只有 4 道 2Wiki 题、4 个属性槽触发，谓词分布为 CountryOf/Origin/Nationality=`1/2/1`，另外 246 题完全惰性。四个 gold 属性表面值均保留在两句半径窗中；已观察的两个 `United States` 均被排除。`583...` 的 `Hong Kong-Chinese` 同句同时包含错误输出 `Hong Kong` 与 gold `Chinese`，ACEW 明确不能解决这种同句语义歧义，本轮不得据此作扩张主张。

v22 复用 v21 完全相同的六题，sample、warm cache、dataset audit SHA-256 仍为 `1c6c1b...ae38`、`314b8d...90cc`、`a24ad3...c67e`。6 个 v19 plan 已离线导入，6 plan attempts 均为 imported/ok，没有 provider 调用。在线只执行 GECS、GRPE、ACEW 三路共 18 条；`slotrag` 仅为 frozen plan source。三个互斥 method worker 同时运行，系统最大并发仍为 4，30 RPM 为服务许可、20 RPM/3 秒间隔为跨进程硬限制，失败恢复降为并发 1。

```text
H70（同源完整性）：6 imported snapshots、18 schema23 replay；逐题 source/effective plan hash 与 provenance 完整，未知或缺失计划为 0。

H71（作用域/窗口门）：ACEW contracts 精确为 2，只落在 254... 与 c520...；fallback=0，总 output chars < input chars；控制与其余四题的 window telemetry 全为 0。

H72（两个国籍目标题）：ACEW 两题都答 American、逐题 F1=1、join=1、deterministic=1；无 generation、evidence fallback、结构失败、repair、grounding rejection 或 length finish，逐题 calls/tokens 均不高于 GRPE。

H73（六题联合门）：ACEW 6/6 final ok，F1 至少 0.8333 且比两个控制至少高 0.1666；平均 calls、tokens、结构失败、repairs、fallbacks、length finishes 均不高于 GRPE。
```

只有 H70-H73 全过才新建 50 题训练门；门槛不得在线后修改。该六题已经被多轮观察，只能作机制诊断，不能作显著性、held-out 或泛化证据。机器预注册与作用域审计见 v22 `offline-validation.json`、`anchor-window-scope-audit.json`。

#### v22 在线闭环：ACEW 通过四门并晋级 50 题训练门

2026-07-22 服务检查三路均为 HTTP 200 后，三个互斥 method worker 并发完成 GECS、GRPE、ACEW 共 18 条 schema23 replay。18/18 final 为 `ok`，18 条 immutable attempt 均停在 attempt 1；manifest 自动保留三条 run request，progress 自动汇总为 completed/attempts/ok=`18/18/18`，没有人工修补。frozen-plan 审计为 6/6 snapshot 有效、6 imported plan attempts 成功、18 replay provenance 完整，缺失、hash mismatch、未知 snapshot、题内 effective-plan variant 均为 0。

以下均为 execution-only 指标，共享的历史编译成本排除在方法比较之外。答案与检索指标如下；`R/P@k` 分别为 evidence recall/precision：

| 方法 | EM | F1 | Evidence Recall | MRR | R@1 | R@5 | R@10 | P@1 | P@5 | P@10 | nDCG@10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GECS | 0.5000 | 0.5000 | 0.8750 | 0.9167 | 0.3750 | 0.8750 | 0.8750 | 0.8333 | 0.4000 | 0.2000 | 0.8698 |
| GRPE | 0.6667 | 0.6667 | 0.9583 | 1.0000 | 0.4583 | 0.9583 | 0.9583 | 1.0000 | 0.4333 | 0.2167 | 0.9586 |
| **ACEW** | **1.0000** | **1.0000** | **0.9583** | **1.0000** | **0.4583** | **0.9583** | **0.9583** | **1.0000** | **0.4333** | **0.2167** | **0.9720** |

成本、时延与可靠性如下；数值为逐题均值，时延单位为毫秒：

| 方法 | LLM calls | Provider calls | Tokens | Wall mean | p50 | p95 | Structured fail | Repair | Ground reject | Evidence fallback | Deterministic |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GECS | 2.3333 | 6.3333 | 3874.2 | 28269 | 21961 | 53532 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.8333 |
| GRPE | 2.3333 | 6.0000 | 3952.3 | 23776 | 20821 | 37575 | 0.5000 | 0.3333 | 0.3333 | 0.1667 | 0.8333 |
| **ACEW** | **2.0000** | **5.6667** | **3454.7** | **21603** | 22177 | **30026** | **0.1667** | **0.1667** | **0.0000** | **0.0000** | **1.0000** |

相对 GRPE，ACEW 的 F1 提高 0.3333，LLM calls、tokens、provider calls 与平均 wall latency 分别下降 14.29%、12.59%、5.56% 和 9.14%。唯一一次 ACEW structured failure/repair 出现在非目标 `05b0...`，最终仍正确；两个预注册国籍目标题均没有该波动。完整列而非本文节选保存在 v22 `metrics.csv` 与 `per_question.csv`，另有 retrieval、macro、stratified、paired-bootstrap、seed-variance、failure 与 frozen-plan CSV；文件 hash 和入口由 `online-validation.json` 固化。

ACEW 作用域精确命中 `254.../CountryOf` 与 `c520.../CountryOfOrigin` 两槽，contracts/selected/dropped=`2/4/6`，fallback=0。抽取输入从合计 4318 字符降至 1466 字符，池化缩减率 66.05%；控制方法和其余四题的全部 window telemetry 均为 0。两题 ACEW 都输出 `American`、F1=1、join output=1、deterministic=1，且 generation、evidence fallback、structured failure、repair、grounding rejection、length finish 全为 0；逐题 calls/tokens 为 `2/2717` 与 `2/2011`，均不高于对应 GRPE 的 `2/3352` 与 `4/4362`。

| 预注册门 | 结果 | 不可变判据核验 |
|---|---|---|
| H70 | **通过** | 6 imported snapshots、18 schema23 replay，同源 provenance/hash 完整且无 variant |
| H71 | **通过** | 精确两个目标 contract；控制和非目标惰性；fallback=0；1466 < 4318 |
| H72 | **通过** | 两个目标均 `American`/F1=1/确定性单行，零生成、回退及错误遥测，成本不高于 GRPE |
| H73 | **通过** | ACEW 6/6 ok、F1=1，较两个控制至少高 0.3333，全部预注册成本/失败项不劣于 GRPE |

运行控制与用户给定额度保持一致：服务许可为 30 RPM，跨进程执行硬上限为每 provider 20 RPM，即相邻 HTTP attempt 至少 3 秒；最大在途并发为 4，本轮因只有三个方法而实际启动三个 worker。最终 item 的 provider attempts 与共享 limiter acquisition counter 完全一致，Agnes/embedding/reranker=`40/34/34`；按首末持久化 final 的 153.07 秒窗口计算，阶段平均分别为 `15.68/13.33/13.33 RPM`。该均值不是瞬时峰值证明，硬上限由每次 retry 也必须取得的共享 permit 保证，本地四竞争者时钟测试最小间隔为 3.0006 秒。

因此 H70-H73 在未改阈值的前提下全部通过，**只授权另建不重叠的 50 题训练门**；200 题 held-out 仍未授权。六题 F1=1 不能作为显著性或泛化结论，也不能用于继续修改 ACEW。机器闭环见 `runs/vldb2027-diagnostic-v22/online-validation.json`。

#### v23：不重叠 50 题训练门预注册

新运行固定为 `runs/vldb2027-training-v23`、阶段 `anchor_window_training_gate`，仅使用 2Wiki train。此前 33 个 2Wiki sample artifact 实际合计只覆盖相同的 50 个唯一 ID；新门在任何模型调用前用确定性种子 2028 冻结另 50 题，历史交集为 0，sample SHA-256 为 `b70d60...6895c`。分层为 bridge-comparison/comparison/compositional/inference=`11/15/22/2`，50/50 题均有 evidence gold；原始 train 为 167,454 条、0 invalid，SHA-256 为 `ad0f27...18f01`。

四路方法固定为默认 SlotRAG、GECS、GRPE、ACEW，共预期 200 条 schema23 final。默认 SlotRAG 只作为 frozen-plan source 和次级方法对照，先顺序生成 50 个计划快照；快照完整后，再让 GECS、GRPE、ACEW 三个互斥 worker 并发 replay，避免计划创建竞争并使三种主比较方法从同一缓存状态开始。共享计划编译成本排除在主方法成本之外；index-inclusive 与 wall latency 必须报告，但因 source 预热和 20 RPM 共享调度不作为晋级硬门。服务许可/执行上限/在途并发继续固定为 `30 RPM / 20 RPM / 4`，相邻同 provider attempt 至少 3 秒，retry 同样占配额。

预注册门槛在在线调用前冻结如下：

| 门 | 通过条件 |
|---|---|
| H74 同源完整性 | 新 50 题保持唯一且历史交集为 0；50 个有效 frozen snapshots、200 个 replay 的 provenance/hash 完整，无缺失、未知、mismatch 或题内 variant |
| H75 作用域与压缩 | 控制 window telemetry 全 0；ACEW 仅在注册的 country/nationality 且 direct-anchor + role-projection 作用域触发，至少 2 题激活、scope mismatch=0、fallback 至多 1、非回退窗不扩张，池化字符缩减至少 30% |
| H76 答案质量 | ACEW 总体 F1 ≥ `max(GECS, GRPE)-0.02`；触发子集 F1 不低于 GRPE 且 paired wins 不少于 losses；ACEW success rate ≥0.98 |
| H77 成本可靠性 | ACEW 的 calls/provider calls/tokens 各 ≤ `1.05×GRPE`；结构失败、repair、ground rejection、evidence fallback、generation、length finish 各 ≤ `GRPE+0.02/题`；deterministic rate ≥`GRPE-0.02` |
| H78 检索保持 | Evidence Recall、MRR、R@1/5/10、P@1/5/10、nDCG@10 每项均 ≥`GRPE-0.02` |
| H79 分母与报告 | 至少 196/200 final ok；全部 benchmark/provider retry 保留；limiter counter 与 provider delta 对账且遵守 20 RPM；aggregate、逐题、retrieval、macro、stratified、paired bootstrap、seed variance、failure、frozen-plan artifact 齐全 |

训练门必须报告 paired bootstrap、效应量、Holm 校正以及逐题 win/tie/loss，但不以训练集显著性作硬门。只有 H74-H79 全部通过，才授权单独冻结 200 题 held-out；若观察本门后修改架构，必须换一组不重叠训练门，不能在同一 50 题上重新宣称通过。机器预注册与交集审计见 v23 `offline-validation.json`、`historical-sample-overlap-audit.json`。

#### v23 提前停止：计划谓词漂移使 H75 不可达

source phase 先完成 50 个默认 SlotRAG 计划与执行：plan/plan-attempt/final/execution-attempt=`50/50/50/50`，全部 snapshot 与 final 为 `ok`，final 均为 schema23/attempt1，benchmark retry=0；唯一一次 provider 内部 retry 同时计入共享编译成本与限流配额。frozen-plan 审计的 missing provenance/result/effective hash、hash mismatch、unknown snapshot、inconsistent pair 与 effective variant 均为 0。source execution-only 的 EM/F1=`0.6200/0.6834`，Evidence Recall/MRR/nDCG@10=`0.7950/0.8723/0.7910`，calls/provider calls/tokens=`2.08/5.32/2709.42`，wall mean/p50/p95=`25.79/22.46/56.93s`；完整列和分层结果保存在 v23 summaries。

在启动三路 replay 前对 75 个冻结槽做必要条件审计，schema23 精确注册的 `CountryOf/CountryOfOrigin/CountryOfCitizenship/Nationality` 出现 **0 次**，因此旧 ACEW 在 50 题上必然完全惰性，H75 的“至少两题激活”已不可达。按预注册的不可变门槛执行 futility stop：不修改 H75，不运行无法改变计划谓词的 150 条 GECS/GRPE/ACEW replay，也不以随机 LLM 差异制造伪组件效果。H75 判失败，H74/H79 因提前停止记为未完成，H76-H78 不评估，200 题 held-out 不授权。

该失败揭示的不是样本中没有国籍关系，而是 **compiler predicate vocabulary drift**。50 个计划中实际有 7 个语义对应 country/nationality 的二跳槽，编译为 `CountryOfBirth×3`、`FromCountry×1`、`HasNationality×3`；其原始 2Wiki evidence relation 七题全部为 `country of citizenship`。source 在这七题只答对 2 题，并出现三个明确的 country/demonym 错误：`United States→American` 两题、`Australia→Australian` 一题。另有 `American→America` 属于 gold 表面别名问题，ACEW 不能自行定义评分别名；`Danish` 题的第一槽遗漏电影约束并检索错导演，局部第二槽也不能修复上游锚点。

因此下一架构组件限定为 **Predicate-Family Normalization for ACEW**：把语义明确的 country/nationality 计划别名映射到同一局部窗口作用域，同时保留 schema23 exact-registry ACEW 作消融。不得使用任意 `country` 子串扩张，不得声称解决上游检索或 gold alias。先在这 7 个已观察训练别名题做新编号诊断；若通过，再换另一组不重叠样本检验泛化。机器判定见 v23 `predicate-scope-audit.json` 与 `early-stop-validation.json`。

#### v24：谓词族归一化 ACEW 诊断结果

schema24 在保持 schema23 exact-registry ACEW 不变的前提下，新增闭合集合别名 `HasNationality`、`CountryOfBirth`、`FromCountry`，并记录 `anchor_window_predicate_normalizations`。实现不引入额外检索、gold/QID、外部知识或额外 LLM；别名窗口仍要求问题锚定的受保护实体值，避免把任意 `country` 子串当作语义关系。新增方法名为 `slotrag-normalized-anchor-window-projection`，旧 ACEW 与 GRPE 作为控制。

本轮使用 v23 已观察的 7 条 2Wiki train 别名题，sample SHA-256=`7722c7...b000`，不把它们当作 held-out 或泛化集。v24 在在线调用前固定了 schema24、21 条记录、7 个 imported frozen plans、两个 worker、服务许可 30 RPM、运行硬限 20 RPM、相邻 permit 3 秒；实际运行只启动两个控制 worker，再启动一个候选 worker。最终 21/21 final `ok`、21/21 immutable attempts、attempt1、benchmark retry=0，7/7 计划 imported/ok，missing/hash mismatch/effective variant/inconsistent pair 均为 0；三项 doctor 均 HTTP 200。完整分母与运行审计见 `runs/vldb2027-diagnostic-v24/summaries/predicate_normalized_anchor_diagnostic/`、`manifest.json`、`progress.json`、`service-doctor.json`。

| 方法 | EM | F1 | Evidence Recall | MRR | R@1/5/10 | P@1/5/10 | nDCG@10 | LLM/provider calls | total tokens | wall mean/p50/p95 (s) | structured fail/repair/ground | deterministic |
|---|---:|---:|---:|---:|---|---|---:|---:|---:|---|---|---:|
| GRPE | 0.2857 | 0.3061 | 0.7857 | 0.7500 | 0.3571/0.7143/0.7857 | 0.7143/0.2857/0.1571 | 0.7279 | 3.4286/8.0000 | 4108.14 | 41.50/47.19/65.64 | 1.0000/0.7143/0.7143 | 0.5714 |
| ACEW（schema23 exact） | 0.2857 | 0.2857 | 0.7857 | 0.7500 | 0.3571/0.7143/0.7857 | 0.7143/0.2857/0.1571 | 0.7279 | 4.1429/8.7143 | 4105.43 | 41.04/45.39/54.18 | 1.0000/0.7143/0.7143 | 0.5714 |
| NACEW（schema24） | 0.4286 | 0.4286 | 0.7857 | 0.7500 | 0.3571/0.7143/0.7857 | 0.7143/0.2857/0.1571 | 0.7279 | 3.4286/8.0000 | 3625.43 | 37.43/35.45/54.53 | 0.7143/0.5714/0.4286 | 0.7143 |

NACEW 相对 GRPE 的平均 token 减少约 11.75%，wall mean 减少约 9.79%；窗口累计输入/输出字符为 `3243/948`，池化字符削减率 `0.7174`，无窗口 fallback。检索指标全部与控制相同，说明本轮收益来自抽取上下文而非检索分布变化。逐题结果显示 NACEW 3/7 正确（`2b7192`、`a04e2f`、`bc4447`），ACEW 2/7、GRPE 2/7；`a04e2f` 的 `United States→American` 被修正，但 `42fc8c` 与 `a78307` 两个 demonym 错误未修正，`5f99e2` 的上游导演计划缺约束，`6b2fb1` 的 gold 表面为 `America`。

预注册门判定：H80 完整性 **通过**；H81 作用域 **失败**（候选仅 3/7 alias contracts 与 3/7 normalizations，控制为 0）；H82 目标质量 **失败**（候选总体 F1 达标，但 3 个预注册 demonym 错误只修正 1 个）；H83 成本/可靠性 **通过**；H84 报告完整性 **通过**。因此不授权新的 disjoint-50 泛化门，也不在同一 7 题上改阈值重跑。失败原因是当前窗口契约依赖 `protected_anchor_values`：含计划常量的题可触发，只有约束或编译缺少实体常量的题不会伪造窗口。下一步改为独立的 **constraint-aware query anchor context** 诊断：仅从计划约束/问题中确定性恢复已出现的锚点，仍保持闭合谓词集合、无外部知识，并换新运行编号验证。

#### v25：Constraint-aware Query Anchor Context

schema25 新增 `query_grounded_anchor_contexts`，候选 `slotrag-context-normalized-anchor-window-projection` 只从两类本地信息恢复锚点：计划 arguments/constraints 中能在问题中逐字落地的值，以及存在 `... of film/movie/song <title>` 关系根时的问题标题短语。它不访问 gold、QID、外部字典或第二个模型，也不改变 GRPE、schema23 ACEW 或 schema24 NACEW。全仓回归为 `190 passed, 1 skipped`，运行源码提交/指纹为 `71af196...a66d6e` / `b9a238...e4af3c`。

v25 是新的架构修复诊断，不改写 v24 阈值；仍明确使用同一组 7 条已观察机制题，因此不能作泛化结论。在线预注册固定 schema25、21 条 final、7 个 imported frozen plans、最大两个互斥 worker、`30 RPM provider / 20 RPM operational / 3s permit`。最终 21/21 final `ok`、21 immutable attempts、benchmark retry=0；7/7 snapshots imported/valid，所有 provenance/hash/variant/inconsistent pair 计数为 0。Agnes/embedding/reranker provider attempts=`73/48/48`，Agnes 有 2 次内部 retry；首末落盘间隔 527.90 秒，对应阶段平均 `8.30/5.46/5.46 RPM`，硬上限仍由共享 permit 保证。

| 方法 | EM/F1 | Evidence Recall/MRR/nDCG | R@1/5/10 | P@1/5/10 | LLM/provider calls | tokens | wall mean/p50/p95 (s) | fail/repair/ground | context/window/norm | deterministic |
|---|---|---|---|---|---|---:|---|---|---|---:|
| GRPE | 0.2857/0.2857 | 0.7857/0.7500/0.7279 | 0.3571/0.7143/0.7857 | 0.7143/0.2857/0.1571 | 3.5714/8.1429 | 4109.57 | 39.30/44.59/54.07 | 1.0000/0.7143/0.7143 | 0/0/0 | 0.5714 |
| ACEW（exact 控制） | 0.4286/0.4286 | 0.7857/0.7500/0.7279 | 0.3571/0.7143/0.7857 | 0.7143/0.2857/0.1571 | 3.4286/8.0000 | 4109.29 | 34.09/29.13/51.09 | 1.0000/0.7143/0.7143 | 0/0/0 | 0.5714 |
| CQAC-NACEW | 0.5714/0.5714 | 0.8571/0.7738/0.7591 | 0.3571/0.7143/0.8571 | 0.7143/0.2857/0.1714 | 3.4286/8.0000 | 3515.71 | 37.56/38.99/63.19 | 0.7143/0.5714/0.4286 | 7/9/9 | 0.5714 |

候选累计窗口输入/输出字符=`13267/2799`，池化削减率 `0.7668`，fallback=0；相对 GRPE token 减少 14.45%，Evidence Recall 与 nDCG@10 分别增加 0.0714/0.0312。逐题正确 4/7：`2b7192`、`42fc8c`、`a04e2f`、`bc4447`；`5f99e2` 仍由缺电影约束的上游计划产生错误导演集合，局部窗口不能恢复 join 根；`6b2fb1` 是 `American` 对 gold `America`；`a78307` 的证据明确写 `Australian`，但 extractor 两次 grounding reject 后回退成 `Australia`。

预注册门判定：H85 **通过**；H86 **失败**，虽然 7/7 题都有一个 query context，但 raw contract/normalization 为 9 而非预注册的恰好 7，因为两题各物化两个 binding contexts；H87 **失败**，候选 F1 与正确数显著高于 GRPE，但同轮旧 ACEW 随机答对 `42fc8c`，候选相对该控制只新增修正 1/3 demonym IDs；H88、H89 **通过**。因此仍不授权 disjoint-50 或 held-out-200，也不再对这 7 题做在线调参。下一步先离线拆分三类剩余错误：compiler root omission、gold surface alias、grounding repair；新的在线门必须使用不同问题，而不是继续追逐七题随机波动。机器判定见 v25 `offline-validation.json`、`online-validation.json` 与完整 summaries。

#### v26：Query-Root + Evidence-Surface Repair 与新 50 题训练门

schema26 将 v25 剩余错误拆成两个互不混淆的局部修复。**Query-root repair** 只在问题中能唯一恢复一个标题、计划中该标题尚未出现、且只有一个无约束的度 1 `*Of` 根槽时，把标题追加为该根槽常量；歧义、多根、非 `*Of`、已有常量或已有约束时保持惰性。**Evidence-surface repair** 只处理闭合 country/nationality 谓词族的角色投影字段：抽取值与证据中的单个原词必须为最短 5 字符的前缀近邻且长度差不超过 2，才用证据原词替换，例如 `Australia -> Australian`；它不访问 gold、QID、外部词典或第二个模型，也不把 `American -> America` 这类评分别名问题伪装成 grounding 修复。新增遥测为 `query_anchor_plan_repairs` 与 `evidence_surface_grounding_repairs`。

实现提交为 `86f0c65`，随后在 `c23f0fc` 增加两个显式单组件方法，形成 CQAC 基座上的 2×2 消融：无修复、仅 root、仅 surface、root+surface。全仓回归为 `195 passed, 1 skipped`，Python compileall 与 diff check 通过；冻结执行源码指纹为 `09de771e...03af1`。六路训练配置为默认 SlotRAG source、GRPE、CQAC、CQAC+root、CQAC+surface、CQAC+root+surface，配置文件为 `configs/experiments/repaired-anchor-training.yaml`。

本轮不是 v23 的失败重跑，而是另建 `runs/vldb2027-training-v26`。在任何在线调用前，先汇总 36 份既有 2Wiki sample artifact 的 100 个唯一 ID，再从 167,454 条公开 train 中排除它们；以种子 2030、与 benchmark sampler 相同的“按层配额 + 最小 `SHA256(seed:dataset:id)`”规则冻结 50 题。结果为 50/50 唯一、历史交集 0，bridge-comparison/comparison/compositional/inference=`11/15/22/2`，sample SHA-256=`5a1ca0e9...9ea91`；原始 train 仍为 0 invalid、SHA-256=`ad0f2771...18f01`。完整文件级交集审计见 `historical-sample-overlap-audit.json`。

执行采用两阶段不可变门：先只运行 50 条默认 SlotRAG，生成同源 frozen plans 和 source finals；只有 H90-H92 全部通过才运行其余 250 条 replay。服务许可/运行硬限/相邻同 provider attempt 固定为 `30 RPM / 20 RPM / 3s`，retry 同样占配额；用户指定的最大并发为 2，因此 replay 最多同时启动两个互斥 worker。完整实验若获授权应有 300 条 schema26 final，250 条 replay 必须共享相同 50 个计划。

| 门 | 预注册通过条件 |
|---|---|
| H90 材料完整性 | 50 个唯一 ID、所有历史 2Wiki 样本交集为 0、数据审计有效，并冻结 revision/fingerprint/config/sample hash；本项在调用前已通过 |
| H91 source 完整性 | 50 个有效计划快照与 50 个 schema26 source final，至少 49/50 final ok；attempt、provider retry、provenance 与 hash 全保留 |
| H92 replay 必要性 | source 计划至少 4 个唯一问题出现闭合 country/nationality 谓词族，且至少 1 个唯一计划可被 query-root repair；source success rate 至少 0.98，否则立即停止，不运行 250 条 replay |
| H93 replay 完整性 | 共 300 final、至少 294 ok；250 replay 同源；missing/unknown/hash mismatch/inconsistent pair/effective variant 全为 0 |
| H94 回答质量 | 完整候选总体 F1 ≥ `max(GRPE,CQAC)-0.02`；任一新修复激活子集上 F1 不低于 CQAC 且 wins≥losses；success rate ≥0.98 |
| H95 作用域与消融 | 2×2 四格只改变 root/surface 开关；完整候选两组件各至少一次真实激活；无越界修复，非回退窗口不扩张，累计字符削减至少 30% |
| H96 成本与可靠性 | 完整候选 calls/provider attempts/tokens 各 ≤`1.10×CQAC`；结构失败、repair、ground reject、evidence fallback、generation、length finish 各 ≤`CQAC+0.02/题`；deterministic rate ≥`CQAC-0.02` |
| H97 检索保持 | Evidence Recall、MRR、R@1/5/10、P@1/5/10、nDCG@10 每项均 ≥`CQAC-0.02` |
| H98 完整报告 | aggregate、逐题、检索、macro、分层、失败、计划、时延分位数、provider/RPM、激活、paired bootstrap 95% CI、精确配对检验、Holm 校正和配对效应量全部落盘 |

统计检验不作为晋级硬门，避免在单个 50 题训练样本上用显著性替代效应与机制证据。只有 H93-H98 全部通过，才授权另行冻结 held-out-200；观察本样本后若再改架构，必须换新的无重叠训练样本。机器预注册见 v26 `offline-validation.json`；source 结束后的不可变判定见 `source-plan-audit.json` 与 `early-stop-validation.json`。

#### v26 source 提前停止：随机训练门缺少 surface 覆盖

三项服务探针均为 HTTP 200 后，source 先顺序运行 50 题；过程中 1 个 embedding HTTP 503 attempt（含 2 次 provider retry）被保留并在恢复探针后以 `attempt-0002` 成功续跑。最终为 50/50 schema26 final `ok`、50/50 计划快照有效、51 个 execution attempts（benchmark retry=1），无缺失计划、provenance、plan hash mismatch、effective variant 或题内不一致。attempt 级失败分母仍报告为 1/51=`0.0196`，不能只报告续跑后的 50/50。

| source SlotRAG 指标（n=50） | 数值 |
|---|---:|
| EM / F1 | 0.8600 / 0.8884 |
| Evidence Recall / MRR / nDCG@10 | 0.8200 / 0.9433 / 0.8317 |
| R@1 / R@5 / R@10 | 0.3950 / 0.8100 / 0.8200 |
| P@1 / P@5 / P@10 | 0.9000 / 0.3680 / 0.1860 |
| LLM calls / provider calls（共享编译排除） | 1.92 / 5.24 |
| shared-compile-inclusive LLM / provider calls | 2.88 / 6.20 |
| execution tokens / shared-compile-inclusive tokens | 2810.04 / 4546.58 |
| wall mean / p50 / p95 / p99（s） | 18.06 / 16.48 / 37.19 / 43.99 |
| structured failure / repair / grounding rejection | 0.1200 / 0.1200 / 0.0200 |
| deterministic answer rate | 0.8600 |
| index build mean / index provider calls | 1.342 s / 0.98 |

所有 source 计划中只有 **1 个唯一问题**出现闭合 country/nationality 谓词族（`HasNationality`），而预注册 H92 要求至少 4 个；query-root repair 的前瞻机会有 5 个，source final success rate 为 1.0。故 H91 **通过**、H92 **失败**：root 组件有覆盖，但 surface 组件没有达到预注册的必要覆盖，不能用 1 题结果声称 2×2 消融有效。按照调用前冻结的 futility rule，不启动 250 条 replay，也不把 H93-H98 记为失败或通过；held-out-200 继续未授权。

source 阶段 benchmark provider attempts（计划编译、索引和执行合计）为 Agnes/embedding/reranker=`147/138/85`，provider retries=`0/2/0`，总计 370 attempts；按落盘记录窗口计算平均 RPM=`3.56/3.34/2.06`，共享 limiter 仍固定执行 `20 RPM` 硬上限、每次 retry 重新取得 3 秒 permit、最大并发 2。完整 source 指标、分层结果、逐题结果、检索指标、失败分母、计划审计和时延分位数均已生成于 `runs/vldb2027-training-v26/summaries/repaired_anchor_training_gate/`。

这次早停说明的是**随机样本的机制覆盖不足**，不是 surface repair 已被证伪。下一步不在这 50 题上补跑；改为新建完全不重叠的、按公开 2Wiki relation strata 预注册的机制门：单独保证足够的 country-of-citizenship 目标题与标题关系根控制题，再重新执行同一 2×2 消融。该机制门的结论只能作为组件诊断，不能替代随机 held-out 泛化评估。

#### v27：Relation-stratified 2×2 机制门预注册

v27 使用 `runs/vldb2027-training-v27` 和阶段 `mechanism_stratified_repair_gate`，方法代码不再改变，仍使用 schema26 与 v26 的四格消融。样本仅按公开 2Wiki `evidences` relation label 和问题文本正则分层，不读取答案：`country of citizenship + film/movie/song title-root` 20 题、`country of citizenship + non-title` 20 题、无 country/nationality 关系的 title-root 控制 10 题。种子 2031 在每层保留最小 `SHA256(seed:dataset:stratum:id)`，排除 37 份历史 sample artifact 的 150 个唯一 ID；最终 50/50 唯一、历史交集 0，sample SHA-256=`94db4089...073d5`。三个候选池在排除历史后分别仍有 `18757/26046/49981` 条，抽样不是因候选不足而放宽。

这是一组**机制分层训练诊断**，不能用于估计自然分布总体 F1，也不能替代随机 held-out。配置提交为 `e516bd6`，冻结源码指纹为 `44f4488e...7e8977`；六路方法仍为 source SlotRAG、GRPE、CQAC、CQAC+root、CQAC+surface、CQAC+root+surface，共预期 300 条 schema26 final。先运行 50 条 source；只有 H99-H101 全部通过，才以最多两个互斥 worker 运行 250 条同计划 replay。30 RPM provider 许可、20 RPM operational 硬限、3 秒 permit、retry 占配额与并发 2 保持不变。

| 门 | 预注册通过条件 |
|---|---|
| H99 材料完整性 | 三个 mechanism strata 精确为 20/20/10；50 个唯一 ID；与全部 150 个历史 2Wiki ID 交集为 0；dataset/config/sample/source fingerprint hash 冻结 |
| H100 source 完整性 | 50 个有效 frozen plans 与 50 个 schema26 source final，至少 49/50 final ok；attempt、retry、provenance 与 hash 全保留 |
| H101 机制覆盖 | 40 个 target 中至少 30 个唯一计划出现闭合 country/nationality 谓词；10 个非目标控制中至多 1 个误入该谓词族；30 个 title-root 题中至少 4 个可前瞻触发 query-root repair；source success rate ≥0.98，否则提前停止 |
| H102 replay 完整性 | 总计 300 final、至少 294 ok；250 replay 同源；missing/unknown/hash mismatch/inconsistent pair/effective variant 全为 0 |
| H103 回答质量 | 完整候选总体 F1 ≥`max(GRPE,CQAC)-0.02`；40 个 target 和每个新修复激活子集上 F1 均不低于 CQAC、paired wins≥losses；success rate ≥0.98 |
| H104 2×2 作用域 | 四格只改变 root/surface 开关；root 与 surface 各在至少 4 个唯一题真实激活；surface 在 10 个非目标控制上为 0；所有修复满足 query-grounded/exact-source/closed-predicate 边界；窗口累计字符削减 ≥30% 且非回退窗不扩张 |
| H105 成本可靠性 | 完整候选 calls/provider attempts/tokens 各 ≤`1.10×CQAC`；结构失败、repair、ground reject、fallback、generation、length finish 各 ≤`CQAC+0.02/题`；deterministic rate ≥`CQAC-0.02` |
| H106 检索保持 | 完整候选的 Evidence Recall、MRR、R@1/5/10、P@1/5/10、nDCG@10 每项均 ≥`CQAC-0.02` |
| H107 完整统计 | 全指标、三层逐层结果、逐题、失败与 provider/RPM 分母、计划审计、paired bootstrap 95% CI、精确配对检验、Holm 校正及配对效应量全部落盘；显著性不作硬门 |

只有 H102-H107 全部通过，才授权另建一组自然分布、无历史交集的随机 100 题训练泛化门；v27 本身不直接授权 held-out-200。若观察 v27 后修改方法或阈值，必须换新样本，不能在这 50 题上重新宣称通过。

#### v27 source 提前停止：极性模板与新谓词别名

source 最终为 50/50 schema26 final `ok`、50/50 frozen plans、50 execution attempts，benchmark retry=0；frozen-plan 审计中的 invalid/missing/hash mismatch/unknown/inconsistent/effective variant 全为 0。Agnes 有 2 次 provider 内部 retry，但同一 final attempt 内恢复，完整 provider attempts（编译、索引、执行合计）为 Agnes/embedding/reranker=`139/133/83`，平均 RPM=`6.80/6.50/4.06`，仍低于 20 RPM 硬限。

| source SlotRAG 指标（n=50，机制分层集） | 数值 |
|---|---:|
| EM / F1 | 0.7600 / 0.7893 |
| Evidence Recall / MRR / nDCG@10 | 0.7150 / 0.8767 / 0.7441 |
| R@1 / R@5 / R@10 | 0.3300 / 0.7150 / 0.7150 |
| P@1 / P@5 / P@10 | 0.8600 / 0.3760 / 0.1880 |
| LLM / provider calls（共享编译排除） | 2.08 / 5.40 |
| shared-compile-inclusive LLM / provider calls | 2.78 / 6.10 |
| execution / shared-compile-inclusive tokens | 2870.18 / 4060.74 |
| wall mean / p50 / p95 / p99（s） | 18.57 / 14.62 / 40.74 / 43.85 |
| structured failure / repair / grounding rejection | 0.3400 / 0.3200 / 0.0200 |
| deterministic answer rate | 0.9400 |

H100 **通过**，H101 **失败**。30 个 title-root 题中 9 个可前瞻触发 query-root repair（阈值 4），10 个非目标控制的 country/nationality 谓词污染为 0（阈值至多 1），source success rate=1.0；但 40 个 relation-target 中只有 10 个计划进入现有闭合谓词族（阈值 30）。互斥分解为：10 个 closed-family、4 个新出现的 `NationalityOf`、26 个单槽 `EvidenceAnsweringQuestion`。后 26 个主要是包含 `same/both` 的 yes/no 比较题，被既有 polar template 有意折叠成证据问答槽；source 在 bridge-comparison/comparison 上 F1=`0.85/1.00`，没有证据支持把局部 surface repair 强行扩到该通用槽。

因此按预注册不启动 250 条 replay，H102-H107 记为未评估，随机 100 与 held-out-200 均未授权。下一架构只作一个闭合词表修正：把语义精确的 `NationalityOf` 加入 normalized country/nationality family；不改变 polar template。随后使用新的无重叠短答案 compositional relation 样本重做机制门，排除 yes/no 极性题造成的不可应用覆盖。机器判定见 v27 `source-plan-audit.json`、`early-stop-validation.json` 和更新后的 `offline-validation.json`。

#### schema27 与 v28：Compositional-only 2×2 机制门预注册

schema27 只做 v27 直接观察支持的最小修正：将语义精确的 `NationalityOf` 加入 normalized country/nationality 闭合谓词族，从而允许该谓词使用查询锚点窗口与证据原词表面修复。它不加入 exact ACEW 谓词集，不修改 `EvidenceAnsweringQuestion` 极性模板，不放宽前缀距离、查询落地或唯一原词约束。实现提交为 `c6a1a12`，runner final schema 升为 27；全仓回归为 `196 passed, 1 skipped`。

v28 固定为 `runs/vldb2027-training-v28`、阶段 `compositional_repair_gate`，配置提交为 `0297ce4`，source fingerprint 为 `c81f6ab2...9e4ab4`。样本仅从 2Wiki train 中 `type=compositional` 的短答案问题选取，不读取 gold answer：`country of citizenship + title-root` 25 题、`country of citizenship + non-title` 15 题、无 country/nationality/citizenship 关系的 title-root 控制 10 题。种子 2032 在每层保留最小 `SHA256(seed:dataset:stratum:id)`，并排除 38 份历史 sample artifact 的 200 个唯一 ID。最终 50/50 唯一、50/50 compositional、历史交集 0，sample SHA-256=`51410fc5...1c295`；三个排除历史后的候选池为 `11748/1834/49968`。控制组的关系标签污染、目标组缺失目标关系、title-root 分层错配均为 0。样本、机制审计、dataset audit 哈希分别为 `51410fc5...1c295`、`efd8f2b6...d63188`、`f3fb2252...bfdb60`。

本轮仍是**机制分层训练诊断**，不估计自然分布总体 F1。六路方法为 source SlotRAG、GRPE、CQAC、CQAC+root、CQAC+surface、CQAC+root+surface，共预期 300 条 schema27 final。先只运行 50 条 source；只有 H108-H110 全部通过，才能以最多两个互斥 worker 运行 250 条同计划 replay。provider 许可/运行硬限/同 provider attempt 最小间隔固定为 `30 RPM / 20 RPM / 3s`，retry 重新取 permit 并保留为不可变 attempt，最大并发为 2。

| 门 | 预注册通过条件 |
|---|---|
| H108 材料完整性 | 三个 compositional mechanism strata 精确为 25/15/10；50 个唯一 ID；与全部 200 个历史 2Wiki ID 交集为 0；控制关系无 country-family 污染；dataset/config/sample/source fingerprint 全部冻结 |
| H109 source 完整性 | 50 个有效 frozen plans 与 50 个 schema27 source final，至少 49/50 final ok；attempt、provider retry、provenance 和 hash 全保留 |
| H110 机制覆盖 | 40 个 target 中至少 35 个唯一计划出现 schema27 闭合 country/nationality 谓词；10 个控制中至多 1 个误入该谓词族；35 个 title-root 题中至少 4 个可前瞻触发 query-root repair；source success rate ≥0.98，否则立即停止 |
| H111 replay 完整性 | 总计 300 final、至少 294 ok；250 replay 同源；missing/unknown/hash mismatch/inconsistent pair/effective variant 全为 0，全部 retry 留存 |
| H112 回答质量 | 完整候选总体 F1 ≥`max(GRPE,CQAC)-0.02`；40 个 target 及 root/surface 各自真实激活子集上 F1 均不低于 CQAC 且 paired wins≥losses；完整候选 success rate ≥0.98 |
| H113 2×2 作用域 | 四格只改变 root/surface 开关；root 与 surface 各在至少 4 个唯一题真实激活；surface 在 10 个控制上为 0；所有修复满足 query-grounded/exact-source/closed-predicate 边界；窗口累计字符削减 ≥30% 且非 fallback 窗不扩张 |
| H114 成本与可靠性 | 完整候选 calls/provider attempts/tokens 各 ≤`1.10×CQAC`；structured failure/repair/ground reject/fallback/generation/length finish 各 ≤`CQAC+0.02/题`；deterministic rate ≥`CQAC-0.02` |
| H115 检索保持 | 完整候选 Evidence Recall、MRR、R@1/5/10、P@1/5/10、nDCG@10 每项均 ≥`CQAC-0.02` |
| H116 完整统计 | aggregate、三层分层、逐题、检索、失败、计划、时延分位数、provider/RPM、激活、paired bootstrap 10,000 次 95% CI、精确 McNemar/配对符号检验、Holm 校正和配对效应量全部落盘；显著性只作描述 |

只有 H111-H116 全部通过，才授权另建自然分布、无历史交集的随机 100 题训练泛化门；v28 本身不直接授权 held-out-200。观察 v28 后若修改架构、谓词集或阈值，必须更换新的无重叠样本。机器预注册为 v28 `offline-validation.json`，source 完成后以 `source-plan-audit.json` 和 `early-stop-validation.json` 作不可变判定。

#### v28 source 通过：授权 250 条同计划 replay

source 最终为 50/50 schema27 final `ok`、50/50 frozen plan snapshot 有效。执行共 51 个 immutable attempts：一题首次触发 300 秒 question timeout，`attempt-0002` 恢复，因此 benchmark retry=1，attempt 失败率为 1/51=`0.0196`；计划编译同样为 51 attempts，另一题首次 timeout 后恢复。两个失败分属不同问题，均未被最终成功记录覆盖；provenance 缺失、snapshot/effective hash mismatch、unknown snapshot 与 effective-plan variant 均为 0。

| source SlotRAG 指标（n=50，compositional 机制集） | 数值 |
|---|---:|
| EM / F1 | 0.4800 / 0.5193 |
| Evidence Recall / MRR / nDCG@10 | 0.7000 / 0.7125 / 0.6743 |
| R@1 / R@5 / R@10 | 0.3400 / 0.6700 / 0.7000 |
| P@1 / P@5 / P@10 | 0.6800 / 0.2680 / 0.1400 |
| LLM / provider calls（共享编译排除） | 2.96 / 7.64 |
| shared-compile-inclusive LLM / provider calls | 4.28 / 8.96 |
| execution / shared-compile-inclusive tokens | 4114.72 / 6266.84 |
| 成功 final wall mean / p50 / p95 / p99（s） | 26.34 / 22.44 / 47.86 / 51.44 |
| structured failure / repair / grounding rejection | 0.4800 / 0.4400 / 0.0400 |
| deterministic answer rate | 0.8200 |
| index build mean / index provider calls | 0.890 s / 0.98 |

机制分层显示 source 在 40 个 target 上 EM/F1=`0.4250/0.4375`，其中 25 个 title-root target 为 `0.2800/0.2800`，15 个 non-title target 为 `0.6667/0.7000`；10 个非 country 控制为 `0.7000/0.8467`。title-root target 的低分只说明这是有意构造的困难机制集，不能当作自然分布性能；同时它为 root/surface 消融提供了足够的差异空间。完整机制分层指标见 `source-mechanism-metrics.json`，标准全列见 `summaries/compositional_repair_gate/`。

H108、H109、H110 全部**通过**。在 40 个 target 中 37 个计划出现 schema27 闭合谓词（阈值 35），包括 `NationalityOf=18`、`HasNationality=6`、`Nationality=4`、`FromCountry=4`、`CountryOfBirth=3`、`CountryOfOrigin=2`；10 个控制污染为 0，35 个 title-root 中 15 个可前瞻触发 query-root repair，source success rate=1.0。三项均越过调用前锁定的 `35/1/4/0.98` 阈值，因此 `early-stop-validation.json` 给出 `CONTINUE_TO_REPLAY`，授权 GRPE、CQAC 与 2×2 四格共 250 条同计划 replay。

source 的计划、索引和执行合计 Agnes/embedding/reranker provider attempts=`217/170/120`，provider retry=`1/0/0`，总计 507 attempts。全部落盘记录窗因两次长停顿跨 21,377.5 秒，故窗口平均 RPM 仅为 `0.61/0.48/0.34`，不将其误当作瞬时吞吐；共享 limiter 仍对每个 attempt/retry 强制 3 秒 permit 和 20 RPM 硬上限。两个 300 秒 deadline 的落盘 wall 异常为约 2,360 秒与 4,240 秒，表明会话暂停或阻塞调用会延迟 Python 信号交付；后续可靠性结论必须同时报告 final 时延与 attempt 长尾，不能只报成功 final。

#### v28 replay 完成：root repair 有效，surface repair 覆盖不足，严格门禁不晋级

v28 replay 在 source 的 50 个冻结计划上完成了五个 replay 方法，共 300/300 final `ok`、303 个 immutable execution attempts。attempt 分母中的 3 个失败均保留：source 有 1 次 `budget_exceeded` 后重试成功，CQAC 有 2 次 embedding HTTP 503 后分别在 `attempt-0002` 恢复；没有最终失败记录被覆盖。所有 final schema 均为 27，provenance 缺失、source plan hash mismatch、unknown snapshot 和未预期的 effective-plan variant 均为 0。

| 方法 | EM / F1 | Evidence Recall / MRR / nDCG@10 | R@1/5/10 | P@1/5/10 | LLM / provider calls | tokens | final wall mean / p95 (s) | struct fail / repair / ground / fallback | deterministic | root / surface 激活题数 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SlotRAG | 0.4800 / 0.5193 | 0.7000 / 0.7125 / 0.6743 | 0.34 / 0.67 / 0.70 | 0.680 / 0.268 / 0.140 | 2.96 / 7.64 | 4114.72 | 26.34 / 47.86 | 0.48 / 0.44 / 0.04 / 0.10 | 0.82 | 0 / 0 |
| GRPE | 0.4400 / 0.4824 | 0.6900 / 0.6762 / 0.6513 | 0.32 / 0.65 / 0.69 | 0.640 / 0.260 / 0.138 | 3.02 / 7.70 | 4330.76 | 27.18 / 54.50 | 0.50 / 0.44 / 0.10 / 0.18 | 0.74 | 0 / 0 |
| CQAC | 0.4800 / 0.5224 | 0.7600 / 0.7154 / 0.6887 | 0.33 / 0.66 / 0.76 | 0.660 / 0.264 / 0.152 | 3.36 / 8.00 | 4241.32 | 28.03 / 52.44 | 0.76 / 0.64 / 0.24 / 0.32 | 0.62 | 0 / 0 |
| CQAC + root | 0.5600 / 0.6024 | 0.8900 / 0.9500 / 0.8864 | 0.47 / 0.87 / 0.89 | 0.940 / 0.348 / 0.178 | 2.42 / 6.38 | 3315.90 | 21.88 / 45.01 | 0.30 / 0.22 / 0.22 / 0.16 | 0.82 | 15 / 0 |
| CQAC + surface | 0.4800 / 0.5224 | 0.7400 / 0.7154 / 0.6793 | 0.33 / 0.65 / 0.74 | 0.660 / 0.260 / 0.148 | 3.32 / 7.92 | 4173.10 | 30.77 / 61.30 | 0.72 / 0.62 / 0.22 / 0.30 | 0.64 | 0 / 0 |
| CQAC + root + surface | **0.5800 / 0.6224** | **0.9000 / 0.9500 / 0.8971** | **0.47 / 0.88 / 0.90** | **0.940 / 0.352 / 0.180** | **2.42 / 6.42** | **3248.28** | **19.87 / 39.07** | **0.28 / 0.20 / 0.20 / 0.12** | **0.86** | **15 / 1** |

表中 calls/tokens 是 execution-only；shared-compile-inclusive 的 combined/CQAC 分别为 `3.74/7.74/5400.40` 与 `4.68/9.32/6393.44`，三项均低于 `1.10×CQAC`。完整列级指标、逐题记录、失败分母、计划审计、时延分位数和 retrieval 指标仍以 `summaries/compositional_repair_gate/` 为准。

配对统计以题目为单位、bootstrap `10,000` 次、seed=`2032`，差值定义为 `combined-reference`；精确 McNemar/配对符号检验只作描述，不作为晋级门槛：

| 比较 | F1 mean Δ | 95% bootstrap CI | wins / ties / losses | bootstrap p (Holm) | exact sign p (Holm) | exact McNemar EM p (Holm) |
|---|---:|---:|---:|---:|---:|---:|
| combined vs GRPE | +0.1400 | [0.0600, 0.2400] | 7 / 43 / 0 | 0.0016 (0.0192) | 0.0156 (0.1406) | 0.0156 (0.1406) |
| combined vs CQAC | +0.1000 | [0.0200, 0.2000] | 5 / 45 / 0 | 0.0128 (0.1280) | 0.0625 (0.4375) | 0.0625 (0.4375) |
| combined vs CQAC + root | +0.0200 | [0.0000, 0.0600] | 1 / 49 / 0 | 0.7248 (1.0000) | 1.0000 (1.0000) | 1.0000 (1.0000) |
| combined vs CQAC + surface | +0.1000 | [0.0200, 0.1800] | 5 / 45 / 0 | 0.0094 (0.1034) | 0.0625 (0.4375) | 0.0625 (0.4375) |

机制分层验证了 root repair 的主要贡献：在 40 个 target 上，combined/CQAC F1=`0.5625/0.4375`；在 15 个 root-active 题上为 `0.6000/0.2667`；surface-active 仅 1 题，F1=`1.0000/0.0000`，因此不能把最后一项当作稳定结论。combined root repair 实际激活 15 题，surface repair 仅激活 1 题；10 个控制题 surface activation=0。anchor-window 的 pooled character reduction=`0.6942`（逐题均值=`0.6602`），非 fallback window 没有扩张。

门禁最终状态如下：

| 门禁 | 状态 | 解释 |
|---|---|---|
| H108/H109/H110 | **PASS** | 样本、source 完整性和机制覆盖满足预注册阈值；source target closed=37/40、control=0/10、prospective root=15/35。 |
| H111 replay integrity | **严格 FAIL；注册 root variant 完整性 PASS** | 300 final、250 replay、hash/provenance 全部一致；但字面预注册要求 effective-plan variant=0，而 root factor 产生了 15 个预期 variant。 |
| H112 answer quality | **PASS** | overall、target、root-active、surface-active 均满足与 CQAC 的预注册比较，combined success=1.0。 |
| H113 factorial scope | **FAIL** | root 激活 15≥4，但 surface 仅 1<4；cell identity、query-grounding、closed-predicate、exact-source 实现边界和窗口不扩张检查通过。 |
| H114/H115/H116 | **PASS** | 成本/可靠性、检索保持和全量统计产物均满足门槛。 |

因此 v28 **不授权**新的随机 disjoint-100，也不授权 held-out-200。失败不是通过调阈值或在同一批题上重放可以解决的：下一轮必须新建无重叠样本和新的预注册。v29 的首要调优是扩大 surface repair 的可触发覆盖，同时把 H111 改成“source plan hash 必须一致、effective variant 只允许出现在预注册 root-active 集合”而不是与 root repair 相互矛盾的 variant=0；在此之前不宣称 surface ablation 已被验证。

本轮机器审计产物：`runs/vldb2027-training-v28/online-validation.json`、`replay-audit.json`、`paired-statistics.json`、`mechanism-replay-metrics.json`；离线预注册快照已更新为 `offline-validation.json` 的 `replay_complete` 状态，source 判定仍保存在 `early-stop-validation.json`。

#### v29 / vldb-submission-v1：五数据集投稿级主协议已冻结

为回答“所有 baseline、benchmark、指标和消融是否完整”的投稿要求，新增统一配置 `configs/experiments/vldb-submission-main.yaml`，运行目录固定为 `runs/vldb2027-submission-v1`。本协议在任何 provider 调用前完成预注册，机器快照为 `offline-validation.preregistered.json`（SHA-256=`32a570562edca74c8e2c1c8fd3922910178acb538a3d89811d9bbe0bf8f06996`），数据审计为 `dataset-audit.json`。

| 阶段 | 数据集 | 题数/数据集 | 方法/因子 | 预期 final |
|---|---|---:|---|---:|
| `main_comparison_smoke` | HotpotQA、2WikiMultihop、MuSiQue、StrategyQA、DROP evaluation | 5 | SlotRAG + Hybrid、IRCoT、ReAct、PlanRAG、SRAG、GraphRAG | 175 |
| `main_comparison` | 同上 | 100 | 同上七路受控适配器 | 3,500 |
| `execution_ablation` | 同上 | 50 | 原问题、自适应/固定/随机/Oracle 顺序，静态规划、no-replan、late-join、eager、no-bindings、no-operators、grounded-role projection；随机顺序使用 2040--2044 五个显式种子 | 3,750 |
| `component_ablation` | 同上 | 25 | source、no-direct、no-extremum-template、no-polar-template、no-polar-consensus、typed-extraction | 750 |

主比较和消融均使用同一 evaluation split、同一确定性分层采样和同一预算（最多 4 steps、64 次 LLM、4 次 retrieval、单题 300 秒）；不允许在线后重采样。每个 provider attempt（包括 retry）都必须取得 3 秒 permit，运行硬限为 20 RPM、许可上限 30 RPM、最大并发 2；失败 attempt 不覆盖，最终记录与 immutable attempts 分开统计。

最终报告注册 EM/F1、Accuracy、DROP EM/F1、Evidence Recall/MRR/R@1/5/10、P@1/5/10、nDCG@10，以及文档/段落访问、索引与各阶段时延 P50/P95/P99、LLM/provider calls、attempt/retry、token、失败类别、结构化修复、grounding rejection、重规划、绑定/算子、anchor/repair 激活等全部列级指标。统计以题目配对为单位，保存 10,000 次 paired bootstrap 95% CI、精确 sign/McNemar 描述检验和 Holm 校正；无 gold evidence 的数据集只报告 N/A，不回填为 0。

这里的 Hybrid、IRCoT、ReAct、PlanRAG、SRAG、GraphRAG 是 `src/slotrag/benchmarking/methods.py` 中在相同 normalized records、retrieval budget 和 provider 限流下运行的**受控本地适配器**；在没有逐项验证上游仓库训练/推理环境前，不把它们标成 exact upstream reproduction。`main_comparison_smoke` 仅用于验证 runner、服务和指标链路，不进入主表、显著性或投稿结论。

晋级条件已在预注册中固定：四个阶段的 final 分母完整、所有 dataset-method cell 存在、最终 `ok` 率达到 0.98（smoke 为 0.95）、attempt/retry/provenance/hash 审计通过、paired statistics 和所有失败分母落盘，并将结果与本节同步后，才可称为 submission-ready。任何架构、谓词集、阈值或样本变化都必须新建运行目录和新的预注册快照；不能在同一 run 上改协议。

#### v29-Qwen36：高并发服务切换与独立复验

原 `runs/vldb2027-submission-v1` 使用旧 Agnes 服务的 smoke 在 52 条 final、52 条 attempts 处停止，未完成且不进入任何主表。根据新的本地服务文档 `docs/qwen3.6-27b.md`，生成服务切换为 Qwen3.6-27B；新运行目录固定为 `runs/vldb2027-submission-qwen36-v1`，与旧服务完全隔离。Qwen 地址通过 `QWEN36_BASE_URL` 传入，配置层会将 `/v1/chat/completions` 规范化为 `/v1`，密钥只从 `QWEN36_API_KEY` 读取，永不写入 manifest 或结果。

Qwen 专用预注册快照为 `runs/vldb2027-submission-qwen36-v1/offline-validation.preregistered.json`，当前 SHA-256=`e0b0974893f6ddc0108dc3ff17b4e0a190da3296ce137f5ab77ca0368b446eb0`。生成服务初始限流为 provider 600 RPM、operational 480 RPM、并发 64；embedding/reranker 保持 30/20 RPM、默认并发 4。新增 `tools/run_benchmark_matrix.py` 按 dataset-method cell 启动最多 64 个独立 worker，单题仍沿用原子 item/immutable attempt、失败重试和共享文件限流，因此不会用线程共享全局 provider delta 伪造成本指标。先完成 35 个 cell 的 smoke（175 条 final），仅以吞吐、HTTP 错误、tool/JSON 解析和指标完整性决定是否提高并发；smoke 仍不进入最终结论。

并发调优记录：64 生成并发的压力轮因 embedding/reranker 20 RPM 排队产生 27 个 300 秒 timeout；将检索侧调到 16 并发/120 operational RPM 后，32 个矩阵 worker 又产生 17 个 Qwen `ReadTimeout`。两数据集、14 cell 的 16 并发探针为 70/70 `ok`，因此 v3 固定生成/矩阵并发 16、生成 240 operational RPM、embedding/reranker 120 operational RPM。v3 干净 smoke 运行目录为 `runs/vldb2027-submission-qwen36-v3`，预注册 SHA-256=`8291de266519cb92c4550d644940ac47b9a890867b0ced0b90f8dbed69772b66`；175/175 final、176 attempts、173 `ok`、1 个空回答、1 个 MuSiQue 计划超过 4 槽的结构性预算失败，无 HTTP/配置失败，smoke gate 通过。空回答 retry 后仍为空，按失败分母保留，不回填为 0；该 smoke 只授权进入主对比，不授权最终论文结论。

---

#### v29-Qwen36-main：3500 条投稿级主对比正式结果（2026-07-23）

> **审计结论：本节结果撤销投稿资格。** 这次运行调用的是
> `src/slotrag/benchmarking/methods.py` 的受控本地适配器，没有调用
> `/data/mzb/SlotRAG/baseline` 中 IRCoT、PlanRAG 或 GraphRAG 的上游推理入口；
> Hybrid/ReAct/SRAG 目录也只有说明性 README。因而本节只能作为 runner、限流、
> 失败分母和统计链路的诊断记录，不能作为“击败已发表 baseline”的主表。
> 机器审计见 `runs/baseline-audit-v1.json`，后续主表必须在每个方法挂接真实入口、
> 固定 commit、数据转换、提示词/模型配置和原始输出后重新生成。

`runs/vldb2027-submission-qwen36-v3` 的 `main_comparison` 已按冻结协议完成 35 个 dataset-method cell，共 3,500/3,500 个 final 和 3,500/3,500 个 immutable attempts，schema v27，缺失记录为 0。最终状态为 3,453 `ok`、30 `empty`、17 `budget_exceeded`，完成率 1.0，最终 `ok` 率 98.657%，通过预注册的 98% 主实验门槛；本轮无重试 attempt，失败状态全部进入分母。HotpotQA 与 2WikiMultiHopQA 共 1,400 条记录有 gold evidence，其他数据集的证据指标严格为 `N/A`。

主指标按数据集定义：HotpotQA/2WikiMultiHopQA/MuSiQue 为 F1，StrategyQA 为 Accuracy，DROP 为 DROP F1。下表是 100 题/格的主指标均值；完整列级指标、逐题记录、分层结果、失败报告和 paired bootstrap 位于对应 summary 目录。

| 数据集（主指标） | SlotRAG | GraphRAG | Hybrid | IRCoT | PlanRAG | ReAct | SRAG |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2WikiMultiHopQA（F1） | **0.6091** | 0.0181 | 0.0183 | 0.0181 | 0.0168 | 0.0179 | 0.4811 |
| HotpotQA（F1） | **0.5041** | 0.0140 | 0.0165 | 0.0151 | 0.0137 | 0.0156 | 0.4561 |
| MuSiQue（F1） | **0.3278** | 0.0054 | 0.0080 | 0.0097 | 0.0085 | 0.0095 | 0.1563 |
| StrategyQA（Accuracy） | 0.8700 | 0.4700 | 0.4700 | 0.4700 | 0.4700 | 0.4700 | **0.8900** |
| DROP（DROP F1） | **0.5851** | 0.0218 | 0.0215 | 0.0218 | 0.0213 | 0.0223 | 0.4641 |

相对最强结构对照 SRAG 的逐题 paired bootstrap 结果如下。SlotRAG 在 2Wiki、MuSiQue 和 DROP 的质量差异显著，在 HotpotQA 和 StrategyQA 上区间包含 0；因此不能把“所有数据集全面显著领先”写入论文。

| 数据集 | SlotRAG-SRAG 均值差 | 95% CI | 胜/平/负 | Holm p |
|---|---:|---:|---:|---:|
| 2WikiMultiHopQA | +0.1280 | [+0.0577, +0.1989] | 26/65/9 | 0.0006 |
| HotpotQA | +0.0480 | [-0.0245, +0.1215] | 30/46/24 | 0.3840 |
| MuSiQue | +0.1715 | [+0.0920, +0.2572] | 44/35/21 | <0.0001 |
| StrategyQA | -0.0200 | [-0.0500, 0] | 0/98/2 | 0.3840 |
| DROP | +0.1210 | [+0.0579, +0.1902] | 16/78/6 | <0.0001 |

跨数据集宏平均用于描述成本与系统行为，不把不同任务的主指标简单当成同一统计量。SlotRAG / Hybrid / SRAG 的关键均值分别为：Evidence Recall@5 `0.7525 / 0.9325 / 0.7400`，Evidence MRR `0.9475 / 0.9833 / 0.9460`，Evidence NDCG@10 `0.7940 / 0.9476 / 0.7736`；唯一文档访问 `4.44 / 6.50 / 4.67`，total tokens `3,836 / 2,010 / 4,894`，provider calls `5.95 / 3.00 / 6.40`，在线 wall latency `18.82 / 21.38 / 22.96 s`。SlotRAG 的编译/执行/物化/生成均值延迟为 `5.83 / 8.16 / 8.16 / 4.82 s`，平均计划为 `1.59 slots / 0.61 joins / complexity 4.76`。这说明方法的质量收益伴随编译和抽取成本，检索证据排序不是当前优势，成本/延迟只在部分数据集改善。

本表的 GraphRAG、Hybrid、IRCoT、ReAct、PlanRAG、SRAG 仍是 `src/slotrag/benchmarking/methods.py` 的受控本地适配器：它们共享 normalized records、题目、检索预算、Qwen3.6 服务和限流，但尚未逐项复现各论文上游仓库的训练、提示词和推理实现。因此不能将本表用于“击败已发表方法”、投稿排名或全面成本优势结论。旧表中的极低 F1 还暴露了 Qwen 推理文本污染答案的问题；评分修订为 `final_tag_or_think_suffix_v2`，先取最后答案标签或最后 `</think>` 后缀，同时保留原始输出，旧数值不与新协议混合。正式原始产物仍保留在 `runs/vldb2027-submission-qwen36-v3/summaries/main_comparison/`，但标记为诊断结果。

#### v30：baseline 真实性门禁与评分协议

新增 `slotrag benchmark baseline-audit --suite configs/experiments/vldb-submission-main.yaml`。每次运行 manifest 现在记录 baseline 的本地路径、git commit、入口文件 SHA-256、缺失运行材料、支持的数据集和 `exact_upstream_execution_verified`；当前值为 `false`，比较有效性固定为 `diagnostic_local_adapters`。只有在逐方法执行记录、原始 stdout/stderr、统一数据映射和答案解析审计全部通过后，才允许把该字段升级为 `upstream_reproduction`。

评分字段同时保留 `prediction_raw_chars`、`prediction_scored` 和 `answer_extraction=final_tag_or_think_suffix_v2`：先排除全部 `<think>...</think>`，再取最后一个 `<answer>/<final>/<final_answer>/<output>/<result>` 标签内容；没有答案标签时取最后一个 `</think>` 后的非空内容。这不会覆盖原始模型输出，也不会把解析后的分数与旧 `main_comparison` 数值混写；所有重跑必须新建 run 目录并重新生成 paired bootstrap、失败报告和数据审计。

离线重评分产物为 `runs/vldb2027-submission-qwen36-v3-rescored-v2-final`（provider calls=0，3500 final + 3500 immutable attempts，缺失=0）。它只替换 `scores`，不改原始 `result.answer`。主指标变化如下，表中仍然只是本地适配器诊断，不具备 upstream baseline 投稿资格：

| 数据集 | SlotRAG | GraphRAG | Hybrid | IRCoT | PlanRAG | ReAct | SRAG |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2WikiMultiHopQA F1 | 0.6872 | 0.8199 | 0.8099 | 0.8116 | 0.7799 | 0.8099 | 0.6040 |
| HotpotQA F1 | 0.6749 | 0.8087 | 0.7844 | 0.7986 | 0.7140 | 0.7818 | 0.6968 |
| MuSiQue F1 | 0.4384 | 0.2133 | 0.4480 | 0.5318 | 0.5001 | 0.4686 | 0.3392 |
| StrategyQA Accuracy | 0.8400 | 0.8900 | 0.9000 | 0.8600 | 0.8600 | 0.8800 | 0.8600 |
| DROP F1 | 0.6245 | 0.6908 | 0.7062 | 0.6735 | 0.6978 | 0.7078 | 0.5845 |

这组结果否定了旧表的“SlotRAG 全面领先”叙事：答案抽取修复后，SlotRAG 只在 MuSiQue 相对部分本地适配器占优，DROP/2Wiki/Hotpot 等需要重新设计方法或改用真实上游实现，不能通过调阈值修饰。下一轮投稿主实验必须以真实可运行 baseline 或明确的不可比清单为前置门禁。

#### v31：投稿级实验执行与完整记录协议

完整执行计划见 [`docs/VLDB2027-experiment-plan-v31.md`](VLDB2027-experiment-plan-v31.md)。新 run 先经过上游 baseline/data/split 审计，再进行 10--20 题 smoke，最后才允许完整 evaluation/test 和不重叠消融；所有阶段固定题目 ID、服务限流、失败分母和统计脚本。记录层新增可选 provider trace：`SLOTRAG_TRACE_ENABLED=true` 时，每个题目和 attempt 保存 Agnes/embedding/reranker 的脱敏请求/响应、HTTP 状态、耗时、retry 和 request ID；`SLOTRAG_TRACE_INCLUDE_PAYLOADS=true` 才保存完整 payload/response，API key 永不写入。矩阵命令同时保存 `matrix-manifest.json`，旧 run 不被覆盖。

#### v32：可审计 smoke 与投稿门禁落地（2026-07-23）

新增 `slotrag benchmark gate`。它把 `manifest.json`、`matrix-manifest.json`、`baseline-audit.json`、`command.txt`、final/item、immutable attempt、trace 的事件数与 SHA-256、dataset-method cell 数量和上游执行真实性合并为一个机器判定；默认不允许用 local adapter 结果生成投稿结论，`--allow-diagnostic-adapters` 只放行内部分析，不改变 `publication_claim_allowed=false`。smoke 阶段即使完整，也固定标为 `diagnostic_complete`，不能进入论文主表。

真实 Qwen3.6-27B 服务 smoke 运行目录为 `runs/vldb2027-smoke-qwen36-trace-v1`，配置为允许 30 RPM、实际 20 RPM、服务级并发 64，embedding/reranker 同样使用 20 RPM 实际限流；Qwen3.6、Qwen3-Embedding 和 BGE-reranker doctor 均为 HTTP 200。HotpotQA evaluation 的 5 题 SlotRAG cell 结果为 5/5 final、5/5 attempt、5/5 `ok`，无 retry、empty 或 budget failure；每题有 1 个 trace 文件，事件数与 SHA-256 审计通过，trace payload 未发现 API key。答案解析版本固定为 `final_tag_or_think_suffix_v2`，示例记录 `prediction_scored` 与 `result.answer` 分离保存。

该 smoke 只证明新 Qwen 服务、限流、答案抽取、trace 和断点记录链路可运行，不证明 SlotRAG 相对任何 baseline 的优势。下一步先为 IRCoT/GraphRAG 建立逐仓库执行记录并按其可支持数据集单独报告；PlanRAG 维持 DQA locating/building 独立实验，不能硬映射到五个 QA 集。完成真实 upstream gate 前，任何全量对比或消融都只生成诊断数据。

IRCoT 上游材料已进一步落盘：`baseline/ircot/processed_data` 官方压缩包解压完成（HotpotQA/2WikiMultiHopQA/MuSiQue/IIRC 的 dev、subsampled test 与 train 文件 hash 见 `runs/ircot-processed-data-sha256-v1.txt`），官方评测仓库固定为 Hotpot `3635853403a8735609ee997664e1528f4480762a`、2Wiki `6bdd033bd51aae2d36ba939688c651b5c54ec28a`、MuSiQue `24cc5b297acc2abfc5fb3d0becb6ef7b73d03717`。隔离环境已生成官方 HotpotQA 配置；`runs/ircot-upstream-preflight-v1.json` 仍判定不可执行，阻塞为 raw Wikipedia corpus 下载源无响应、retriever/LLM server 未启动，以及上游 `openai.Completion(code-davinci-002)` 与 Qwen Chat Completions 接口不兼容。因此没有伪造 IRCoT Qwen 结果，也没有把官方旧 prediction 当作当前实验结果。

#### v33：共享服务适配协议与 HotpotQA trace smoke（2026-07-23）

为保证在上游 runner 不可直接映射到当前五个 QA 集时仍能做可复核的受控比较，新增
`src/slotrag/benchmarking/adapted_protocol.py` 和 `adapter-audit.json`。该协议明确标记
`protocol=shared_provider_adapted`、`publication_scope=adapted_protocol_only`，并为每个
baseline 固定仓库 commit、入口 SHA-256、适配差异、统一题目/语料/模型/答案解析和失败
分母检查；它永远不会把 `exact_upstream_execution_verified` 置为 true。默认 gate 仍拒绝
适配器主表，只有显式 `--allow-adapted-protocol` 且审计字段全部通过时，才会返回
`publication_ready_adapted_protocol`，并在输出中保留 `publication_scope=adapted_protocol_only`。

新的 HotpotQA 5 题/7 方法 smoke 目录为 `runs/vldb2027-adapted-smoke-hotpot-v1`：
35/35 final、35/35 immutable attempts、35/35 trace，schema v28，0 retry、0 failed、0
empty、0 budget failure；records-audit 的 `complete=true`、`missing_trace_count=0`，适配
gate 的 `analysis_ready=true`。由于仍是 smoke 且 IRCoT/PlanRAG/GraphRAG 未执行其上游入口，
gate 正确返回 `status=diagnostic_complete`、`publication_ready=false`；该目录只用于验证
限流、trace、断点续跑和统计链路，不能支撑质量排名或投稿结论。完整统计已写入
`runs/vldb2027-adapted-smoke-hotpot-v1/summaries/main_comparison_smoke/`，原始输出和 trace
不含 API key。

#### v34：五数据集适配协议主对比完成（2026-07-24）

在不改变题目、语料、Qwen3.6-27B、答案抽取和失败分母的前提下，完成
`runs/vldb2027-adapted-main-v1` 的五数据集主对比：3500/3500 final，3507 次
immutable attempts，3507 条 trace；其中 3457 个 final 为 `ok`，31 个为空回答，12 个
预算失败，发生 7 次 retry。`records-audit-main.json` 的 `complete=true` 且没有缺失
attempt/trace；显式 `--allow-adapted-protocol` 后 gate 返回
`publication_ready_adapted_protocol`，但 `exact_upstream_execution_verified=false`。
因此下面只能作为 shared-provider adapted 表，不能写成复现了外部仓库的 exact baseline。

| 数据集 | SlotRAG | GraphRAG* | Hybrid* | IRCoT* | PlanRAG* | ReAct* | SRAG* |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2WikiMultiHopQA F1 | 0.7027 | 0.8199 | 0.8199 | 0.8016 | 0.7799 | 0.8155 | 0.6287 |
| HotpotQA F1 | 0.6896 | 0.8231 | 0.7938 | 0.8177 | 0.7570 | 0.7895 | 0.7164 |
| MuSiQue F1 | 0.4896 | 0.2130 | 0.4394 | 0.5139 | 0.4774 | 0.4811 | 0.3096 |
| StrategyQA Accuracy | 0.8600 | 0.8700 | 0.8800 | 0.8900 | 0.8600 | 0.8700 | 0.8800 |
| DROP F1 | 0.6178 | 0.7094 | 0.7195 | 0.7195 | 0.6944 | 0.7078 | 0.5639 |

主指标宏平均为 SlotRAG 0.6719，低于 IRCoT* 0.7485、ReAct* 0.7328 和 Hybrid*
0.7305；SlotRAG 的平均访问文档数约 4.45，低于 Hybrid* 的 6.50，但平均 total
tokens 约 3819，高于 Hybrid* 的 2003，evidence R@5 也更低。换言之，当前实现只
显示出访问文档数减少这一局部特征，尚未证明质量/成本 Pareto 优势，更不能宣称“全面
领先”。31 个 PlanRAG* 空回答和 12 个预算失败已按 final/attempt 双分母保留在
`summaries/main_comparison/failure_report.csv`；下一步用不重叠 evaluation 子集完成
execution/component ablation，并据此决定是否建立新的候选方法配置。

`*` 表示受控适配器，不是对应仓库的 exact upstream 执行；完整原始记录、配置、代码
revision、cache reuse provenance 和统计 CSV 均保存在上述 run 目录。

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

单文档退化计划
vs. 禁用拓扑感知退化并强制结构编译

字段极值类型化入口
vs. 仅关闭该确定性入口并保留原 LLM 编译与安全事后改写

极性比较拓扑路由
vs. 仅关闭该路由并保留原 LLM 编译与 fallback

行级极性共识投影
vs. 禁用共识并保留最终生成器

锚点中心属性抽取窗
vs. 在完整检索段落上抽取与 grounding

查询根常量修复
vs. 保持编译器输出的无约束关系根

证据原词表面修复
vs. 保持抽取器返回的规范化实体表面
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
