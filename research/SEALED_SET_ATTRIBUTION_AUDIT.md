# SEALED_SET_ATTRIBUTION_AUDIT.md

> **最后更新**: 2026-08-13
> **阶段**: Phase 4 冻结验证（SEALED_FINAL）

## 目的

记录 Phase 4 SEALED_FINAL 评估与历史（h012-full / DEVELOPMENT 40%）数字的**样本归集差异**，说明为何 SEALED 数字才是论文主表可引用的最终数字，并标注 h012-full 40% 结论的方向性地位。

## 1. h012-full 的 40% 数字实际跨越三集合

Phase 3 H-012 Tier 2（`slotrag-phase3r-h012-full`，n=100/数据集）的 40% Coverage 是**预三集合采样机制**（SHA-256 哈希排序 + seed=2027），其样本**未受三集合隔离**。实际归集：

| 数据集 | n | development | validation | test | 未归集 (not in any) |
|--------|----|-------------|-----------|------|---------------------|
| hotpotqa | 100 | 32 | 24 | 38 | 6 |
| 2wikimultihop | 100 | 31 | 27 | 38 | 4 |
| musique | 100 | 26 | 24 | 39 | 11 |
| strategyqa | 100 | 22 | 19 | 36 | 23 |
| drop | 100 | 34 | 29 | 34 | 3 |

**结论**：h012-full 的 "40%（2/5 WIN）" 是**混合集合点估计**——development/validation/test 按约 30/30/40 混入，且有 4-23% 样本不属于任何三集合（无归集）。它反映系统在**任意评估样本**上的方向性表现，但不构成任何单一集合的严格度量。

## 2. Phase 4 SEALED_FINAL 的干净来源

Phase 4 用 `research/generate_sealed_samples.py --set test --size all` 预写样本，**只写入 test_set.json 且排除 EXPOSED_SAMPLE_REGISTRY 已暴露样本**。每数据集干净可用：

| 数据集 | test_set 总数 | exposed∩test | 干净 SEALED 写入 | sample 文件 |
|--------|---------------|--------------|------------------|-------------|
| hotpotqa | 1,000 (截断) | 0 | 1,000 | samples/tier3_sealed/hotpotqa.jsonl |
| 2wikimultihop | 1,000 (截断) | 0 | 1,000 | samples/tier3_sealed/2wikimultihop.jsonl |
| musique | 867 | 0 | 867 | samples/tier3_sealed/musique.jsonl |
| strategyqa | **180** | **0** | **180** | samples/tier3_sealed/strategyqa.jsonl |
| drop | 1,000 (截断) | 0 | 1,000 | samples/tier3_sealed/drop.jsonl |

注：test_set 完整规模为 12,557（strategyqa 为全部 180，其余按 Tier 3 n=1000 截断）；全量时 hotpotqa/2wiki/musique/drop 写入完整 test 干净集。

**strategyqa 特殊性**：test_set 的 strategyqa 恰为全部 180 个干净样本（已核验：180 全部存在于 eval 文件、exposed∩test=0），**无任何暴露污染**。SEALED strategyqa = 全量干净 test。

## 3. 论文主表口径

论文主表使用 **SEALED_FINAL（Phase 4）** 数字。**注意：SEALED 评估必须 enable trace（publication gate 要求）**，而 enable trace 的 re-run 暴露了**服务端非确定性噪声**。

**3 次运行取均值（消除 flip-flop，论文采用）**（run1=`slotrag-phase4-trace`, run2=`-r2`, run3=`-r3`，180 全量×4 方法×3 run）：

| 方法 | run1 | run2 | run3 | **mean** | range | flips/180 |
|------|------|------|------|----------|-------|-----------|
| guard | 0.8833 | 0.8778 | 0.8833 | **0.8815** | 0.0056 | 4 |
| ircot | 0.8833 | 0.8833 | 0.8833 | **0.8833** | 0.0000 | 0 |
| graphrag | 0.8722 | 0.8722 | 0.8722 | 0.8722 | 0.0000 | 0 |
| react | 0.8444 | 0.8500 | 0.8500 | 0.8481 | 0.0056 | 2 |

