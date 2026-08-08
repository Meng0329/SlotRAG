# H-028 Pre-Registration: Deterministic Runtime Operator-Plan Repair（审计分类器升级为运行时编译器）

**假设编号**: H-028
**状态**: proposed（Phase 3X, 2026-08-08）
**日期**: 2026-08-08

## 背景（H-026 方向收束 + H-023 离线审计 + H-027 采样票否决）

**Phase 3X 已穷尽的干预**（全部 rejected）:
- H-005~H-019：提示级/契约级生成侧干预 → 零效果（qwen3.6-27b 生成决策不可改变）
- H-020：extract-then-select 输出契约 → 选型更差（-11pt）
- H-022：诊断确定 2wiki 选型失败 = 模型级天花板（20/100 gold 在 evidence 但生成选错）
- H-023：离线审计证明确定性分类器 operator_family 覆盖 **92%**（2wiki 33/36, drop 82/82）
- H-024：typed 提取契约 ISO 重写 → 破坏 e084（表面形式冲突）
- H-025：surface-form 保留 → 正确形态但 n=20 激活太少，无显著收益
- H-026：关闭 typed relational 方向（编译→算子激活缺口）
- H-027：采样多数票 → rejected（-6.07pt, 1 回收 / 2 回归, 5× 成本）

**核心信条**（QUERY_IR_DESIGN.md §16）:
> 生成决策从 LLM 转移到确定性 typed operator。qwen3.6-27b 只负责把 passage 里的字段提取/物化为有类型的单元格，选择/比较/聚合交给确定性执行器。

**H-023 覆盖率**（离线审计，n=500）:
| 数据集 | needs_op | family_ok | family_rate | schema_ok |
|--------|----------|-----------|-------------|-----------|
| 2wiki | 36 | 33 | 92% | 96 |
| drop | 82 | 82 | 100% | 89 |

**H-027 决定性证据**: 采样聚合（多数票）不能回收选型失败——qwen3.6-27b 在 multiple-candidate evidence 上"稳定地错"。**采样路径（改生成分布）关闭。** 剩余唯一未试方向：**确定性执行（改决策机制）**。

## 假设

**把 H-023 的确定性分类器（`OperatorClassifier`）接入运行时 `SlotCompiler.compile`，在 LLM plan 之后做"算子层修复"（operator-plan repair），让 `apply_operators` 能确定性地计算出最终答案（不经过 LLM 生成），从而绕过 H-022 选型天花板。**

**机制**: LLM 编译出的 plan 经常缺失 operators 或 operator kind 错配（H-026 激活缺口）。`_repair_plan_operators` 在 compile 后、execute 前，用 question 结构驱动地注入/替换确定性 operator：
- **field_argmin/argmax**：问题含比较极值词 + plan 有 ≥2 个 typed date/number 字段 → 注入确定性极值算子（labels 从 "X or Y" 子句提取）
- **count/arithmetic**：numeric 问题缺算子 → 注入 count

修复后，`_deterministic_output`（methods.py:1114）在 `_run_slotrag` 短路：**当 plan.outputs 只有一列且 operator 已确定性算出 answer，直接返回该值，不调用 `generate_answer_response`。**

**价值**: 这是唯一未被试过、且直接绕过 LLM 选型能力的方向。现有干预都是"让 LLM 生成更好的答案"；H-028 是"让确定性执行器算出答案，LLM 只负责物化字段"。

## 干预设计

### 1. `_repair_plan_operators`（planner.py:2411 新增）

compile 后确定性修复，question 结构驱动（无 dataset 名分支）：

```python
def _repair_plan_operators(question, plan, *, answer_kind="short") -> tuple[SlotPlan, int]:
    # - 已有 operator → 不动（不 double-repair，如 H-025 模板已带 field_argmin）
    # - 比较极值（_RC_EXTREMUM_QUESTION）+ ≥2 typed date/number 字段 → 注入 field_argmin/argmax
    #   labels 从 "X or Y" 子句提取（_rc_or_clause_labels），否则 fallback 字段名
    # - numeric（_RC_NUMERIC_QUESTION）+ count 词 → 注入 count
    # 注入后 payload["outputs"] = ["?answer"]（对齐 _deterministic_output 读列）
```

