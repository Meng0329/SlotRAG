# QUERY_IR_DESIGN.md — SlotRAG-X Typed Relational Query IR 设计

> **日期**: 2026-08-07 · **阶段**: Phase 3X H-023 准备（§2-13 设计）
> **状态**: 设计定稿，待 H-023 实现
> **目标**: 在不更换 qwen3.6-27b 的情况下，用 Typed Relational Execution 关闭 2wiki/DROP 与最强 baseline 的差距

---

## 0. 设计动机（为什么需要 Typed IR）

### 0.1 现有架构的致命约束（已由代码确认）

| 约束 | 位置 | 后果 |
|------|------|------|
| `BindingRow.bindings: dict[str,str]` | models.py:212 | **纯 scalar 字符串**，无类型/无单位/无 entity_id |
| `apply_operators` 处理 `list[dict[str,str]]` | planner.py:2216 | 所有算子对字符串做启发式强转（`_as_number`/`_as_date`） |
| `field_argmin/max` 要求**同一行**两个字段 | planner.py:2248-2276 | 跨 passage 的属性需先 JOIN 到同一行，Join 断链即失败 |
| `_ordered_scalar` 只识别 date/number | planner.py:2188 | **序数词**（"first"/"earlier"）无法编码进 < 比较 |
| `arithmetic` 只取 `result[0]` 第一行 | planner.py:2285-2286 | 多值数字答案（DROP: gold `'88.32 88.32 11.68'`）被压缩成单值 |
| `_field_extremum_template` 硬编码 regex | planner.py:890 | 仅匹配 `which film has the director who was born first/earlier/later, X or Y`，覆盖 4/29 比较题 |
| `SlotMaterializer` 每槽独立物化，不感知下游需要哪些属性 | planner.py:1137+ | **无 attribute demand 传播**，跨 passage 中间属性（如 director）物化失败 |

### 0.2 用户 22 节指令的架构落点

用户的 Section 2-13 全部映射到上述缺口的修复。核心转变：

```
CURRENT:   question → [scalar slot plan] → LLM 提取 scalar bindings → scalar operators → string answer
TYPED:     question → QueryIR (typed operators) → AttributeDemand 传播
                                                → LLM 提取 typed rows → 确定性 typed operator 执行 → typed answer
                                                                  ↑ 一个关键信条
                                                                  qwen3.6-27b 只做「谓词→typed row」的提取，
                                                                  不做「选择/比较/聚合」的最终决策
```

**核心信条（Section 16）**：生成决策从 LLM 转移到**确定性 typed operator**。qwen3.6-27b 只负责把 passage 里的字段**提取/物化**为有类型的单元格，选择/比较/聚合交给确定性执行器。这正是 H-020/H-021 失败的修复：它们让 LLM 做选择（选型能力天花板），typed execution 则不依赖模型选型。

---

## 1. TypedValue / TypedTuple / Provenance（Section 5）

### 1.1 TypedValue

向下兼容 `dict[str,str]`，但每个值携带类型与 provenance：

```python
class TypedValue(StrictModel):
    value: str                     # 物化的文本值（保留原文，供 generation 引用）
    type: Literal["string", "entity", "number", "date", "boolean"]
    unit: str | None = None        # 数值单位（如 "million", "years", "months"）
    entity_id: str | None = None   # 若为实体，其规范 id（用于 entity 归一化 join）
    source_id: str | None = None   # 来源 passage
    source_span: str | None = None # 来源 span
    normalized: str | None = None  # 规范化后的可比较值（日期 ISO、数字 float、实体 id）
```

### 1.2 TypedTuple / BindingRow 扩展

`BindingRow` 保持 `dict[str,str]` 兼容访问（所有现有一级字段不变），**新增** typed 视图：

```python
class BindingRow(StrictModel):
    slot_id: str
    bindings: dict[str, str]                 # ← 向后兼容：scalar 视图（原）
    typed_values: dict[str, TypedValue] = Field(default_factory=dict)  # ← 新增
    source_id: str
    source_span: str
    confidence: float
    retrieval_score: float | None = None
```

`typed_values` 与 `bindings` 双写：`bindings[var] = typed_values[var].value`。这样**所有现有下游（generation, metrics, binding beam）零改动**，新增的 typed operator 层优先读 `typed_values`。

