# ARCHITECTURE_GAP_ANALYSIS.md — SlotRAG-X 架构缺口分析

> **日期**: 2026-08-07 · **阶段**: Phase 3X H-023 准备
> **目的**: 对照用户 Section 3-13 的 Typed Relational Execution 要求，审计现有架构的能力/缺口/可扩展性

---

## 1. 现有能力审计

### 1.1 数据模型

| 组件 | 当前定义 | 位置 | 类型 |
|------|---------|------|------|
| **BindingRow.bindings** | `dict[str, str]` | models.py:213 | ❌ 纯 scalar，无类型/无 provenance 字段 |
| **BindingRow** 含 | `source_id`, `source_span`, `confidence`, `retrieval_score` | models.py:212-218 | 部分 provenance |
| **EvidenceRecord** | `source_id, source_span, slot_id, bindings` | models.py:221-225 | 有 slot binding |
| **ExecutionResult.rows** | `list[dict[str, str]]` | models.py:506 | ❌ 纯 scalar |
| **Slot** | `id, predicate, arguments, estimated_cardinality, binding_contexts` | models.py:12-50 | 有谓词/参数 |
| **JoinSpec** | `left_slot, left_field, right_slot, right_field` | models.py:56-84 | 字段名 join |

### 1.2 RelationalOperator（现有 12 种）

| kind | 功能 | 已实现 | 备注 |
|------|------|--------|------|
| filter | 行筛选 | ✅ | `_compare()` 支持 eq/ne/lt/le/gt/ge/contains |
| project | 列投影 | ✅ | |
| intersect | 去重 | ✅ | |
| count | 计数 | ✅ | |
| sort | 排序 | ✅ | 含 limit |
| argmin | 最小值行 | ✅ | |
| argmax | 最大值行 | ✅ | |
| **field_argmin** | 跨字段最小 | ✅ | 需同类型；输出 label |
| **field_argmax** | 跨字段最大 | ✅ | 需同类型；输出 label |
| compare | 布尔比较 | ✅ | |
| boolean | 非空判断 | ✅ | |
| **arithmetic** | 四则运算+date_diff | ✅ | add/subtract/multiply/divide/date_diff_months |

**关键发现**:运算库已相当完整！但**缺失**:
- GROUP / COUNT-distinct
- SUM（目前只有 add on row 0）
- SUBTRACT（已有，但只对第一行）
- AVERAGE
- MIN/MAX 聚合（field_argmin 是 row-level，不是聚合）
- MULTISET_COLLECT / LIST_COLLECT（无序/有序收集）
- SEMI_JOIN
- DATE_DIFF（已有 date_diff_months）

### 1.3 执行引擎

| 组件 | 位置 | 能力 | 缺口 |
|------|------|------|------|
| **apply_operators** | planner.py:2216 | 11 种确定性算子 | 对 dict[str,str] 执行 |
| **AdaptiveExecutor.execute** | planner.py:2736 | slot 顺序执行 + binding propagation | 无 demand-driven |
| **SlotMaterializer.materialize** | planner.py ~1998 | LLM 提取 + evidence retrieval | 输出纯 scalar bindings |
| **PhysicalPlan** | qo.py | cost-based slot 排序 | 无 attribute demand |
| **_field_extremum_template** | planner.py:890 | regex 识别 "director born earlier/later" | **硬编码 1 种模式**，仅匹配 4/29 比较题 |
| **_polar_comparison_template** | planner.py:938+ | regex 识别 "same nationality" | 布尔比较模板 |
| **runtime_replan** | ExecutionOptions | 空 rows 时可重试 | 无 attribute 级重优化 |

### 1.4 与用户规则的对齐

| 用户规则 | 当前状态 | 符合？ |
|---------|---------|--------|
| 禁止 `if dataset == "xxx"` | planner.py 无 dataset 分支 | ✅ |
| 只按 question semantics 决定 | `_field_extremum_template` 按 question regex 决定 | ⚠️ regex-based，非 IR-based |
| AnswerSchema 支持 MULTISET/LIST | `ExecutionResult.rows: list[dict]` 支持多行 | ⚠️ 无 cardinality 标注 |
| Demand-Driven Attribute Materialization | 无 | ❌ 缺失 |
| SemanticJoin | 无（有 `_cross_join_rows` 但非 targeted retrieval join） | ❌ 缺失 |
| Provenance-Preserving | BindingRow 有 source_id/span，无 DAG | ⚠️ 部分 |
| Logical/Physical 分离 | SlotPlan → PhysicalPlan 已有 | ✅ |
| Runtime Reoptimization | 有 runtime_replan（空 rows → 重试） | ⚠️ 仅空 rows |
| TypedValue（带 type/unit/entity_id） | 无 | ❌ 缺失 |
| AnswerCardinality | 无 | ❌ 缺失 |

