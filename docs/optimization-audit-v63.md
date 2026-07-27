# SlotRAG Optimization Audit v63

日期：2026-07-27  
状态：development-only research reset；未使用 evaluation split 调参；未启动 2×2 主实验。

## 0. 先回答五个核心问题

### 当前最大的可利用 headroom 位于哪里？

当前可验证的最大 headroom 位于 `global_corpus` 下的检索与证据选择，而不是新的稀疏 guard。

* 同一批 40 题上，HotpotQA primary 从 local 的 `0.6764` 降至 global 的 `0.4467`，绝对下降 `0.2298`；2Wiki 从 `0.7239` 降至 `0.4825`，绝对下降 `0.2414`。
* global 的 evidence recall 分别只有 HotpotQA `0.5000`、2Wiki `0.4188`；local 分别为 `0.7125`、`0.8625`。
* 80 个 global development 问题中，离线 answer-surface proxy 发现 `40/80` 个问题的 available evidence 中存在答案，但最终 retrieved evidence 中不存在答案；当前 retrieved evidence 可回答 proxy 仅为 `33/80`。
* slot 级 oracle 近似中，简单扩大现有 top-k 只可挽回 HotpotQA `4` 个、2Wiki `4` 个 materialization；available-answer retrieval miss 则两个数据集各 `20/40`。因此只加 `EXPAND_TOPK` 仍是稀疏动作，核心必须覆盖 query reformulation、retriever switching 或多路检索。

结构化抽取是第二大方向：global 有 `50/80` 个问题触发过 `structured_output_failures`，但该覆盖率只是“受影响样本到满分”的乐观 ceiling，不是因果增益。严格 slot proxy 发现 gold evidence 已选中但未形成完整 row：HotpotQA `6`、2Wiki `2`。

### retrieval、planner、executor、generator 中哪个预期收益最大？

排序为：`retrieval/evidence selection` > `structured extraction` > `generator verification`；planner 与 executor 的真实 oracle 排名目前不可识别。

* retrieval 有 local/global 受控差值、evidence recall 和逐 slot ranked trace 支持。
* extraction 有 gold-evidence-selected-but-no-complete-row proxy 支持，但需和 retrieval miss 分开消融。
* rows 包含 answer surface 但 final answer 非满分的 generic proxy 为 `4/80`；更严格的 development analyzer 为 HotpotQA `0`、2Wiki `2`，因此 generator headroom 明显小于 retrieval。
* 现有样本没有 gold logical plan，`gold logical plan + current executor` 必须报告 `N/A`。不能用 plan validation error 的共现频率推断 planner 是最大瓶颈。

### 当前 benchmark 是否足以证明新模块有效？

不足。现在已经具备真实的 shared `global_corpus` development 诊断，但仍只有每数据集 40 个 train/development 问题、一个方法、一个 seed、BM25-only、没有冻结 paired evaluation，也没有 exact-upstream baseline。它足以否决坏设计和决定下一步，不足以支撑论文主结论或 SOTA 声称。

### 最近十余次迭代为什么主要产生 tie？

历史 v40-v53 主要修改低覆盖 guard；v54 已测得 frontier guard 只影响 `13/1200`。v63 再次表明 fixed top-k 扩展只覆盖 8 个 slot 级机会，而 global 的主要失败是证据没有被当前 query/ranking 召回。局部 guard 不改变大多数问题的检索路径，自然产生大量 tie。另一个原因是此前 benchmark 主要为 local-context evidence selection，很多题的 evidence 已被限制在自身 passages 内，进一步压缩了检索模块可表现的差异。

### 哪些模块删除、保留为 ablation 或降级为 safety option？

* 删除默认路径资格：predicate-specific repair、frontier guard、binding guard、selective dual-query guard。保留旧代码和历史结果作为独立 safety ablation，不再叠加新规则。
* 保留：逻辑/物理计划数据结构、compile telemetry、完整逐题 trace、manifest/provenance、deterministic answer operators。
* 暂不晋级：当前 Evidence Sufficiency calibrator。local holdout 看似可用，但 global 两个数据集均未通过校准 gate。
* 暂不计作方法贡献：当前 physical action policy 只产生 telemetry，没有改变执行路径。
* 下一版只允许独立改动两件事：修复 shared-index 数据管理瓶颈；使 sufficiency 使用有辨识度的 backend-aware 原始分数，并让有限动作真正执行。两者必须分别消融。

