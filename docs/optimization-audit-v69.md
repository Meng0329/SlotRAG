# SlotRAG-QO v69：Dependency-safe Physical Planning Global Smoke

日期：2026-07-27

## 结论

v69 的单一方法改动通过了 correctness gate：physical planner 只在 dependency-ready 的 slots 中进行
cost-based ordering，并将 dependency cycle 视为 compile error。v68 的唯一 paired loss 被消除；在同一
8 个 train/global-corpus 问题、同一冻结逻辑计划上，physical/QO 相对 SlotRAG 的 primary
gain/tie/loss 在 HotpotQA 和 2Wiki 均为 `0/4/0`。

v69 没有通过 quality-cost gate。所有四种方法在 2Wiki 的 primary 均为 `0.50`，在 HotpotQA 均为
`0.25`；evidence recall 和 nDCG 也完全持平。相比 SlotRAG，QO 在 2Wiki 的 calls/tokens/wall latency
从 `1.25/2010/5596 ms` 增至 `1.75/3583/9354 ms`，在 HotpotQA 从
`2.75/4286/17653 ms` 增至 `5.50/11282/35807 ms`。额外 retrieval 没有产生 answer-quality gain，
因此禁止扩大到 evaluation/full matrix。

这次 null result 支持下一步转向 development trace 上的 action marginal-gain 分析；不支持在 4 题 smoke
上调 utility threshold。当前冻结 evaluation + exact upstream + 同协议 SOTA 的可比单元格仍为 `0`，
不能声称达到 80% SOTA 覆盖。

## 运行有效性

第一次运行目录 `runs/slotrag-qo-dependency-safe-global-smoke-v69` 在完成 24/32 records 后，工作树被外部
提交从启动时 provenance 改变；最后两个 cells 被 runner 以 `run manifest provenance mismatch` 拒绝。
该目录保留为 provenance-invalid，不与任何有效结果合并。

有效运行从干净 revision `8e7336b85453aecdd04731d601acc99276987736` 重新开始：

* 目录：`runs/slotrag-qo-dependency-safe-global-smoke-v69-valid`；
* 配置：`configs/experiments/slotrag-qo-dependency-safe-global-smoke-v69.yaml`；
* split/protocol/backend：train / global-corpus / BM25；
* HotpotQA、2Wiki 各 4 题，四方法，共 32 records；
* 32/32 `ok`，failure/empty/unsupported/retry 均为 0；
* 32 finals、32 attempts、missing trace/attempt 均为 0；
* 8/8 frozen plans 有效并导入，32 records 的 effective plan 每题一致；
* 样本与 v68/v67 完全相同，与 v63 development 样本 overlap=`0`；
* publication gate=`analysis_ready_nonpublication`，原因是 smoke stage 和 train split。

保存的原始命令：

```bash
/home/test/biosoft/enter/bin/python tools/run_benchmark_matrix.py \
  qo_dependency_safe_global_dev_v69_smoke \
  --suite configs/experiments/slotrag-qo-dependency-safe-global-smoke-v69.yaml \
  --output-dir runs/slotrag-qo-dependency-safe-global-smoke-v69-valid \
  --workers 2
```

compact 分析命令：

```bash
PYTHONPATH=src:. /home/test/biosoft/enter/bin/python tools/analyze_2x2_runtime.py \
  --run-dir runs/slotrag-qo-dependency-safe-global-smoke-v69-valid \
  --stage qo_dependency_safe_global_dev_v69_smoke \
  --output runs/slotrag-qo-dependency-safe-global-smoke-v69-valid/summaries/qo_dependency_safe_global_dev_v69_smoke/runtime-action-audit-v69.json
```

## 2x2 结果

