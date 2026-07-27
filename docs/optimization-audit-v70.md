# SlotRAG-QO v70：Bounded Top-k Action Headroom 与冻结策略

日期：2026-07-27

## 结论

v70 使用 v63 global train/development traces 做策略选择，并仅用与其问题零重叠的 v66-valid traces 做
冻结后验证。分析为 provider-free，`provider_calls=0`。在 development 上，记录的更大 candidate pool
只为 `8/131=6.11%` 个 slot materializations 提供“当前 selected top-k 无 gold、candidate pool 有 gold”
的检索上界；validation 为 `7/150=4.67%`。这只是 evidence recovery proxy，不保证 extraction、join、
generation 或 final answer 改善。

按 v61 已声明的 retrieval-call penalty `λ=0.08`，development 选择结果为 `no_expansion`。当前 utility
扩展 82/131 次，只命中 6 个 proxy positives，precision/recall=`0.0732/0.7500`，proxy net utility
=`-0.004275`；零重叠 validation 扩展 105/150 次，命中 6 个，precision/recall=`0.0571/0.8571`，
net utility=`-0.016000`。因此现有 bounded `EXPAND_TOPK` 应从主方法降级，保留为 utility ablation；
不得继续在该 action 上搜索阈值。

`status_safe` 也不能替代这一结论：development 的 8 个 positives 中有 5 个被 frozen calibrator 标为
`SUFFICIENT`，validation 的 7 个中有 2 个；直接禁止 SUFFICIENT expansion 会系统性丢失上界机会。
虽然 status-safe 在 validation 的 proxy net utility 为 `+0.001333`，它在 development 为
`-0.000916`，且 validation 不允许反向用于策略选择。

## 标签与边界

`src/slotrag/benchmarking/development.py` 的 analysis schema 升为 3。每个 strong-supervision slot
materialization 记录：gold/selected/candidate canonical evidence IDs、selected/candidate counts、是否有
扩展空间、gold 是否已选中、candidate pool 是否包含 gold，以及 `expand_topk_recoverable`。weak
answer-surface 样本明确标为 action-supervision ineligible。

标签定义：

```text
expand_topk_recoverable =
    gold evidence not in selected results
    AND gold evidence in the already-recorded larger candidate pool
```

该定义没有重新调用 retriever，也没有运行扩大 top-k 后的 extractor/generator。所有报告均带
`candidate_pool_is_counterfactual_proxy=true`，不能把 TP 解释成最终答案 gain。

## Development 策略选择

v63 sources：HotpotQA 69 examples、2Wiki 62 examples，共 80 questions、131 examples；missing source=0。

| Policy | Expansions | TP/FP/FN | Precision | Recall | Mean calls | Proxy net utility |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| no expansion | 0 | 0/0/8 | 0.0000 | 0.0000 | 0.0000 | 0.000000 |
| fixed top-k | 131 | 8/123/0 | 0.0611 | 1.0000 | 1.0000 | -0.018931 |
| rule | 77 | 5/72/3 | 0.0649 | 0.6250 | 0.5878 | -0.008855 |
| current utility | 82 | 6/76/2 | 0.0732 | 0.7500 | 0.6260 | -0.004275 |
| status safe | 39 | 3/36/5 | 0.0769 | 0.3750 | 0.2977 | -0.000916 |
| candidate-pool oracle | 8 | 8/0/0 | 1.0000 | 1.0000 | 0.0611 | 0.056183 |

oracle 不参与选择。排序为 `no_expansion > status_safe > current_utility > rule > fixed_topk`。

## 零重叠 Validation

v66-valid 共 80 questions、150 examples；与 development question overlap=`0`，missing source=0。冻结
策略仍为 `no_expansion`，下表其他策略只作诊断，未用于改选。

