# SlotRAG 实验交接（更新至 2026-07-27，v53 已完成）

## Task

继续优化 `/data/mzb/SlotRAG` 的 SlotRAG 方法，完成可审计的指标、消融和 baseline 对比，并始终使实验工件、方法决策与主文档一致。不得伪造“领先 10%”、显著性或投稿就绪结论。

## State

- v49 分析工具和三份文档已更新；提交 hash 以交接时的 `git log -1` 为准。运行工件保持不可变，新增分析只写入 v49 的 summary 子目录。
- v47 因子消融已完成：`runs/slotrag-grounding-retrieval-factorial-v3`。grounding-only primary `0.7180` vs plain `0.6930`，绝对 `+2.50pp`、相对 `+3.61%`；预注册多重校正后不显著。
- v47 机制审计已完成：`grounding-mechanism-audit`将 6 道非 tie 题固定为带 final/attempt/trace SHA 的索引。提交：`f2fd8b4`。
- 新方法 `slotrag-grounded-binding-guard` 已实现：防止 role-projected extraction 把已知 binding 值复制到未绑定输出，不含 QID/gold/dataset 特例。提交：`b63318e`。
- v48 已完成：`runs/slotrag-grounding-binding-guard-train-v1`，300/300 final、attempt、trace；297 `ok` + 3 个同题三方法对称的 retrieval-budget 终止；0 timeout/provider/retry；100/100 frozen plans 有效。gate=`analysis_ready_nonpublication`（train split）。
- v48 五数据集宏平均：plain `0.7030`，旧 grounding `0.7236`，binding guard `0.7330`。guard-plain=`+0.0300` (`+4.27%`), CI `[-0.0100,+0.0700]`；guard-old=`+0.00935`, CI `[-0.01065,+0.03500]`；两项 Holm p 均 `0.7343`，不显著。
- guard 仅触发 2/100 题：1 题不改变 exact；Hotpot `5a8efb615542997ba9cb3163` 将旧 grounding 的 `Pakistan Movement` (EM=0/F1=.5) 修正为 `Khilafat Movement` (EM/F1=1)。未观察到触发后 exact loss，但 n=2，只能定义为低频正确性保护。
- v48 关键工件 SHA：`summary.json=e773e916...f397`，`per_question.csv=4e1f2524...ba45`，`paired_analysis.json=0c5bfd39...968`，`gate.json=eaa4938d...fdab`。完整值在主文档 v48 节。
- 旧 adapted baseline 主表在 `runs/vldb2027-adapted-main-v1`：SlotRAG `0.6719`，IRCoT* `0.7485`，ReAct* `0.7328`，Hybrid* `0.7305`。这些是 `shared_provider_adapted` 本地适配器，`exact_upstream_execution_verified=false`，不能宣称复现或击败论文原方法。v48 train 与此旧 evaluation run 不能直接排名。
- v49 已完成：配置 `configs/experiments/slotrag-binding-guard-fixed-main-eval-v1.yaml`，输出 `runs/slotrag-binding-guard-fixed-main-eval-v1`，只运行 guard，不重跑 baseline；500/500 final、attempt、trace，494 `ok`、6 `budget_exceeded`（HotpotQA 2、MuSiQue 4），0 timeout/provider/retry。
- v49 的 5×100 evaluation samples 已 prepare 和 audit，与旧 `main_comparison` SHA 逐一相同，与 v48 train 重叠为 0。`sample-audit.json` 已落盘。冻结计划来自 `runs/slotrag-final-candidate-v2/plans/imported_main`，五数据集各 100，missing=0。
- v49 primary guard=`0.6838417`，旧 SlotRAG*=`0.6719169`；guard-old=`+0.0119249`，95% CI `[-0.0067178,+0.0306060]`，sign-flip `p=0.2059`，七比较 Holm=`0.4524`。guard 低于 IRCoT*/Hybrid*/ReAct* `6.47/4.67/4.89pp`，高于 SRAG* `6.41pp`；所有 baseline 仍是 `shared_provider_adapted` local adapter，`exact_upstream_execution_verified=false`。
- v49 guard 触发审计：15/500 题、28 次拒绝（HotpotQA 5、MuSiQue 10），2 exact gain、0 exact loss、13 exact tie。完整 145 指标 paired artifacts 位于 `runs/slotrag-binding-guard-fixed-main-eval-v1/summaries/binding_guard_fixed_main_eval/fixed_main_analysis/`。
- v50 已完成：配置 `configs/experiments/slotrag-binding-guard-budget-train-v1.yaml`，输出 `runs/slotrag-binding-guard-budget-train-v1`，五数据集各 20 train 题，100/100 final、attempt、trace 全部 `ok`；100/100 imported plans 有效，0 timeout/provider/retry，gate=`analysis_ready_nonpublication`。
- v50 guard@12 primary=`0.7429571`，相对同题 v48 guard@6 配对 `+0.0100`，95% CI `[0.0000,+0.0300]`，sign-flip `p=1.0000`，胜/平/负=`1/99/0`；EM/F1 各 `-0.0100`。失败率从 `1/100` 降为 `0/100`，total tokens `+1.51%`、provider calls `+1.20%`，只据此保留 10/12 预算候选，不宣称质量显著提升。
- v50 全指标与 paired artifacts 位于 `runs/slotrag-binding-guard-budget-train-v1/summaries/budget_sensitivity_train/`，包含 145 指标、失败分母、CI/p、Holm 输入和 SHA；预算配对报告在 `fixed_budget_analysis/`。核心 `per_question.csv` SHA=`c7ab6f7a3f83453e483aea1f43e77212e7ddabd7a866e7a44f13e97d9bfc8655`，`paired_analysis.json` SHA=`b7a86fbf40a65ccb8d0c0b8e63d05f869225ebcff03d87be9b0c940ea72933be`。
- v51 已完成：`runs/slotrag-binding-guard-fixed-main-eval-v2`，500/500 final、attempt、trace；499 `ok`，HotpotQA 1 条 `failed/other`（`slot S3 has no join path`），0 timeout/provider/retry；500/500 imported plans 有效，sample 与 v49 SHA 相同、与 v48 train overlap=0。
- v51 primary=`0.6888553`，相对 v49 guard@4/4 `+0.0050136`，95% CI `[-0.0049578,+0.0161357]`，p=`0.3894`、Holm=`0.7787`，胜/平/负=`7/487/6`；六个 v49 budget failure 中五个转为 `ok`，一个转为 join-path failure。provider calls `+3.60%`、total tokens `+3.85%`，保留 10/12 预算但不宣称显著质量提升。
- v51 对 adapted SlotRAG*/GraphRAG*/PlanRAG*/Hybrid*/ReAct*/IRCoT*/SRAG* 的 primary 差值依次为 `+0.0169/+0.0018/-0.0249/-0.0417/-0.0439/-0.0597/+0.0691`；Holm 后只保留对 IRCoT* 的劣势与对 SRAG* 的优势。完整 145 指标和 6,006 条 contrasts 在 v51 `fixed_main_analysis/`，baseline exact-upstream 仍为 false。
- 全量测试在加入离线分析工具后为 `247 passed, 1 skipped`，包含 `tests/test_fixed_main_analysis.py`；`compileall` 与 `git diff --check` 通过。
- v52 方法候选已实现：`ExecutionOptions.frontier_safe_selection` 将下一槽位限制在已物化子图
  的显式 `JoinSpec` frontier；新方法 key 为 `slotrag-grounded-frontier-guard`，历史方法默认
  关闭。三项审计指标为 `frontier_guard_checks/interventions/candidates_pruned`。
