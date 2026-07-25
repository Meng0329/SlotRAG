# VLDB 2027 实验执行计划 v31

## 目标

建立可投稿、可复核、可重新分析的实验闭环。任何结果只有在 baseline 入口、数据 split、模型/提示词、答案解析、失败分母和原始调用记录都可追溯时，才允许进入论文主表。现有 `main_comparison` 和 `rescored-v2` 只作为本地适配器诊断，不进入投稿结论。

截至 2026-07-24，`runs/vldb2027-adapted-main-v1` 已完成五数据集、七方法、每 cell 100
题的 shared-provider adapted 主对比（3500 final / 3507 attempts / 3507 traces），并
通过 records audit；gate 仅在显式 `--allow-adapted-protocol` 下返回
`publication_ready_adapted_protocol`。该 run 的 `exact_upstream_execution_verified=false`，
所以它可以进入单独的 adapted 结果表和方法诊断，不能作为击败 exact baseline 的投稿主表。
当前主指标并未显示 SlotRAG 全面领先；后续消融必须使用不重叠 evaluation 题目，并把
执行因素、组件因素、失败分母和 paired bootstrap 结果同步回本文档。

## 当前方法调优状态（2026-07-25）

外部 baseline 的 adapted 数值已冻结，不再为了调优重复执行。SlotRAG 内部先在 train 做
方法筛选：`runs/slotrag-method-tune-v1`（11 个模块变体、550 final）和
`runs/slotrag-method-tune-v2`（7 个候选、350 final）均保留 manifest、trace、immutable
attempt、records audit、gate 和全指标 CSV。v2 的双查询检索候选在 train primary 宏平均上为
`0.7015`，高于 plain `0.5811`，但检索调用约翻倍且有预算失败；该结果只能用于选择 held-out
候选，不能作为投稿优势声明。

最终候选采用双协议记录：严格 4 steps / 4 retrieval calls 的
`runs/slotrag-final-candidate-v1` 因重新编译计划导致高预算失败而被主动停止，目录含
`INCOMPLETE_FOR_SUBMISSION.txt` 和 `scheduler-stop.json`，不得进入任何表。可解释的执行因素
验证改为 `runs/slotrag-final-candidate-replay-v1`：从适配主实验 SlotRAG final record 导出 500
个校验过的 frozen plans（`input_sha256`/`plan_sha256`/来源状态），在完全相同的 500 个问题上
比较 plain、DQR 和 grounded-DQR。replay 使用 10 steps / 12 retrieval calls，仅用于同计划模块
因果与成本比较；它与原 4/4 adapted 主表分栏，完成后必须重新运行 records audit、gate、完整
指标、paired bootstrap 和失败报告，才允许文档写入任何质量结论。

### v36 replay 结果与决策（2026-07-25）

`runs/slotrag-final-candidate-replay-v1` 已完成 1500/1500 final、1500/1500 attempts、
1500/1500 trace，最终状态为 1420 `ok`、77 `budget_exceeded`、3 `failed`。500 个 imported
plans 有效，1423 条记录发生 replay，计划 hash/provenance/variant 审计全为 0 错误；严格
records audit 为 `complete=true`，gate 为 `publication_ready`。9 条在首次 provider 事件前超时
的记录使用 `tools/backfill_zero_event_traces.py` 写入 `event_count=0` 的空 trace，并保留原始
timeout 状态和失败分母。`src/slotrag/tracing.py` 同步修复为进入 trace 上下文即创建文件，后续
零事件超时不再被误判为缺 trace。

Held-out replay 的 primary 宏平均为 plain `0.6545`、DQR `0.6468`、Grounded-DQR `0.6610`；
Grounded-DQR 仅比 plain 高 `0.0064`（约 0.98%），DQR 低 1.18%，而 retrieval calls 从 1.538
增至 2.712/2.804、wall latency 从 60.22 s 增至约 105 s。Evidence Recall/MRR/nDCG 的宏平均
为 plain `0.7550/0.9239/0.7712`、DQR `0.7438/0.8960/0.7686`、Grounded-DQR
`0.7788/0.9285/0.7995`。逐 dataset paired bootstrap 经 Holm 校正均不显著；与冻结 adapted
主实验 SlotRAG 的 500 题宏差值为 plain `-0.0174`、DQR `-0.0251`、Grounded-DQR `-0.0110`，
不能写成外部 baseline 优势。完整指标和失败分类以 replay run 的 `summary.json`、CSV、trace、
fixed-baseline comparison 为准。