| Dataset | Method | Primary | Evidence recall | nDCG@10 | Calls | Tokens | Wall ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2Wiki | SlotRAG | 0.50 | 0.250 | 0.3066 | 1.25 | 2010 | 5596 |
| 2Wiki | + sufficiency | 0.50 | 0.250 | 0.3066 | 1.25 | 2010 | 5350 |
| 2Wiki | + physical | 0.50 | 0.250 | 0.3066 | 1.75 | 3176 | 7409 |
| 2Wiki | + both/QO | 0.50 | 0.250 | 0.3066 | 1.75 | 3583 | 9354 |
| Hotpot | SlotRAG | 0.25 | 0.500 | 0.4626 | 2.75 | 4286 | 17653 |
| Hotpot | + sufficiency | 0.25 | 0.500 | 0.4626 | 2.75 | 4291 | 16765 |
| Hotpot | + physical | 0.25 | 0.500 | 0.4626 | 5.00 | 10126 | 33635 |
| Hotpot | + both/QO | 0.25 | 0.500 | 0.4626 | 5.50 | 11282 | 35807 |

样本只有每数据集 4 题，不能用其置信区间、p 值或单题结果选择策略参数。该表只用于 correctness、runtime
和成本 gate。

## Action 审计

| Dataset/method | Executed action usage | Extra calls/question | Rows added/question | Coverage |
| --- | --- | ---: | ---: | ---: |
| 2Wiki/physical | ANSWER 4, EXPAND_TOPK 2, STOP_SLOT 1 | 0.50 | 0.00 | 1.00 |
| 2Wiki/QO | ANSWER 4, EXPAND_TOPK 2, STOP_SLOT 1 | 0.50 | 0.25 | 1.00 |
| Hotpot/physical | ABSTAIN 1, ANSWER 3, EXPAND_TOPK 7, STOP_SLOT 5 | 2.00 | 0.25 | 1.00 |
| Hotpot/QO | ABSTAIN 1, ANSWER 1, EXPAND_TOPK 8, STOP_SLOT 7 | 2.50 | 0.25 | 1.00 |

所有 treatment action execution coverage 均为 `1.0`，所以这不是 v67 的 no-op 问题。Hotpot QO 每题
2.50 次 action-induced retrieval 只增加 0.25 rows，且 primary/evidence 无变化；当前 utility 对
`EXPAND_TOPK` 的预期收益明显未被真实 marginal outcome 校准。

## 修改与测试

v69 只修改 dependency correctness：

* dependency-constrained cost-based topological sort；
* 只有 incoming dependencies 已满足的 slot 可进入 ready queue；
* dependency cycle 从 warning 升为 compile error；
* 增加 dependency ordering、cycle 和 runtime replay 回归测试。

全量验证：`PYTHONPATH=src:. pytest -q` 为 `318 passed, 1 skipped`；
`PYTHONPATH=src:. python -m compileall -q src benchmark tools` 与 `git diff --check` 均通过。

## Artifact hashes

* runtime audit：`d9d3d98ef9f237b82d922204602ba16131c4a83df89bf5e31b45093fc367716c`；
* record audit：`291e6dd3b38fb4082ec43140e6d29d13e6bef08db2d2b28d8dacd7bd696bb5bf`；
* sample audit：`a088fd868f7271a2e54f3c4a3e5c676ba7111973f16f476619b53e30f8d49ccd`；
* publication gate：`ba293d4cb8873fb38d5a463ea6bd90186d63a51cfdca7f3618baa945da1c96bb`；
* frozen-plan audit：`d9a70691009dcbc4aa54466d0d0ef5bed73ff883caed677061b5e53ddaa2f0f3`；
* record fingerprint：`d730087c85045fabf622b56a969a041104e62a187451849542d21e5908ddbd0c`。

## v70 Gate

v70 先在 v63 global development traces 上定义 action outcome，在与其零重叠的 v66-valid traces 上固定
验证。`EXPAND_TOPK` 只能使用 strong gold-evidence supervision；candidate pool recovery 是 top-k 扩展
的近似上界，不等价于一次真实 provider counterfactual。至少报告 expansion precision/recall、false
expansions、recoverable positives、按 dataset/status/plan depth 分层和调用成本。若正例过少，不拟合高维
模型；若离线 gate 不通过，保留 null result 并停止为该 action 堆补丁。
