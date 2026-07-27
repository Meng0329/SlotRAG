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

### v45/v46 2×3 因子消融基础设施修正（2026-07-26）

v45 的 600 条 final/attempt/trace 和 100 个只读 plan snapshot 全部落盘，sample、records、
plan hash/provenance 审计均完整。但 59 个 `budget_exceeded` 中有 49 个是
`question timeout exceeded (300s)`，只有 10 个是真实 retrieval budget 超限；超时在单元间
不均。提交 `c3b5356` 使 publication gate 对 question timeout 硬阻断，v45 现为
`analysis_ready=false / publication_ready=false`，历史结果只能用于基础设施诊断。同一 plain
单元 v44→v45 宏 primary 变化 `+0.02949`（4 win / 93 tie / 3 loss），后续必须显式报告
运行间稳定性。v44 也反查到 13 个同类超时，v37 有 7 个，两者的原始增益数值不再用于晋级。

v46 使用 `configs/experiments/slotrag-grounding-retrieval-factorial-v2.yaml`，新目录为
`runs/slotrag-grounding-retrieval-factorial-v2/`。它与 v45 的唯一协议差异是将单题 deadline
从 300 秒提高到 900 秒；数据、seed、冻结计划、六个单元、三项计数预算和并发协议均不变。
必须全量执行 600 条，禁止只挑 v45 失败题补跑。硬门为 question timeout=0，真实
retrieval budget 失败保留在分母。

在调用前固定五个 primary contrast：`G`（grounding 主效应）、`A`（always-slot）、
`U`（unbound-slot）、`G×A`、`G×U`。每题先在六单元内计算 contrast，再做 10,000 次
paired bootstrap（seed 27182）、95% CI、双侧置换/Bootstrap p 值与五对比 Holm 校正；
同时报告逐数据集效应、EM/F1、evidence Recall/MRR/nDCG@10、retrieval/provider/tokens/wall、
失败类型与 v44/v45/v46 plain 稳定性。不得在观察 v46 后增删主 contrast。

v46 已按预注册完成 600/600 item、attempt、trace 和 100/100 plan snapshot；
records audit 完整，最终为 `582 ok + 18 budget_exceeded`，其中 13 条为真实
retrieval budget、5 条为 900 秒 question timeout。代表性超时的 12 个 provider
事件均为 HTTP 200、0 retry，总服务延迟 2.4666 秒，与 900.0007 秒题级 wall
不符；另一条只有 3.5700 秒 provider 延迟而 wall 为 900.0009 秒。根因为旧文件
RPM 限流器的同步唤醒抢锁导致 waiter 长时间饥饿，而不是 provider 服务超时。

该轮还有独立的 provenance 污染：矩阵约 02:40 启动，限流源码在 03:22 修改，
但 16-worker 调度器会在前序 cell 完成后才启动后续 14 个 cell，故部分 DROP cell
加载了新实现，首个 manifest 却仍记录 `9f64ce1/code_dirty=false`。v46 因而只作
不可变基础设施诊断，不运行 factorial analyzer。通用汇总保留完整的 145 列宏指标、
182 列 cell 指标、170 列逐题指标、74 列检索指标、183 列分层指标和失败分母；
所有描述数值均不得用于模块晋级。

提交 `f88b95f` 已改为原子预约 `next_available_at` 后单次等待的 schema-2 限流，
并保持对 schema 1 的兼容。提交 `5cc1537` 又使后续 cell 的 revision、dirty 状态或
源指纹与首个 cell 不一致时直接拒绝续跑。专项限流测试 6/6、benchmark runner 12/12、
全套件 `237 passed, 1 skipped`。v47 固定
`configs/experiments/slotrag-grounding-retrieval-factorial-v3.yaml` 与
`runs/slotrag-grounding-retrieval-factorial-v3/`，从单一干净提交启动并冻结运行时代码。它与 v46 使用
完全相同的题目/计划、seed、六单元、6/64/6 预算、900 秒 deadline、16 个 matrix
worker、provider 30 allowed/20 operational RPM 与服务并发上限 64；基础设施差异仅为
公平限流和 provenance 硬保护。仍必须全量重跑 600 条，不允许定点重跑；通过条件是
question timeout=0 及 records/sample/frozen-plan audits 全部完整。五个 primary contrasts、
10,000 次分层 paired bootstrap、双侧 sign-flip 置换与 Holm 校正保持不变。
v47 仍是 train 模块选择试验，不得因干净 gate 通过而标为投稿主证据。

