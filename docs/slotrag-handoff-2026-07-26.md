# SlotRAG 实验交接（2026-07-26）

## Task

继续优化 `/data/mzb/SlotRAG` 的 SlotRAG 方法，完成可审计的指标、消融和 baseline 对比，并始终使实验工件、方法决策与主文档一致。不得伪造“领先 10%”、显著性或投稿就绪结论。

## State

- 工作区干净，当前提交为 `4b8c71c` (`docs(exp): record guard ablation and fixed baseline eval`)。
- v47 因子消融已完成：`runs/slotrag-grounding-retrieval-factorial-v3`。grounding-only primary `0.7180` vs plain `0.6930`，绝对 `+2.50pp`、相对 `+3.61%`；预注册多重校正后不显著。
- v47 机制审计已完成：`grounding-mechanism-audit`将 6 道非 tie 题固定为带 final/attempt/trace SHA 的索引。提交：`f2fd8b4`。
- 新方法 `slotrag-grounded-binding-guard` 已实现：防止 role-projected extraction 把已知 binding 值复制到未绑定输出，不含 QID/gold/dataset 特例。提交：`b63318e`。
- v48 已完成：`runs/slotrag-grounding-binding-guard-train-v1`，300/300 final、attempt、trace；297 `ok` + 3 个同题三方法对称的 retrieval-budget 终止；0 timeout/provider/retry；100/100 frozen plans 有效。gate=`analysis_ready_nonpublication`（train split）。
- v48 五数据集宏平均：plain `0.7030`，旧 grounding `0.7236`，binding guard `0.7330`。guard-plain=`+0.0300` (`+4.27%`), CI `[-0.0100,+0.0700]`；guard-old=`+0.00935`, CI `[-0.01065,+0.03500]`；两项 Holm p 均 `0.7343`，不显著。
- guard 仅触发 2/100 题：1 题不改变 exact；Hotpot `5a8efb615542997ba9cb3163` 将旧 grounding 的 `Pakistan Movement` (EM=0/F1=.5) 修正为 `Khilafat Movement` (EM/F1=1)。未观察到触发后 exact loss，但 n=2，只能定义为低频正确性保护。
- v48 关键工件 SHA：`summary.json=e773e916...f397`，`per_question.csv=4e1f2524...ba45`，`paired_analysis.json=0c5bfd39...968`，`gate.json=eaa4938d...fdab`。完整值在主文档 v48 节。
- 旧 adapted baseline 主表在 `runs/vldb2027-adapted-main-v1`：SlotRAG `0.6719`，IRCoT* `0.7485`，ReAct* `0.7328`，Hybrid* `0.7305`。这些是 `shared_provider_adapted` 本地适配器，`exact_upstream_execution_verified=false`，不能宣称复现或击败论文原方法。v48 train 与此旧 evaluation run 不能直接排名。
- v49 已预注册但尚未启动 provider 实验。配置：`configs/experiments/slotrag-binding-guard-fixed-main-eval-v1.yaml`；输出：`runs/slotrag-binding-guard-fixed-main-eval-v1`；只运行 guard，不重跑 baseline。
- v49 的 5×100 evaluation samples 已 prepare 和 audit，与旧 `main_comparison` SHA 逐一相同，与 v48 train 重叠为 0。`sample-audit.json` 已落盘。冻结计划来自 `runs/slotrag-final-candidate-v2/plans/imported_main`，五数据集各 100，missing=0。
- 全量测试最后结果：`245 passed, 1 skipped`。

## Key decisions

- 保留 binding guard 进入 evaluation，因为它修复了一个可解释的 binding-copy 错误，且不增加 retrieval；不把 v48 全部 `+3pp` 归因于它。
- DQR/always/unbound 不是当前默认；它们在之前 held-out 上成本明显上升且质量不稳定。
- v49 只用于固定样本 adapted 数值对照。该 500 题曾用于早期候选评估，baseline 又不是 exact upstream，所以不能写成全新 one-shot held-out 或投稿主表。
- 所有失败保留在 final/attempt 分母；不得换 seed、删除坏题、追加择优 retry 或运行中偷看均值。
- 实验结束必须同步更新 `docs/SlotRAG：面向 VLDB 2027 的轻量新型 RAG 方法.md` 和 `docs/VLDB2027-experiment-plan-v31.md`，并记录 run/config/commit/SHA/失败/统计边界。

## Gotchas