- 五槽星形回归中旧策略复现 `S2 -> S3` join-path failure，新策略完成
  `S2 -> S1 -> S3 -> S4 -> S5`；`tests/test_execution.py` 99/99、
  `tests/test_benchmark_methods.py` 36/36 通过。该修复不含 QID/dataset/gold 特例。
- manifest-based 离线扫描覆盖 4,841 个 plan 文件，得到 402 个唯一 train plan variants，
  static frontier risk=0；因此先做与 v50 同题同计划的运行时零回归门，不从拓扑择优抽题。
- v52 已完成：`runs/slotrag-frontier-guard-train-v1`，100/100 final/attempt/trace 且全部 `ok`，
  100/100 imported plans 有效，sample 与 v50 完全一致。checks/interventions/pruned 总和为
  `48/2/2`；与 v50 binding guard 的 148 指标配对 primary `Δ=0`、CI `[0,0]`、p=`1.0`，
  EM/F1 各 `+0.01`（CI `[0,+0.03]`），干预题 2/2 primary tie，无 gain/loss。gate 为
  `analysis_ready_nonpublication`，不晋级默认方法。跨 run 工件在
  `runs/slotrag-frontier-guard-train-v1/summaries/frontier_guard_train/frontier_vs_binding_guard/`。
- v53 已完成：`runs/slotrag-frontier-guard-train-v2`，五数据集各 100 train、两个 guard 方法，
  1000/1000 final/attempt/trace，records audit 完整；binding guard 999 `ok` + 1 个 MuSiQue
  `slot S1 has no join path`，frontier guard 同题为 `ok`，无 timeout/provider/retry。共享 frozen
  plans 500/500 有效，sample 与 v48/v50 overlap=0，gate=`analysis_ready_nonpublication`。
