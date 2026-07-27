# SlotRAG research reset：v65-v67 校准、独立验证与 2x2 runtime 审计

日期：2026-07-27

本报告只汇总 v65-v67 已落盘的代码、逐题记录和分析工件。它不把 train/development
结果解释为 evaluation 结果，不把本地 adapted baseline 解释为 exact upstream，也不把接口 smoke
解释为方法质量提升。

## 结论先行

1. 当前最大的已观测 headroom 仍在 global-corpus retrieval/query formulation。v66-valid 的 80 题中，
   `available_answer_retrieval_miss` proxy 为 32；相对地，扩大现有 top-k 可恢复 7 个 slot opportunity，
   已选证据但抽取失败 7 个，rows 正确但最终答案错误 1 个。这些是诊断计数，不是可以直接相加的准确率
   上界。
2. v65 的 backend-aware sufficiency 在独立 v66 development 样本上优于冻结 legacy 特征。HotpotQA 的
   paired Brier delta 95% CI 不跨 0；2Wiki 的 CI 跨 0，因此后者只能视为有方向但不确定的结果。
3. v67 不是有效的 physical-policy 方法结果。trace 显示策略选择了动作，但 executor 没有执行动作；
   两个 treatment 的 selected-action execution coverage 都为 0。该运行的 2Wiki -0.25 和 HotpotQA 0.00
   只能作为实现缺陷证据，不能用于判断新方法有效或无效。
4. 继续只加 fixed top-k、binding/frontier guard 或 predicate-specific repair 的平均收益上限很低。
   下一版本必须先把有限动作真正接到 runtime，并以预算、动作覆盖率、unsupported-answer 和逐题配对
   结果作为 gate。
5. 当前没有任何冻结 evaluation split + exact upstream baseline + 同协议 SOTA 对照单元格。因此，
   “达到 80% 数据集/官方指标 SOTA”的已验证覆盖是 `0` 个可比单元格；分母也尚未由 upstream protocol
   registry 固化。不得声称 SOTA 或接近 SOTA。

## 环境与验证

v68 runtime patch 合入实验前的代码门禁：

```bash
PYTHONPATH=src:. /home/test/biosoft/enter/bin/python -m pytest -q
/home/test/biosoft/enter/bin/python -m compileall -q src tools tests
git diff --check
```

实际结果：`317 passed, 1 skipped`；compileall 和 diff check 通过。pytest 唯一额外输出是
`pytest-asyncio` 的 future loop-scope deprecation warning，不是测试失败。

仓库 instructions 引用的 `/home/test/.codex/RTK.md` 在本环境不存在；本报告没有假定其中内容。

## v65：backend-aware Evidence Sufficiency

v65 只在 v63 train/development enriched traces 上选择特征族和正则强度，没有使用 evaluation split。
冻结选择为：

| Dataset | 冻结候选 | 独立验证 examples/questions | Brier | ECE | Precision | Recall | Accuracy |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2Wiki | `structural_backend_raw@l2=0.1` | 61/40 | 0.1449 | 0.1547 | 0.8222 | 0.9250 | 0.8197 |
| HotpotQA | `full_v2@l2=0.01` | 89/40 | 0.1508 | 0.0717 | 0.7778 | 0.7955 | 0.7865 |

冻结 legacy comparator：

| Dataset | Legacy Brier | Legacy ECE | Legacy Accuracy | selected - legacy Brier，95% CI |
| --- | ---: | ---: | ---: | --- |
| 2Wiki | 0.1684 | 0.2189 | 0.7541 | -0.02345 `[-0.05103, 0.00694]` |
| HotpotQA | 0.2036 | 0.1275 | 0.6742 | -0.05284 `[-0.09516, -0.01289]` |

bootstrap 为 10,000 次、seed 2027，单位是 slot-materialization example。2Wiki CI 跨 0，不能写成
确定改善；HotpotQA 在该独立 development validation 上支持更低 Brier loss。两者都不是 answer-quality
或 evaluation 结论。