### v47 干净因子结果与下一轮决策（2026-07-26）

v47 在执行提交 `6686d818db3a240680a3ad3b039f62aef7a98074`上完成 600/600
final/attempt/trace，`587 ok + 13` 个真实 retrieval budget，question timeout=0。
100/100 frozen plans 和全部 sample/record/trace/provenance 审计通过。Gate 为
`analysis_ready_nonpublication`，唯一原因是 train split。六单元 primary 为
off-slot/off-always/off-unbound=`0.6930/0.7054/0.6830`，on-slot/on-always/on-unbound=
`0.7180/0.7280/0.7280`。

预注册的 `G/A/U/G×A/G×U` effect 为
`+0.03085/+0.01123/0.00000/-0.00246/+0.02000`，95% CI 分别为
`[+0.00830,+0.05849]`、`[-0.03245,+0.05368]`、`[-0.03000,+0.03000]`、
`[-0.03471,+0.02979]`、`[0.00000,+0.05000]`；Holm p 为 `0.1530/1/1/1/1`。
没有 primary contrast 达到多重校正显著。分析后审计修正了近零浮点同时计入
win/tie 的统计 bug；提交 `8d45cae` 加入互斥计数与分析器源码 SHA 记录，完整测试
`238 passed, 1 skipped`。重生的统计输入/分析器 SHA-256 为
`88e0d905d79085b07aaddfa19fa7e708c8c61438b5f4d6473ce8decb7e8883f8` /
`76da527beb06a674aa3e9cbde0cb373eae8256ffb02f5ae84d4a4374e1055e8a`。

架构选择为“轻量优先、等待外部确认”：`slotrag-grounded-role-projection` 相对 plain
primary `+3.61%`、EM/F1 `+0.0200/+0.0250`，retrieval/provider/wall 仅
`+0.7%/+1.4%/+0.9%`。always/unbound 最高仅相对 plain `+5.05%`，但明显增加
检索、provider 和延迟，且 `A/U` 主效应不显著，因此两者不再作默认候选。

后续顺序冻结为：

1. 只在 v47 train 上审计 `G` 产生非零差异的 6 题，将改变归类为计划、抽取、连接、grounding 拒绝、fallback 和答案出口；保留原始 trace，禁止 QID/gold 特例。
2. 若存在通用错误机制，只在 train/dev 实现和消融；不再增加双查询阈值变体。
3. 冻结候选后，在新的、不重叠的 dev/evaluation 题上只比较 plain 与 grounding-only，使用 frozen-plan paired protocol、完整失败分母、trace、bootstrap 和 Holm 校正。
4. 若新样本上质量优势不复现或成本恶化，回退 plain；不得追加重试、换 seed 或修改统计对比。

### v47 机制审计与 v48 binding guard 预注册（2026-07-26）

`grounding-mechanism-audit` 已将 v47 的 6 道非 tie 题固化为机器可读索引；每个六单元
记录都附 final/attempt/trace SHA-256。候选 grounding-only 的分类为 2 个
`candidate_exact_gain`、1 个 `candidate_overlap_only_gain`、3 个
`factor_only_no_candidate_change`。其中 overlap-only 题把已知输入
`Pakistan Movement` 复制为 `otherMovement`，EM=0，仅因与 gold 共享 `Movement`
得到 0.5 F1，不能算正确收益。

v48 冻结配置为 `configs/experiments/slotrag-grounding-binding-guard-train-v1.yaml`，run 为
`runs/slotrag-grounding-binding-guard-train-v1/`。新变体
`slotrag-grounded-binding-guard` 只增加通用的 known-binding 非自反输出保护，不含 QID、
gold 或 dataset 分支；旧 grounding 方法保持不变。矩阵固定五数据集 × 20 题 ×
`plain/old-grounding/guard` 三方法，同 v47 seed、sample、frozen plan、预算和 deadline。

运行前停止规则：五个 sample SHA 必须逐一等于 v47；代码提交、dirty 状态和源码指纹在
全部 cell 间一致。运行后必须有 300/300 final、attempt、trace，question timeout=0，
records/sample/frozen-plan audit 全通过。预注册 overall primary 家族仅含
`guard-plain` 与 `guard-old-grounding` 两项，按 dataset 等权、题内配对，10,000 次
bootstrap/sign-flip、seed 27182、Holm-2；EM/F1、全检索质量、调用、token、延迟和失败
作为完整 secondary 指标。若 guard 丢失 v47 的任一 exact gain、产生 exact loss 或增加
检索成本，则回退 old grounding；该 train 轮无论结果如何均不允许进入投稿主表。

