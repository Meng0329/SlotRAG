# SlotRAG v54 优化上限审计

日期：2026-07-27  
审计类型：离线、provider-free、不可变工件读取  
审计工具：`tools/analyze_slotrag_headroom.py`

## 1. 环境与审计边界

当前提交为 `5779388`。工作区在审计开始时干净；历史 run 工件没有被修改。

实际执行命令：

```bash
PYTHONPATH=src:. pytest -q
python -m compileall -q src benchmark tools
git diff --check
PYTHONPATH=src:. python tools/analyze_slotrag_headroom.py \
  --run-dir runs/slotrag-frontier-guard-train-v2 \
  --run-dir runs/slotrag-answer-contract-train-v1 \
  --output-dir runs/slotrag-frontier-guard-train-v2/summaries/optimization_audit_v54
```

基线测试结果：`251 passed, 1 skipped`。裸 `pytest -q` 因未安装 `src` 布局包而在收集阶段产生 `ModuleNotFoundError`，不属于测试逻辑失败；后续统一使用 `PYTHONPATH=src:.`。

本次离线分析读取：

- v53 frontier/binding 配对：1000 条 item；
- answer-contract train v1：200 条 item；
- 合计 1200 条 item、对应 samples 和 result metrics；
- 不调用 embedding、reranker 或 generation provider。

完整输出位于：
`runs/slotrag-frontier-guard-train-v2/summaries/optimization_audit_v54/`。

历史 v53、answer-contract 结果均为 train/local-context 或 adapted 协议，不能作为 global-corpus 或 exact-upstream 投稿主表。

## 2. 主要发现

### 2.1 最大可利用 headroom

最有意义的已观测机制 headroom 是 structured extraction：

| 机制 | 影响题数 | 覆盖率 | 受影响题平均到完美上限 | 全体平均理论上限 |
| --- | ---: | ---: | ---: | ---: |
| `structured_output_failures` | 167 | 13.92% | 0.4416 | 0.0615 |
| `grounding_rejections` | 112 | 9.33% | 0.4533 | 0.0423 |
| `binding_contexts_pruned` | 62 | 5.17% | 0.3398 | 0.0176 |
| `protected_anchor_rejections` | 18 | 1.50% | 0.4506 | 0.0068 |
| `frontier_guard_interventions` | 13 | 1.08% | 0.3231 | 0.0035 |

`reoptimizations` 覆盖率为 38.5%，但它是执行活动计数而非可独立归因的改进模块，因此不作为优化优先级。

当前 retrieval 中已有可回答答案的估计比例为 `739/1200 = 61.58%`；完整可用 evidence 中存在答案、但 top-k evidence 未包含答案的估计为 `91/1200 = 7.58%`。这说明 shared-corpus retrieval telemetry 和 evidence sufficiency 是首要基础设施，而不是继续增加低覆盖率 guard。

约 `70/1200 = 5.83%` 样本的 rows 中已经出现 gold answer，但最终回答错误。这是 generator/extraction/answer verification 的可利用上限估计，不代表可直接取得的增益。

gold logical plan counterfactual 为 `N/A`：现有历史 item 没有可用 gold plan，不能推断 planner 或 executor 的真实 oracle headroom。

### 2.2 近期迭代为何主要产生 tie

- v53 binding/frontier 的 pairwise 结果为 `6/487/7`（按 binding 相对 frontier），answer-contract v1 为 `3/95/2`；合并 pairwise tie rate 为 `97%`。
- frontier intervention 只覆盖 `1.08%` 题，protected-anchor 只覆盖 `1.50%` 题；低覆盖率决定了全体平均增益上限很低。
- 许多变化发生在已能正确回答的题上，只改变内部路径、成本或安全计数，不改变 final answer。
- 当前 benchmark 每题单独建立 retriever，无法测量跨问题 distractor、共享索引收益或真实 top-k sufficiency。
- 历史 item 没有完整 ranked retrieval score、margin、entropy、sparse/dense agreement 和 binding-pruning path，因此无法验证阈值或策略是否真的改善 retrieval。