- v53 宏平均 binding/frontier primary=`0.746887/0.752679`、EM=`0.5160/0.5220`、
  F1=`0.586086/0.593828`、evidence R@10=`0.86625/0.86625`、provider calls=`5.222/5.238`、
  total tokens=`2466.934/2478.264`、wall=`40358.24/40063.48 ms`。Paired primary
  Δ=`+0.005791`、CI=`[-0.006586,+0.018424]`、p=`0.3746`、胜/平/负=`7/487/6`；EM/F1
  Δ=`+0.0060/+0.007742`，均未显著。frontier 触发 7 题，checks/interventions/pruned=`18/9/11`，
  gain/tie/loss=`1/6/0`，无干预损失。结论是低成本安全模块，不是 10% 领先或投稿主表证据。
- v53 关键工件：config SHA=`fe4843b5f598a6023ce70cb3fab2ec9fe5877e45a165f19ffc01097945954590`；
  `summary.json=6ae729912cb2f1643b2845ea6ebad1e04f96385097b0859ad7b50d2a10415ec7`；
  `per_question.csv=2f0748042697b1a9d916c16d228ecabdb939ae53935bc801e531f39b127d43ed`；
  `paired_analysis.json=f55c3630da8c021a98f5bb1d767f9d3ae4a39dc48263cb63eeaeb510e51f1b6b`；
  `frontier_selection_audit.json=25d838087477c6f70ed12a55e4921017a4bf31aecc85cf55d642853ab6678f5e`。

## Key decisions

- 保留 binding guard 进入 evaluation，因为它修复了一个可解释的 binding-copy 错误，且不增加 retrieval；不把 v48 全部 `+3pp` 归因于它。
- DQR/always/unbound 不是当前默认；它们在之前 held-out 上成本明显上升且质量不稳定。
- v49 只用于固定样本 adapted 数值对照。该 500 题曾用于早期候选评估，baseline 又不是 exact upstream，所以不能写成全新 one-shot held-out 或投稿主表；不得根据这批题调参后回填。
- 所有失败保留在 final/attempt 分母；不得换 seed、删除坏题、追加择优 retry 或运行中偷看均值。
- 实验结束必须同步更新 `docs/SlotRAG：面向 VLDB 2027 的轻量新型 RAG 方法.md` 和 `docs/VLDB2027-experiment-plan-v31.md`，并记录 run/config/commit/SHA/失败/统计边界。

## Gotchas

- 根目录有 `.codegraph/`。理解或定位代码前必须先用 `codegraph explore "..."`，再用 `rg`。用户特别要求的是 CodeGraph，不是 graphify。
- `.env` 默认仍把生成端点设为 Agnes，且 `SLOTRAG_MAX_CONCURRENCY=4`；但 v49 实际运行的 `services/doctor-before.json` 已记录 Qwen3.6-27B 内网 `/v1`、三服务 HTTP 200、trace=true、30/20 RPM 和 64 并发。后续不要从 `.env` 默认值推断 v49 provider。
- 不要把 key 写入命令、交接文档或 trace。可在 `source .env` 后以 `QWEN36_API_KEY="$SLOTRAG_EMBEDDING_API_KEY"` 做运行时映射；两者在当前部署使用同一网关凭证。
- `QWEN36_BASE_URL` 应为 `http://10.200.37.71:8801/v1/chat/completions`，模型 `qwen3.6-27b`。自定义 config 会自动剔除 `/chat/completions` 后缀再由 client 拼接。
- 必须显式设 `SLOTRAG_TRACE_ENABLED=true` 与 `SLOTRAG_TRACE_INCLUDE_PAYLOADS=false`。provider 允许 30 RPM，实际上限 20 RPM；每服务 max concurrency 可设 64，v49 仅有 5 个 dataset-method cells，matrix workers 用 5。
- v49 stage 配置中同时列出 `slotrag` 和 guard，是因为 `frozen_plan_source` 必须位于 methods 列表；历史命令已完成，不要重复启动 provider。gate 的 `publication_ready` 只表示本方法记录完整，baseline comparison 仍受 exact-upstream 阻塞。
- 旧 baseline 主表全是 local controlled adapters，即使 v49 数字高也只能说“在 fixed shared-provider adapted 样本上”，不能说“超过 IRCoT/ReAct 原方法”。