决策：Grounded-DQR 暂保留为候选消融，不设为默认；下一轮只围绕失败率、question timeout、双查询
wall latency 和 MuSiQue/StrategyQA 退化做受控优化。任何新变体先在 train/dev 的不重叠题目上筛选，
通过相同 frozen-plan paired gate 后才能进入下一次 held-out；不通过时保留数据和日志，但不调整数值、
不删除失败、不把 adapted 结果升级为 exact upstream baseline 结论。

### v37 自适应双查询配对 replay（2026-07-25）

`runs/slotrag-grounded-adaptive-replay-v1` 因启动时漏传 `QWEN36_API_KEY` 导致 Qwen3.6 HTTP 401，已
写入 `INCOMPLETE_FOR_SUBMISSION`，其部分记录不进入统计。修正密钥映射后，v2 使用与 v36 相同的
500 个冻结计划、相同问题样本和 10 steps / 12 retrieval calls 预算，配对运行 plain 与
`slotrag-grounded-adaptive-dual-query-retrieval`。v2 的 1000/1000 final、attempt、trace 均完整，
records audit 缺失项为 0；状态为 991 `ok`、7 `budget_exceeded`、2 `failed`。500 个 imported snapshots
有效，993 条记录完成 replay，计划 hash/provenance/variant 错误全为 0。gate 为 `publication_ready`，
但 `exact_upstream_execution_verified=false`，只能作为方法内部 controlled adapted replay。

| 方法 | primary | EM | F1 | Evidence Recall/MRR/nDCG | OK/500 | retrieval calls | provider calls | wall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| plain SlotRAG | 0.6656 | 0.3300 | 0.4740 | 0.7788/0.9489/0.7938 | 495 | 1.564 | 5.110 | 46.77 s |
| Grounded adaptive DQR | **0.7012** | **0.3500** | **0.4988** | **0.8388/0.9735/0.8516** | 496 | 2.514 | 6.936 | 59.96 s |

候选 primary 相对提升 `+0.0357`（`+5.36%`），五个数据集方向均为正；但逐数据集 paired bootstrap
的 95% CI 均跨 0，Holm 校正后的 p 值为 `0.487/1.000/0.6876/1.000/0.6408`，不能声称显著或
“远超 10%”。代价为 retrieval calls `+60.7%`、provider calls `+35.7%`、wall `+28.2%`，所以
Grounded adaptive DQR 仍是候选消融而非默认方法。下一轮门槛是：在不重叠 train/dev 上做 evidence-
confidence 门控、查询扩展缓存和长尾 timeout 控制；任何改动都要复用相同 frozen-plan paired gate，
并同时报告质量、证据、成本、延迟、失败分母和 Holm 校正结果。完整 CSV/JSON/trace 在
`runs/slotrag-grounded-adaptive-replay-v2/summaries/adaptive_candidate_replay/`。

### v38 自适应双查询 v4 train 筛选（2026-07-25）

`configs/experiments/slotrag-method-tuning-v4.yaml` 在 train split 运行 5 个方法 × 5 个数据集 × 10 题，
共 250 final/attempt。`runs/slotrag-method-tune-v4` records audit 为 `complete=true`，状态 231 `ok`、
19 `budget_exceeded`，trace 完整。宏平均如下：plain SlotRAG primary `0.6694`、DQR `0.6794`、adaptive DQR
`0.6094`、grounded DQR `0.6394`、grounded adaptive DQR `0.6230`。DQR 相对 plain 仅约 `+1.49%`，但
retrieval/provider/wall 增加；adaptive 变体在 HotpotQA/MuSiQue 失败较多。逐题 bootstrap Holm 校正均未显著，
该轮只能用于训练筛选，不能进入投稿主表或外部 baseline 结论。完整 summary/CSV/trace 在
`runs/slotrag-method-tune-v4/summaries/method_tune/`。