### v48 结果与 v49 固定 baseline 确认（2026-07-26）

v48 完成 300/300 final/attempt/trace，297 `ok` + 3 个同题、三方法对称的
retrieval-budget 终止，0 timeout/provider/retry；100/100 frozen plans 有效且所有哈希/
provenance 检查通过。primary 宏平均为 plain `0.7030`、旧 grounding `0.7236`、
guard `0.7330`。guard-plain=`+0.0300`，CI `[-0.0100,+0.0700]`；guard-old=
`+0.00935`，CI `[-0.01065,+0.03500]`；Holm-2 两项均为 `0.7343`。guard 触发 2/100 题，
其中 1 题保持 exact，1 题将 overlap-only 错答修复为 exact，无触发后 exact loss。
决策为保留 guard 作为低频正确性保护，但因效果未显著且仅为 train，不写入投稿结论。

v49 预注册为 fixed-sample adapted 确认：

- 配置：`configs/experiments/slotrag-binding-guard-fixed-main-eval-v1.yaml`；
- 输出：`runs/slotrag-binding-guard-fixed-main-eval-v1`；
- 只执行 `slotrag-grounded-binding-guard`，不重跑已冻结 baseline；
- 数据：复用 `vldb2027-adapted-main-v1/main_comparison` 五数据集×100 evaluation 题，seed 2040；
- 计划：复用 `runs/slotrag-final-candidate-v2/plans/imported_main` 的 500 份 SlotRAG frozen plans；
- 预算：与原主对比一致的 4 steps / 64 LLM / 4 retrieval / 300 s；
- 完整性：500/500 final/attempt/trace，保留 timeout、empty、budget 和 provider 失败分母；
- 分析：与旧 SlotRAG 逐题配对，并与旧 IRCoT*/ReAct*/Hybrid* 宏值作同样本诊断对照；
- 边界：该样本已用于早期候选评估，且 baseline 不是 exact upstream，故不标记为全新
  one-shot held-out 或投稿主表。

v49 已完成并固定以下结果与分析协议：500/500 final、attempt、trace，494 `ok`、6
`budget_exceeded`（HotpotQA 2、MuSiQue 4），无 timeout/provider/retry；500/500 imported
plans 有效，hash/provenance/variant 均为 0。guard 的 primary 宏平均为 `0.6838417`，旧
SlotRAG* 为 `0.6719169`，整体差值 `+0.0119249`（`+1.775%`），分层 bootstrap 95% CI
`[-0.0067178,+0.0306060]`，sign-flip `p=0.2059`，与七个固定适配器的 Holm p=`0.4524`。
逐数据集 guard-old SlotRAG* 差值为 2Wiki `+0.0172`、DROP `-0.0113`、HotpotQA `+0.0232`、
MuSiQue `+0.0404`、StrategyQA `-0.0100`，均未通过数据集级显著性。

同题逐项比较的 adapted primary 为：guard-GraphRAG* `-0.0032` (Holm `0.8777`)、
guard-PlanRAG* `-0.0299` (`0.4524`)、guard-Hybrid* `-0.0467` (`0.0884`)、guard-ReAct*
`-0.0489` (`0.0555`)、guard-IRCoT* `-0.0647` (`0.0078`)、guard-SRAG* `+0.0641`
(`0.0007`)。这些值只能作为同一 shared-provider local adapter 样本的诊断，不能转写成
exact-upstream 论文结论；`baseline_execution.exact_upstream_execution_verified=false`。

全指标分析使用仓库现有 `slotrag.benchmarking.paired`，145 个指标、数据集分层、10,000
次 bootstrap/sign-flip、seed=`27182`，整体 primary 七比较做 Holm。机器报告和完整可用分母
在 `runs/slotrag-binding-guard-fixed-main-eval-v1/summaries/binding_guard_fixed_main_eval/fixed_main_analysis/`
（`paired_analysis.json`、`paired_contrasts.csv`、`paired_input.csv`、`report.json`）；
guard 触发题审计在 `protected_anchor_audit.{json,csv}`，15/500 题、28 次拒绝、2 exact gain、
0 exact loss、13 exact tie。分析入口 `tools/analyze_fixed_main.py` 的 SHA-256 为
`81e5e6a5657d5738b12055d3e70af89b1be5cc2bb3833083dfc9d79bf79601e7`。