---

## 2. 关键 Gap 汇总

### Gap A: 数据模型 — Scalar → Typed Tuple
- **现状**: `BindingRow.bindings: dict[str,str]`
- **需要**: `TypedTuple { fields: dict[str, TypedValue], provenance, confidence }`
- **影响**: 所有下游（apply_operators, join, extraction prompt）
- **工作量**: 中（扩展 model 层，需要向后兼容 dict[str,str]）

### Gap B: Extraction Prompt — Answer → Typed Rows
- **现状**: LLM 被要求返回单个 answer string
- **需要**: LLM 返回 typed rows（如 `[{film: "X", director: "Y"}, ...]`）
- **影响**: SlotMaterializer 的 extraction prompt 和 parse 逻辑
- **工作量**: 高（核心 prompt 重写 + schema validation）

### Gap C: Demand-Driven Attribute Materialization
- **现状**: 每个 slot 独立物化，不关心下游需要什么属性
- **需要**: 下游 operator（ARGMAX birth_date）反向传播 attribute demand
- **影响**: SlotCompiler + AdaptiveExecutor
- **工作量**: 高（新机制）

### Gap D: SemanticJoin（跨 passage targeted retrieval）
- **现状**: JoinSpec 只做字段名匹配（row 字典合并）
- **需要**: 根据 join key 做 targeted retrieval（如用 director 名检索其 birth_date）
- **影响**: AdaptiveExecutor.execute 的 join 阶段
- **工作量**: 高（新 retrieval 路径）

### Gap E: Operator Library 扩展
- **现状**: 12 种，缺 GROUP/SUM/AVERAGE/MULTISET/SEMI_JOIN
- **需要**: 扩展 RelationalOperator.kind enum + apply_operators 实现
- **影响**: models.py + planner.py
- **工作量**: 低-中

### Gap F: AnswerCardinality（多值保留）
- **现状**: count 只输出 `{"count": "N"}`，无 MULTISET/LIST
- **需要**: 多值答案保留（如 `['88.32', '11.68']`）
- **影响**: apply_operators + output 逻辑
- **工作量**: 低

---

## 3. 扩展可行性评估

### 可以不改核心的(低风险)
- Gap E: 扩展 operator kind enum + apply_operators — 纯加法
- Gap F: AnswerCardinality — 纯加法

### 需要改核心但有坚实基础的(中风险)
- Gap A: TypedValue — BindingRow 已有 source_id/span，扩展为 TypedValue 可向后兼容
- Gap D: SemanticJoin — 已有 SlotMaterializer.materialize 可复用

### 需要新架构机制的(高风险)
- Gap B: Extraction Prompt — 核心 prompt 重写，需要验证 qwen3.6-27b 能否按 schema 输出
- Gap C: Demand-Driven — 全新机制，需重新设计 SlotCompiler

---

## 4. Phase 3X 执行优先级

基于"最小改动覆盖最多失败模式"原则:

| Phase | Gap | 优先级 | 数据集影响 | 预期收益 |
|-------|-----|--------|-----------|---------|
| H-024 | B: Typed extraction rows | P0 | 2wiki/drop | 2wiki:10/29 wrong comparison → 属性物化 |
| H-024 | A: TypedValue data model | P0 | 全部 | 下游 operator 可以做类型判断 |
| H-025 | D: SemanticJoin | P0 | 2wiki | 28/28 F1=0 里 20 个 gold 连续 |
| H-026 | typed comparison (field_argmin/argmax 通用化) | P1 | 2wiki | 10/29 wrong comparison |
| H-027 | E+F: arithmetic+multiset | P1 | drop | drop: 88.32×2+11.68 multi-value |
| H-028 | C: Demand-Driven | P2 | 2wiki | 跨 passage 属性传播 |