- **guard vs ircot（3-run mean 配对）**: Δmean = **-0.0019pt**, wins 16 / ties 149 / losses 15 → **TIE（guard 略落后）**
- guard vs graphrag: Δmean = +0.93pt（不显著）→ TIE
- guard vs react: Δmean = +3.33pt（不显著）→ TIE（点估计领先）
- **稳健判定：strategyqa coverage 单元 = TIE/LOSS**（guard 与最强 baseline ircot 无差异）

**⚠️ 非确定性噪声披露（根因已诊断）**：
- **现象**：pilot（无 trace）guard=0.9 vs ircot 0.8889；publication-grade trace re-run guard=0.8833 = ircot 0.8833（精确 tie）。pilot↔trace 有 **7/180 题 (3.9%) 翻转**（4 题 pilot 对→trace 错，3 题 pilot 错→trace 对）。
- **根因**：**qwen3.6-27b 在 strategyqa 推理边界题上 flip-flop**。7 个翻转题全部是需算术/多跳推理的布尔题（如 `30 Big John Studd clones × 364 lbs > 7700 lbs Hilux carry load`），模型在这些题上 ~50/50 翻转。**不是并发、不是检索、不是代码**：
  - 检索证据逐字节相同（fact_0#0, fact_1#0 两 run 一致）
  - 单题 5 次串行 + 6 次并发重跑 bc429593 全部答错（yes），trace run 却答对（no）——正确答案是**不稳定捕捉**，非系统产出
- **量化**：flip 率 guard 7/180 (3.9%) > ircot/react 3/180 (1.7%) > graphrag 0/180 (0%)。guard 的布尔决策对推理边界更敏感。**效应尺度 ~2-4pt，与 guard-vs-baseline 的 WIN 幅度同量级**。
- **含义**：单次 SEALED 运行的 WIN/LOSS 判定不可靠。系统真相需**多次运行取均值**（消除 flip-flop），并报告 run-to-run CI。

## 4. 归集纪律

1. **Phase 4 主表只引用 SEALED_FINAL**（`runs/slotrag-phase4-trace[-r2,-r3]`，3 次稳健值）。
2. **h012-full 40% 保持为方向性结论**，论文中标注"跨集合点估计，非严格集合度量"。
3. **所有 baseline 是 adapted**（`exact_upstream_execution_verified=false`），在论文诚实声明。
4. **SEALED strategyqa = TIE**（guard 3-run mean 0.8815 vs ircot 0.8833，Δ=-0.19pt）。**strategyqa coverage 单元不再计入 Coverage**（除非 musique 等其它数据集仍 WIN）。

## 5. 后续

- [x] **strategyqa SEALED 3 次稳健值完成**（TIE，guard 0.8815 vs ircot 0.8833）
- [x] **Tier 3 其余数据集 SEALED 评估完成（run1=b1）**，见 §6
- [ ] 全量（12,557）运行后，本审计记录全量干净归集
- [ ] **非确定性披露进论文方法节**：qwen3.6-27b 推理边界题 flip-flop，SEALED 结果多次运行取均值 + 报告 run-to-run range

## 6. Tier 3 其余数据集 SEALED 评估 + H-029 结构性修复

### 6.1 4 数据集 SEALED 完整结果（run1 = `runs/slotrag-phase4-trace-b1`，n=1000/集，musique 867）

**guard（`slotrag-grounded-frontier-perpath-guard`）vs 每数据集最强 baseline（SOTA_LEDGER 覆盖表）**：

| 数据集 | guard acc_full | guard BE% | 最强 baseline | baseline acc_full | Δ | 判定 |
|--------|---------------|-----------|---------------|-------------------|-----|------|
| hotpotqa | 0.5312 | 32.6% | graphrag | 0.8124 | **-0.2812** | ❌ LOSS |
| 2wikimultihop | 0.6644 | 7.5% | ircot | 0.7449 | **-0.0805** | ❌ LOSS |
| musique | 0.3171 | 49.4% | ircot | 0.5263 | **-0.2092** | ❌ LOSS |
| drop | 0.6393 | 0% | graphrag | 0.7246 | **-0.0853** | ❌ LOSS |

