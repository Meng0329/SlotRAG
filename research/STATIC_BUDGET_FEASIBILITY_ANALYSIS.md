# STATIC_BUDGET_FEASIBILITY_ANALYSIS.md — Local-Allocation / Global-Budget Mismatch

> **日期:** 2026-09-03
> **CPU-only 分析**（无 LLM / 无检索 / 无 answer），基于 350 validation
> executable-eligible 冻结计划 + H-STRUCT-1 static 执行结果。

---

## 1. 目的

程序化解释 H-STRUCT-1/H-STRUCT-2 中 static 臂系统性 budget_exceeded 的机制，
取代口头归因：**局部（per-slot）分配请求与全局（B=8）预算不匹配**。

## 2. 方法

对每个冻结 SlotPlan：
1. `logical_plan_from_slot_plan` → logical plan（与真实执行路径一致）。
2. **static**：`compile_physical_plan(top_k=8)`（确定性物理编译器）→
   per-slot `budget_allocation` → `sum_static = Σ_s allocation_static(s)`。
3. 可行性定义：`Feasible_static(q) = sum_static ≤ B`（B=8）。
4. 对照：该题 static 臂的实际执行结果（`validation_confirmatory_results.csv`，
   `status == budget_exceeded`）。

## 3. static per-slot 分配分布（B=8 冻结预算下）

| sum_static | 题数 | 是否 Feasible(≤8) |
|-----------|------|-------------------|
| 4 | 73 | ✓ |
| 8 | 3 | ✓ |
| 12 | 114 | ✗ |
| 16 | 151 | ✗ |
| 20 | 6 | ✗ |
| 24 | 2 | ✗ |
| 36 | 1 | ✗ |

- **76/350 题理论可行**（sum ≤ 8），**274/350 理论不可行**。
- static 编译器固定 per-slot top_k=8 的物理分配在深计划（≥2 slot 且每 slot 满配）
  上系统性超过全局 B=8。

## 4. 混淆矩阵（predicted infeasible vs actual budget_exceeded）

| 预测 | actual BE=是 | actual BE=否 | 合计 |
|------|-------------|-------------|------|
| **Feasible(≤8)** | **0** | 76 | 76 |
| **Infeasible(>8)** | **146** | 128 | 274 |
| **合计** | **146** | 204 | 350 |

- **Feasible → actual BE: 0/76（0%）** —— 理论可行时静态绝不超预算。
- **Infeasible → actual BE: 146/274（53%）** —— 理论不可行时超预算，
  剩余 128 题由运行时 action policy/adaptive binding 在预算内降级完成。
- 总体精确率 76/350=21.7% 的预测可行集与 actual BE=146 完全无重叠。

**结论：静态预算耗尽的结构必要条件是 `sum_static > B`（所有 146 个 actual BE
都在不可行集内，预测可行集内 0 个 BE），充分性由运行时自适应补足（非全部
不可行题都超预算）。机制 = 局部固定分配 vs 全局预算不匹配，已被数据证实。**

## 5. budget counterfactual frontier（CPU-only 模拟）

对 B ∈ {4,6,8,12,16}，静态/flat/chain 各自计算 plan-feasible rate（`sum ≤ B`）
与平均分配调用数：

| B | static feasible | flat feasible | chain feasible |
|---|-----------------|---------------|----------------|
| 4 | 73/350 | 341/350 | 341/350 |
| 6 | 73/350 | 349/350 | 349/350 |
| **8** | **76/350** | **349/350** | **349/350** |
| 12 | 190/350 | 350/350 | 350/350 |
| 16 | 341/350 | 350/350 | 350/350 |

- **B=8 并非对 static 不利的异常选择**：flat/chain 在 B=4 已 341/350 可行，
  B=8 下 349/350；static 即便 B=12 也只 190/350，需 B=16 才到 341/350。
- 静态需要比 flat/chain **高出一倍以上的预算**才能达到相同可行性。
- 这是 **budget efficiency improvement**（flat/chain 在全局预算感知下用更少
  检索调用达成计划），而非 **static intelligence failure**。

## 6. 论文可声明的机制（取代口头归因）

> **Local-allocation / global-budget mismatch.** The deterministic static
> compiler allocates a fixed per-slot retrieval budget; on deep plans
> (structural_hops ≥ 2) this local allocation sums beyond the global
> matched budget, so static exhausts its budget before materializing
> evidence. Any global budget-aware allocator (flat or chain importance)
> fits the same plans within B=8 (349/350 vs 76/350 feasible at B=8), and
> reproduces both the effectiveness and the zero-budget-exceeded outcome.

**资产：** `research/hstruct_validation_census/budget_feasibility_frontier.csv`
（350 行 × 每 B 的 flat/chain sum/feasible/slots + static 请求总量）。