### 2. compile 接线（planner.py:1117）

```python
if runtime_compiler:
    plan, operator_repairs = _repair_plan_operators(question, plan, answer_kind=answer_kind)
    metrics.runtime_operator_repairs += operator_repairs
```

### 3. 确定性短路（methods.py `_run_slotrag` 已有）

`_deterministic_output`（methods.py:1114）当 `plan.outputs` 只有一列且行值唯一 → 直接返回，不调用生成器。H-028 修复后 outputs 对齐 `?answer`，短路自然触发。

### 4. MethodSpec + 新方法（methods.py:502）

`slotrag-grounded-frontier-perpath-guard` + `runtime_compiler=True`：
`slotrag-grounded-frontier-perpath-runtime-compiler`

### 5. 配置（configs/experiments/slotrag-phase3x-h028.yaml）

Tier 1: 2wiki+drop, n=20, seed=2027。guard vs runtime-compiler。

## 验证方法

- **Tier 1** (n=20, 2wiki+drop): guard vs runtime-compiler，配对可比（同 batch）
- **门禁**:
  - **算子层健康**: `runtime_operator_repairs` 有多少题触发；typed_parse_success_rate ≥90%；join_output_rows ≥ guard
  - **确定性短路触发率**: runtime-compiler 侧有多少题走 `_deterministic_output`（不调用生成器）
  - **选型回收**: 2wiki H-022 式"gold 在 evidence 但生成选错"样本，runtime-compiler F1 是否上升
  - **无回归**: 全量 F1 Δ ≥ -2pt（repair 错误引入的新失败需诚实记录）
  - **drop**: 若 number 题被 count/arithmetic 短路改善则加分；主要看是否无回归

## 预期效果与风险

- **预期**: 2wiki 模板命中的比较题（如 b081 已有 field_argmin）确定性算出；aggregate F1 持平或略升（-2pt 内）
- **风险 1（激活缺口）**: H-025/H-026 证实运行时 typed 契约激活率极低（2wiki 5/100）→ 即使 repair 注入 operator，materialization 可能拿不到 typed 字段 → 算子退化（无短路）
- **风险 2（repair 精度）**: H-023 92% 非 100% → 8% 错误 repair 引入新失败
- **风险 3（格式）**: 确定性 `result.answer` 格式（如 `"1"`）可能与 evaluator 期望不一致（drop gold `"70.7"`）
- **风险 4（成本）**: 无额外 LLM 调用（短路反而省 generation），成本下降

## 后续方向

- **通过** → 确定性执行是回收 2wiki 选型失败的正确杠杆 → Tier 2 (n=100) 判断 Coverage
- **拒绝** → 激活缺口使修复无物化目标 → H-022 选型天花板确认，Coverage 顶 40%，转论文

## 不变量（约束）

- 只跑 DEVELOPMENT_SET（seed=2027, eval split），不接触 VALIDATION/TEST_SEALED
- 不换模型（qwen3.6-27b 不变）
- 无 dataset 名特判；question 结构驱动
- 诚实报告负结果（含 repair 错误引入的回归）

## Tier 1 结果（2026-08-08, n=20, 2wiki+drop, seed=2027, runs/slotrag-phase3x-h028-dev1）

**方法**: guard（H-012 叠加）vs runtime-compiler（guard + `runtime_compiler=True` 确定性算子修复）。