v49 后不晋级 guard 为默认方法，也不以此轮 adapted 表支撑“领先 10%”或投稿结论。下一轮
必须新建不重叠 train/dev 机制门，优先分析 MuSiQue/HotpotQA 的抽取失败与 6 个预算失败；
任何修改都要先预注册，再用新的 held-out/test 样本验证。exact-upstream baseline 的执行阻塞
仍保持不变，不能用本地 adapter 填补。

### v50 预算敏感性 train 预注册（2026-07-26）

v49 的 6 个 evaluation budget failure 中 5 个为 5/9-slot 计划，另 1 个为 4-slot 计划在
4 次检索调用后耗尽；v48 train 的 6 次检索预算仍有 3 个 5-slot failure。v50 只回答“预算
上限是否是主要阻塞”，不改变 SlotRAG 代码、prompt、答案解析或检索器：

- 配置：`configs/experiments/slotrag-binding-guard-budget-train-v1.yaml`；run：
  `runs/slotrag-binding-guard-budget-train-v1`；stage：`budget_sensitivity_train`；
- 样本：与 v48 完全相同的五数据集×20 train 题，seed=`27182`，复用同一组 imported
  SlotRAG frozen plans；只运行 guard（`slotrag` 仅作为 frozen-plan source）；
- 唯一变量：预算从 v48 的 `max_steps=6/max_retrieval_calls=6` 改为
  `max_steps=10/max_retrieval_calls=12`，LLM 上限 64；timeout 900 s；provider/operational
  RPM 仍为 30/20，服务并发 64；
- 预注册 primary：guard@12 - guard@6 的题内配对 primary，数据集等权，10,000 次
  bootstrap/sign-flip，seed=`27182`；secondary 为 budget failure rate、EM/F1、evidence、
  retrieval/provider/LLM calls、tokens、wall P50/P95/P99 和 145 个运行指标；
- 晋级规则：只有 failure rate 明显下降且 primary 的 95% CI 下界不低于 `-0.020`，同时
  provider calls 与 total tokens 的均值增幅分别不超过 `+50%`，才保留为执行配置候选；
  否则记录为诊断并否决，不进入 evaluation/test；无论结果如何不得改写 v49。

运行前必须完成 sample/frozen-plan/source fingerprint audit；运行后必须有 final/attempt/trace
完整记录、失败分母、gate=`analysis_ready_nonpublication`，再由配对统计和完整成本报告决定
是否需要新的计划压缩模块。

### v50 完成记录（2026-07-26）

v50 已完成且审计通过：100/100 final、attempt、trace，100 条均为 `ok`；0 timeout/provider
failure/retry；100/100 imported frozen plans 有效，所有 provenance/hash/variant 异常计数为 0。
宏平均 guard@12 为 primary=`0.7429571`、EM=`0.5400`、F1=`0.5720`、evidence R@10=`0.8313`、
LLM calls=`1.950`、retrieval calls=`1.560`、provider calls=`5.070`、total tokens=`2418.0`。

与 v48 同题 guard@6 的配对 primary 为 `+0.0100`，95% CI `[0.0000,+0.0300]`，sign-flip
`p=1.0000`，胜/平/负=`1/99/0`；EM/F1 均为 `-0.0100`。失败率从 `1/100` 降为 `0/100`，
total tokens 增幅约 `+1.51%`，provider calls 增幅约 `+1.20%`，通过预注册晋级门槛；这只支持
保留 10/12 作为下一轮执行预算，不支持显著质量提升或领先结论。完整 145 指标、失败分母和
配对 CI/p 位于 `runs/slotrag-binding-guard-budget-train-v1/summaries/budget_sensitivity_train/`
及其 `fixed_budget_analysis/`，配对 seed=`27182`、10,000 次 dataset-stratified
bootstrap/sign-flip。train gate 仍为 `analysis_ready_nonpublication`。

### v51 fixed-main evaluation 预注册（2026-07-26）

