# LEGACY_RESULT_LEDGER — 历史结果断点清算

**日期**: 2026-08-19
**目的**: 承接 vldb2027 submission → TKDE 重投的断点清算。明确哪些历史 run
延展到 TKDE 线、哪些结论被 reviewer 修正、哪些仅作 smoke 不升格。
**原始记录**: `TKDE_EXPERIMENT_LEDGER.csv` (7 runs) + `TKDE_FAILURE_LEDGER.csv` (空)。
**不重复 CSV**: 本文件只记录"延展/修正/降级"决策,原始数据见 CSV。

## 〇、逐 run 原始字段 (TODO Phase 0 line 18: dataset/split/model/budget/污染状态)

| run_id | dataset | split | n | budget | 污染状态 | 是否进入 TKDE 论文 |
|---|---|---|---|---|---|---|
| g3-ablation-postfix-musique-3hop1 | musique | train-3hop1 | 5 | max_retrieval_calls=8 | clean (seed 2027 确定性样本) | ✅ Section 5 (≥3-slot) |
| g3-ablation-postfix-hotpotqa | hotpotqa | validation | 5 | max_retrieval_calls=6 | clean | ✅ Section 5 (≥3-slot) |
| g6-2wiki-cross-dataset | 2wikimultihop | evaluation | 20 | max_retrieval_calls=8 | clean (seed 2027) | ✅ Section 7 (no-regression) |
| g8-hover-smoke | hover | evaluation | 15 | max_retrieval_calls=6 | clean (seed 2027) | ⚠️ Section 9 pilot (R1.7 决定扩样) |
| g9-feverous-smoke | hover (text+table corpus) | evaluation | 2 | max_retrieval_calls=6 | clean (seed 2027, hand-built corpus) | ⚠️ Section 9 pilot |
| g11-musique-3hop | musique | validation (24-stratified) | 24 | matched-budget-8 | clean | ✅ Section 7 (coverage) |
| data-reachability | n/a (download) | n/a | n/a | n/a | n/a | ❌ 非实验,仅工具验证 |

**模型**: 全部 slotrag 方法 (g7-static/flat/chain),生成器 qwen3.6-27b via Agnes;
g8/g9 为 slotrag-hover (typed-boolean)。G11 用混合检索 backend。所有数字来自
真实 provider 调用 (无模拟,符合仓库 integrity 规则)。

**污染状态** 依据 `EXPOSED_SAMPLE_REGISTRY` + 确定性采样 (seed 2027) 判定:
均无泄漏记录。注意 TKDE_EXPOSED_SAMPLE_REGISTRY.csv 目前空 (R1.3 审计发现),
故"clean" 依赖采样确定性而非 registry — 该缺口已记入 `R1_3_SEALED_SPLIT_REPORT.md`。

## 一、延展到 TKDE 线的结论 (CARRY-FORWARD)

| 结论 | 原始 run | 状态 | TKDE 去向 |
|---|---|---|---|
| G3 chain-rule ≥3-slot 节省检索调用 (τ=2d-1) | g3-ablation ×2 | CONFIRMED | Section 5 (allocator), 3-slot 子域 |
| G3 链律确定性 (零方差) | g3-ablation | CONFIRMED | Section 5, 论文核心主张 |
| G6 optimizer-ablation no-regression | g6-2wiki (n=20) | CONFIRMED | Section 7, 诚实 no-regression claim |
| G8 HoVer 80% EM smoke | g8-hover-smoke | CONFIRMED_transfer | Section 9, 降级为 pilot |
| G9 FEVEROUS 2/2 EM smoke | g9-feverous-smoke | CONFIRMED_transfer | Section 9, 降级为 pilot |
| G11 musique ≥3-slot 节省 26% calls, EM parity | g11-musique-3hop | CONFIRMED | Section 7, 诚实 coverage |

## 二、被 reviewer 修正/撤销的结论 (CORRECTED)

| 原结论 (vldb2027) | 修正后 (TKDE) | 修正依据 |
|---|---|---|
| "Strongest-Baseline Coverage 0/10" | 保留为诚实基线,非主贡献 | reviewer B/D 拒稿主因是 framing,非数字 |
| "strictly dominates static" | 降级为 "≥3-slot 子域 matched quality at lower calls" | P0-R0.4 (mismatched budget / call数错误) |
| "explicit optimizer that searches" | 重定位为 "deterministic importance-weighted allocator" | P2 path (b), reviewer A |
| "3-slot chain 4.7c vs static 6.3c −26%" | 3.04 vs 3.36 (−10%) per-question | P0-R0.3 call数修正 |
| musique "chain 4/7=57%" | 3-slot 子域 57% chain / 71% flat / 67% static | P0-R0.2 stratum 修正 |

## 三、仅作 smoke、不升格为正式实验的 (SMOKE-ONLY)

- **G8/G9 HoVer/FEVEROUS**: smoke 证明 transfer, 非 full benchmark。R1.7 决定是否扩到 n≥100。
- **data-reachability**: HTTP 200 验证, 非实验。

## 四、TKDE_FAILURE_LEDGER.csv 空的原因

TKDE 线 7 个 run 全部 CONFIRMED 或 IN_PROGRESS,无实验失败。空 ledger 是
**诚实信号**: 不是没记录失败,而是 TKDE 线上没有失败需要记录。
(对照: main repo 的 FAILURE_LEDGER 有历史失败条目。)

## 五、尚未延展的结论 (PENDING)

- **R1.1 外部 baseline** (进行中): hybrid/ircot/react matched-budget — 完成后
  决定是否进入 Section 7 主表。
- **R1.4 多 run 方差** (待跑): qwen3.6-27b 生成器非确定性量化 — 完成后并入
  Section 7 的 CI/方差披露。
- **R1.6 β_s 敏感性**: 未启动。

---

**审计者**: Claude, 2026-08-19
**来源**: `TKDE_EXPERIMENT_LEDGER.csv` (7 runs), `TKDE_FAILURE_LEDGER.csv` (0 rows)
**下次动作**: R1.1 完成后更新 PENDING → 结果
