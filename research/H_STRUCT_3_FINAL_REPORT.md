# H-STRUCT-3 FINAL REPORT — STRUCTURE-GATE NECESSITY & POLICY A′ OFFLINE REPLAY

> **Date**: 2026-09-03
> **Status**: COMPLETE — **GATE NECESSARY (CASE G1)**
> **Regime**: 离线重放（zero new LLM / retrieval / answer execution）。所有数字都是已观测结果的组合（25,948 行 exploratory 三臂 trace / 350 对 validation confirmatory / V1.2 census）。
> **Frozen gate**: `structural_hops >= 2`（τ=2，结构证据图含 operator 边）。阈值未重新搜索。
> **脚本**: `tools/replay_hstruct3_policy.py`, `tools/hstruct3_gate_test.py`, `tools/hstruct3_population.py`, `tools/hstruct3_aprime_vs_flat.py`
> **结果 CSV**: `research/hstruct_validation_census/policy_replay_per_question.csv`, `hstruct3_four_policy_summary.csv`, `hstruct3_gate_test.csv`, `hstruct3_heterogeneity.csv`, `hstruct3_validation_350_pairs.csv`, `hstruct3_aprime_vs_flat.csv`, `hstruct3_population_summary.json`

---

## 0. Executed trace 与评审口径（必须披露）

- **§3–§6（四种策略比较 + gate 测试 + 异质性）使用 exploratory 三臂 trace**：`research/depth_analysis/structural_per_question.csv`，25,948 行，严格三臂配对后 **n=8,632 题**（8,660 候选 − 28 缺 arm/指标单元）。该 trace 的预算体制是 **permissive**（macro BE 率：static 4.4% / flat 3.3% / chain 3.8%，全部 3–5%），与 H-STRUCT-1/2 的冻结 matched-budget 8-call 体制（confirmatory validation static BE 41.7%）是**不同的实验**。permissive 下 BE 不是主导因素，因此 §5 的 gate 必要性判定**不依赖 BE 消除**，而是依赖**质量（EM）层面的 flat 浅层伤害**。
- **§7–§9（人口级效应）使用 confirmatory validation 350 配对**（`validation_confirmatory_results.csv` static/chain + `hstruct2_flat_results.csv` flat），与 H-STRUCT-1/2 同口径、同 estimand（ATE_exec_eligible），流行率 P(Eligible∧Executable)=0.05390 取自 V1.2 validation census（N=6,494）。
- **§10（A′ vs always-flat）使用 §3 的 8,632 配对 trace**（四种策略的逐题逐列都在 policy_replay_per_question.csv 中，可按任何配对口径重复）。

---

## 1. 策略定义（不变式：arm ≠ policy）

| Policy | 规则 | 性质 |
|--------|------|------|
| P_static | 全部用 static 臂 | 固定物理分配器 |
| P_flat | 全部用 budget-aware flat 臂（importance={}，全 1.0） | 固定物理分配器 |
| P_chain | 全部用 chain 臂（importance={sid:2(idx+1)-1}） | 固定物理分配器 |
| **P_gate_flat = Policy A′** | 若 `structural_hops>=2 AND executable` 用 flat，否则 static | **元以上调度策略**（非新物理优化器） |

A′ 的 `executable` 在 replay 中由「三臂均在 trace 中」保证（全部 8,632 题均编译且执行过三臂 → executable=1）。Frozen gate 的 `structural_hops>=2` 未重新搜索 τ=1/2/3/4。

---

## 2. 四策略宏观对比（n=8,632，strict three-arm pairing，permissive trace）

| Policy | Macro EM | Micro EM | Macro F1 | Macro LLM calls | Macro retrieval calls | BE rate | completion |
|--------|----------|----------|----------|-----------------|----------------------|---------|------------|
| P_static | **0.4434** | 0.5012 | 0.5661 | 27.03 | 1.80 | 4.4% | 0.926 |
| P_flat | 0.4361 | 0.4855 | 0.5682 | **21.75** | 1.75 | 3.3% | 0.936 |
| P_chain | 0.4315 | 0.4794 | 0.5661 | 22.91 | 1.69 | 3.8% | 0.931 |
| **P_gate_flat (A′)** | **0.4482** | **0.5052** | **0.5727** | 23.81 | 1.74 | **2.8%** | **0.941** |

- A′ 是**唯一同时达到以下三点的策略**：macro EM 严格最高（0.4482）、BE 率最低（2.8%）、completion 最高（94.1%）。
- always-flat 在 permissive regime 下反而**轻微降低**整体 EM（0.4361 < static 0.4434）——因为浅层（n=8,085，占 93.6%）flat 伤害未被深层（n=547）收益抵消。这正是 gate 介入的动机。
- 注意：macro EM 的 A′=0.4482 与最早 offline replay 的 A_depth_only 0.4483 一致（同一 gate τ=2，配对口径差异 8634 vs 8632 → 0.0001 级差异）。