基于 v50 的预算门禁，v51 将 `max_steps=10/max_retrieval_calls=12` 固定到 evaluation 复核，
不再调整预算、prompt、代码或解析。配置：
`configs/experiments/slotrag-binding-guard-fixed-main-eval-v2.yaml`；run：
`runs/slotrag-binding-guard-fixed-main-eval-v2`；stage：`binding_guard_fixed_main_eval_v2`。
五个数据集各 100 题、seed=`2040`，复用 v49 已审计的 500 份 imported plans，只运行 guard，
`slotrag` 仅作为 frozen-plan source；timeout=300 s、LLM 上限 64、provider/operational
RPM=30/20、服务并发=64 保持不变。运行前固定 sample/plan fingerprint，运行后要求
500/500 final/attempt/trace、完整失败分母、全指标汇总和 gate。该 evaluation 样本曾用于早期
候选诊断且 baseline 仍非 exact upstream，因此 v51 只能作为 adapted 预算复核，不能写成
全新 held-out 投稿主表。

### v51 完成记录（2026-07-26）

v51 已完成：500/500 final、attempt、trace，499 `ok`；HotpotQA
`5a801e68554299485f59856f` 为 1 条 `failed/other`（`slot S3 has no join path`），无
timeout/provider/retry。500/500 imported plans 有效，sample SHA 与 v49 一致且与 v48 train
overlap=0；plan/provenance/hash/variant 异常均为 0。gate 对本方法为 `publication_ready`，
但 baseline comparison 仍为 `diagnostic_local_adapters`、exact-upstream=false。

宏平均 primary=`0.6888553`、EM=`0.3540`、F1=`0.5022`、accuracy=`0.8600`、DROP
F1=`0.5955`、evidence R@10=`0.7938`、LLM calls=`1.996`、retrieval calls=`1.564`、
provider calls=`5.124`、total tokens=`2557.3`。相对同题 v49 guard@4/4：primary
`+0.0050136`，95% CI `[-0.0049578,+0.0161357]`，sign-flip `p=0.3894`，八比较
Holm=`0.7787`，胜/平/负=`7/487/6`；六个旧 budget failure 中五个转为 `ok`，一个转为
上述 join-path failure。provider calls 增加约 `+3.60%`，total tokens 增加约 `+3.85%`。
结论是保留 10/12 作为候选执行预算，但不宣称显著质量提升。

同题 adapted primary 为：v51-SlotRAG* `+0.0169`（Holm `0.3140`）、GraphRAG*
`+0.0018` (`0.9293`)、PlanRAG* `-0.0249` (`0.6965`)、Hybrid* `-0.0417`
(`0.1775`)、ReAct* `-0.0439` (`0.1350`)、IRCoT* `-0.0597` (`0.0189`)、SRAG*
`+0.0691` (`0.0008`)。完整 145 指标与 6,006 条 paired contrasts 在
`runs/slotrag-binding-guard-fixed-main-eval-v2/summaries/binding_guard_fixed_main_eval_v2/`
及 `fixed_main_analysis/`。该结果不满足领先 10% 或 exact-upstream 投稿门槛；下一轮只允许
在 train/dev 预注册通用 join-path 退化机制，不得在这 500 个 evaluation 题上继续调规则。

### v52 显式物化前沿保护 train 预注册（2026-07-27）

v51 唯一的非预算失败暴露出一个通用执行不变量缺口：旧选择器依据当前 binding 字段筛选
候选，但增量连接器只接受与已物化子图存在显式 `JoinSpec` 边的下一槽位。在共享变量经中心
槽位传递的星形计划中，旧策略可能先选择两个兄弟叶槽，随后以 `has no join path` 终止。
该缺陷来自执行器两个判据不一致，而不是计划图不连通。修复采用独立开关
`frontier_safe_selection`，默认关闭以保持历史 run 语义；候选
`slotrag-grounded-frontier-guard` 在 binding guard 上开启该开关。每次非初始选择记录
`frontier_guard_checks`，候选集合变化记录 `frontier_guard_interventions`，被排除的非前沿
候选数记录 `frontier_candidates_pruned`。不允许 QID、dataset、gold 或答案文本特判。

TDD 回归固定了五槽星形计划：旧策略必须复现 `S2 -> S3` 和 join-path failure，新策略必须
执行 `S2 -> S1 -> S3 -> S4 -> S5` 并得到输出；执行器 99/99、方法路由 36/36 测试通过。
另以 run manifest 的 stage split 离线审计现有 4,841 个计划文件：402 个可确认的唯一 train
计划变体中静态风险为 0，表明风险依赖运行时 binding，不能用拓扑预筛形成择优样本。

