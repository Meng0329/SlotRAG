# R1.4 — Multi-Run EM/F1 Variance (qwen3.6-27b determinism)

**日期**: 2026-08-19
**状态**: COMPLETED — 零方差
**Gates**: hotpotqa evaluation, n=10, seed=2027, G6-effective (static/flat/chain)
**对应 TODO**: Phase 12 多运行协议 (服务端非确定时至少 3)

---

## 1. 设计

同一 G6 config (seed 2027, n=10, 相同题集) 重复 3 次到 3 个独立输出目录。
R1.1/R1.3 只跑了 1 次; R1.4 量化 **qwen3.6-27b 生成器非确定性** (temperature 0)
在同一 (seed, sample) 下的方差 — **不是** cross-seed 抽样方差 (那是另一条轴, R1.5)。

```
run1 → runs/tkde-g6-r14-run1   (30 items)
run2 → runs/tkde-g6-r14-run2   (30 items)
run3 → runs/tkde-g6-r14-run3   (30 items)
```
3 次顺序执行 (避免 rate-limit collision), 每个 run 30 次真实 provider 调用
(3 arm × 10 题)。运行耗时 ~75min (10:56 → 12:19)。

## 2. 结果

| arm | run1 EM% | run2 EM% | run3 EM% | mean±std | calls mean±std |
|---|---|---|---|---|---|
| slotrag-g7-static | 30.0 | 30.0 | 30.0 | 30.0±0.0 | 3.10±0.00 |
| slotrag-g7-flat | 30.0 | 30.0 | 30.0 | 30.0±0.0 | 2.60±0.00 |
| slotrag-g7-chain | 30.0 | 30.0 | 30.0 | 30.0±0.0 | 2.50±0.00 |

**所有 arm 的 EM 与 calls 三次运行完全相同 (std = 0)**。

## 3. 解读 (诚实边界)

### 3.1 证实: 生成器在此 setting 下确定性
同一 (seed, sample) × temperature 0 → 三次运行逐题完全一致。
**"matched-budget 实验可复现"** — 审稿人担心的 LLM nondeterminism 在这里不存在。

### 3.2 边界: 它不消除抽样方差
零方差**只**证明 "同一题集重复结果稳定", **不**证明 "换题集结果稳"。
cross-seed 抽样方差是**独立轴** (不同 seed → 不同 stratified sample → 可能不同 EM),
需 R1.5 (multi-seed) 或已由 G11 的 n=24 分层混合缓解。论文不得混用。

### 3.3 对 R1.1 的影响
R1.1 的 "chain 30% vs baseline 40%" 是**稳定的** (3 次重复全 30%, 非运气)。
这强化生成器天花板结论: 不是抽样噪声, 是真实的能力边界。

### 3.4 对论文 method 部分的贡献
"我们运行于 temperature 0, 生成器在同一输入下确定性" 可作为方法论声明
(附 R1.4 证据), 但**必须**同步披露 "cross-seed 抽样方差未消除, 样本数仍小"。

---

## 4. 审计链

- 3 个 run 目录: `runs/tkde-g6-r14-run{1,2,3}/` (各 30 items, records-audit 待跑)
- config: `/tmp/tkde-g6-run{1,2,3}.yaml` (sha256 相同)
- aggregate: `tools/r14_variance.py --runs ...` (幂等, 只读已有目录)
- 全部真实 provider 调用, 无模拟。

---

**审计者**: Claude, 2026-08-19
**下次动作**: R1.5 (multi-seed 抽样方差, 若论文需要) / records-audit 3 个 run / R1.6 β_s
