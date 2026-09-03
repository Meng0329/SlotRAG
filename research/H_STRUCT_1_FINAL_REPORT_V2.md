# H-STRUCT-1 确认性测试最终报告 V2 — 统计修正版

> **STATISTICAL CORRECTION ONLY**
> **NO MODEL RE-EXECUTION · NO HYPOTHESIS CHANGE · NO EFFECT-SIZE CHANGE**
> **日期:** 2026-09-03
> **协议:** H_STRUCT_1_PRE_REGISTRATION_V1_2.md（FROZEN，无任何后验修改）
> **数据:** validation（primary, UNEXPOSED）+ train supplement（未参与策略选择）
> **原版报告:** `research/H_STRUCT_1_FINAL_REPORT.md`（保留，不覆盖）

---

## 0. 为什么有 V2（统计修正声明）

V1 报告（2026-09-02）的结论与效应量**方向完全不变**，但统计报告有两个实现级缺陷，本版以修正后的实现重新计算：

1. **Full-N paired bootstrap 的 CI 取错切片。**
   V1 的分析器调用 `paired_bootstrap()`（返回**按 dataset 分组**的对比列表）后取
   `boot_comps[0]`——即**第一个数据集（2wikimultihop）的 CI**，不是 pooled 的 CI。
   修正：新增 `paired_bootstrap_vector(a, b, iterations=10000, seed=2027)`，
   对**全部 N 个 question-level 配对差值** `d_i = EM_chain_i − EM_static_i`
   做 paired resampling，validation / train / pooled 各自独立给出 CI。

2. **McNemar 主检验是 mid-p，而非精确二项检验。**
   V1 的 `statistics.mcnemar` 实现为 mid-p 修正（`0.5·C(n,b)/2^n`）。
   修正：主检验改为 `scipy.stats.binomtest(b, n=b+c, p=0.5, alternative="two-sided")`
   （`p_exact_binomial`），mid-p 降为 secondary sensitivity，另保留连续性校正卡方。

**声明：以下数字是同一批执行、同一评分、同一假设下的修正统计报告。**

---

## 1. 修正后的主要结果（H-STRUCT-1A）

**检验:** McNemar exact two-sided（α=0.05，主检验 `p_exact_binomial`）+
full-N paired bootstrap（10,000 resamples, seed=2027）。

### 1.1 Pooled（validation + train, n=1092, ITT）

| 指标 | Static | Chain | Δ |
|------|--------|-------|---|
| **EM** | 0.0907 | 0.2326 | **+0.1419** |
| **McNemar** | b=164, c=9 | p_exact_binomial | **p<0.001** |
| p_midp（sensitivity） | — | — | p<0.001 |
| p_chi_square | — | — | 137.09, p<0.001 |
| **95% CI(ΔEM)** | — | — | **[+0.1209, +0.1639]** |
| **判决** | | | **CONFIRMED**（CI 不含 0，p<0.001，b≫c） |

### 1.2 Validation-only（primary, UNEXPOSED）

| 指标 | Static | Chain | Δ |
|------|--------|-------|---|
| EM | 0.1714 | 0.2571 | **+0.0857** |
| McNemar | b=36, c=6 | p_exact_binomial | **2.83e-06** |
| p_midp | — | — | 1.64e-06 |
| 95% CI(ΔEM) | — | — | **[+0.0514, +0.1229]** |
| **判决** | | | **CONFIRMED** |

### 1.3 Train-only（supplementary）

| 指标 | Static | Chain | Δ |
|------|--------|-------|---|
| EM | 0.0526 | 0.2210 | **+0.1685** |
| 95% CI(ΔEM) | — | — | **[+0.1415, +0.1968]** |
| **判决** | | | **CONFIRMED** |

### 1.4 与 V1 报告的差异（仅 CI 口径）

| 集合 | V1 报的 CI | V2 修正 CI | 差异原因 |
|------|-----------|-----------|---------|
| validation | [+0.0508, +0.1328] | [+0.0514, +0.1229] | V1 取的是 2wiki per-dataset CI |
| pooled | [+0.0994, +0.1460] | [+0.1209, +0.1639] | 同上 |
| train | [+0.1091, +0.1682] | [+0.1415, +0.1968] | 同上 |

ΔEM、b/c、McNemar 显著性与判决**均不变**。