v52 第一层使用 `configs/experiments/slotrag-frontier-guard-train-v1.yaml`，run 为
`runs/slotrag-frontier-guard-train-v1`，stage 为 `frontier_guard_train`。它与 v50 使用完全
相同的五数据集×20 train 题、seed=`27182`、100 份 imported frozen plans 和 10/12 预算，
只运行新候选；v50 的 `slotrag-grounded-binding-guard` immutable per-question 结果作为跨 run
配对 reference，不重跑旧方法或任何 baseline。运行前必须证明五个 sample SHA、100 个
question key、plan SHA/provenance 全部一致。

预注册 primary 为 frontier guard - v50 binding guard 的数据集等权 paired primary，10,000
次 dataset-stratified bootstrap/sign-flip，seed=`27182`；secondary 为 EM/F1、StrategyQA
accuracy、DROP EM/F1、全部 evidence 指标、145+ 运行指标、失败分母、calls/tokens、wall
P50/P95/P99 和三项前沿机制计数。晋级要求：100/100 final/attempt/trace 完整，不能新增
failure/timeout/provider error；primary 95% CI 下界不低于 `-0.020`；provider calls 与 total
tokens 均值增幅各不超过 `+10%`。若 intervention>0，还要求 intervention 子集无 primary
loss；若 intervention=0，只能证明随机 train 上无回归，不能宣称质量贡献，下一步必须使用
新 seed 的更大 train 样本。v51 已见 evaluation 题只保留为故障来源和单元回归，不进入 v52
质量统计，也不得用于晋级。

### v52 完成记录（2026-07-27）

v52 第一层按预注册完成：100/100 final、attempt、trace，100 条均为 `ok`，无 timeout、
provider failure 或 retry；100/100 imported plans 有效，provenance/effective-plan/hash/variant
异常均为 0。sample 与 v50 五个 JSONL SHA 完全相同，gate=`analysis_ready_nonpublication`。

frontier candidate 的宏平均为 primary=`0.7429571`、EM=`0.5500`、F1=`0.5820`、DROP
EM/F1=`0.7000/0.7130`、StrategyQA accuracy=`0.8500`、evidence R@10=`0.8313`、
provider calls=`5.080`、total tokens=`2434.58`、wall=`21703.78 ms`。新计数器总和为
checks=`48`、interventions=`2`、candidates_pruned=`2`（宏平均 `0.48/0.02/0.02`）。

与 v50 同题同计划 binding guard 的 148 指标配对分析（10,000 次 dataset-stratified
bootstrap/sign-flip，seed=`27182`）显示 primary `Δ=0.0000`、95% CI `[0.0000,0.0000]`、
`p=1.0000`、胜/平/负=`0/100/0`；EM/F1 各 `+0.0100`、CI `[0.0000,+0.0300]`、
`p=1.0000`；provider calls `+0.0100`、total tokens `+16.59`（CI `[-14.03,+63.73]`）、
wall `-92.21 ms`（CI `[-1343.82,+1227.19]`）。两道干预题均为 MuSiQue，candidate/reference
均 `ok`，primary/EM/F1 均 tie，无 exact gain/loss；因此该轮只支持“无回归的安全性证据”，
不支持质量增益或默认方法晋级。

v52 关键工件：config SHA=`0e3fcb625c0a9b76c1f5443af2cb3786ea3c40d000f02c481ca3d09c93a74ec2`；
`summary.json=c70f55b6a326d29702b1852783f61ed8bc7f8680f595078dff0c4b5d17047ff4`、
`metrics.csv=212a8c0360dc66fc8485a5cd5c6dc10232046898d2ce7ec693a85eec9585d427`、
`per_question.csv=a31712ffe5225de87b6f4b822524eef9e3b645ec0866934817ec09a61c93d51b`、
`frontier_vs_binding_guard/paired_analysis.json=c23359e0d2d26502a12335b4af984a13a494c2a7a4cfc54560baeeb95a71551c`、
`frontier_selection_audit.json=4b59fae1681d4189f6a89feb2940d0bffdd170afbefe7220e065535b7e2e7497`、
`report.json=793a17312d0c9caba3a7712dc9c796abc0a0b9637e0baf2b1e7f7babc00438c6`。paired 报告
已扩展为 148 指标，历史 v50 缺失的三个新计数器只在分析输入中显式补零，v50 原工件未修改。

### v53 更大 train 机制验证预注册（2026-07-27）