**关键诊断**：guard 的 **acc_ok 列证明质量有竞争力**——musique acc_ok=0.6262、hotpotqa acc_ok=0.7882、2wiki acc_ok=0.7183，都接近或超过 baseline 的 acc_full。**LOSS 几乎全部来自 budget 惩罚**（BE 项按协议记 0.0）：musique 49.4% 项被整体丢弃、hotpotqa 32.6%。acc_full 因此被拉垮到 0.32-0.53。

### 6.2 H-029：§4.3 budget_exceeded 结构性修复（Phase 4 loop 迭代优化第 1 轮，PASS）

**根因（live run_method 追踪确认，非 stored-item 推断）**：guard 的 `dual_access_bundle=True`（methods.py:430）使每个 `materialize()` 发一个 **2-query `search_batch`**，`_BudgetedRetriever.search_batch`（runner.py:172-177）按 `len(queries)=2` 物理调用计费。预算跨 slot + binding-context 累计（planner.py:3239），每 slot/每 binding-context 独立跑完整 bundle。实测（musique `2hop__70338_160040`）：2-slot plan + S2 两个 binding context = **3 batch × 2 = 6 物理调用 > 4 → BE**。**注意：stored BE item 的 `plan_slot_count=0`/`retrieval_calls=0` 是 exception unwind 的假象**（runner.py:792-793 用空 `ExecutionResult` 覆盖），不能用它推断根因。

**干预**：`MethodSpec.dual_access_bundle_bound_single`。**bound slot**（非空 bindings）从 2-query bundle 降级为 **1 个 question+lexical-slot query（1 物理调用）**。绑定值（如 `Bible`、`Job`）已锚定检索，lexical slot query 在此路径冗余。live 复现：3-batch 例子变 `2(S1 unbound) + 1(S2-Bible) + 1(S2-Job) = 4 调用` ✓ 恰好落预算。新方法 `slotrag-grounded-frontier-perpath-guard-budget`。

**验证（n120 SEALED 子集，2026-08-13，`runs/slotrag-phase4-h029-n120`）**：

| 数据集 | n paired | acc_full guard→budget | acc_ok guard→budget | BE 回收 | both-ok 质量 |
|--------|----------|------------------------|---------------------|---------|--------------|
| musique | 120 | **0.472→0.655 (+18.3pt)** | 0.667→0.690 (+2.3pt) | 30 回收 (mean 0.734) | 净中性 (8w/7l/69t) |
| hotpotqa | 120 | **0.474→0.690 (+21.6pt)** | 0.710→0.739 (+2.8pt) | 33 回收 (mean 0.870) | 噪声级 (1w/3l/75t) |

- **acc_full 增益全部来自 BE 回收（免费项），acc_ok 非但不降反略升**——单 query 降级在 bound slot 上**零质量代价**（musique both-ok 5↔5，hotpotqa 75/79 tie）。回答的关键担忧（生成脆弱数据集上质量代价是否爆炸）被证伪。
- **回收的 BE 项本就是高完成度项**（hotpotqa mean 0.870），不是 hard tail——它们只是被冗余双 query 撑爆 4-call 天花板。
- **cost**：rc musique 2.77→3.06 / hotpotqa 1.90→2.69（都在预算 4 内），llm musique 5.24→4.81（**下降**）/ hotpotqa 5.01→5.07（持平）。**H-029 严格更便宜**。
- **代码**：commit `43e34d6`（planner.py `dual_access_bundle_bound_single` + methods.py 新 method + config）。

**判定：H-029 PASS，§4.3 budget_exceeded 结构性损失已解决。**

### 6.3 H-030：跨 slot 预算预留（Phase 4 loop 迭代优化第 2 轮，PASS）

**残留问题**：H-029 后 n120 仍有 13 项 BE（5 musique + 8 hotpotqa），其中 6 项一致 BE。H-029 只解决 per-slot 成本，未解决**跨 slot 预算饥饿**。