### v39 置信度门控双查询 train 筛选（2026-07-25）

新增门控：先执行 slot-only 检索，首条重排分数达到阈值时跳过原问题扩展，否则执行第二路并做 RRF；
`dual_query_confidence_skips` 作为独立成本指标写入 RunMetrics。第一次 v5 运行继承 `trace.enabled=false`，
已标记 `runs/slotrag-method-tune-v5/INCOMPLETE_FOR_SUBMISSION.txt`，不回填伪 trace。显式开启 trace 后在
`runs/slotrag-method-tune-v5-traced` 重跑同一 250 条 train 矩阵，records audit/gate 均通过，236 `ok`、14
`budget_exceeded`。

| 方法 | primary | EM | F1 | Evidence Recall/MRR/nDCG | OK/50 | retrieval | expansion/skip/conf-skip | tokens | provider | wall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SlotRAG | 0.6612 | 0.4800 | 0.5413 | 0.7875/0.8500/0.7962 | 46 | 1.360 | 0/0/0 | 3072.0 | 5.620 | 103.38 s |
| gated DQR 0.5 | **0.7479** | **0.5600** | **0.6080** | **0.8625/0.9500/0.8808** | 48 | 1.660 | 0.36/0/0.94 | 3232.4 | 6.160 | 103.49 s |
| gated DQR 0.75 | 0.6879 | 0.5000 | 0.5480 | 0.8625/0.9500/0.8768 | 46 | 1.600 | 0.38/0/0.84 | 2903.4 | 6.360 | 112.33 s |
| grounded adaptive gated 0.5 | 0.7212 | 0.5200 | 0.5813 | 0.8125/0.9000/0.8268 | 47 | 1.700 | 0.30/0.46/0.64 | 3321.5 | 6.380 | 115.26 s |
| grounded adaptive gated 0.75 | **0.7512** | 0.5400 | **0.6113** | **0.8625/0.9500/0.8728** | 49 | 1.740 | 0.28/0.48/0.70 | 3947.3 | 6.340 | 107.41 s |

质量/成本折中暂选择 `gated DQR 0.5` 作为下一次候选；相对本轮 plain primary `+13.1%` 只是 train
筛选结果，Holm 校正未显著。下一步必须在新、不重叠 held-out 题目上复现，沿用 `--require-trace`、immutable
attempt、完整失败分母和 paired bootstrap；若质量优势或成本节省不稳定，默认回退 plain SlotRAG。该轮
所有产物在 `runs/slotrag-method-tune-v5-traced/summaries/method_tune/`。

### v40 race-free held-out 门控复验（2026-07-25）

`runs/slotrag-confidence-gate-replay-v1` 标记为不可投稿诊断：并发冻结计划创建竞态导致 6 个问题的 `unknown_snapshot_hash_count=6`、`inconsistent_pair_count=6`。代码提交 `2f398c2` 在快照存在性检查、编译、写入之间加入跨进程锁，`400e3ba` 将冻结计划哈希异常加入 gate 阻断条件；v1 原始 attempt/trace 保留，禁止回填或覆盖。

干净复验使用 `configs/experiments/slotrag-confidence-gate-replay-v2.yaml` 与同 SHA 的不重叠 evaluation 样本，冻结计划从 v1 只读导入，1000 条 final/attempt/trace 全部完整。结果：995 `ok`、5 `budget_exceeded`；500/500 导入快照有效，`unknown_snapshot_hash=0`、`inconsistent_pair=0`、`plan_hash_mismatch=0`；records audit 和 gate 均为 ready。宏平均 plain/gated primary 为 `0.6382/0.6415`（+0.52%），但 EM `0.2940/0.2840`、F1 `0.4463/0.4398`，retrieval/provider/wall 分别 `+24.6%/+15.9%/+16.0%`；Holm 校正的五个 paired p 值全部为 `1.0`。这只能作为方法内部的 held-out adapted comparison，不能作为 exact upstream baseline 结果或显著优势。