冻结工件：

* `frozen-selection-validation-v65.json` SHA256：
  `c6fc076cef93f71112e47efb1b95bcd6dc6fc46853e2b1456a3541498a71f655`；
* runtime calibrator SHA256：
  `858653ec76bcd85c4d3b3399a0fddffb4fc6bbe1e68bf2b8dbfd9af3003044d8`。

## v66：不重叠 development validation

有效运行目录是 `runs/slotrag-qo-development-validation-v66-valid`。seed 314159，HotpotQA 和 2Wiki
各 40 题，均来自 train split，并通过 sample audit 确认与 v63 global development 样本 overlap=`0`。

执行命令：

```bash
/home/test/biosoft/enter/bin/python tools/run_benchmark_matrix.py \
  qo_trace_global_dev_v66_validation \
  --suite configs/experiments/slotrag-qo-development-validation-v66.yaml \
  --output-dir runs/slotrag-qo-development-validation-v66-valid \
  --workers 2
```

逐题状态为 80/80 `ok`，retry/failed/empty/unsupported 均为 0；record audit 完整，trace 缺失为 0。
结果仅用于 headroom 和校准验证：

| Dataset | F1/primary | EM | Evidence recall | nDCG@10 |
| --- | ---: | ---: | ---: | ---: |
| 2Wiki | 0.4167 | 0.4000 | 0.5250 | 0.5764 |
| HotpotQA | 0.4791 | 0.4250 | 0.4875 | 0.4720 |

150 个 sufficiency examples 中，2Wiki 为 40 positive/21 negative，HotpotQA 为 44/45；missing source=0。
oracle/headroom proxy：

| Category | Count |
| --- | ---: |
| available evidence 含答案但当前 retrieval miss | 32 |
| 扩大当前 top-k 可恢复的 slot opportunity | 7 |
| evidence selected 但 extraction failed | 7 |
| rows 含正确答案但 final answer 错误 | 1 |

publication gate 是 `analysis_ready_nonpublication`，唯一数据切分 blocker 为
`training_split_not_for_publication`。这批数据不能进入论文主结果。

第一次同名运行目录 `runs/slotrag-qo-development-validation-v66` 必须保留但标记无效：80/80 都因
`SLOTRAG_AGNES_API_KEY` 未加载而成为 configuration failure。不得把该目录与 `-valid` 合并或重跑覆盖。

## v67：2x2 global smoke 与 no-op 根因

运行目录：`runs/slotrag-qo-2x2-global-smoke-v67`。协议为 train split、global-corpus BM25、每数据集 4 题，
四个方法共享冻结 plan：

1. `slotrag`；
2. `slotrag-sufficiency`；
3. `slotrag-physical-policy`；
4. `slotrag-qo`。

命令：

```bash
/home/test/biosoft/enter/bin/python tools/run_benchmark_matrix.py \
  qo_trace_global_dev_v66_validation \
  --suite configs/experiments/slotrag-qo-2x2-global-smoke-v67.yaml \
  --output-dir runs/slotrag-qo-2x2-global-smoke-v67 \
  --workers 2

PYTHONPATH=src:. /home/test/biosoft/enter/bin/python tools/analyze_2x2_runtime.py \
  --run-dir runs/slotrag-qo-2x2-global-smoke-v67 \
  --stage qo_trace_global_dev_v66_validation \
  --output runs/slotrag-qo-2x2-global-smoke-v67/summaries/qo_trace_global_dev_v66_validation/runtime-action-audit-v67.json
```

32/32 records 为 `ok`，record/trace 完整。primary smoke：

| Dataset | SlotRAG | + sufficiency | + physical policy | + both/QO |
| --- | ---: | ---: | ---: | ---: |
| 2Wiki | 0.50 | 0.50 | 0.25 | 0.25 |
| HotpotQA | 0.25 | 0.25 | 0.25 | 0.25 |