### 1.3 AnswerProvenanceDAG（Section 5）

记录每个答案单元格如何从物化行推导而来，用于可解释性 + 审计（论文卖点之一，也防"dumb 算子 hardcode 数据集"）：

```python
class ProvenanceNode(StrictModel):
    kind: Literal["scan", "extract", "join", "operator"]
    operator_id: str | None
    slot_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    value: str | None
    parent_ids: list[str] = Field(default_factory=list)
```

`ExecutionResult` 新增 `provenance: list[ProvenanceNode]`。

---

## 2. AnswerSchema / AnswerCardinality（Section 4）

### 2.1 AnswerSchema

```python
class AnswerSchema(StrictModel):
    cardinality: Literal["ONE", "OPTIONAL_ONE", "MANY_SET", "MANY_LIST", "MANY_MULTISET"] = "ONE"
    value_type: Literal["SCALAR_ENTITY", "SCALAR_STRING", "BOOLEAN", "NUMBER", "DATE",
                        "MULTI_SPAN", "LIST", "SET", "MULTISET", "NUMERIC_LIST"] = "SCALAR_ENTITY"
    numeric_unit: str | None = None
    allow_partial: bool = False     # 是否允许部分命中（如 drop 多值数字）
```

### 2.2 推断规则（compile 阶段，不依赖模型）

question → AnswerSpec 的**确定性**推断（regex + 句型）：

| 句型触发 | cardinality | value_type |
|---------|-------------|-----------|
| `how many` | ONE | NUMBER |
| `what is the difference/sum/product` + numeric | ONE | NUMBER (NUMERIC_LIST if ≥3 operands) |
| `X or Y` + 比较级 (`earlier/later/older/younger`) | ONE | SCALAR_ENTITY |
| 列举 `and` / 复数主语 | MANY_SET | MULTI_SPAN |
| `same ... as each other` 布尔 | OPTIONAL_ONE? | BOOLEAN |

> **为什么确定性**: 用户 Section 15 禁止"数据集特定 regex"，但服务器上的是**泛化句型规则**（任意 passage 都可触发），不是 `if dataset=="drop"`。这与现有 `_field_extremum_template` / `_polar_comparison_template` 的哲学一致，只是推得更广。

### 2.3 对多值答案的修复（drop）

`AnswerSchema.cardinality = MANY_MULTISET` + `value_type=NUMERIC_LIST`。
执行端：`apply_operators` 的 `MULTISET_COLLECT` 保留全部值（不丢，数字计算，与 gold 对齐），而不是把 `'88.32 88.32 11.68'` 压缩成单值 `88.32`。

---

## 3. Logical Operator Library 扩展（Section 3, 7）

现有 12 种（models.py:91-104）缺 GROUP/SUM/AVERAGE/MULTISET。新增：

```python
kind: Literal[
    # ... 现有 12 种保留 ...
    "group", "sum", "average",           # 数值聚合
    "min_agg", "max_agg",                # 聚合 min/max（区别于 row-level argmin）
    "semi_join",                          # targeted retrieval join
    "multiset_collect", "list_collect",   # 多值收集
    "date_diff", "ordinal_extremum",      # ordinal 比较（"first/later"）
]
```

| 新增 kind | 覆盖的失败模式 |
|-----------|---------------|
| `SemiJoin` | 2wiki 跨 passage join 时 targeted 补检索缺失实体属性 |
| `MultisetCollect` | drop 多值数字 |
| `Group`/`Sum`/`Average` | 聚合类（strategyqa 某些计数） |
| `OrdinalExtremum` | 2wiki "which/fewest/most" 序数比较 |

`OrdinalExtremum` 专门修复 `_ordered_scalar` 无法比较序数的问题：它接受 `normalized`（数字/日期），对序数词先在 extract 阶段物化出 `normalized` 数字。

---

## 4. Attribute Demand Propagation（Section 6, 8）

### 4.1 机制

编译后，PhysicalPlanner 沿 operator 依赖反向传播"需要哪些属性列"：

```python
class AttributeDemand(StrictModel):
    variable: str
    needed_for: list[str]        # 需要在哪个 operator 用到（如 argmax/compare）
    required: bool = True        # False = 可选（篇幅/成本权衡）
```