因此 `gated DQR 0.5` 撤回默认，plain SlotRAG 暂为默认。下一阶段先在 train/dev 做选择性双查询优化：按数据集/问题类型校准门控阈值；扩展后计算证据支持置信度，支持度下降则回退 slot-only 结果；设置每题额外检索上限并记录触发/回退/成本 telemetry。只有新、不重叠 held-out 复验在质量和成本上同时通过，才允许晋级主方法；所有结果继续写入本节和方法文档，禁止手工调整数值。

### v41 selective guard train 筛选（2026-07-25）

新增 `slotrag-confidence-guarded-dual-query-0p5`，与 plain、`slotrag-confidence-gated-dual-query-0p5` 在 `configs/experiments/slotrag-selective-guard-train-v1.yaml` 的同题同计划协议下运行：五个数据集各 20 题，300 条 final/attempt/trace 全部落盘，`291 ok + 9 budget_exceeded`，records/trace audit 完整。100 个冻结计划快照全部有效，293 条 replay 的计划哈希和 provenance 审计全为 0 异常；完整产物在 `runs/slotrag-selective-guard-train-v1/summaries/method_tune/`。

训练宏平均 primary 为 plain `0.6930`、gated `0.7042`、guarded `0.6995`；相对 plain 分别 `+1.62%`、`+0.95%`，但 gated/guarded 的 EM/F1 均下降，Holm 校正的逐数据集 paired p 值全部为 `1.0`。gated 的 retrieval/provider/wall 成本为 `+20.4%/+14.9%/+31.3%`，guarded 为 `+15.1%/+14.9%/+13.9%`；total tokens 分别 `-14.0%/-17.7%`。三者 evidence Recall/MRR/nDCG@10 宏平均均为 `0.8313/1.0000/0.8635`，且 guard fallback 触发数为 0，故没有证据证明新模块贡献。

选择结论：plain 仍是默认；gated/guarded 仅作消融，不得写成外部 baseline 或显著优势。下一轮只做 guard 触发率、证据支持置信度校准与相关性诊断；若继续为 0 或不改善质量/成本，则删除 guard 复杂度。不得根据训练差值修改 held-out 结果，任何晋级必须经过新的不重叠 frozen-plan paired evaluation。

### v42 guard trigger telemetry 诊断（2026-07-25）

提交 `3c48c52` 增加 `dual_query_guard_checks`，并新增 overlap-tolerant relaxed guard。75 条 train diagnostic（每数据集 5 题、三方法）final/attempt/trace 完整，`records audit` 通过；25 个冻结计划快照、75 条 replay 均无哈希/provenance 异常。strict/relaxed 各有 9 次 guard check，但 fallback 均为 0；relaxed 的宏 primary=`0.6144`，与 plain 相同，EM/F1 更低，不能证明模块贡献。

结论：relaxed guard 不晋级；strict guard 仅保留为安全回退 telemetry，不写成质量提升。下一轮测试 confidence gate + `dual_query_unbound_only`，专门验证多槽位计划的重复扩展成本与质量变化。

### v43 unbound-only confidence gate 筛选（2026-07-25）

新 seed 的 train 筛选使用 `configs/experiments/slotrag-unbound-gate-train-v1.yaml`：五个数据集各 10 题，plain、gated DQR 0.5、unbound-only gated 共 150 条 final/attempt/trace，`147 ok + 3 budget_exceeded`；50 个 frozen-plan 快照有效，147 条 replay 无哈希/provenance 异常。宏 primary 为 `0.7328/0.6893/0.7043`，EM/F1 为 `0.5600/0.5928`、`0.5200/0.5493`、`0.5200/0.5643`；unbound-only 的 retrieval/provider/wall 为 `1.680/5.360/67.04s`，低于原 gated 的 `1.840/5.740/79.69s`，但仍高于 plain 成本且质量未恢复。Holm 校正 p 值全部为 `1.0`。

选择结论：unbound-only 只保留为成本消融，plain 仍是默认；下一轮停止扩展双查询变体，转向 plain 主路径的 evidence recall、答案稳定性和失败预算优化。任何主方法晋级仍需新不重叠 evaluation 的 frozen-plan paired 复验。

### v44 grounded-adaptive 冻结计划确认（2026-07-26）