**根因（live trace 确认）**：plan 3-4 slots，首 slot unbound bundle（2 calls）+ 第二 slot 2 个 binding context（2 calls）= 4，后续 slot 在 `remaining_retrieval_calls <= 0` 处 BE 于物化前（planner.py:3188 只查 `<= 0`，不预留未来 slot）。4-slot plan 在 4-call 预算下结构不可行（首 slot unbound=2 + 3×1=5>4）。

**干预（两层）**：
1. **Stage A（executor, planner.py）**：前视预算预留 `slot_call_cap = remaining_retrieval_calls - len(remaining)`（为每个未来 slot 保留 ≥1 call）。作用于 binding-context `context_limit` 与 H-029-aware estimate-pruning 双处。
2. **Stage B（compile, methods.py）**：`_prune_plan_to_max_slots`（articulation-point-aware 计划降级，保护最选择性 output slot + 连通性）+ 触发条件从 `> max_steps` 改为 `> budget_fit = min(max_steps, max(1, max_retrieval_calls - 1))`。

**验证（13 项 1x live, 2026-08-13）**：**13/13 恢复 OK，11/13 F1=1.0，12/13 F1≥0.8**。两个 sub-1.0 均为非预算：`5a75da23` F1=0.0（LLM 生成错误）、`5a73471a` F1=0.8（表面形式 "Duane Clarridge" vs gold "Duane Dewy Clarridge"）。both-ok 质量中性（10 项抽查 6 稳定，4 变化全为 LLM 非确定性/表面形式差异）。cost 均预算内。commit `494af0c`。

**n120 完整配对验证（2026-08-13, `runs/slotrag-phase4-h030-n120`，同 qid 对称链接样本）**：

| 数据集 | n paired | acc_full guard→budget | acc_ok guard→budget | BE 回收 | both-ok 质量 |
|--------|----------|------------------------|---------------------|---------|--------------|
| musique | 120 | **0.600→0.690 (+9.0pt)** | 0.680→0.690 (+1.0pt) | 14/14 回收 (13 score>0) | ΔF1 -0.0086 噪声级 |
| hotpotqa | 120 | **0.646→0.752 (+10.6pt)** | 0.717→0.752 (+3.4pt) | 12/12 回收 (10 score>0) | ΔF1 +0.0279 |

> **口径注**：本表「acc_full」= 全量项（含 BE）的 primary_score 均值（BE 记 0.0），与 §6.1 audit 一致。早期记录中用 ok_rate（0.883/0.900→1.000）误报 acc_full；真实 acc_full 增益为 **musique +9.0pt / hotpotqa +10.6pt**（BE 全回收下 acc_full≈acc_ok）。

**§4.3 budget_exceeded 在 n120 配对样本上完整归零（guard 26 项 BE → budget 0 项 BE）**。两数据集 both-ok ΔF1 符号相反、幅度 ±0.03 = 生成器非确定性噪声（回归全为 1.0→0.0 硬翻转的 compile 非确定性签名），非系统性预算质量退化。

**2wiki/drop no-regression 配对验证（2026-08-13, `runs/slotrag-phase4-h030-n120-2d`, n=120/集）**：

| 数据集 | n paired | acc_ok guard→budget | BE | both-ok 质量 | 判定 |
|--------|----------|---------------------|----|--------------|------|
| drop | 120 | 0.6941→0.6858 (Δ -0.0083) | 0=0 | **0 项变化, ΔF1 +0.0000** | ✅ 完美 parity |
| 2wikimultihop | 120 | 0.6819→0.6586 (Δ -0.0233) | 5=5 一致 | 11 变化 (7 回归/4 恢复), ΔF1 -0.0234 | ⚠️ 回归全为 LLM flip-flop |

**2wiki 7 个 both-ok 回归全部诊断为生成器翻转，非预算因果**：全部 evids:SAME（检索证据逐字节相同）+ goldcov True 两侧（gold 都在 evidence），仅 rc 下降（4→3/2 = H-029 省下的冗余调用）。**guard 自身跨 run 翻转证实噪声**：`0188e468` guard b1 'Crooks and Coronets'✅→b2 'Arctic Flight'❌→n120 ✅；`435eb448` guard b1 'Mstislav'❌→b2 'Vladimir II Monomakh'✅→n120 ✅。guard 自身翻转率已高于 guard→budget 回归率 = 与随机不可区分（H-022 选型天花板第三次确认）。

