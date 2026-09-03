# H-STRUCT-2 最终报告 — Chain-Importance vs Budget-Aware-Flat Control

> **状态:** 执行完毕 + 统计判决完成（2026-09-03）
> **协议:** H_STRUCT_2_PRE_REGISTRATION.md（FROZEN，flat 执行前冻结）
> **数据:** 350 validation executable-eligible 题（UNEXPOSED），复用 H-STRUCT-1 冻结计划
> **执行:** 仅新增 flat 臂；static/chain 复用 H-STRUCT-1 frozen outcomes（无重跑）

---

## 0. 研究问题

> Does dependency-sensitive chain importance improve effectiveness or efficiency
> beyond a budget-aware flat optimizer on structurally eligible executable plans?

H-STRUCT-1 已确认 chain > static，但 static 与 chain 同时差两项：优化器搜索 +
requirement importance。H-STRUCT-2 新增 flat 控制臂（同 chain 的优化器搜索空间与
硬预算，但 importance 全 = 1.0），把唯一剩余差异隔离为 chain-rule importance。

---

## 1. 执行概要

| 项 | 值 |
|----|-----|
| 主样本 | 350 validation executable-eligible（H-STRUCT-1 冻结计划，plan_hash 三臂一致） |
| 新增执行 | **flat 350/350**（349 ok + 1 infra error，0 budget_exceeded） |
| 复用执行 | static 350 + chain 350（validation_confirmatory_results.csv，无重跑） |
| flat infra error | `4hop1__344155_765799_282674_759393`（musique，ReadTimeout@60s 两轮，EM=0） |
| plan_hash 一致 | 所有配对三臂相同（来自同一 plan_json） |
| 预算 | 三臂均 max_steps=8, max_retrieval_calls=8, max_llm_calls=96 |
| 单次执行 | 每题每臂恰好一次；budget_exceeded 视为合法结果；error 经 frozen resume 重试 |

**Identity:** flat 与 chain 仅差 `requirement_importance`（flat={} → 全 1.0；
chain={sid: 2(i+1)−1}）。同 plan / question / corpus / retriever / reranker /
generator（qwen3.5-9b）/ 预算 / prompt / 执行代码 / 优化器搜索空间。
审计见 `H_STRUCT_2_METHOD_IDENTITY_AUDIT.md`，STOP 条件未触发。

---

## 2. 三臂对比（validation, n=350）

### 2.1 Effectiveness（EM）

| 对比 | Static EM | 候选 EM | ΔEM | 95% CI(ΔEM) | b | c | p_exact_binomial | 判决 |
|------|-----------|---------|-----|-------------|---|---|-------------------|------|
| static → chain | 0.1714 | 0.2571 | +0.0857 | [+0.0514, +0.1229] | 36 | 6 | 2.8e-06 | 显著 |
| static → flat | 0.1714 | 0.2486 | +0.0771 | [+0.0486, +0.1086] | 30 | 3 | 1.4e-06 | 显著 |
| **flat → chain（PRIMARY）** | 0.2486 | 0.2571 | **+0.0086** | **[−0.0257, +0.0429]** | 20 | 17 | **0.7428** | **不显著** |

CI 为 full-N paired bootstrap（10,000, seed=2027），McNemar 主检验为
`binomtest(b, b+c, 0.5, two-sided)`。

**chain 与 flat 在 350 个 eligible·executable 题上无显著差异**（p=0.74，CI 包含 0，
b/c 近乎对称 20/17）。两者各自显著优于 static。mid-p sensitivity：p_midp=0.627，
同向不显著；卡方 p=0.108，一致。

### 2.2 Efficiency（calls, budget_exceeded）

| 臂 | ok | budget_exceeded | error | avg LLM calls | avg retrieval calls |
|----|----|----------------|-------|---------------|---------------------|
| static | 204 | **146 (41.7%)** | 0 | 7.19 | 6.17 |
| flat | 349 | **0** | 1 | 6.54 | 5.25 |
| chain | 350 | **0** | 0 | 5.58 | 4.51 |

配对差值：

| 对比 | ΔLLM calls | Δretrieval calls |
|------|-----------|-----------------|
| static → chain | −1.61 | −1.65 |
| static → flat | −0.65 | −0.91 |
| flat → chain | −0.96 | −0.74 |

**budget_exceeded：static ≫ flat ≈ chain（146 vs 0 vs 0）。** flat 完整复制了 chain
的预算内完成率——静态编译器（每槽固定 top_k=8）在 deep 计划上系统性吃穿全局
8-call 预算，而**任何**全局预算感知分配（无论 importance 是否依赖结构）都能在
预算内完成。

### 2.3 Sensitivity（flat infra error）