- 根目录有 `.codegraph/`。理解或定位代码前必须先用 `codegraph explore "..."`，再用 `rg`。用户特别要求的是 CodeGraph，不是 graphify。
- `.env` 仍把生成端点设为 Agnes，且 `SLOTRAG_MAX_CONCURRENCY=4`。交接前最后一次 doctor 因没有 QWEN36 运行时变量，检查到了 Agnes，不是 v49 允许的生成服务。这次 doctor 没有启动实验。
- 不要把 key 写入命令、交接文档或 trace。可在 `source .env` 后以 `QWEN36_API_KEY="$SLOTRAG_EMBEDDING_API_KEY"` 做运行时映射；两者在当前部署使用同一网关凭证。
- `QWEN36_BASE_URL` 应为 `http://10.200.37.71:8801/v1/chat/completions`，模型 `qwen3.6-27b`。自定义 config 会自动剔除 `/chat/completions` 后缀再由 client 拼接。
- 必须显式设 `SLOTRAG_TRACE_ENABLED=true` 与 `SLOTRAG_TRACE_INCLUDE_PAYLOADS=false`。provider 允许 30 RPM，实际上限 20 RPM；每服务 max concurrency 可设 64，v49 仅有 5 个 dataset-method cells，matrix workers 用 5。
- v49 stage 配置中同时列出 `slotrag` 和 guard，是因为 `frozen_plan_source` 必须位于 methods 列表。启动 matrix 时必须加 `--method slotrag-grounded-binding-guard`，才能不重跑 plain。gate 会根据 matrix-manifest jobs 只期待这 5 个 cell。
- 旧 baseline 主表全是 local controlled adapters，即使 v49 数字高也只能说“在 fixed shared-provider adapted 样本上”，不能说“超过 IRCoT/ReAct 原方法”。

## Next steps

1. 在不暴露凭证的前提下导出 v48 相同的运行环境：

   ```bash
   set -a
   source .env
   set +a
   export QWEN36_BASE_URL=http://10.200.37.71:8801/v1/chat/completions
   export QWEN36_MODEL=qwen3.6-27b
   export QWEN36_API_KEY="$SLOTRAG_EMBEDDING_API_KEY"
   export SLOTRAG_TRACE_ENABLED=true
   export SLOTRAG_TRACE_INCLUDE_PAYLOADS=false
   export SLOTRAG_PROVIDER_RPM=30
   export SLOTRAG_OPERATIONAL_RPM=20
   export SLOTRAG_MAX_CONCURRENCY=64
   export SLOTRAG_AGNES_PROVIDER_RPM=30
   export SLOTRAG_AGNES_OPERATIONAL_RPM=20
   export SLOTRAG_AGNES_MAX_CONCURRENCY=64
   export SLOTRAG_EMBEDDING_PROVIDER_RPM=30
   export SLOTRAG_EMBEDDING_OPERATIONAL_RPM=20
   export SLOTRAG_EMBEDDING_MAX_CONCURRENCY=64
   export SLOTRAG_RERANKER_PROVIDER_RPM=30
   export SLOTRAG_RERANKER_OPERATIONAL_RPM=20
   export SLOTRAG_RERANKER_MAX_CONCURRENCY=64
   ```

2. 在同一 shell 内运行 doctor，确认输出生成模型是 `qwen3.6-27b`、生成 base URL 是内网 Qwen `/v1`、trace=true、provider/operational RPM=30/20、max concurrency=64，三服务 HTTP 200。若仍显示 Agnes，禁止启动。
3. 确认工作区干净且 HEAD=`4b8c71c`，然后在同一 shell 启动：

   ```bash
   .venv/bin/python tools/run_benchmark_matrix.py binding_guard_fixed_main_eval \
     --suite configs/experiments/slotrag-binding-guard-fixed-main-eval-v1.yaml \
     --output-dir runs/slotrag-binding-guard-fixed-main-eval-v1 \
     --workers 5 \
     --method slotrag-grounded-binding-guard
   ```

4. 运行中只监控 items/attempts/traces 数量、status 分布、provider/timeout 错误和进程；不读取中途均值。完成目标是 500/500，不提前截断。
5. 完成后运行 `records-audit --require-trace`、`gate --require-trace`、`summarize`；保留 gate 对 adapted/exact-upstream 边界的原始判定。
6. 用 `tools/compare_fixed_baseline.py` 将 v49 `per_question.csv` 与 `runs/vldb2027-adapted-main-v1/summaries/main_comparison/per_question.csv` 按 question ID 配对，候选方法只选 guard。额外生成五数据集与宏平均的 SlotRAG/GraphRAG*/Hybrid*/IRCoT*/PlanRAG*/ReAct*/SRAG* 对照表，但明确标注 `* = local adapted adapter`。
7. 分析完整指标：primary、EM/F1/Accuracy/DROP EM/F1，evidence R/P/Hit@1/5/10、MRR、nDCG@10，retrieval/provider/embedding/reranker/LLM calls，tokens，wall P50/P95/P99，文档/段落访问，repair/grounding/guard trigger，failure/timeout/retry。
8. 核查 evaluation 中所有 `protected_anchor_rejections>0` 的题：比较 gold、旧 SlotRAG 预测、guard 预测、EM/F1，判定是 exact gain/loss/tie，不将 token-overlap 伪增益当作正确性。
9. 将最终数值、CI/p、工件 SHA、失败分母、机制案例和 go/no-go 决策同步到两份 docs，运行全量测试并提交。
10. 不论 v49 是否高于旧 adapted baseline，投稿级最终结论仍需全新、不重复的 evaluation/test 样本和 exact-upstream 可执行 baseline；无法完成时必须如实写为阻塞，不能用 local adapter 冒充。

## Suggested skills

- `results-analysis`：v49 完成后做全指标、配对 CI/p、失败分母和机制分析时使用。
- `tdd`：只在分析发现新的通用错误机制、需要修改方法时使用；先失败测试，再实现，并新建预注册 run。
- `academic-paper-reviewer` 或 `paper-self-review`：只在实验工件完整且结论边界写入 docs 后，审查是否真正达到 VLDB 实验标准。