## 1. 审计输入与有效性

### 1.1 有效 development runs

| 协议 | 数据集 | 问题数 | Run | Manifest SHA-256 |
| --- | --- | ---: | --- | --- |
| local_context | HotpotQA + 2Wiki | 80 | `runs/slotrag-qo-development-trace-v63-local-valid` | `a4fc0f319e60a1af040e85242f04d0fd985dd4782111ddf09297dabea8c2d08a` |
| global_corpus | HotpotQA | 40 | `runs/slotrag-qo-development-trace-v63-global-valid` | `5e20eb1d8a9b6d6823d2c735e6e18b3aa0b6202ae5eed2fb575d4a763077b9d8` |
| global_corpus | 2Wiki | 40 | `runs/slotrag-qo-development-trace-v63-global-2wiki-valid` | `c700814282e29e4ff40a6e46f8993391eebc85e8b6b5ebf1a33ee2abc7f91a7a` |

三者的 `source_fingerprint_sha256` 都为 `13f1ff15b8f0150a3607d59217438c771e034e46ead644fcdb990b4561d4b624`，stage execution profile SHA-256 都为 `c6bd4c1feae731036b59d6506ced23b7abb1557b42d62c76d9015c81c00e34be`。Hotpot shard 记录为旧 revision + dirty，2Wiki shard 记录为随后生成的等内容 clean commit；由于 source fingerprint 和 execution profile 相同，本报告只在 development diagnostics 层合并分析，不把两个目录伪装成一个 immutable run。

所有 160 个 local/global item 状态均为 `ok`，provider retry 为 `0`。raw items、attempts、traces、samples、manifest 和 records audit 均保留在各自 run 目录。

### 1.2 明确无效、不得引用的 runs

* `runs/slotrag-qo-development-trace-v63`：配置写作 BM25，但实际仍调用 hybrid；同时发生 code drift。
* `runs/slotrag-qo-development-trace-v63-corrected`：item 执行使用 development 限流，但根 manifest 留有 smoke 的 `15/10` profile，provenance 不一致。
* `runs/slotrag-qo-development-trace-v63-global-valid` 中失败的 2Wiki 首次尝试：索引完成后检测到 revision/dirty metadata 变化并硬失败。失败 log 保留，不计入结果。

## 2. 实际执行命令与测试

主要离线命令：

```bash
PYTHONPATH=src:. python tools/analyze_qo_development.py \
  --run-dir runs/slotrag-qo-development-trace-v63-local-valid \
  --stage qo_trace_local_dev_v63_valid \
  --output-dir runs/slotrag-qo-development-trace-v63-local-valid/analysis/qo_trace_local_dev_v63_valid \
  --holdout-fraction 0.2 --minimum-examples 20

PYTHONPATH=src:. python tools/analyze_qo_development.py \
  --run-dir runs/slotrag-qo-development-trace-v63-global-2wiki-valid \
  --stage qo_trace_global_dev_v63_valid \
  --output-dir runs/slotrag-qo-development-trace-v63-global-2wiki-valid/analysis/qo_trace_global_dev_v63_valid \
  --holdout-fraction 0.2 --minimum-examples 20

PYTHONPATH=src:. python tools/analyze_slotrag_headroom.py \
  --run-dir runs/slotrag-qo-development-trace-v63-global-valid \
  --run-dir runs/slotrag-qo-development-trace-v63-global-2wiki-valid \
  --output-dir runs/slotrag-qo-development-trace-v63-global-2wiki-valid/analysis/headroom-v63-combined
```

测试：