| Policy | Expansions | TP/FP/FN | Precision | Recall | Mean calls | Proxy net utility |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| no expansion | 0 | 0/0/7 | 0.0000 | 0.0000 | 0.0000 | 0.000000 |
| fixed top-k | 150 | 7/143/0 | 0.0467 | 1.0000 | 1.0000 | -0.033333 |
| rule | 99 | 6/93/1 | 0.0606 | 0.8571 | 0.6600 | -0.012800 |
| current utility | 105 | 6/99/1 | 0.0571 | 0.8571 | 0.7000 | -0.016000 |
| status safe | 60 | 5/55/2 | 0.0833 | 0.7143 | 0.4000 | 0.001333 |
| candidate-pool oracle | 7 | 7/0/0 | 1.0000 | 1.0000 | 0.0467 | 0.042933 |

## 分层结果

| Split | Dataset | Examples | Positives | Current utility precision/recall | Status-safe precision/recall |
| --- | --- | ---: | ---: | ---: | ---: |
| development | HotpotQA | 69 | 4 | 0.0769 / 0.7500 | 0.1364 / 0.7500 |
| development | 2Wiki | 62 | 4 | 0.0698 / 0.7500 | 0.0000 / 0.0000 |
| validation | HotpotQA | 89 | 4 | 0.0606 / 1.0000 | 0.0909 / 1.0000 |
| validation | 2Wiki | 61 | 3 | 0.0513 / 0.6667 | 0.0625 / 0.3333 |

Status positive counts：development `INSUFFICIENT/PARTIAL/SUFFICIENT=3/0/5`；validation=`4/1/2`。
Depth positive counts：development depth `0/1/2/3=4/3/0/1`；validation=`5/1/0/1`。正例横跨
bridge、comparison、compositional 和 bridge-comparison，没有足够样本支持 predicate/question-type
规则；不得从这些小格增加 hard-coded repair。

## 实现、命令与工件

新增 `src/slotrag/benchmarking/action_headroom.py`、`tools/analyze_action_headroom.py` 和
`tests/test_action_headroom.py`。工具输出 development/validation summary、完整逐样本 JSONL、冻结
policy selection、manifest 和 Markdown report；输出目录不可覆盖。

```bash
PYTHONPATH=src:. /home/test/biosoft/enter/bin/python tools/analyze_action_headroom.py \
  --development-run runs/slotrag-qo-development-trace-v63-global-valid qo_trace_global_dev_v63_valid \
  --development-run runs/slotrag-qo-development-trace-v63-global-2wiki-valid qo_trace_global_dev_v63_valid \
  --validation-run runs/slotrag-qo-development-validation-v66-valid qo_trace_global_dev_v66_validation \
  --calibrator runs/slotrag-qo-development-validation-v66-valid/analysis/qo_trace_global_dev_v66_backend_features_complete/sufficiency-calibrator-v65-frozen.json \
  --output-dir runs/slotrag-qo-action-headroom-v70 \
  --retrieval-call-penalty 0.08
```

关键 SHA256：

* manifest：`4b53867cc498d64dabfc7c362bfebbc237eaeb0593f1a6b9af00da5611923bf8`；
* policy selection：`47cdd707bf9068955fa64e7b12f4d1e6a7d09a832110d61143061026337d137e`；
* development summary/examples：`ee01526c6453e676df4d800ddac4af89f6be67e39012541bca84b768163e3a1c` /
  `738594a6cce24900182ec33d56820c0ef395a2836a411110a56cafff87c7b6ee`；
* validation summary/examples：`f72f61d903150261741ae6b9693399721fe75aa2191915e64fa9f5413bccb504` /
  `cd8d0f1aebb53dfd283104e075cef66da152ad4f3b4ea68a44a406d3ba185197`；
* frozen sufficiency calibrator：`858653ec76bcd85c4d3b3399a0fddffb4fc6bbe1e68bf2b8dbfd9af3003044d8`。

Focused action/development tests 为 `7 passed`，compileall 与 `git diff --check` 通过。v71 的单一改动是
主 physical/QO methods 使用 development-selected `no_expansion`；旧 utility 行为保留为显式 ablation。
v71 先在同一 8 题 frozen-plan smoke 验证 action count 和成本是否回落，不宣称质量提升。