示例：`ARGMAX(death_date)` 会向 **R2 (director, death_date)** 声明 `demand(death_date)`；向 **R1 (film, director)** 不需要 death_date（它是 director 的属性），但 R1 的值被 join 传播给 R2。

### 4.2 传播到提取 prompt

`SlotMaterializer.materialize(slot, ..., attribute_demand=demand)`：当该槽合约要求物化 `?death_date` 为 typed date 时，提取 prompt 会**显式要求 LLM 输出结构化 typed 单元格**（`{director: "Fritz", death_date: {value: "1931", type: date}}`），而不是只抽取实体名。

### 4.3 SemanticJoin（cross-passage targeted retrieval）

当 join key（如 director 名）物化成功后但目标 passage 未检索到时，`SEMI_JOIN` 触发 **targeted 检索**：拿已知实体名去检索能回答下游属性（death_date）的 passage。这是给 join 断链（H-014 失败点）补上"主动取回缺失属性"的能力——H-014 只在 rows 空时重试，这里是**按属性需求主动取**。

---

## 5. 执行引擎改造（Section 10-12）

### 5.1 Logical → Physical 分离（保留）

现有 `compile → SlotPlan → ... ` 已分离。新增层面：

```python
class LogicalQueryIR (StrictModel):
    inputs: list[InputRelation]       # base tables/passages
    relations: list[LogicalRelation]  # named intermediate relations（R1, R2, ...）
    operators: list[RelationalOperator]
    output_spec: AnswerSchema
    execution_constraints: ExecutionConstraints
```

### 5.2 确定性 executor（复用 apply_operators 扩展）

`apply_operators` 改为消费 `TypedValue`（通过 `.normalized`），其余逻辑不变。**复用**已有 12 种 + 新增，保证回归最小。

### 5.3 Runtime Reoptimization（Section 13）

现有 `runtime_replan` 只在空 rows 触发。新增**运行时 demand 再物化**：
- 某算子因缺 `normalized` 字段返回空 → 记录该 operator 的 demand
- 触发一次该属性的**定向物化**（re-materialize 该槽，显式要求该属性）
- 再执行一次 operator 链

---

## 5. 2Wiki 编译示例（闭合用户 Section 7 的 2wiki 用例）

**问题**: "Which film has a director who was born earlier, MovieA or MovieB?"

**Current architecture**: `_field_extremum_template` 生成 4 slots（S1-S4），硬编码匹配 4/29。若问题措辞不同（如含年份/不含 or），**正则失配 → 退化为普通标量提取** → 选型靠 LLM → 失败。

**Typed IR 编译**:
```
InputSpec:
  - passage #1 (document A)  → 物化为 R1(filmA, directorA)    [film 槽, FilmRel]
  - passage #2 (document B)  → 物化为 R2(filmB, directorB)
  - evidence broker-passage  → 物化为 R3(directorX, death_date)
SemanticJoin 主动补 R3: 用 directorA/directorB 去检索 death_date
LogicalPlan:
  R_A := ???
  R_joinA := [director=d, (film,dt)] ← DEMAND death_date via dictionary
物理 planning: kind-ordering, attribute propagation → slot 执行顺序
Output: ARGMAX/death min → chosen film
```

在这个例子里，关键是 **R3(death_date) 由 SemanticJoin 主动检索**（而不是等一个硬编码 slot），且 death_date 被标记为 `required`、物化为 typed `date`，operator `field_argmin` 就能在 typed normal段比较，而不是需同行的 string 猜测。

---

## 6. DROP 数值 Query Compiler（Section 13）

DROP 的问题有两类：
1. **多值数字压缩**（gold `'88.32 88.32 11.68'`）— 由 `AnswerSchema.cardinality=MANY_MULTISET` + `MULTISET_COLLECT` 修复
2. **算术运算**（gold 是计算值，非原文）— 由 `NumericalQueryCompiler` 把 question 编译成 arithmetic 算子链

```
DROP question: "What is X times Y ...?"
→ AnswerSpec: {cardinality: ONE, value_type: NUMBER, numeric_unit: years}
→ LogicalPlan: 解析 X, Y → arithmetic(MULTIPLY) / 多算子 DAG
→ 执行: 提取 X, Y 的 normalized 数值 + op 确定性计算
```

关键：**不写 dataset 特判**，而是**根据 question 的句型/数字结构**在编译期决定。与其他数据集共享同一 operator 库。