---

## 3. §5 Gate Necessity Test — 浅层（structural_hops<2）flat vs static（n=8,085）

配对 bootstrap（full-N question-level，iterations=10,000，seed=2027）：

| 指标 | Δ (flat − static) | 95% CI | 判定 |
|------|-------------------|--------|------|
| EM | **−0.0210** | **[−0.0273, −0.0146]** | **显著，flat 伤害浅层质量** |
| F1 | −0.0078 | [−0.0130, −0.0024] | 显著（弱） |
| LLM calls | −0.92 | [−1.886, +0.045] | n.s.（p=0.060） |
| Retrieval calls | +0.015 | [+0.010, +0.020] | 显著，flat 浅层略多检索 |
| W/T/L（EM，flat 胜/平/static 胜） | — | 261 / 7,393 / 431 | flat 输多赢少 |
| BE | 279 (static) → 315 (flat) | — | flat 不省预算 |  |

→ 在**质量维度**上，always-flat 对浅层计划施加**显著且可重复的 EM 伤害**（−0.0210，CI 完全排除 0，p<0.001）；成本维度无显著补偿（LLM 相近，retrieval 略增）。
→ **CASE G1（GATE NECESSARY）**：若没有 `structural_hops>=2` gate，flat 优化器会被应用到它不适用的大多数计划（93.6%）上并造成净伤害。

---

## 4. §6 Dataset 异质性（dataset × hops bucket，flat − static EM）

| Dataset | hops0 | hops1 | hops>=2 |
|---------|-------|-------|---------|
| 2wiki | **−0.0445** (n=2,384) | −0.0181 (n=910) | **−0.0393** (n=229) |
| hotpotqa | +0.0003 (n=2,165) | +0.0110 (n=512) | **+0.1654** (n=260) |
| musique | −0.0069 (n=1,155) | +0.0068 (n=959) | +0.0172 (n=58) |

- **2wiki 在全部三个 strata 都为 flat 伤害**，且 hops0 最重（−0.0445）——确认 spec §6 预警的 "2Wiki always-flat harm" 证据，**且该伤害不是深层特有**，最主要发生于浅层（hops0）。→ 强化 GATE NECESSARY。
- flattened 深层面在 hotpotqa（+0.1654）与 musique（+0.0172）为正——flat 的收益域是**深链计划**（与 G3/G5 链律的 ≥3-slot 域一致），而非浅层。
- 浅层 pooled 的 −0.0210 由 2wiki hops0 主导（2,384/8,085 = 29%）。

体系内揭示的一个诚实点：热点的深层面受益（+0.1654）在总量上不足以抵消 2wiki 浅层损失，因此 always-flat 整体劣于 static；而 A′ 在这两者之间正确分配。

---

## 5. §7/§8 人口级 A′ 效应（confirmatory validation n=350，V1.2 census P=0.05390）

estimand = ATE_population(A′) = P(Eligible∧Executable) × ATE_exec_eligible，参数**由真实数据重算**（非硬编码）：

- **ATE_exec_eligible** = E[EM_flat − EM_static | eligible∧exec] = **+0.0771**（r²：flat 0.2486 vs static 0.1714，与 H-STRUCT-2 完全一致）
- eligible-stratum 95% CI = [+0.0457, +0.1086]
- **ATE_population(A′) = 0.05390 × 0.0771 = +0.004158**（每个自然问题 +0.42 EM points）
- 两成分先导 bootstrap（350 配对重采样 d_i，全国 CI 乘 P）：**95% CI [+0.002464, +0.005852]** — 不含 0 → 人口级效应显著。

population 效应为正但小（+0.42pt/题），**与 H-STRUCT-1 人口级定位一致**：「深度计划的预算内自适应降级」而非「全局切换」。

---

## 6. §9 人口级 budget_exceeded 削减（每 1000 自然问题）

confirmatory 350 配对（B=8 matched-budget）：static BE 146/350（41.7%）→ flat 0/350。

| | static | A′ |
|--|--------|-----|
| BE / 1000 自然问题 | **22.48** | **0.00** |
| 绝对削减 | — | **22.48 / 1000** |
| 相对削减 | — | **100%**（相对 eligible 域 static BE） |

