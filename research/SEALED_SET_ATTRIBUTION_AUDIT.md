# SEALED_SET_ATTRIBUTION_AUDIT.md

> **最后更新**: 2026-08-10
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
- [ ] Tier 3 其余数据集（hotpotqa/2wiki/musique/drop）SEALED 评估待运行（同样需多次运行取均值）
- [ ] 全量（12,557）运行后，本审计记录全量干净归集
- [ ] **非确定性披露进论文方法节**：qwen3.6-27b 推理边界题 flip-flop，SEALED 结果多次运行取均值 + 报告 run-to-run range