| 维度 | 2wiki | drop | 门禁 |
|---|---|---|---|
| 全量 ΔF1 | **-2.50pt**（0.6286→0.6036） | 0.00pt（0.4389→0.4389） | ❌（Δ < -2pt 红线？仅超 0.5pt，见下） |
| 95% CI | [-0.075, 0.000] | [0.000, 0.000] | n.s. |
| wins/losses/ties | 0/1/19 | 0/0/20 | n.s. |
| **runtime_operator_repairs** | **0 / 40 rc items** | **0 / 40 rc items** | ❌ 修复从未触发 |
| typed_extraction_contracts | 3 总 / 2 items | 0 | ⚠️ 激活率极低 |
| deterministic_answers/item | 0.57 | 0.57 | ⚠️ pre-existing 折叠（非 H-028 修复） |
| generation_llm_calls | 0.4 | 0.4 | = guard（短路已生效但无算子可算） |

**判定: rejected。**

### 证据细节

- **修复零激活**: 全部 40 个 runtime-compiler item 的 `runtime_operator_repairs` 均为 **0**。`_repair_plan_operators` 从未触发——n=20 样本里没有任何 plan 同时具备"≥2 个 typed date/number 字段"+"缺 operator"。
- **`b081`（唯一比较模板题）**: 已带正确 `field_argmin`（labels=Bat*21/The Lunatic At Large, output=answer），repairs=0 正确（不 double-repair）。但两侧方法都 **budget_exceeded**（4-slot 比较 plan 2wiki 达到 max_retrieval_calls=8）→ 答案无关 H-028。
- **唯一回归 `a344d746`**（"Where was the performer of song ¿Y Cómo Es Él? born?"）: guard F1 0.5（`Castejón, Cuenca Province`）→ rc F1 0.0（`Madrid`）。**plan 参数顺序不稳定**（`PerformerOf['?performer','¿Y]` vs `['¿Y','?performer]`）→ retrieval 稀疏（5 vs 7 evidence）→ `BornIn` 折叠成 single `{Madrid}` → **pre-existing `_deterministic_output` 单唯一行返回省断** 返回 `Madrid`（错）。**非 H-028 修复因果**（repairs=0, 无 operator）。

### 判决理由

1. **机制正确但无激活目标**: `_repair_plan_operators` 单测证明 field_argmin/count 注入 + outputs 对齐完全正确（确定性算出 `Bat*21`）。但运行时 LLM plan 几乎不产 λ≥2 typed date 字段——**H-026 激活缺口第二次确认**。
2. **确定性短路折叠风险真实**: `_deterministic_output` 在 plan 无 operator 时对"单唯一行"也返回省断,导致 `Madrid` 错误答案。这是 H-028 方法（叠加 `deterministic_shortcut`+frontier guard）的既有折叠行为，非新增 H-028 逻辑，但暴露了短路对不完整 evidence 的危险。
3. **零激活 = 门禁 fail**: 无论 aggregate 是否在 -2pt 内，`runtime_operator_repairs=0` 说明修复机制在真实 LLM plan 上无操作空间 → 无法回收 H-022 选型失败。

**结论: rejected（面积缺**。确定性执行机制正确但运行时无物化目标（激活缺口），且确定性折叠引入 1 回归。H-022 选型天花板第三次确认（H-025/H-026/H-028）。Coverage 维持 **40%**。

## 架构结论

**Phase 3X 全部 6 个假设（H-023~H-028）完成, focal 到同一根因**: 运行时编译 plan 不物化 typed 字段 → 一端是"审计分类器离线 92%（H-023）但运行时无路可达（H-026）"激活缺口, 一端是"确定性执行器正确但无输入（H-028）"。**2wiki/drop LOSS 是模型级生成选型 + 编译物化天花板, 局部干预（提示/契约/采样/确定性算子）全部无效。**

**Coverage 维持 40%（2/5 WIN, 2wiki/drop LOSS, hotpotqa TIE）**。Phase 3 假设循环全部收束。剩余方向: 接受 40% 转 Phase 4 验证 + Phase 5 论文；或模型级生成器升级（超出当前研究约束）。