v52 仅有 2/100 干预题，不能估计低频安全模块的质量/成本分布。v53 使用新 seed=`314159`、
五数据集各 100 条 train 题（总 500），排除 v48/v50 已用 sample 目录，避免题目重叠；不使用
evaluation gold 选择样本。配置为 `configs/experiments/slotrag-frontier-guard-train-v2.yaml`，
run=`runs/slotrag-frontier-guard-train-v2`，stage=`frontier_guard_train_v2`。同一 source
`slotrag` 只生成一份冻结计划，配对运行 `slotrag-grounded-binding-guard` 与
`slotrag-grounded-frontier-guard`；不运行外部 baseline。

预算固定 10/12、LLM 上限 64、timeout 900 s；服务配置固定为 provider/operational RPM=30/20、
max concurrency=64、trace=true/payload=false。主检验为 frontier-bind guard 的数据集等权
paired primary，10,000 次分层 bootstrap/sign-flip；完整报告 148 指标、EM/F1、任务指标、
evidence、calls/tokens、wall P50/P95/P99、失败分母和干预子集。晋级/停止规则预先固定：
500/500 final/attempt/trace 且无新增 timeout/provider failure；primary CI 下界 ≥`-0.020`；
provider calls 和 total tokens 均值增幅 ≤`+10%`；所有干预题 primary 不得出现 loss。违反任一
条件则保留为安全诊断，不进入 evaluation；无论结果如何不改写 v52。

### v53 完成记录：500 题前沿保护机制门（2026-07-27）

v53 完成 1000 条 paired final/attempt/trace（五数据集各 100 题、binding guard 与 frontier
guard），records audit 完整，缺失/非连续 attempt、missing trace 和 trace error 均为 0；无
timeout、provider failure 或 retry。binding guard 有 999 `ok` + 1 个 MuSiQue
`failed/other`（`2hop__650240_59201`，`slot S1 has no join path`），frontier guard 同题为
`ok`；该失败保留在分母。共享 source frozen plan 为 500/500 有效，plan attempt 500/500，
provenance/effective-plan/hash/variant 异常均为 0；新 sample 与 v48/v50 overlap=0。gate 为
`analysis_ready_nonpublication`，因为是 train split，`publication_ready=false`。

| 方法 | primary | EM | F1 | evidence R@10 | DROP EM/F1 | StrategyQA acc. | provider calls | total tokens | wall ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| binding guard | 0.746887 | 0.5160 | 0.586086 | 0.86625 | 0.5500/0.6327 | 0.8600 | 5.222 | 2466.934 | 40358.24 |
| frontier guard | 0.752679 | 0.5220 | 0.593828 | 0.86625 | 0.5600/0.6427 | 0.8500 | 5.238 | 2478.264 | 40063.48 |

148 指标 paired（10,000 次 dataset-stratified bootstrap/sign-flip，seed=`314159`）得到 primary
`Δ=+0.005791`，95% CI `[-0.006586,+0.018424]`，`p=0.3746`，胜/平/负=`7/487/6`；EM
`+0.0060`（CI `[-0.0040,+0.0160]`），F1 `+0.007742`（CI `[-0.001703,+0.018538]`）。
provider calls `+0.016`（约 +0.31%）、total tokens `+11.33`（约 +0.46%）、wall
`-294.76 ms`，均通过成本门槛。frontier 触发 7 题，checks/interventions/pruned=`18/9/11`，
触发子集 gain/tie/loss=`1/6/0`；唯一 exact gain 为 MuSiQue
`3hop1__131682_66618_440465`。旧策略的 join-path failure 被新策略修复为 `ok`，但最终
primary 仍为 0，不计为质量 gain。该轮支持保留 frontier 作为低成本安全模块，不支持显著质量
增益、10% 领先或默认方法晋级；不得进入 evaluation 主表。

关键 SHA：config=`fe4843b5f598a6023ce70cb3fab2ec9fe5877e45a165f19ffc01097945954590`；
summary=`6ae729912cb2f1643b2845ea6ebad1e04f96385097b0859ad7b50d2a10415ec7`；
per_question=`2f0748042697b1a9d916c16d228ecabdb939ae53935bc801e531f39b127d43ed`；
records-audit=`8f839b4ae204cdc60b263feced6afab2cdfc61e6edea32898f6ee93b6bd7d348`；
gate=`7ab6a216f260da39158cabb1e17f96487c18348e0e9621ec8c47ccf37b2feebd`；
paired-analysis=`f55c3630da8c021a98f5bb1d767f9d3ae4a39dc48263cb63eeaeb510e51f1b6b`；
frontier-audit=`25d838087477c6f70ed12a55e4921017a4bf31aecc85cf55d642853ab6678f5e`。

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