| 口径 | 对比 | n | ΔEM | CI | p |
|------|------|---|-----|-----|---|
| ITT（error=EM 0） | static→chain | 350 | +0.0857 | [+0.0514,+0.1229] | 3e-06 |
| complete-pair 排除 | static→chain | 349 | +0.0860 | [+0.0516,+0.1232] | 3e-06 |

结论不变。

---

## 3. Interpretation（按 H-STRUCT-2 预注册 §7 判决规则）

**CASE B：chain ≈ flat**（p=0.74，CI 含 0，无显著差异，方向微小为正）。

> **BUDGET-AWARE OPTIMIZATION CONFIRMED**
> **CHAIN-SPECIFIC VALUE NOT ESTABLISHED**

### 对 H-STRUCT-1 的机制解释

H-STRUCT-1 中 chain 相对 static 的 ΔEM 几乎全部来自**全局预算感知分配**（global
budget-aware allocation），而非**依赖敏感的重要性**（dependency-sensitive
importance）。flat 以 0.0771 的 ΔEM（p=1.4e-06）复制了 chain 0.0857 的绝大部分，
而 chain 相对 flat 仅剩 +0.0086（不显著）。预算耗尽机制上，static 的 146 个
budget_exceeded 在 flat 和 chain 下均为 0。

---

## 4. 对论文/后续的决定（按预注册 §7 CASE B 预设动作）

1. **不扩展 train flat experiment**（CASE B 明确禁止）。
2. **论文主方法改名为：Structure-Gated Budget-Feasible Physical Planning**；
   主贡献从 chain-rule importance 调整为"结构门控 + 全局预算可行物理规划"。
3. **chain-rule importance 降级为一个实现 / ablation**，而非核心创新。
   H-STRUCT-1 仍作为"chain（任一实现）> static"的确认性证据成立。
4. budget_exceeded 的机制解释采用**程序化**的 local-allocation/global-budget
   mismatch（见 `STATIC_BUDGET_FEASIBILITY_ANALYSIS.md`），不再口头归因。

### 待下一轮（CASE B 下可选，非 train-flat 扩展）

- **budget sensitivity（CPU-only）**：已部分完成（`budget_feasibility_frontier.csv`，
  B∈{4,6,8,12,16}，确认 B=8 非异常选择，flat/chain 在 B=4 已 341/350 可行）。
- **Policy A' 离线重放**：`if structural_hops ≥ 2 → flat else static` 的人口级
  效应（用现有 350 题 + frontier 数据，无需新执行）。

---

## 5. 门禁符合性

| Gate | 状态 |
|------|------|
| 预注册先于 flat 执行冻结 | PASS（commit feca29f 先于执行） |
| identity audit（importance-only 差异） | PASS（H_STRUCT_2_METHOD_IDENTITY_AUDIT.md） |
| plan_hash flat==static==chain | PASS（350/350 来自同一 plan_json） |
| flat 恰好一次 / static/chain 不重跑 | PASS |
| 主检验精确二项 | PASS（binomtest two-sided） |
| full-N paired bootstrap | PASS（paired_bootstrap_vector） |
| 解释门声明先于 outcome | PASS（预注册 §7） |

**已知限制：**
1. n=350（validation only，无 train supplement——CASE B 预注册决定）。
2. flat 1 题基础设施失败（musique，ReadTimeout），作 EM=0，敏感性与排除法一致。
3. 判决"chain 无独立增益"是**未证明**而非"chain 有害"；ΔEM 点估计 +0.0086
   方向为正但置信区间宽（±0.034）。

---

## 6. 结论

**H-STRUCT-2 CONFIRMED as CASE B**: chain 相对 flat 无显著附加价值
（ΔEM +0.0086, CI [−0.026, +0.043], p=0.74），而 flat 与 chain 都显著优于 static
并消除全部 budget_exceeded。**H-STRUCT-1 的 chain 优势归因于全局预算感知的物理
分配，而非依赖敏感的 chain-rule importance。** 论文主方法定位须改为
Structure-Gated Budget-Feasible Physical Planning，chain-rule 降为 ablation。

---

**资产：**
- flat 结果: `research/hstruct_validation_census/hstruct2_flat_results.csv`（350，gitignored 或保留见说明）
- 三臂对比: `research/hstruct_validation_census/hstruct2_three_arm_comparison.csv`
- 修正统计: `research/hstruct_validation_census/hstruct1_corrected_statistics.csv`
- 预算前沿: `research/hstruct_validation_census/budget_feasibility_frontier.csv`
- 身份审计: `research/H_STRUCT_2_METHOD_IDENTITY_AUDIT.md`
- 预算机制: `research/STATIC_BUDGET_FEASIBILITY_ANALYSIS.md`