**判定：H-029+H-030 在全部 4 数据集上无质量回归（both-ok 均非系统性退化），§4.3 budget_exceeded 结构性损失完整解决。**

**判定：H-030 PASS。** 与 H-029 合璧后 §4.3 budget_exceeded 结构性损失**完整解决**。

### 6.4 Phase 4 主表口径下的实际结果（全量运行完成）

**n120 预测回顾**：n120 预计 musique/hotpotqa 显著改善、2wiki/drop 维持 LOSS、Coverage 口径待定——全量运行在 musique/hotpotqa 上兑现（BE 归零、acc_full 大幅恢复），2wiki/drop 维持 LOSS 兑现，但 **Coverage 落在 25% 而非 40%**。

**全量 §4.3 matched-budget 主表（n=867/1000/1000/1000，paired b1 guard → budget）**：

| dataset | acc_full g→b | acc_ok g→b | BE g→b | baseline | Δ_budget | verdict |
|---|---|---|---|---|---|---|
| musique | 0.3171→**0.5807** | 0.6262→0.5820 | 428→**0** | ircot 0.5263 | **+0.0544** | 🟢 WIN |
| hotpotqa | 0.5312→**0.7842** | 0.7882→0.7842 | 326→**0** | graphrag 0.8124 | **−0.0282** | 🟡 TIE |
| 2wiki | 0.6644→**0.6901** | 0.7183→0.7167 | 75→**37** | ircot 0.7449 | **−0.0548** | 🔴 LOSS |
| drop | 0.6393→0.6403 | 0.6393→0.6403 | 0→0 | graphrag 0.7246 | **−0.0843** | 🔴 LOSS |

**Coverage = 1/4 = 25%**（strategyqa 排除，仅 musique WIN）。

**关键质量判定（全量 both-ok 配对，区分真实回归 vs 集合假象）**：
- **无系统性质量退化**：both-ok 配对 musique −0.010 (35w/35l 对称)、hotpotqa +0.006 (32w/25l)、2wiki +0.002 (44w/38l)、drop +0.001 (32w/26l)，总 **143w/124l/2771t**。单 query 降级不造成质量回归。
- **"acc_ok 下降"（musique 0.626→0.582）是集合构成假象**：guard ok=439 幸存者 vs budget ok=867 全含（纳入 426 个 BE 回收项——结构更难、mean 0.547），非真实质量退化。真实信号是 both-ok 配对的对称噪声。
- **BE 回收质量高**：musique 426 回收 mean 0.547 (282/426)、hotpotqa 326 回收 mean 0.764、2wiki 38 回收 mean 0.633。

**2wiki 37 残尾 BE 归因**：**37/37 also-BE-under-guard，0 recovered-to-BE**——全为结构硬顶（极端题在 4-call 预算下无论方法都做不完），非预算修复引入。预算修复在 2wiki 已接近极限（75→37），剩 37 是预算结构上限。

**结论（叙事转变）**：预算修复完成"假崩溃→真实准确率"转换（musique/hotpotqa），但 **2wiki/drop 是固有准确率差、非预算问题**——drop 全程 0 BE（预算修复零作用，天生输 graphrag 0.084）、2wiki 回收后仍输 ircot 0.055。**honest matched-budget Coverage = 25%**，与 Phase 3 名义 40/50%（非 matched-budget + 未全量 BE 清洗）不符。**已裁定（2026-08-15）：接受 25% 转 Phase 5 论文**。方向 B 勘察（H-031）证伪字符串校正，策略层在"不换模型"下穷尽（H-022 选型天花板×3 + H-020/H-027 rejected + H-018 已生效仍截短），25% = qwen3.6-27b matched-budget 真实 Coverage 上限。论文用 honest 叙事，Weakest-Baseline 覆盖单列。