* `PYTHONPATH=src pytest -q`：collection 失败，原因是根目录未进入 import path，`benchmark` 和 `tools` 无法导入；这是命令环境错误，保留记录。
* `PYTHONPATH=src:. pytest -q`：在本轮 analyzer 修复前为 `295 passed, 1 skipped`。
* `PYTHONPATH=src:. pytest -q tests/test_headroom_analysis.py tests/test_development_analysis.py`：本轮修复后为 `8 passed`。
* `PYTHONPATH=src:. pytest -q`：本轮 analyzer 修复后最终为 `297 passed, 1 skipped`；唯一 skip 为仓库既有条件性测试。

## 3. local_context 与 global_corpus 结果

| 协议 | 数据集 | N | Primary | Evidence recall | nDCG@10 | LLM calls | Retrieval calls | Mean wall ms | Mean retrieval-query ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| local_context | HotpotQA | 40 | 0.6764 | 0.7125 | 0.7179 | 156 | 68 | 20,334.6 | 0.0* |
| local_context | 2Wiki | 40 | 0.7239 | 0.8625 | 0.8668 | 124 | 65 | 15,674.3 | 0.0* |
| global_corpus | HotpotQA | 40 | 0.4467 | 0.5000 | 0.5332 | 161 | 69 | 15,735.1 | 2,948.3 |
| global_corpus | 2Wiki | 40 | 0.4825 | 0.4188 | 0.4680 | 140 | 62 | 19,844.6 | 3,064.3 |

`*` local retriever query latency 没有被 shared-index telemetry 记录为独立字段，不能解读为真实零延迟。

这些是 train/development 描述统计，不是 baseline 对比、不是置信区间结果，也不是论文主表。

## 4. Corpus 与数据管理审计

| 数据集 | Source questions | Documents | Chunks | Artifact size | Build latency | Reused flag |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| HotpotQA | 90,447 | 482,021 | 483,921 | 391 MB | 62.9 s | false |
| 2Wiki | 167,454 | 369,378 | 401,090 | 332 MB | 2,487.2 s | true |

两份 corpus manifest 都声明 `gold_evidence_not_used=true`，available evidence policy 为完整 split passages，评估 query 不获得 gold supporting passage。

`reused_persisted_index=true` 当前命名不准确：实现只复用 `passages.jsonl`（hybrid 时另有 embedding cache），`HybridRetriever` 初始化时仍重建 `rank_bm25.BM25Okapi`。此外 `_aggregate_passages` 在每次重复 passage 出现时都执行 `sorted(set(existing_ids) | {question_id})`；2Wiki 的共享 passage 重复率高，这使 provenance 聚合接近按重复组平方增长。2Wiki “复用”仍耗时约 41.45 分钟，正是该实现问题的实测证据。下一版必须把 passage provenance 聚合改为一次性 set accumulation，并对 sparse postings 做真实持久化；修复前不得做昂贵 global 矩阵。

SQLite FTS5 官方文档确认其索引、BM25 排序和外部/无内容表能力可用于持久化原型，但切换 ranking engine 会改变检索协议。为保持 v63 可比性，第一优先方案是持久化现有 BM25 状态并校验 index ID/checksum；FTS5 只作为单独 backend ablation，不静默替换当前 `bm25`。

## 5. Evidence Sufficiency 校准

| 协议 | 数据集 | Strong examples | Holdout N | Brier | ECE | Precision | Recall | Accuracy | Gate |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| local | HotpotQA | 68 | 13 | 0.0206 | 0.0797 | 1.000 | 0.909 | 0.923 | diagnostic pass |
| local | 2Wiki | 65 | 15 | 0.0665 | 0.0619 | 0.923 | 1.000 | 0.933 | diagnostic pass, imbalanced |
| global | HotpotQA | 69 | 13 | 0.2381 | 0.3286 | 0.750 | 0.667 | 0.615 | fail |
| global | 2Wiki | 62 | 16 | 0.2325 | 0.2381 | 0.615 | 1.000 | 0.688 | fail |

local analyzer 原先有 18 个 chunk source 无法回连；修复为按 frozen stage profile 重建 local chunks 后，missing source 为 `0`，2Wiki 标签从 `56/9` 修正为 `58/7`。旧 local calibration artifact 已被新的派生分析覆盖，raw run 未修改。