A′ 在 eligible 域用 flat（BE=0），非 eligible 域用 static（与 static 完全一致），因此人口级 BE 削减恰等于 P × static-eligible-BE-rate。这是 confirmatory matched-budget 体制下的核心工程收益（完成率 94.1% vs static 92.6%，macro 口径）。

---

## 7. §10 A′ vs always-flat（8,632 配对）

| 指标 | Δ (A′ − always-flat) | 95% CI | p_boot |
|------|----------------------|--------|--------|
| EM | **+0.0197** | **[+0.0138, +0.0256]** | <0.001 |
| F1 | +0.0073 | [+0.0024, +0.0121] | 0.003 |
| LLM calls | +0.86 | [−0.030, +1.753] | 0.059 (n.s.) |
| Retrieval calls | **−0.0144** | **[−0.0192, −0.0095]** | <0.001 |

Per-dataset ΔEM (A′−flat)：2wiki **+0.0333**、hotpotqa +0.0017 (p=0.513, n.s.)、musique +0.0012 (p=0.830, n.s.)。

**判定**：A′ 在**质量（EM/F1）与检索成本**两个维度显著优于 always-flat，LLM 调用略增但不显著（+0.86, p=0.059）。非干净 Pareto（LLM direction 混合），但质量优势与检索下降显著。**这是「gate 增加价值」的直接证据**——移除 gate（always-flat）会付出同量级质量代价。→ 一致支持 GATE NECESSARY。

---

## 8. §11 Chain-vs-flat exploratory efficiency audit（confirmatory validation 350，n=349 有效对）

| 指标 | mean Δ (chain − flat) | median Δ | 95% CI | paired perm-p |
|------|----------------------|----------|--------|---------------|
| LLM calls | **−0.9857** | −1.0 | [−1.109, −0.862] | <0.001 |
| Retrieval calls | **−0.7593** | — | [−0.857, −0.665] | <0.001 |

chain importance 在成本上对 flat 有**显著的 exploratory 效率优势**（LLM 每题少 0.99 次调用，检索少 0.76 次）。**但这只是效率 audit，不可列为「confirmed」**：H-STRUCT-2 已证明 chain 相比 flat 的 EM 增益 +0.0086 的 CI 跨零、p=0.743 不显著。效率优势不构成准确率贡献，且 chain 已**永久降级为 ablation**（见 §13）。

---

## 9. §12 可行性命题 + 混淆矩阵（confirmatory frozen plans n=350）

**命题**：静态分配在 B=8 预算下**结构性可完成**当且仅当 Σ_s allocation_static(s) ≤ B；否则 static executor 在完整物化前耗尽预算 → budget_exceeded。

| | 观测: not-exceeded | 观测: budget_exceeded |
|--|--------------------|-----------------------|
| 预测: Feasible (Σ≤8) | TN=**76** | FP=**0** |
| 预测: Infeasible (Σ>8) | FN=**128** | TP=**146** |

- **precision = 1.0**（0 个「预测可完成却 BE」——命题上位可判定准确）、recall = 0.5328（146/274；128 个 Infeasible 计划实际未 BE，因 `max_steps / max_llm_calls` 兜底亦可能提前正常终止）。
- 反侧面（FP=0）说明：**没有计划在 Σ≤8 时仍然 BE** → 静态 BE 的必要条件就是 Σ>8。flat/chain 在每个可执行 plan 上都把分配压进 B=8（frontier: 349/350 feasible）。

---

## 10. GO 裁决 — §16

| 问题 | 结果 |
|------|------|
| 浅层 always-flat 是否明显降低质量？ | **是**（ΔEM −0.0210, CI 排除 0, p<0.001, 2wiki hops0 主导） |
| 浅层总是-flat 是否显著增加成本？ | 否（LLM n.s.；retrieval 略增） |
| A′ 是否明显优于 always-flat？ | **是**（ΔEM +0.0197 / ΔF1 +0.0073 / Δretrieval −0.0144 全显著；LLM 略增但 n.s.） |
| A′ 是否保留 flat 的完整 BE 消除？ | 是（confirmatory 350: BE 146→0；人口级 −22.48/1000） |
| Chain importance 是否仍需保留为主方法？ | 否（H-STRUCT-2 CASE B；§11 仅效率、无准确率） |

**VERDICT: GATE NECESSARY (CASE G1)。** 方法名保留 **「Structure-Gated Budget-Feasible Physical Planning」**。Gate 的 raison d'être 是**质量保护**（把 flat 限制在能受益的 ≥2-hop 结构化计划）而非仅仅成本——always-flat 在 permissive regime 下反噬 EM，而 A′ 同时握住 flat 的深层收益 + BE 消除 + 浅层质量。