但 runtime audit 给出了决定性实现问题：

| Dataset/method | selected actions | executed actions | execution coverage | 对 SlotRAG delta | gain/tie/loss |
| --- | --- | --- | ---: | ---: | --- |
| 2Wiki/physical | ANSWER 4, EXPAND_TOPK 1 | 0 | 0.00 | -0.25 | 0/3/1 |
| 2Wiki/QO | ANSWER 4, STOP_SLOT 1 | 0 | 0.00 | -0.25 | 0/3/1 |
| Hotpot/physical | ABSTAIN 2, ANSWER 3, EXPAND_TOPK 3, REWRITE_QUERY 1 | 0 | 0.00 | 0.00 | 0/4/0 |
| Hotpot/QO | ANSWER 2, EXPAND_TOPK 3, STOP_SLOT 4 | 0 | 0.00 | 0.00 | 0/4/0 |

`slotrag-sufficiency` 与 `slotrag` 的 answers/rows/evidence 在两个数据集都是 100% exact match，符合
predictor-only 因子的 2x2 语义；sufficiency 的作用应通过与 physical policy 的 interaction 测量。

v67 compact audit SHA256：
`a96ec0568bc2d64abee94fcdd1d505a78d67f516d67e8420978277f61a63dba4`；其 record fingerprint 为
`5f6cde6162c9e17952b56d6c59b9d24be8c029cf058636981184eac751c08d03`。

### 为什么最近迭代多为 tie

* v53 类 sparse guards 只影响极少样本，平均效果有硬上限；
* v65 sufficiency 是 predictor，单独因子按设计不改变答案；
* v67 physical actions 只写 telemetry，没有修改 retrieval/control flow；
* shared frozen plan 会消除编译随机差异，这是正确的实验控制，但也暴露出 treatment 没有执行机制；
* global retrieval miss 比可由当前 top-k 恢复的样本多，单纯预算扩张覆盖不足。

## 模块处置

| 模块 | 处置 | 依据 |
| --- | --- | --- |
| persistent global BM25/shared index | 保留 | v64 已解决 warm reuse 与可验证 artifact；不改变排序语义 |
| LogicalPlan/PhysicalPlan 与 compile telemetry | 保留 | 是数据库优化内涵和可独立消融的接口基础 |
| backend-aware sufficiency | 保留为实验因子 | 独立 development calibration 有改善，但 2Wiki CI 跨 0 |
| adaptive binding beam | 保留为 ablation，继续审计 | 尚无足够 gold-path pruning 证据 |
| v53 以前 predicate/binding/frontier guards | 默认降级为 legacy/safety ablation | 覆盖稀疏、平均 headroom 小 |
| 未实现的 rewrite/switch/backtrack 等动作 | runtime 禁用 | 不能再把 no-op 暴露为候选动作 |
| 新 predicate-specific repair | 禁止进入核心方法 | 会在固定失败样本上形成不可泛化规则搜索 |

## v68 进入条件

v68 只验证一个垂直切片：`EXPAND_TOPK` 必须真实调用 materializer、合并 rows/evidence/trace、重新评估
sufficiency，并严格遵守全局和 per-slot retrieval budget。控制动作 `STOP_SLOT`、`ANSWER`、`ABSTAIN`
必须记录 selected/executed；其余没有执行器的动作不进入候选集合。

smoke gate：

* 所有测试通过；
* treatment 中 selected action execution coverage 为 1；
* 至少有一次真实 top-k expansion，或由 provider-free deterministic test 覆盖该路径；
* `physical_action_extra_retrieval_calls` 与总 retrieval calls 对齐且不超预算；
* 不增加 failed/unsupported records；
* 负结果原样保留，不据 4 题 smoke 调策略阈值。

在这个 gate 通过前，不运行昂贵 evaluation/full baseline matrix。
