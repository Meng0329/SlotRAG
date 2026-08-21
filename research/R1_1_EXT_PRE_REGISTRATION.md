# R1.1-EXT — External Baseline Matched-Budget Comparison (SEALED pre-registration)

**日期**: 2026-08-20
**状态**: PRE-REGISTERED (sealed before run)
**决策链**: P17 审计发现主表无外部基线 → 用户拍板「扩 R1.1 到主表基线面」→ 选择「n=20 对齐 G6 主表」
**对应 TODO**: Phase 12 主表 5+ 受控 baselines

---

## 1. 目的（与 R1.1 的关系）

R1.1（n=10, hotpotqa-only）已证明外部 baseline 基建可用，但样本不足进主表。
R1.1-EXT 把外部基线对比扩到 **主表同协议规模**，使 Results 节具备
「slotrag vs 外部 RAG 基线」的诚实对比面。

## 2. 协议（密封，跑前冻结）

### 2.1 数据集 / 样本

| 数据集 | stage | split | seed | n | 对应主表 |
|---|---|---|---|---|---|
| hotpotqa | tkde-r11-ext-baselines | evaluation | 2027 | 20 | tab:overall HotpotQA |
| 2wikimultihop | tkde-r11-ext-baselines | evaluation | 2027 | 20 | tab:overall 2Wiki |
| musique | tkde-r11-ext-baselines-musique | evaluation | 2027 | 24 | tab:overall MuSiQue |

**同 sample IDs 保证**（FROZEN_PROTOCOL §6）：每个数据集的 question hash 集
与 G6/G11 主表 run **完全相同**（外部基线复用同一 frozen sample 生成器，
无独立抽样）。slotrag 臂与外部臂跑**同 20/24 题**。musique 用独立 stage
(tkde-r11-ext-baselines-musique) 以对齐 G11 主表 n=24。

### 2.2 Arms（matched budget, hybrid backend）

| arm | 类型 | 检索策略 |
|---|---|---|
| hybrid | 外部基线 | 单趟整问混合检索 (1 call) |
| ircot | 外部基线 | 迭代检索-思维链，budget-matched |
| react | 外部基线 | 行动-观察循环，budget-matched |
| slotrag-g7-static | 本文消融 | 槽位静态执行 |
| slotrag-g7-chain | 本文方法 | 链式执行 (τ=2d−1) |

- 预算上限：max_retrieval_calls=8（全部 arm）。
- 外部基线为 **adapted 实现**（exact_upstream_execution_verified=false），
  按 FROZEN_PROTOCOL §4.2 只能进 adapted comparison，不得声称对比官方实现。
- **不设 frozen_plan_source**：外部基线无 plan 概念，slotrag 臂走各自
  compile 路径（与 R1.1 一致，隔离的是端到端方法而非 plan 选择）。

### 2.3 Primary metrics（冻结）

- **EM / F1**（每数据集每臂）
- **retrieval_calls**（每臂均值）
- **Δcalls**（chain − baseline，paired bootstrap 100k, CI95）

### 2.4 统计检验（冻结）

- paired bootstrap CI on Δcalls（seed 2027）
- McNemar exact（EM 二元，discordant pairs）
- 报告点估计与 CI，不做「点估计差 = WIN」宣称
- multiple-comparison：Holm 校正（若多假设同族）

### 2.5 预期诚实边界（pre-registered）

- slotrag EM **可能 ≤** 外部基线（R1.1 n=10 显示 chain 30% < baselines 40%）——
  这是**诚实报告**，不粉饰
- 成本：chain **仅对 iterative baselines (ircot/react) 有节省**（8→2.5 calls）；
  vs hybrid（1 call）反超。这个二分必须原样呈现
- n=20 样本下 EM 差异大概率不显著（McNemar 无 discordant 或太少）——
  不宣称质量 WIN/LOSS，只报告点估计 + 检验

## 3. 成功标准（跑前冻结）

- **不预设成功**。R1.1-EXT 是「报告型」实验：无论结果如何，产出 5-arm
  同表对比 + 诚实解读，供 Results 节引用。
- 基建验收：records-audit complete=True + gate blocking_reasons=[]。
- 若 slotrag 显著落后（McNemar p<0.05 且差方向一致），如实写入失败归因。

## 4. 不可变记录

- runs: `runs/tkde-r11-ext-baselines/`
- 每个 run 生成 manifest/matrix-manifest/baseline-audit/adapter-audit/command.txt
- 汇总: `tools/summarize_tkde_main_table.py --run-dir runs/tkde-r11-ext-baselines`

---

**预注册者**: Claude, 2026-08-20
**审计链**: 本文件 hash 固化于 run 前；run 后结果写入 TKDE_EXPERIMENT_LEDGER.csv