---

## 7. 向后兼容与回归策略（Section 15 禁用语）

### 7.1 兼容性

|| 现有消费方 | 改动 |
|----|---------|------|
| `BindingRow.bindings` dict | generation/metrics/beam | **保留**，typed_values 并行 |
| `apply_operators` scalar | 现有方法 | 扩展（读 typed）；scalar 路径保留 |
| `SlotPlan` | 全部 compile 消费者 | 新增 `logical_ir` / `answer_spec` 可选字段 |

### 7.2 用户禁止清单 vs 本设计

| Section 15 禁 | 本设计 |
|---------------|--------|
| ❌ 改 prompt 措辞 | 不改 **generation** prompt；改的是**提取契约**（结构化 typed 输出） |
| ❌ top_k 调参 | 不碰检索 top_k |
| ❌ 更多 answer 契约 | 不新增 generation 侧指令；加的是 AnswerSpec（执行侧） |
| ❌ dataset 特判 | 全句型驱动，无 `if dataset=="drop"` |
| ❌ self-verification | 无 |
| ❌ 仅证据重排 | `SemanticJoin` 是 active retrieval，非重排 |
| ❌ 归因 qwen 选型 / 换更强者为主方法 | 提取归 qwen，**决策归确定性算子** |

---

## 8. H-023 离线编译审计（Section 22 step 7）

### 8.1 前置：必须**不触碰 SEALED 集合**（PROTOCOL 三集合）

- 只用 `DEVELOPMENT_SET` (seed=2027, eval split, n=100×5=500)
- 绝不在编译审计阶段查看 `VALIDATION`/`TEST_SEALED`
- 所有审计只在 dev 集上判 gate

### 8.2 审计指标

| metric | 定义 | 可复现 |
|--------|------|--------|
| **plan_valid_rate** | QueryIR 编译通过 plan 构造校验的比例（对照模型必须全 valid） | ✅ |
| **answer_spec_accuracy** | AnswerSpec 正确推断比例（gold 标注 vs 推断） | ✅ |
| **operator_family_rate** | 编译器正确选择 operator family（比较→field_argmin→..., 聚合→...) | ✅ |
| **typed_attr_recall** | 编译器正确声明需要物化的属性列 | ✅ |
| **output_cardinality** | AnswerSpec 的 cardinality 与 gold 一致 | ✅ |

### 8.3 人工审查

从 500 个里人工细看 100 个 plan：检查 logical script 是否正确映射问题结构、operator 是否选对、属性 demand 是否完整。

### 8.4 GATE（Section 14）

| gate | 阈值 |
|------|------|
| plan_valid_rate | ≥95% |
| answer_schema_accuracy | ≥95% |
| operator_family | ≥90% |

---

## 9. 试验序列（映射用户 Section 14 H-023~H-028）

| 假设 | 内容 | gate |
|------|------|------|
| **H-023** | Typed Query IR Coverage Audit（本节 §8） | ≥95/95/90 |
| **H-024** | Demand-Driven Attribute Materialization | 物化属性列准确 |
| **H-025** | Provenance Semantic Join（2wiki n=30） | ≥30% join-wrong 恢复 ≤5% both-right 回归 |
| **H-026** | Typed Comparison Execution（通用替代 `_field_extremum_template`） | ≥50% 比较错误恢复 |
| **H-027** | Numerical Relational Execution | drop_f1 +5pt |
| **H-028** | Adaptive Physical Planner | 成本↓而 accuracy 不↓ |

---

## 10. 风险

1. **typed 提取可靠性**: qwen3.6-27b 能否稳定返回 schema typed 单元格（非选择，只物化字段）——H-024 验证
2. **SemanticJoin 差成本**: targeted 检索多一次 LLM/retrieval 调用——每样本 +1~2
3. **回归**: typed 路径须与 scalar 路径正交——gate 中设 both-right 回归 ≤5%
4. **"是否只是换了个壳的取词"**: 审稿人可能问 typed operator 是否真的改善了"选型"。答：从"LLM 选型"转移到"确定性算子选型"，是实质差异（H-020/H-021 已证 LLM 选型天花板）

---

*Phase 3X Typed IR 设计 v1 · 2026-08-07 · 待 H-023 实现。*