## Next steps

1. 不要重复启动 v49 或 v50 provider。v50 的 `records-audit.json`、`gate.json`、
   `manifest.json`、`summaries/budget_sensitivity_train/summary.json` 和
   `fixed_budget_analysis/report.json` 已完成并记录 SHA-256；复核时保持这些工件不可变。
2. 不要重复启动 v51 provider。先复核 v51 的 `sample-audit.json`、`records-audit.json`、
   `gate.json`、`summary.json` 和 `fixed_main_analysis/report.json`；核心
   `per_question.csv` SHA=`557a49fb599bfbe312bd0613b50aabd107c4a02784be55e57b3661ad16039049`，
   `paired_analysis.json` SHA=`2b9bddbfc065ea3e0c790684ebcd879108eedcc629f8d1b90c55b24f78bdcda7`。
3. 复跑 v49 离线分析时使用：

   ```bash
   .venv/bin/python tools/analyze_fixed_main.py \
     --candidate-per-question runs/slotrag-binding-guard-fixed-main-eval-v1/summaries/binding_guard_fixed_main_eval/per_question.csv \
     --baseline-per-question runs/vldb2027-adapted-main-v1/summaries/main_comparison/per_question.csv \
     --output-dir runs/slotrag-binding-guard-fixed-main-eval-v1/summaries/binding_guard_fixed_main_eval/fixed_main_analysis \
     --candidate-method slotrag-grounded-binding-guard \
     --baseline-method slotrag --baseline-method graphrag --baseline-method hybrid \
     --baseline-method ircot --baseline-method planrag --baseline-method react --baseline-method srag \
     --candidate-items-dir runs/slotrag-binding-guard-fixed-main-eval-v1/items/binding_guard_fixed_main_eval \
     --iterations 10000 --seed 27182
   ```

   该工具只读取 immutable CSV/items，输出 145 指标的逐题 paired contrasts、整体/数据集
   分层 CI/p、Holm primary family 和 binding-guard 触发审计；不调用任何服务。
4. v53 已完成，勿重复启动 provider；复核时只读取 immutable run 工件，保留 148 指标 paired
   对比、frontier/protected-anchor audit 和失败分母。不得把 v51 已见 evaluation 题纳入质量增益。
5. 新候选必须保留 `plain`、旧 grounding、guard 的 frozen-plan paired 对照，并报告
   质量、evidence、calls/tokens、wall P50/P95/P99、失败分母和机制计数。只有不重叠的
   held-out/test 样本才能进入投稿表。
6. 继续推进 exact-upstream baseline 审计：IRCoT 需要其 processed data/Elasticsearch
   retriever/official config，PlanRAG 只能在其 DQA 场景报告，GraphRAG 不能把本地 QA
   adapter 标成官方执行。缺少 exact 入口时，保留 `publication_claim_allowed=false`。
7. 文档同步顺序固定为：运行/分析完成 → 更新主方法文档和实验计划 → 更新本交接文档 →
   全量测试、`compileall`、`git diff --check` → 提交。任何数字变化必须同时更新三处记录。

## Suggested skills

- `results-analysis`：v49 完成后做全指标、配对 CI/p、失败分母和机制分析时使用。
- `tdd`：只在分析发现新的通用错误机制、需要修改方法时使用；先失败测试，再实现，并新建预注册 run。
- `academic-paper-reviewer` 或 `paper-self-review`：只在实验工件完整且结论边界写入 docs 后，审查是否真正达到 VLDB 实验标准。

## v54 research reset 状态（2026-07-27）

