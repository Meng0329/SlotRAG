# H-024 Pre-Registration: Demand-Driven Attribute Materialization（typed 契约 date/number 扩展）

**假设编号**: H-024
**状态**: Tier 1 完成 → **rejected**（从 pass_with_caveats 修正, 2026-08-07）
**日期**: 2026-08-07

## 背景（诊断证据）

Phase 3X 断言"typed relational execution"可行。H-023 离线审计已证明：句型结构驱动的确定性编译器能把 operator_family 覆盖从模板 11% 提到 92%（plan_valid 100%，operator_family 92.4%，answer_schema 91%）。**但 H-023 只证明"编译器能判对算子族"，没有解决物化端**：compare/arithmetic/field_argmin 算子需要的 typed 属性列（日期、数字）没有可靠物化。

**根因**：`variable_types: dict[str, Literal["string","boolean","number","date"]]`（models.py:17）类型系统已存在，编译契约（planner.py:73）允许 4 种类型，但 **typed 提取契约只处理 boolean**：
- `extraction_tool`（planner.py:166）只对 `== "boolean"` 输出 `enum ["yes","no","unknown"]`
- date/number 单元格以原始 string 物化，执行端靠 `_as_date`/`_as_number`/`_ordered_scalar`（planner.py:2239/2246/2264）**字符串启发式强转**——`"1.5 million"`、`"Feb 1999"`、`"about 100 years"` 全部解析失败
- 没有**需求传播**：编译出的算子需要 `?birthDate`（date）/`?num`（number），但没有反向标注该 slot 的 `variable_types`，提取端不知道要按 typed 输出

## 假设

把 typed 提取契约从 boolean-only 推广到 date/number，让 LLM 物化出**规范化的 typed 单元格**（ISO `YYYY-MM-DD` date / bare float number），算子 `_ordered_scalar`/`_as_number` 就能可靠消费 → 2wiki 比较 / drop 算术的物化质量提升。

**价值（诚实）**：H-024 是**物化层**修复，不换模型、不改生成。若 date/number typed 单元格规范化后算子解析率上升，则证明 typed extraction 可行（支撑 H-026/H-027 的 typed 执行）。

## 干预设计

### 1. typed_fields 通用化（planner.py 1591-1595）
把 `boolean_fields`（只筛 boolean）扩为 `typed_fields`（boolean|date|number），再分桶：
```python
typed_fields = {field for field, value_type in slot.variable_types.items()
                if self.typed_extraction_contracts and value_type in _TYPED_VALUE_TYPES and field in requested_fields}
boolean_fields = {f for f in typed_fields if slot.variable_types.get(f) == "boolean"}
date_fields    = {f for f in typed_fields if slot.variable_types.get(f) == "date"}
number_fields  = {f for f in typed_fields if slot.variable_types.get(f) == "number"}
```

### 2. 泛化 `extraction_tool` schema（planner.py 163-168，inline+bundle 共享）
`== "boolean"` 分支扩为三分支，date/number 用 string+description 提示 ISO/canonical-float 格式（避免 tool-call JSON number 舍入失真）。

### 3. `_normalize_typed_value`（planner.py 2272）
模块级规范化辅助：
- `number` → `_as_number`，成功则 `str(int(n)) if n.is_integer() else f"{n:.10g}"`；`nan/inf/解析失败 → None`（abstain）
- `date` → `_as_date`（6 format + `%Y` 年只补 `-01-01`），成功则 `parsed.strftime("%Y-%m-%d")`；失败 → `None`（abstain，不猜测）
- `boolean`/`string` → passthrough

### 4. inline 路径规范化 + abstention（planner.py 1783-1801）
每行每个 date/number field 规范化后写入 `normalized[field]`；`None` → 该行 abstain（不入 rows）。**全行 soft-abstain 时 break（不 retry）**，否则确定性规范化会重复失败；hard field-mismatch 仍 retry（保留原 SchemaError 语义）。

### 5. bundle 路径规范化（`_extract_via_bundle` 2064-2080）
同一 `_normalize_typed_value` 在 grounding/protected-anchor 检查后、构建 `BindingRow` 前应用，对 `raw_bindings` 原地规范化；`None` → 该行 `continue`（+1 `typed_extraction_abstentions`）。

### 6. 编译器 demand 标注（`_field_extremum_template` 934-937）
给两个 `BirthDate` slot 加 `variable_types={"birthDate1": "date"}` / `{"birthDate2": "date"}`（H-024 最小 demand 标注；H-026 进一步泛化模板）。