---

## 2. 修正后的 estimand（H-STRUCT-1B）

V1 将 H-STRUCT-1 的效应量称为 "eligible-stratum ATE"，但 361 个 structurally
eligible 计划中只有 350 个 physically executable（11 个不可编译，无富余池可补）。
修正措辞：

```
ATE_exec_eligible = E[Y_chain − Y_static | Eligible=1, Executable=1]   （正式称呼）
```

**不再**称其为所有 eligible 计划的无条件 ATE。Population effect 按 Policy A
的实际部署定义（`if Eligible AND Executable: chain else: static/fallback`）：

```
ATE_population = P(Eligible ∧ Executable) × ATE_exec_eligible
```

### 2.1 Validation census prevalence（修正后，含 executable 口径）

| dataset | raw_n | eligible_n | executable_eligible_n | P_eligible | P_eligible_executable |
|---------|-------|-----------|----------------------|-----------|----------------------|
| 2wikimultihop | 3698 | 258 | 256 | 0.06977 | 0.06923 |
| hotpotqa | 2146 | 68 | 64 | 0.03169 | 0.02982 |
| musique | 650 | 35 | 30 | 0.05385 | 0.04615 |
| **pooled** | **6494** | **361** | **350** | 0.05559 | **0.05390** |

### 2.2 Population effect

`ATE_population = 0.05390 × +0.1419 ≈ +0.0076 EM/题`（weighted over
validation census）。V1 用 P_eligible 低估的差异可忽略（0.05559 vs 0.05390）。

---

## 3. Infrastructure deviation sensitivity（facfc8）

train 中 1 题（2wiki `facfc8f3088411ebbd6dac1f6bf848b6`）两臂均
ReadTimeout@60s。准确记录（替换任何 "zero retries" 措辞）：

> A symmetric infrastructure failure was retried through the frozen resume
> path and failed in both arms.

| 口径 | n | ΔEM | 95% CI | p_exact_binomial |
|------|---|-----|--------|------------------|
| ITT-style（fac=0/0） | 1092 | +0.1419 | [+0.1209, +0.1639] | <0.001 |
| complete-pair（排除该题） | 1091 | +0.1421 | [+0.1210, +0.1650] | <0.001 |

**结论变化: NO** — 主结论对对称性基础设施失败不敏感。

---

## 4. 门禁与协议符合性

与 V1 报告一致（全 PASS），补充修正项：

| Gate | 状态 | 注 |
|------|------|-----|
| full-N paired bootstrap（修正） | PASS | `paired_bootstrap_vector`，question-level，seed=2027 |
| 主检验精确二项（修正） | PASS | `scipy.stats.binomtest(b, b+c, 0.5, two-sided)` |
| mid-p sensitivity | PASS | 保留为 secondary，与主检验同向 |
| estimand 措辞（修正） | PASS | ATE_exec_eligible，不再称无条件 ATE |
| facfc8 sensitivity | PASS | 结论不变 |

**统计修正不影响：** 执行（无重跑）、评分（score_record）、配对（plan_hash
一致）、单次执行规则、假设、效应量方向。

---

## 5. 结论

**H-STRUCT-1A CONFIRMED（修正口径不变）**：在冻结 eligible·executable 计划上、
冻结预算内，chain 显著优于 static（primary n=350：ΔEM=+0.086, 95% CI
[+0.051,+0.123], p_exact_binomial<0.001；pooled n=1092：ΔEM=+0.142, CI
[+0.121,+0.164], p<0.001）。**预算耗尽机制、静态臂 67.7% budget_exceeded
占比、以及 "matched-budget 预算内可实现性" 的叙事框架均与 V1 一致。**

> **注：** V2 的统计修正与 H-STRUCT-2 预算可行控制实验（chain vs flat）并行完成。
> H-STRUCT-2 的结论见 `H_STRUCT_2_FINAL_REPORT.md`——它直接回答了本报告中
> "chain 优势来自什么" 的机制问题。

---

**资产：**
- 修正统计: `research/hstruct_validation_census/hstruct1_corrected_statistics.csv`
- 三臂对比: `research/hstruct_validation_census/hstruct2_three_arm_comparison.csv`
- 预算前沿: `research/hstruct_validation_census/budget_feasibility_frontier.csv`