`configs/experiments/slotrag-grounded-adaptive-frozen-train-v1.yaml` 在 v41 的五数据集各 20 条 train
问题上，对 plain、grounded-adaptive DQR、0.5 gate 和 0.75 gate 做共享 frozen-plan 的四路比较。
400 final/attempt/trace 完整，`385 ok + 15 budget_exceeded`；100/100 imported snapshots 有效，
所有 provenance/hash/pair/variant 异常为 0，records audit 和 own-method gate 通过。

宏 primary 为 `0.6533/0.7330/0.6730/0.7080`（按 plain/full/0.5/0.75 排列）；full 相对
plain 为 `+12.20%`，EM/F1 为 `+0.0500/+0.0612`，证据 Recall/MRR/nDCG@10 为
`+0.0813/+0.0500/+0.0787`，但 retrieval/provider/wall 增加 `69.0%/39.6%/4.6%`。full 的
100 个同题比较为 11 win / 87 tie / 2 loss；逐数据集 Holm 校正均未显著。DROP primary 下降
`0.0500`，不能声称全数据集一致领先。

该结果必须与 v37 的独立 evaluation 一起解释：v37 同一 full candidate 仅相对提升 `5.36%`，
且五数据集 CI 均跨 0、成本显著增加。因此不晋级默认，不再搜索更多 confidence threshold。下一阶段
是预先指定的 2×3 因子消融：`grounding {off,on} × retrieval {slot-only,always-DQR,
unbound-only-DQR}`；继续使用 v44 的 100 个 train 问题和只读计划，报告主效应、交互、逐题
bootstrap、Holm 校正、失败分母和完整成本。只有先定位正贡献模块，才允许设计下一版方法。

## 门禁与顺序

### 1. 上游基线审计

- IRCoT：固定 `baseline/ircot` commit，使用其 `processed_data`、官方 config、Elasticsearch retriever 和 `reproduce.sh` 流程；只在它公开支持的 HotpotQA、2WikiMultiHopQA、MuSiQue、IIRC 上报告。
- PlanRAG：固定 `baseline/PlanRAG` commit，按其原始 DQA locating/building 场景运行；不把 DQA 分数与五个 QA 数据集混成同一主表。
- GraphRAG：固定 `baseline/graph_rag` commit；若用当前 QA 记录构建索引，必须标为“GraphRAG adapted protocol”，不能标 exact reproduction。
- Hybrid/ReAct/SRAG：当前目录只有说明性 README，若保留，只能标为 repository-local diagnostic adapter；主表优先替换为有可执行上游代码和公开评测协议的 baseline。
- 每个方法生成 `baseline-audit.json`、commit、入口 SHA-256、依赖锁定、数据转换脚本和可运行命令；缺失任何一项就停在审计阶段。
- 当上游入口无法映射到统一 QA 集时，矩阵必须额外生成 `adapter-audit.json`。该文件只能把结果归入 `shared_provider_adapted` / `adapted_protocol_only`，不能把 `exact_upstream_execution_verified` 置为 true；投稿 gate 需要显式 `--allow-adapted-protocol` 才允许生成适配协议表。

当前 IRCoT 前置状态记录在 `runs/ircot-upstream-preflight-v1.json`：processed data 和 official evaluation 已固定，但 raw Wikipedia corpus、retriever/LLM server 和 Completion API 兼容性仍未通过；该报告的 `ready_for_exact_execution=false` 是正式阻塞，不得用本地方法替代。

### 2. 数据与 split 冻结

- 记录公开数据集来源、下载日期、文件 SHA-256、原始 split、规范化脚本版本和题目 ID 集合。
- 调参只能使用 train/dev；最终主表使用预注册且不重复的 test/evaluation ID。不得因服务失败或结果不理想重新抽样。
- 主对比优先覆盖官方完整 evaluation/test split；若资源不足，必须在 provider 调用前按统计功效预注册样本量、分层规则和停止条件。
- 所有方法接收同一题目 ID、同一 passage 范围和同一答案评分协议；检索指标只在有 gold evidence 的数据集报告，缺失写 `N/A`。

### 3. 统一答案与指标协议