### 2.3 该优化 retrieval、planner、executor 还是 generator

建议顺序：

1. 先修复 benchmark protocol，建立 global-corpus 和完整 retrieval telemetry；否则 retrieval headroom 无法被可信测量。
2. 在协议修复后实现 evidence sufficiency 和 physical action policy，优先扩大 evidence coverage 并控制成本。
3. 同时加入 rows/evidence 驱动的可验证答案生成；现有数据中 rows-correct/final-wrong 高于 frontier 触发率。
4. planner/executor 只在存在 gold-plan 或可审计执行 oracle 的 slice 上优化；当前数据不足以证明 planner 是最大瓶颈。

## 3. 错误与 counterfactual

错误分类统计：

| 类别 | 数量 |
| --- | ---: |
| `ANSWER_GENERATION_ERROR` | 249 |
| `EXTRACTION_ERROR` | 71 |
| `EVIDENCE_PARTIAL` | 37 |
| `BINDING_PRUNED` | 25 |
| `RETRIEVAL_MISS` | 4 |

没有从历史工件中可靠得到 `PLAN_UNCOMPILABLE` 或 gold-plan executor 估计；缺失项保持 `N/A`，不补猜。

| Counterfactual | 结果 | 状态 |
| --- | ---: | --- |
| gold evidence + 当前 generator 的受影响题 | 116/1200 | estimated |
| 当前 retrieval + oracle answerability | 739/1200 | estimated |
| gold logical plan + 当前 executor | 0/1200 | N/A |
| 当前 plan + gold slot bindings | 601/1200 | estimated |
| 完整 evidence 有答案但 top-k 无答案 | 91/1200 | estimated |
| rows 有正确答案但 final 错误 | 70/1200 | estimated |

这些 counterfactual 是 headroom 诊断，不是论文结果，也不允许直接转化为方法增益。

## 4. Benchmark 充分性审计

当前协议不足以支撑论文主结论：

- `BenchmarkRunner._retriever()` 对每个问题的 passages 单独构建 `HybridRetriever`，即 local-context，而非 shared-corpus RAG；
- StrategyQA 下载脚本把每题 `facts` 拆成该题 passages，形成 question-scoped fact retrieval；
- DROP `operation_type` 是下载时基于问题词的启发式分类，缺少原始 operation provenance；
- adapted IRCoT、ReAct、PlanRAG、GraphRAG 不能写成 exact upstream execution；
- 历史 item 缺少 top-k/reranker score 关系、source diversity、binding recall、join success 和 answer groundedness telemetry。

因此 v54 不产生 publication-ready 结论，也不启动全矩阵实验。

## 5. 模块处理决定

- `frontier_guard`、`binding_guard`、answer-contract：保留为历史 replay 和独立 safety ablation，不作为新核心方法。
- predicate-specific repair：禁止继续扩展；已有实现仅保留为 legacy/safety 对照。
- `reoptimizations`：保留为 telemetry，不作为质量模块归因。
- 新开发方向：`slotrag-qo`，核心是 shared-corpus、LogicalPlan/PhysicalPlan、evidence sufficiency、physical action policy、adaptive binding beam 和可验证答案。

## 6. v54 结论与 gate

v54 通过离线审计完整性 gate：

- 工具可读取现有 item/sample 工件并输出 CSV、JSON、Markdown；
- 1200 条记录无 provider 调用；
- retrieval、binding、generator 缺失 telemetry 被明确标记；
- 没有使用 evaluation split 选择阈值或样本；
- 没有发现足以支持“领先 10%”或 SOTA 的证据。

下一步只能是修复 `local_context/global_corpus` 协议和 telemetry。若后续 development 仍显示只影响少量样本、CI 跨 0 或成本收益不匹配，应停止继续堆补丁并报告 null result。
