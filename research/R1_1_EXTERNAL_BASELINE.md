# R1.1 — 外部基线 matched-budget 对比 (SEALED)

**日期**: 2026-08-19
**状态**: COMPLETED — 结论已入 `TKDE_EXPERIMENT_LEDGER.csv`
**Gates**: 数据集=hotpotqa (evaluation), n=10, seed=2027, matched-budget-8
**对应 TODO**: Phase 12 主表 5+ 受控 baselines (先导)

---

## 1. 设计

R1.1 是 TKDE 主表外部基线对比的先导实验:把 slotrag-g7-chain/g7-static 与
**共享 provider 适配的外部 baseline** (hybrid / ircot / react) 在同一
`max_retrieval_calls=8` 预算上限下对比。所有 arm 调用真实 provider:
`AgnesClient.complete()` (qwen3.6-27b) + `HybridRetriever.search()`。

| arm | 检索策略 | 预算上限 |
|---|---|---|
| hybrid | 单趟混合检索 (1 call) | 8 (实际 1) |
| ircot | 迭代检索-思维链 | 8 (实际 8) |
| react | 行动-观察循环 | 8 (实际 8) |
| slotrag-g7-static | 槽位静态执行 | 8 |
| slotrag-g7-chain | 链式执行 (本文) | 8 |

**matched-budget 口径**: 同一预算上限, 不强制花完; 实际 calls 逐 arm 汇报。

---

## 2. 结果

```
arm                  n    EM%    F1   calls   Δcalls vs chain  p_boot        CI95
hybrid              10  40.0   0.56   1.00      +1.50          0.002 [ 0.60, 2.50]
ircot               10  40.0   0.56   8.00      -5.50          0.000 [-6.40,-4.50]
react               10  40.0   0.61   8.00      -5.50          0.000 [-6.40,-4.50]
slotrag-g7-static   10  30.0   0.39   3.10      -0.60          0.214 [-1.50, 0.00]
slotrag-g7-chain    10  30.0   0.39   2.50      (基准)
```

**每题逐位 (E=EM 正确)**:
```
hybrid            .E.E.E..E.
ircot             .E.E.E..E.
react             .E.E.E..E.
slotrag-g7-static .E.E.E....
slotrag-g7-chain  .E.E.E....
```
(10 列 = 第 1..10 题; chain/static 比 baseline 少对第 9 题。)

---

## 3. 诚实解读 (FROZEN_PROTOCOL 视角)

### 3.1 质量 (EM) — **无显著差异, 无质量赢面**
- 点估计 chain 30% < hybrid/ircot/react 40%, 但 **McNemar exact p=1.000**
  (n=10, discordant pairs 仅 0/1/1/0)。40% vs 30% 在 n=10 时只是 1 题的差。
- **结论: slotrag 对全部外部 baseline 无 EM 显著差 (p=1.000)。** 不能写成 "优于"。

### 3.2 成本 — **分层的, 不是笼统的**
- **vs 迭代式 baseline (ircot/react)**: chain 2.50 vs 8.00 calls,
  省 **5.5 calls (95% CI [-6.40,-4.50], p<0.001)**。成本赢面成立。
- **vs 单趟 baseline (hybrid)**: chain 2.50 vs 1.00, **多 1.5 calls (p=0.002)**。
  成本赢面**反转**。论文必须如实写这一层, 不得笼统 "省 calls"。
- **vs 同类 static**: chain 2.50 vs 3.10 (−0.60, p=0.214) 点估计省但**不显著**。
  (与 G6/G11 一致: cost 收益域集中在 ≥3-slot 链, 结构性 τ 下限。)

### 3.3 机制证据 — 检索无关天花板
三个外部 baseline (1-call 的 hybrid 和 8-calls 的 ircot/react) **答对的是完全
同一批题目** `.E.E.E..E.`。8 倍检索预算不改变任何一题的答案 → **瓶颈在
qwen3.6-27b 生成侧天花板, 与检索策略无关**。这与 H-017 (生成侧干预全失败)、
H-031 (selection ceiling 泛化) 一致。

---

## 4. 对论文主表的影响

- **进入主表资格**: R1.1 是 n=10 先导, 不进主表; 但证明了 5-arm 外部 baseline
  基建可用 (真实 provider, 预算已打通)。
- **主表扩展**: R1.1 完整版应扩到 n≥50 (用 3-run 方差协议, 见 R1.4), 在
  validation set 上做, 以支撑 "parity + cost-savings vs iterative baselines" 的
  **严格受限** claim。
- **主张边界 (必须写进论文)**:
  1. 质量: parity (非 win)。McNemar p=1.000, n=10。
  2. 成本: 仅对 iterative baselines (ircot/react) 成立; 对 single-pass (hybrid)
     不成立, 甚至反超。
  3. 天花板: 生成器, 非检索。三外部 arm 逐题同 pattern 是核心证据。

---

## 5. 审计链

- 原始 per-question records: `runs/tkde-r11-baselines/items/.../{arm}/*.json` (10/arm)
- 汇总: `tools/summarize_tkde_main_table.py --stage tkde-r11-baselines`
- budget 打通: `methods.py:_run_hybrid/_run_ircot/_run_react` 共享
  `max_retrieval_calls=8` (IRCOT/ReAct 均精确 hit 8, 无 early-stop)
- 所有数字来自真实 provider 调用, 无模拟。

---

**审计者**: Claude, 2026-08-19
**下一次动作**: R1.4 3-run 方差跑完 → 决策 R1.1 是否扩样至 n≥50 进主表