### 7. 新方法（methods.py 429）
`slotrag-grounded-frontier-perpath-typed` = `slotrag-grounded-frontier-perpath-guard` 全叠 + `typed_extraction_contracts=True`。复用既有 flag，无新 MethodSpec 字段。

### 8. 配置（configs/experiments/slotrag-phase3x-h024.yaml）
Tier 1 冒烟：2wikimultihop + drop（typed 密集：field_argmin 日期、arithmetic 数字），n=20，guard（typed off）vs typed（typed on），seed=2027。

## 验证方法

- **Tier 1** (n=20, 2wiki+drop)：`slotrag-grounded-frontier-perpath-guard` vs `slotrag-grounded-frontier-perpath-typed`，配对可比（同 batch）
- **门禁**：
  - `typed_parse_success_rate`：typed 单元格经 `_normalize_typed_value` 成功规范化的比例（**在编译标注了 date/number 的 slot 上**）；≥70% 视为物化可行
  - 比较/算术题 F1：typed vs guard 不降（ΔF1 ≥ -2pt）
  - 无回归：全量 F1 不降
- **Tier 2**（n=100, 2wiki+drop）：若 Tier 1 有效，配对 wilcoxon + bootstrap CI，判断对 react/graphrag baseline 的 F1 缺口

## Tier 1 结果（2026-08-07, n=20, 2wiki+drop, seed=2027）

**run**: `runs/slotrag-phase3x-h024-dev2`（80/80 items, guard=typed off, typed=typed on）

| 维度 | 2wiki | drop | 门禁 |
|---|---|---|---|
| `typed_parse_success_rate` | 5/5 = **100%** | N/A（0 contracts） | ✅ (2wiki) |
| 比较/算术 F1（Δ≥-2pt） | 2wiki guard 0.5786 → typed 0.5833（**+0.48pt**） | drop 0.4722 → 0.4722（0） | ✅ |
| 全量无回归 | +0.48pt | 0.00pt | ✅ |

**诊断发现**:
1. **drop 未激活**: 0 个 number/date-typed slots 被编译 → H-024 的 number 扩展无法评估（arithmetic 算子不编译 number-typed variable_types）
2. **typed-attributable 回归**: qid `e084363c0bda`（typed, BirthDate×2）F1 1.0→0.0。typed 日期规范化为 ISO `1955-01-26`，answer generator 直接 echo ISO，不格式化为 gold 的 `"January 26, 1955"` → **格式层回归**，非数据层错误
3. 该回归被聚合 F1 掩盖（另 2 题改善 +1.0/+0.43）：`a344d7460` 的 -0.5 是 run-to-run 噪声（typed_contracts=0，非 H-024 效果）；`fa3e9b640` 改善 +1.0

**判决**: **rejected**（从 pass_with_caveats 修正）— typed date 契约在 Tier 1 净负（帮助 0 题 + 破坏 1 题 e084），aggregate +0.48pt 是 typed_contracts=0 的 run 噪声。根因: 提取层强制 ISO 与 2wiki 答案表面格式冲突。typed 契约若要做需**答案层回注表面形式**，见 H-025。

## 预期效果与风险

- **预期**：`_as_date`/`_as_number` 吃到规范值后，field_argmin 日期比较、arithmetic 数字运算的解析率上升；2wiki/drop 的"算子已编译但属性列不可用"样本减少
- **风险 1**：LLM 可能不遵守 ISO/canonical 格式 → parse 失败率仍高 → typed 契约无效（诚实否定）
- **风险 2**：`_field_extremum_template` 覆盖本来就少（2wiki 比较题命中有限）→ date 规范化提升落在少数样本 → 效果不显著（诚实否定物化层，H-026/H-027 再评估算子层）
- **风险 3**：typed 契约使提取更严格，可能把本可 string 强转成功的行转成 abstain → 反而掉分

## 后续方向

- 通过 → 物化层可行，支撑 H-026/H-027 typed 执行；2wiki/drop 若 F1 提升，Coverage 可朝 3/5-4/5
- 拒绝 → 记录 typed extraction 物化层不可行（2wiki/drop 非物化问题），回到算子层/生成层评估

## 不变量（约束）

- 只跑 DEVELOPMENT_SET（seed=2027, eval split, n=100×5），不 touch VALIDATION/TEST_SEALED
- 不换模型（qwen3.6-27b 不变）
- 无 dataset 名特判；type/question 驱动
- 诚实报告负结果
