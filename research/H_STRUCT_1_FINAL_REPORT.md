# H-STRUCT-1 确认性测试最终报告 — depth_only 策略（structural_hops ≥ 2 → chain）

> **状态**: 执行完毕 + 统计判决完成（2026-09-02）
> **协议**: H_STRUCT_1_PRE_REGISTRATION_V1_2.md（FROZEN，无任何后验修改）
> **数据**: validation（primary, UNEXPOSED）+ train supplement（二者均未参与策略选择）

---

## 0. 执行概要

| 项 | 值 |
|----|-----|
| 冻结计划 | validation 361 eligible → **350 executable**（11 个物理计划不可编译，无富余池可补）; train 742 |
| 执行 | **validation 700/700 完成（0 error）**; **train 1484/1484（2 error = 1 题两臂 ReadTimeout）** |
| 总配对 | **n = 1092**（validation 350 + train 742），为预注册目标 1,105 的 **98.8%** |
| plan_hash 一致性 | 所有配对题两臂 plan_hash 相同（0 mismatch） |
| 预算 | 两臂均为 `max_steps=8, max_llm_calls=96, max_retrieval_calls=8`（冻结预算身份） |
| 单次执行规则 | 每题每臂恰好一次；budget_exceeded 视为合法结果（空答案 → EM=0），不重跑 |

**执行期间基础设施失败**（均与策略无关，作 EM=0 处理）：
- train：1 题（2wiki `facfc8f3…`，两臂）持久 Agnes ReadTimeout @60s（问题规模正常，3012 chars/10 passages），主跑与 resume 均失败。
- validation：0 error。

---

## 1. 主要结果（H-STRUCT-1A: 配对静态-vs-chain，eligible 集）

**统计检验：** McNemar exact two-sided (α=0.05) + full-N paired bootstrap (10,000 resamples, seed=2027)。

### 1.1 Pooled Primary（validation + train, n=1092）

| 指标 | Static | Chain | Δ |
|------|--------|-------|---|
| **EM** | 0.0907 | 0.2326 | **+0.1419** |
| **F1** | 0.1294 | 0.3642 | **+0.2348** |
| LLM calls（平均） | 8.3 | 7.1 | **−1.2** |
| **McNemar** | discordant b=164, c=9 | OR=17.32 | χ²=137.09, **p=0.0000** |
| **95% CI(ΔEM)** | — | — | **[+0.0994, +0.1460]** |
| **判决** | | | **CONFIRMED**（CI 不含 0，p<0.05，b≫c） |

### 1.2 Per-Dataset（pooled）

| 数据集 | n | Static EM | Chain EM | ΔEM | b | c | OR | McNemar p(2s) |
|--------|---|-----------|----------|-----|---|---|-----|---------------|
| 2wikimultihop | 815 | 0.0528 | 0.1755 | +0.1227 | 106 | 6 | 16.39 | **<0.0001** |
| hotpotqa | 212 | 0.2217 | 0.4434 | +0.2217 | 49 | 2 | 19.80 | **<0.0001** |
| musique | 65 | 0.1385 | 0.2615 | +0.1231 | 9 | 1 | 6.33 | **0.0117** |
| **pooled** | **1092** | 0.0907 | 0.2326 | +0.1419 | 164 | 9 | 17.32 | **<0.0001** |

三个数据集方向一致、均显著（Holm-corrected 后 pooled 三数据集全保留）。

### 1.3 Validation-only（primary, UNEXPOSED）

| 指标 | Static | Chain | Δ |
|------|--------|-------|---|
| EM | 0.1714 | 0.2571 | **+0.0857** |
| F1 | 0.2529 | 0.4086 | **+0.1558** |
| McNemar | b=36, c=6 | OR=5.62 | **p=0.0000** |
| 95% CI(ΔEM) | — | — | **[+0.0508, +0.1328]** |
| **判决** | | | **CONFIRMED** |

### 1.4 Train-only（supplementary）

| 指标 | Static | Chain | Δ |
|------|--------|-------|---|
| EM | 0.0526 | 0.2210 | **+0.1685** |
| 95% CI(ΔEM) | — | — | **[+0.1091, +0.1682]** |
| **判决** | | | **CONFIRMED** |

---

## 2. 方差的主导机制：静态臂的预算耗尽（诚实披露）

**budget_exceeded 完全集中于 static 臂**——pooled 中 static 739/1092 (67.7%) 触发，chain 0/1092 (0%)：

| 数据 | static budget_exceeded | chain budget_exceeded |
|------|------------------------|----------------------|
| validation | 146/350 (41.7%) | 0/350 (0%) |
| train | 593/742 (79.9%) | 0/742 (0%) |