## v54 research reset 审计记录（2026-07-27）

v54 只完成离线 headroom 审计，未修改方法、未调用 provider、未启动全矩阵实验。命令为：

```bash
PYTHONPATH=src:. python tools/analyze_slotrag_headroom.py \
  --run-dir runs/slotrag-frontier-guard-train-v2 \
  --run-dir runs/slotrag-answer-contract-train-v1 \
  --output-dir runs/slotrag-frontier-guard-train-v2/summaries/optimization_audit_v54
```

输入 1,200 条 immutable 逐题记录。结果：结构化抽取错误的观测覆盖率为 `0.1392`，乐观平均 headroom ceiling 为 `0.0615`；当前 retrieval oracle answerability 估计为 `739/1200=0.6158`；rows 正确但 final answer 错误为 `70/1200=0.0583`；最近配对比较 tie rate 为 `0.9700`。frontier guard 仅影响 `13/1200=0.0108` 条记录，稀疏 guard 不再作为主优化方向。

v54 报告：`docs/optimization-audit-v54.md`。该报告中的 oracle/counterfactual 是历史 trace 的离线估计，不能写入论文主结果。下一门禁是先重构 `local_context` 与 `global_corpus` 协议、修复 StrategyQA/DROP 元数据并补齐 retrieval/plan/execution/generation telemetry；门禁通过前不得开始昂贵完整实验。

## v55 global-corpus protocol 实现与 smoke（2026-07-27）

已新增 `SharedCorpusIndex`/`CorpusManifest`，并将 `StageConfig.retrieval_protocol` 固定为
`local_context` 或 `global_corpus`。global corpus 按完整 split 构建，不按评估题 gold evidence
选取 passages；每道题的记录分别写入 available/gold/retrieved evidence ID 集合。runner 的新记录
schema 为 `29`，旧 run 工件不回写。

StrategyQA 适配器现在把 bundled facts 归入 `gold_facts_only`，不再送入检索索引；DROP 的
`operation_type` 保存来源（新数据为 `question_heuristic`，旧数据为 `legacy_unknown`）。因此
StrategyQA 在缺少外部语料时不能进入 retrieval quality 主表，必须报告 evidence unavailable。

provider-free smoke 使用：

```bash
PYTHONPATH=src:. python tools/run_global_corpus_smoke.py \
  --output-dir runs/slotrag-global-corpus-protocol-smoke-v55
```

结果为 3 个 source questions、3 个 documents、3 个 chunks、1 次 query；manifest 记录
`index_bytes=52`、`build_latency_ms≈379.24`、`query_latency_ms≈0.80`、`gold_evidence_not_used=true`，
provider calls 为 0。该 smoke 只验证协议和可追溯工件，不进入质量统计。全量测试为
`258 passed, 1 skipped`。下一门禁是对真实 benchmark 做 local/global 受控 smoke；在其完成前
不启动昂贵完整矩阵，也不实现基于固定 evaluation split 的阈值搜索。

## v56 真实 local/global smoke 与成本门禁（2026-07-27）

服务 doctor 三项均 HTTP 200；运行时配置 provider RPM=30、operational RPM=20、max concurrency=64、
trace=true、include_payloads=false。local 工件位于 `runs/slotrag-retrieval-local-smoke-v56/`，
2/2 final/attempt/trace 成功，平均 primary/F1=`0.395833`、EM=`0`、evidence recall=`1.0`、
wall=`5545.65 ms`；这是 adapted `hybrid` 诊断，不是 SlotRAG 主结果。

global 工件位于 `runs/slotrag-retrieval-global-smoke-v56/`。完整 HotpotQA evaluation split 为
7,405 questions、73,700 passages、73,911 chunks，约 2,310 个 embedding batches；在 operational
RPM=20 下理论构建下界约 115.5 分钟，超过受控 smoke 成本门禁。进程在最终 corpus/item 生成前
中止，`abort.json` 已记录 `status=aborted_cost_gate`；records-audit 为 0 final、
`analysis_ready=false`。该 cell 没有质量结果，不能与 local 结果比较。

结论：full-split global corpus 的主要下一步是离线/持久化索引构建及可复用向量 manifest，而不是
继续增加在线 guard。v56 不晋级 publication，不启动完整 global 矩阵；先完成成本方案与
LogicalPlan/PhysicalPlan 设计，再进入 `slotrag-qo`。