本轮完成了不改方法的离线审计。新增 `tools/analyze_slotrag_headroom.py` 和
`tests/test_headroom_analysis.py`，报告为 `docs/optimization-audit-v54.md`，原始审计汇总位于
`runs/slotrag-frontier-guard-train-v2/summaries/optimization_audit_v54/`。审计读取
frontier-guard-train-v2 与 answer-contract-train-v1 的 immutable records，共 1,200 条，provider
调用为 0。

审计结论：主要可利用空间在结构化抽取/答案生成及证据协议，而不是继续增加稀疏 guard；最近配对结果 tie rate 为 97%，frontier guard 覆盖率为 1.08%。现有 local-context、per-question retriever、adapted baseline 协议不足以支撑论文级检索结论。planner oracle 因历史 trace 缺少可比字段而为 N/A。v54 只完成 audit gate，尚未实现 `slotrag-qo`，也未运行 global-corpus 或 2×2 ablation。

本轮验证命令：`PYTHONPATH=src:. pytest -q`（`253 passed, 1 skipped`）、
`python -m compileall -q src benchmark tools`、`git diff --check`。按用户要求，完成 v54 后暂停；下一轮从 shared-corpus benchmark protocol 开始，不能把本轮离线 oracle 估计当作新方法增益。

## v55 global-corpus protocol 状态（2026-07-27）

已完成协议层第一版，新增：

* `src/slotrag/benchmarking/corpus.py`：`SharedCorpusIndex`、`CorpusManifest`，跨完整 split 聚合 available passages。
* `StageConfig.retrieval_protocol`：显式区分 `local_context` 与 `global_corpus`；runner schema 升为 29。
* 每条新记录的 `evidence_inventory`：available/gold/retrieved 三类 evidence ID 分离；global run manifest 列出 corpus manifest。
* `configs/experiments/global-corpus-protocol-smoke-v55.yaml` 与 `tools/run_global_corpus_smoke.py`。

v55 provider-free smoke 工件：
`runs/slotrag-global-corpus-protocol-smoke-v55/`。3 个 source questions、3 个 documents、3 个
chunks，1 query，`index_bytes=52`，构建约 `379.24 ms`，查询约 `0.80 ms`，provider calls=0。

协议修复：StrategyQA facts 不再作为 available corpus，标记 `gold_facts_only`；DROP 新生成
`operation_type_source=question_heuristic`，旧记录来源为 `legacy_unknown`。本轮全量验证为
`258 passed, 1 skipped`，compileall 和 diff check 通过。尚未开始真实 provider 的 local/global
质量实验，尚未实现 `slotrag-qo`。

下一轮执行顺序：真实数据小规模 local/global smoke → records/gate 审计 → 冻结协议 → LogicalPlan/
PhysicalPlan 数据结构和编译器验证。完成下一次版本实验后继续停下来汇报，不能把 v55 smoke 当作
质量提升或投稿主结果。

## v56 real protocol smoke 状态（2026-07-27）

doctor：Agnes、embedding、reranker 均 HTTP 200；运行参数为 provider 30 RPM、实际 20 RPM、并发
64、trace 开启且 payload 脱敏。

local run：`runs/slotrag-retrieval-local-smoke-v56/`，HotpotQA evaluation 2 题，adapted
`hybrid` 2/2 成功、0 retry/timeout；primary/F1=`0.395833`、EM=`0`、evidence recall=`1.0`，
平均 wall=`5545.65 ms`、index build=`2252.49 ms`、total tokens=`2435.5`。records-audit
完整，gate `analysis_ready=true`，但 smoke 不具备 publication scope。

global run：`runs/slotrag-retrieval-global-smoke-v56/`，目标是完整 HotpotQA evaluation split
共享 corpus。只读计数得到 7,405 questions、73,700 passages、73,911 chunks、约 2,310 embedding
batches；20 RPM 理论下界约 115.5 分钟，超过成本门禁。进程在 final corpus/item 前中止，
`abort.json` 记录 `aborted_cost_gate`，records-audit 为 0 final、analysis_ready=false。没有
global 质量结果，不得计算 local/global 差异。

下一轮从“离线/持久化 shared index + immutable vector manifest”开始，再实现 LogicalPlan/
PhysicalPlan 与 `slotrag-qo`；不要为了完成 smoke 把 full split 改回 per-question 或删除跨题
distractors。v56 已完成并暂停。
