# SlotRAG-QO v68：Executable Physical Action Global Smoke

日期：2026-07-27

## 结论

v68 修复了 v67 的 runtime no-op：所有 treatment selected actions 都有对应 executed action，execution
coverage=`1.0`；`EXPAND_TOPK` 真实增加 retrieval calls，并在部分 slot 增加 rows。工程闭环 gate 通过。

质量/成本 gate 不通过。2Wiki physical/QO 相对 SlotRAG 都是 `-0.25`、gain/tie/loss=`0/3/1`；HotpotQA
都是 `0.00`、`0/4/0`。同时 treatment 的 retrieval calls、tokens 和 wall latency 显著增加，evidence
recall 没有改善。禁止扩大到 evaluation/full matrix。

唯一 primary loss 的根因是物理 join order 违反 binding dependency，而不是新执行的 top-k expansion：
冻结逻辑计划 `PerformerOf(S1) -> FatherOf(S2)` 被排成 `S2 -> S1`。baseline 的 `S1 -> S2` 得到正确答案
Mathew Knowles；physical/QO 先执行未绑定 `FatherOf`，adaptive beam 随后剪掉 3 个候选，输出 Öztürk
Serengil。该条 trace 同时记录 `MISSING_SELECTIVITY` 和 planner regret=`0.6667`。

## 协议与完整性

配置：`configs/experiments/slotrag-qo-action-execution-global-smoke-v68.yaml`。

* split：train；protocol：global-corpus；backend：BM25；
* HotpotQA/2Wiki 各 4 题，四方法，共 32 records；
* sample ID 与 v67 完全一致，并继续与 v63 development 样本零重叠；
* 8 个 frozen plans 全部从 v67 导入，32 个 method records 全部 replay 相同 plan；
* 32/32 `ok`，failed/empty/unsupported/retry 均为 0；
* record audit：32 finals、32 attempts、0 missing trace、0 manifest error；
* schema version：31；
* publication gate：`analysis_ready_nonpublication`，blockers 为 `smoke_stage_not_for_publication` 和
  `training_split_not_for_publication`。

运行：

```bash
PYTHONPATH=src:. /home/test/biosoft/enter/bin/python \
  tools/run_benchmark_matrix.py qo_action_execution_global_dev_v68_smoke \
  --suite configs/experiments/slotrag-qo-action-execution-global-smoke-v68.yaml \
  --output-dir runs/slotrag-qo-action-execution-global-smoke-v68 \
  --workers 2
```

分析：

```bash
PYTHONPATH=src:. /home/test/biosoft/enter/bin/python tools/analyze_2x2_runtime.py \
  --run-dir runs/slotrag-qo-action-execution-global-smoke-v68 \
  --stage qo_action_execution_global_dev_v68_smoke \
  --output runs/slotrag-qo-action-execution-global-smoke-v68/summaries/qo_action_execution_global_dev_v68_smoke/runtime-action-audit-v68.json
```

## 2x2 结果

| Dataset | Method | Primary | Evidence recall | nDCG@10 | Calls | Tokens | Wall ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2Wiki | SlotRAG | 0.50 | 0.250 | 0.3066 | 1.25 | 2010 | 11489 |
| 2Wiki | + sufficiency | 0.50 | 0.250 | 0.3066 | 1.25 | 2010 | 11870 |
| 2Wiki | + physical | 0.25 | 0.125 | 0.1533 | 2.00 | 3525 | 24682 |
| 2Wiki | + both/QO | 0.25 | 0.125 | 0.1533 | 2.25 | 4892 | 27586 |
| Hotpot | SlotRAG | 0.25 | 0.500 | 0.4626 | 2.75 | 4259 | 18625 |
| Hotpot | + sufficiency | 0.25 | 0.500 | 0.4626 | 2.75 | 4280 | 20149 |
| Hotpot | + physical | 0.25 | 0.375 | 0.3093 | 5.00 | 9207 | 32492 |
| Hotpot | + both/QO | 0.25 | 0.375 | 0.3093 | 5.25 | 9276 | 31679 |

样本只有每数据集 4 题，任何 CI/p 值都没有模型选择意义。该表只用于 runtime gate 和根因定位。

## Action 执行

| Dataset/method | Executed action usage | Extra calls/question | Rows added/question | Coverage |
| --- | --- | ---: | ---: | ---: |
| 2Wiki/physical | ANSWER 4, EXPAND_TOPK 2, STOP_SLOT 1 | 0.50 | 0.25 | 1.00 |
| 2Wiki/QO | ANSWER 4, EXPAND_TOPK 2, STOP_SLOT 1 | 0.75 | 0.25 | 1.00 |
| Hotpot/physical | ANSWER 4, EXPAND_TOPK 7, STOP_SLOT 5 | 2.00 | 3.00 | 1.00 |
| Hotpot/QO | ANSWER 2, EXPAND_TOPK 7, STOP_SLOT 7 | 2.25 | 2.50 | 1.00 |

扩展经常在 pre-action status=`SUFFICIENT` 时执行，并且多次 rows added=0；当前 utility 是启发式预期值，
没有被真实 counterfactual action outcome 校准。v69 先只修 join-order correctness，不同时调 utility
阈值。之后应在更大的 development trace 上标注 expansion marginal gain，再决定 policy 参数。

## Answer adapter 核查

部分 Qwen generation 的 raw `result.answer` 包含 reasoning 和 `</think>`。这是为了保留原始预测的设计；
`scores.prediction_scored` 已调用 `extract_answer_span`，正确取最后一个 `</think>` 后或最后一个 final/answer
tag 的内容。例如 raw 2767 chars 的样本实际评分文本为 `The supplied evidence is insufficient.`。因此 v68
不存在已发现的 think-text scoring contamination；raw 和 scored answer 必须继续同时保留。

## Artifact hashes

* runtime audit：`5dcca94da38fbf391e4f34c1731331c2c02e75f3d6f935fe0872ae3f41cb542f`；
* record audit：`559a648d19ff538428a22735348b28280e4f0e33345706173f7d871d3dedad78`；
* sample audit：`3800b84691fe79b11cc1a8dba9150d91f86e2d72d0905c7e004c3691bcf054cf`；
* publication gate：`342a2a9fedef841a931d6e5fa6e710cb7a086f7d034c3afa0e0dcbfe7a1f8952`；
* record fingerprint：`d1d02f28e859be1bc131ad0b1beb163ed930ab83f1746ab9a73621e256b57e25`。

## v69 单一改动

physical compiler 改为 dependency-constrained cost-based topological sort：只有 incoming dependencies 已
满足的 ready slots 可以参与 cost/cardinality/selectivity 排序；dependency cycle 从 warning 升为 compile
error。不改 sufficiency、action utility、retrieval 或 generation。

TDD 红灯为 2 个 dependency-order/cycle 断言；修复后全量为 `318 passed, 1 skipped`，compileall 和
`git diff --check` 通过。v69 使用同一 8 题、同一冻结逻辑计划复跑，验证 loss 是否消失，并单独记录
cost 增幅是否仍不匹配质量收益。