global 失败不是简单阈值问题。131 个 retrieval search 的 `top_k` 固定为 10；BM25-only RRF top-1 `score` 恒为 `0.0081967213`，top-1/top-2 margin 和 entropy 几乎恒定。当前 sufficiency 的 `top1_score/topk_score/margin/entropy` 因而缺少辨识度。原始 BM25 top-1 与最终 primary 的 Pearson proxy 为 `0.1919`，而 binding count 仅为 `0.0210`；reranker score 因 BM25 协议未调用而为 `N/A`。下一版必须使用 backend-aware 原始分数、rank/quantile 和跨查询一致性，不能继续在固定 RRF 分数上搜索阈值。

## 6. 错误分类与 counterfactual 边界

更新后的 v63-aware analyzer 读取 `result.slot_traces`，global 80 题的启发式单标签计数为：

| Category | Count |
| --- | ---: |
| PLAN_UNCOMPILABLE | 22 |
| EXTRACTION_ERROR | 10 |
| EVIDENCE_PARTIAL | 9 |
| BINDING_PRUNED | 3 |
| RETRIEVAL_MISS | 3 |

该表使用 precedence-ordered heuristic，只能用于失败切片，不能当作因果分解。尤其 plan validation error 可能已经被 fallback/local repair 恢复；没有 gold plan 时不能估计 planner oracle。

| Counterfactual / proxy | Count | Denominator | 状态与解释 |
| --- | ---: | ---: | --- |
| gold supporting evidence + current generator | 47 | 80 | opportunity proxy，未真正重跑 generator |
| current retrieval + oracle answerability | 33 | 80 | answer-surface proxy |
| gold logical plan + current executor | 0 | 80 | N/A，无 gold plan |
| current plan + gold slot bindings | 33 | 80 | row-surface proxy，不是真正注入 gold bindings |
| answer in available evidence but not retrieved evidence | 40 | 80 | answer-surface proxy |
| answer surface in rows but final non-perfect | 4 | 80 | generic surface proxy；严格 analyzer 为 2 |

## 7. Gate 决策

当前禁止启动昂贵 2×2/full matrix，原因如下：

* global calibrator 两个数据集都失败；
* fixed top-k 和 RRF score 没有足够特征变化；
* physical policy 目前没有改变执行行为；
* 2Wiki shared-index 冷启动/伪复用约 41 分钟；
* 只有一个方法、每数据集 40 题，尚无多 seed 或多 slice 的 paired improvement。

解除 gate 的顺序：

1. 优化 `_aggregate_passages` 并实现真实 sparse-index persistence，记录 cold/warm build latency 和 checksum。
2. 在同一 development inventory 上重新生成 backend-aware sufficiency examples，不使用 evaluation split。
3. 预注册 global calibration gate，例如同时要求 Brier、ECE、precision/recall 和 unsupported-answer rate 不恶化；阈值必须在 fit split 冻结。
4. 让 `EXPAND_TOPK`、`RETRIEVE_QUESTION_PLUS_SLOT`、`REWRITE_QUERY`、`STOP_SLOT/ANSWER` 至少一组动作真正改变执行，并记录 action-level gain/tie/loss。
5. 先跑小规模 paired 2×2 development smoke；只有多 slice 可复现且质量-成本匹配，才进入冻结 evaluation。

## 8. 投稿路线的当前判断

* Regular Systems Paper：当前不具备。缺少冻结 global-corpus paired 主结果、exact-upstream baseline、统计显著性、真实持久化索引以及 end-to-end physical action 收益。
* EA&B Paper：有潜力，但仍未达到提交状态。当前最有价值的是诚实的 protocol reset、immutable artifacts、local/global 差异、校准 null result 和 shared-index 数据管理瓶颈；需要完成至少一个可复现的系统优化与 2×2 结果。

本报告没有 SOTA、领先 10% 或显著性声明。所有数值来自上述 run、trace 或离线派生 artifact；缺少 gold plan、reranker/global dense 和冻结 evaluation 的部分均明确记为缺失。
