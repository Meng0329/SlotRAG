# H-025 Pre-Registration: typed 契约保留表面形式（surface-form preservation，撤销 ISO 重写）

**假设编号**: H-025
**状态**: proposed（Phase 3X, 2026-08-07）
**日期**: 2026-08-07

## 背景（H-024 决定性证据）

H-024 假设 typed 契约需要把 bindings 预规范化为 ISO date / bare float 供算子消费。Tier 1（dev2）验证：

- **typed 契约净效应 = 帮助 0 题 + 破坏 1 题**（e084 guard 1.0→typed 0.0）
- 3 个 aggregate "win" 全 typed_contracts=0 → run 噪声
- **e084 破坏机制（决定性）**: `extraction_tool` date schema（planner.py:176-181）指示 LLM "Output as ISO YYYY-MM-DD" → LLM 输出 `1955-01-26` → bindings 被改写为 ISO → 答案生成器 echo ISO，而 gold 是表面形式 `"January 26, 1955"`
- **算子层不需要预规范化**: `field_argmin`（planner.py:2371）用 `_ordered_scalar`→`_as_date`/`_as_number` 解析，**能从表面形式 `"January 26, 1955"` 直接解析出 datetime**（`_as_date` 的 `%B %d %Y` format，planner.py:2266）。预规范化 bindings 是假设了不存在的瓶颈

## 假设

**typed 契约应保留表面形式**（LLM 从 passage 原样提取，bindings 保持 `"January 26, 1955"`），算子层消费时用 `_ordered_scalar`/`_as_number` 临时解析。这样：
1. **答案格式正确**（bindings 是表面形式，生成器直接得到 `"January 26, 1955"`）
2. **算子照常工作**（`_ordered_scalar` 能从表面形式解析）
3. **保留 validation 收益**（`_normalize_typed_value` 校验可解析性，不可解析 → abstain）

**价值**: 这是 H-024 的反向验证。若 surface-form 保留让 e084 恢复且算子消费不退化，则证明 H-024 的 ISO 重写是纯破坏，typed 契约的正确形态是"validate-only，不改写"。

## 干预设计

### 1. 新 flag: `typed_surface_form: bool = False`（MethodSpec + SlotMaterializer）

与 `typed_extraction_contracts` 组合：
- `typed_extraction_contracts=True` alone = H-024 行为（ISO 重写）——保持现状作对照
- `typed_extraction_contracts=True + typed_surface_form=True` = H-025 行为（surface-form 保留）——治疗

### 2. `extraction_tool` date/number schema 改指示（planner.py:170-181）

H-024:
```python
elif ... value_type == "number":
    schema = {"type": "string", "description": "A numeric value as a plain decimal string (no commas, no units)..."}
elif ... value_type == "date":
    schema = {"type": "string", "description": "A calendar date as ISO 'YYYY-MM-DD'..."}
```

H-025（surface form）:
```python
elif ... value_type == "number":
    schema = {"type": "string", "description": "The numeric value exactly as it appears in the passage (may include commas/units)."}
elif ... value_type == "date":
    schema = {"type": "string", "description": "The date exactly as it appears in the passage (e.g. 'January 26, 1955')."}
```

### 3. `_normalize_typed_value` 增加 surface mode（planner.py:2285）

新参数 `preserve_surface: bool = False`。当 True：
- 校验可解析性（`_as_number`/`_as_date` 成功）
- 但**返回原始字符串**（不重写为 ISO/float）
- 不可解析 → None（abstain，保留 validation）

### 4. inline + bundle 路径（planner.py:1789/2069）

传入 `preserve_surface=self.typed_surface_form`。

### 5. 新方法（methods.py）

`slotrag-grounded-frontier-perpath-typed-surface` = perpath-guard + `typed_extraction_contracts=True` + `typed_surface_form=True`。

### 6. 配置（configs/experiments/slotrag-phase3x-h025.yaml）

Tier 1: 2wiki+drop, n=20, seed=2027。方法：guard（对照）vs typed-surface（治疗）。

## 验证方法

- **Tier 1** (n=20, 2wiki+drop): guard vs typed-surface，配对可比（同 batch）
- **门禁**:
  - **e084 恢复**: typed-surface 在 e084 上 F1 恢复为 1.0（pred 是 `"January 26, 1955"` 表面形式）
  - **算子不退化**: 有 field_argmin/算子的题（b081 等）join/operator 执行不因 surface-form 变差
  - **无回归**: 全量 F1 不降（Δ ≥ -2pt）
  - **typed_parse_success_rate 保持**: surface-form 也校验可解析性，parse rate 不降

## 预期效果与风险

- **预期**: e084 恢复 1.0（bindings 保留 `"January 26, 1955"`，生成器直接得到正确表面形式）
- **风险 1**: surface-form 让算子 `_ordered_scalar` 解析失败率上升（表面形式多样）→ field_argmin 退化。但 `_as_date` 已支持 `%B %d %Y`/`%b %d %Y` 等，风险低
- **风险 2**: LLM 不遵守"extract verbatim"仍输出 ISO → surface-form 无效（bindings 仍是 ISO，e084 不恢复）
- **风险 3**: 无回归但也没收益（e084 是单样本，恢复后 aggregate 变化极小）→ 诚实记录

## 后续方向

- 通过 → typed 契约的正确形态是 surface-form（validate-only），支撑 H-026/H-027 在算子层做 typed 执行
- 拒绝 → H-024 ISO 重写和 surface-form 都无效 → typed 契约在 2wiki 上无价值，转向其他方向

## 不变量（约束）

- 只跑 DEVELOPMENT_SET（seed=2027, eval split, n=100×5），不 touch VALIDATION/TEST_SEALED
- 不换模型（qwen3.6-27b 不变）
- 无 dataset 名特判；type/question 驱动
- 诚实报告负结果