- 原始输出永远保存；评分先移除 `<think>...</think>`，取最后答案标签或最后 `</think>` 后缀，记录 `prediction_scored` 和解析版本。
- 报告 EM、token F1、StrategyQA Accuracy、DROP EM/F1；同时报告 evidence Recall/MRR/R@1/5/10、P@1/5/10、nDCG@10。
- 报告 LLM/provider/embedding/reranker calls、prompt/completion/total tokens、在线 wall latency P50/P95/P99、索引成本、文档/段落访问、计划 slot/join/operator、重规划、绑定、结构失败、repair、grounding rejection、timeout、retry 和最终/attempt 失败分母。
- 质量比较以题目配对 bootstrap 95% CI、精确 sign/McNemar 描述检验和 Holm 校正为准；不使用跨任务宏平均宣称质量领先。

### 4. 运行阶段

1. `audit`：零 provider 调用，检查数据、baseline、依赖、配置和服务健康。
2. `smoke`：每个真实可运行 cell 10–20 题，验证入口、输出 schema、答案抽取、trace、限流、断点续跑和失败分母。
3. `main`：冻结后跑完整 evaluation/test split；每个 dataset-method cell 独立日志和目录，最多 2 个 matrix worker，服务实际 RPM 不超过 20。
4. `ablation`：主方法通过完整性门后，在 train/dev 选择因素；用新建不重叠样本做 execution/component ablation，测试集只做一次最终验证。
5. `analysis`：只读取 run 目录生成 CSV/JSON/Markdown，不修改 item/attempt；重评分使用独立目录并写明 `provider_calls=0`。

每个正式阶段结束后运行 `slotrag benchmark records-audit <stage> --output-dir <run> --require-trace`，再运行 `slotrag benchmark gate <stage> --output-dir <run> --require-trace`；前者报告 `complete=true` 且后者报告 `analysis_ready=true` 才能进入统计汇总。只有 `publication_ready=true` 才能进入论文主表。旧 run 若没有 trace、matrix manifest、baseline audit 或 command manifest，只能保留为历史诊断，不能回填为完整投稿记录。

适配协议阶段还必须运行：

```bash
slotrag benchmark gate <stage> --output-dir <run> --require-trace --allow-adapted-protocol
```

只有返回 `status=publication_ready_adapted_protocol` 时，结果才可进入单独的“shared-provider adapted”表；该表必须与 exact upstream 表分栏，不能合并成“击败 baseline”的结论。

## 完整记录布局

```text
runs/vldb2027-exact-v31/<run-id>/
  manifest.json                 # code/config/baseline/data/environment fingerprints
  matrix-manifest.json          # exact matrix command, jobs, workers, safe env
  preregistration.yaml
  command.txt
  dataset-audit.json
  baseline-audit.json
  adapter-audit.json
  environment/packages.json
  services/doctor-before.json
  services/doctor-after.json
  logs/<stage>/<dataset>__<method>.log
  samples/<stage>/<dataset>.jsonl
  traces/<stage>/<dataset>/<method>/<question>/attempt-0001.jsonl
  attempts/<stage>/<dataset>/<method>/<question>/attempt-0001.json
  items/<stage>/<dataset>/<method>/<question>.json
  plans/<stage>/...               # frozen plan and provenance when applicable
  summaries/<stage>/{summary.json,metrics.csv,per_question.csv,
    retrieval_metrics.csv,paired_bootstrap.csv,stratified_metrics.csv,
    failure_report.csv,REPORT.md}
```

`attempt` 只追加不覆盖；`item` 是当前最终状态；retry、HTTP 错误、provider request ID、raw answer、tool call、评分输入和评分输出都保留。trace payload/response 默认脱敏且不写 API key；只有在新 run 的配置中显式启用时才保存完整请求/响应快照。

## 晋级条件

- 任何 dataset-method cell 缺 final、attempt、trace 或 provenance，主表不生成。
- exact upstream baseline 必须有真实入口执行记录；local adapter 和 adapted protocol 分栏显示。
- 最终 `ok` 率、retry、timeout、空回答和预算失败按 attempt/final 双分母报告。
- 结果、统计和文档引用同一个 run manifest SHA-256；架构、提示词、解析器、阈值或数据变化必须新建 run ID。
