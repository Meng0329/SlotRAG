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
| F5 | v6 2Wiki `55b23a90084c11ebbd56ac1f6bf848b6`：问题问 `Find Me Guilty` 与 `Tear Gas Squad` 哪部电影的导演出生更早。编译器生成四个事实抽取槽和第五个 `Compare(?bd1, ?bd2)` 槽；首次 attempt 因 `5 > max_steps=4` 返回 `budget_exceeded`，重试又在 embedding 端点超时。 | `Compare` 是对已抽取字段的确定性运算，却被错误物化为语义检索槽；两个独立事实分支也缺少由字段算子声明的关系连接，执行器只能处理等值 join。 | 将严格可证明的字段比较槽规范化为 `field_argmin`/`field_argmax` 类型算子；答案候选标签必须来自问题中已落地的计划常量，算子显式连接两个事实分支，执行器只对这些算子连接的分支做受控笛卡尔组合。保持 `max_steps=4`，不以放宽预算掩盖错误建模。 | v6 真实失败 plan 冻结重放已从 5 槽改写为 4 槽，`operator_rewrites=1`，冻结日期输出 `Tear Gas Squad`；在线同样本仍待验证。 | schema v9 冻结重放通过 |
| F6 | v6 2Wiki 的三个 `comparison` 样本金答案均为 `no`；SlotRAG 分别输出语义正确的 `No, ...` 解释，单题 F1 仅 0.143/0.143/0.083。另一个 `bridge_comparison` 同样正确回答 `No. ...`，F1 为 0.095。Hybrid 也受同一评分契约影响。 | Hotpot/SQuAD token-F1 奖励最短答案，但生成器没有对一般数据集的极性问题强制 canonical `yes/no`；这会把正确解释误计为低质量，并混淆方法质量与输出格式。 | 后续 schema 单独增加无金标泄漏的统一极性规范化：仅当问题句法为 yes/no 问句且最终答案以 yes/no/true/false 开头时，映射为 `yes`/`no`；对所有方法在 `run_method` 出口一致应用，新增可审计计数。不得用 gold answer 决定是否触发。 | v6 冻结重评分仅改变双方相同的 4 个极性题：SlotRAG F1 0.546→0.900，Hybrid 0.648→1.000；检索、证据和成本不变，差距仍由 F5 失败造成。 | 冻结协议通过，待 schema v10 实现 |
| F7 | v6 的 31 个 SlotRAG attempts 共记录 25 次计划校验错误：断图 7、比较符别名 4、缺工具调用 4、无变量槽 3、未知输出 2、错误 join field 2、其余 3。最终记录中，有校验错误的 11 题平均编译 2.64 calls/6,549 tokens/46.62 s；无校验错误的 19 题为 0.42/755/5.21 s。 | 大量成本来自可分类的结构协议不一致，而不是查询本身需要多轮规划；不过缺工具调用、未落地常量等错误不能安全本地猜测。两组还混有 direct 路由和 provider 失败，当前差值只作诊断。 | schema v9/F6 完成后，单独验证白名单本地规范化：`=`/`==`/`equal`→`eq`、`!=`→`ne`，缺失 operator id 用稳定哈希/序号补全；只有算子字段能证明连接时才补逻辑连通。其他错误继续重试或 fallback。 | 冻结重放必须逐类报告成功修复率、误修复率、编译 calls/tokens/延迟和最终答案；不得把所有 ValidationError 吞掉。 | 已定位，待后续预注册 |

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

首次在线启动门槛检查于 `2026-07-21T20:06:05+08:00` 执行：Agnes 为 `HTTP 200`，但 embedding 与 reranker 均在 60 秒后 `ReadTimeout`。因此本次没有创建 manifest、样本或逐题结果，也不计为 v7 实验 attempt；只生成了数据审计和无密钥的 `runs/vldb2027-diagnostic-v7/service-doctor.json`。探针执行时源码指纹为 `7b146469...b0be`；补齐 `field_argmax` 对称测试后的最终候选指纹为 `be5b59803d2b84dbfd59c4b8fa6ff74efb3c53a4d0bf4a85d5e8c26185e5068d`，完整离线门槛保存在 `offline-validation.json`。审计 SHA-256 与前轮一致。恢复后必须先重跑 doctor，三项服务全部通过才允许创建 v7 manifest。

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

单文档退化计划
vs. 禁用拓扑感知退化并强制结构编译
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