**含义（必须如实陈述）：** H-STRUCT-1 的 ΔEM 大头并非"静态臂答错、chain 答对"，而是"**静态臂在冻结的 8 次检索预算内无法完成深度计划、产出空答案（EM=0），chain 的自适应分配总能完成**"。这与 G6/G7 的既有发现一致（matched-budget 下 chain 以更少调用达到相同或更高 EM）。在 eligible 定义（structural_hops ≥ 2）下的 2wiki/hotpotqa/musique 深度题域，静态臂的固定 per-slot top_k=8 物理计划结构性吃穿总量 8 的检索预算；这正是 **Policy A 要解决的域**（预算内完成率）。

**这仍是可发布的正面结论，但必须是"预算内可实现性 + 同等预算 EM 双赢"的叙述，而非"更聪明"的叙述。** 若读者把静态臂当作强基线，则会正确质疑其预算耗尽是否为现实缺陷——回答是：**在 1,092 个 eligible 题中，静态方案在真实检索预算内 68% 的题交不出答案，这正是策略切换的真实收益来源。**

---

## 3. 人口效应估计（H-STRUCT-1B）

用 validation census prevalence 外推（`ATE_population = P(Eligible|val) × ATE_eligible`）：

| 数据集 | Prevalence (val census) | ATE_eligible | ATE_population |
|--------|------------------------|--------------|----------------|
| hotpotqa | 68/2146 = 0.0317 | +0.2217 | +0.0070 |
| 2wikimultihop | 258/3698 = 0.0698 | +0.1227 | +0.0086 |
| musique | 35/650 = 0.0538 | +0.1231 | +0.0066 |

总人口级收益（加权平均 ΔEM over eligible prevalence）约 **+0.008 EM/题**——eligible 题在自然分布中仅占 3-7%，因此全量策略切换的人口级收益小但方向为正，且对 eligible 题无成本（预算内调用反而更少）。

---

## 4. 门禁与协议符合性

| Gate | 状态 | 注 |
|------|------|-----|
| 计划冻结（V1.2 compile path） | PASS | 361 validation + 750 train eligible 用 `compile_slotrag_plan` 全量重编译 |
| 配对计划一致性 | PASS | 所有 ok/budget 配对两臂 plan_hash 相同 |
| 单次执行规则 | PASS | 无重跑/无预算膨胀（budget_exceeded 一律保留为 EM=0 结果） |
| 评分方式 | PASS | `score_record()` post-execution，CSV 只有原生 answer |
| McNemar 精确检验 | PASS | scipy.stats + 冻结 exact two-sided |
| full-N paired bootstrap | PASS | seed=2027, 10,000 resamples, CI 符号已修正为 ΔEM=chain−static |
| 社交探索 vs 确认性 | PASS | 策略、阈值、分析计划无任何后验修改 |

**已知限制（如实披露）：**
1. **n=1092 vs 预注册目标 1,105**（98.8%）：validation 11 个 eligible 计划物理不可编译（2wiki 2、hotpotqa 4、musique 5），无富余 eligible 池可补（validation eligible 全集恰为 361）。对 80% power 目标影响可忽略。
2. **train 1 题两臂永久失败**（facfc8 ReadTimeout）：基础设施级，作 EM=0 配对。
3. **静态臂预算耗尽的高占比**（67.7%）把 ΔEM 主效应与"预算内完成率"强耦合——应在论文中以 matched-budget 叙事呈现（同 plan、同预算、同检索协议，唯一差别是 chain 的自适应物理分配）。

---

## 5. 结论

**H-STRUCT-1A CONFIRMED**：在冻结的 eligible 计划上、冻结预算内，chain 臂显著优于 static 臂（primary n=350：ΔEM=+0.086, 95% CI [0.051,0.133], p<0.001；pooled n=1092：ΔEM=+0.142, 95% CI [0.099,0.146], p<0.001；三数据集独立显著）。chain 同时平均少用 ~1.2 次 LLM 调用。**这为"对 structural_hops ≥ 2 的计划使用 chain（自适应物理分配）"这一深度仅有策略提供了首个确认性证据。** 但收益主导机制是静态臂在冻结预算内的大比例不可完成（EM=0），论文叙述必须围绕 matched-budget 预算内可实现性展开，避免"静态方案更笨"的错误归因。

**对论文/政策的影响：** Policy A（depth_only, τ=2）是可发表的深度策略；eligible 自然流行率仅 3–7%，提示该策略作为**对深度计划的自适应降级**而非全局切换来叙述。

---

**执行资产：**
- 结果: `research/hstruct_confirmatory/train_confirmatory_results.csv`, `research/hstruct_validation_census/validation_confirmatory_results.csv`, pooled = 前二者合并
- 报告: `research/hstruct_confirmatory/pooled_confirmatory_report.md`, `.../train_confirmatory_report.md`, `research/hstruct_validation_census/validation_confirmatory_report.md`
- 命令: `tools/run_confirmatory.py --manifest <m> --results <r> --progress <p>`; `tools/analyze_hstruct_confirmatory.py --results <r> --manifest <m> --report <f>`