POPULATION 理解（诚实）：人口级 EM 提升小（+0.42pt/题，CI 不含 0），核心工程收益在 budget_exceeded 消除（−22.48 BE/1000 自然问题，相对 100%）。论文须用 matched-budget budget-feasibility 叙事，不夸大人口级 EM。

---

## 11. §13 不隐藏 chain 负结果（应提交论文措辞）

> 「The chain-specific importance law did not yield a detectable accuracy gain over a uniform budget-aware optimizer (paired ΔEM = +0.0086, 95% CI [−0.026, +0.043], exact McNemar p = 0.743). This falsification motivated the simpler uniform flat physical policy used in our final system, and motivated the structural gate as the mechanism that keeps that uniform policy confined to the plans where it pays.»

报告内完整数字：static→chain ΔEM +0.0857 (p=2.8e-06)、static→flat +0.0771 (p=1.4e-06)、**flat→chain +0.0086, CI[−0.026,+0.043], p=0.743（n.s.）**；chain 效率优势（§11）不构成准确率贡献。

---

## 12. §14 Positioning 与 §15 Contributions 的落地文件

- `research/TKDE_STRUCTURAL_POLICY_POSITIONING.md` — 已按 §14 更新（无任何 "first adaptive/budget-aware/query-planner/structure-aware RAG" 声称；slotrag vs Adaptive-RAG/RAG-on-a-Diet/PlanRAG/PAGE-RAG 差异叙述）。
- `research/PAPER_CONTRIBUTIONS_V3.md` — 3 个贡献 C1/C2/C3；chain-rule importance **不是贡献**（ablation / falsified hypothesis，§11×§13 数字）。

---

## 13. 生成文件

| 文件 | 内容 |
|------|------|
| `research/hstruct_validation_census/policy_replay_per_question.csv` | 8,632 题 × 26 列：四策略逐题 EM/F1/LLM/retrieval/BE + structural_hops + topology + selected_policy_Aprime |
| `research/hstruct_validation_census/hstruct3_four_policy_summary.csv` | 四策略 × per-dataset/macro/micro 全部指标 |
| `research/hstruct_validation_census/hstruct3_gate_test.csv` | §5 gate 测试逐指标 Δ/CI/p + WLT |
| `research/hstruct_validation_census/hstruct3_heterogeneity.csv` | §6 dataset×hops 全部单元 |
| `research/hstruct_validation_census/hstruct3_aprime_vs_flat.csv` | §10 A′−flat 配对 Δ/CI/p（pooled + per-dataset） |
| `research/hstruct_validation_census/hstruct3_validation_350_pairs.csv` | 350 三臂配对逐题 EM/F1/calls/status |
| `research/hstruct_validation_census/hstruct3_population_summary.json` | §7–9/11/12 全部点估计 + CI + 混淆矩阵 |
| `tools/replay_hstruct3_policy.py` / `tools/hstruct3_gate_test.py` / `tools/hstruct3_population.py` / `tools/hstruct3_aprime_vs_flat.py` | 全部 CPU-only 可复现脚本 |

---

## 14. 完整复核数字（供论文引用）

- **Exploratory replay n** = 8,632（strict three-arm）
- 四策略 macro EM：static 0.4434 / flat 0.4361 / chain 0.4315 / A′ 0.4482
- 四策略 macro LLM calls：static 27.03 / flat 21.75 / chain 22.91 / A′ 23.81
- 浅层 flat−static：ΔEM −0.0210 [−0.0273,−0.0146] p<0.001；ΔLLM −0.92 [−1.886,+0.045] n.s.；Δretrieval +0.015
- A′−always-flat：ΔEM +0.0197 [+0.0138,+0.0256] p<0.001；ΔLLM +0.86 [−0.030,+1.753] p=0.059；Δretrieval −0.0144 [−0.0192,−0.0095]
- 人口级 A′：ATE_exec_eligible +0.0771；ATE_population = 0.05390×0.0771 = +0.004158 [0.002464, 0.005852]
- §9 BE：static 22.48/1000 → A′ 0.00/1000（绝对 −22.48/1000，相对 100%）
- §11 chain−flat：LLM −0.986 [−1.109,−0.862] perm-p<0.001；retrieval −0.759 [−0.857,−0.665] perm-p<0.001（仅效率，非准确率）
- §12 confusion：TN 76 / FP 0 / FN 128 / TP 146（precision 1.0, recall 0.533）
- H-STRUCT-2 保真数字（CASE B）：flat→chain ΔEM +0.0086 [−0.026,+0.043] p=0.7428

---

*本报告所有统计均由 CPU-only 脚本产出，无新的 LLM/检索/答案执行。*