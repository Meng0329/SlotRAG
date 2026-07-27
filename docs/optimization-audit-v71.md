# SlotRAG-QO v71：Development-selected No-top-k Runtime Smoke

日期：2026-07-27

## 结论

v71 将 v70 在 development 上冻结选择的 `no_expansion` 接入主 `slotrag-physical-policy` 和
`slotrag-qo`，旧 utility expansion 作为显式 ablation 保留。与 v69 相同的 8 个 train/global-corpus
问题和 8 个 frozen plans 上，32/32 records 为 `ok`；两个数据集所有 treatment 相对 SlotRAG 均为
gain/tie/loss=`0/4/0`，answers、rows、evidence 的 exact-match rate 全为 `1.0`。

成本 gate 通过，质量 gate 为 null。physical/QO 的 `EXPAND_TOPK=0`、action-induced retrieval calls=0；
2Wiki 四方法 calls/tokens 均为 `1.25/2010`，HotpotQA 均约为 `2.75/4280`。这消除了 v69 中 QO 在
HotpotQA 的 calls/tokens `5.50/11282` 和 2Wiki 的 `1.75/3583`，同时没有降低当前 8 题质量。
但 primary/evidence 仍与 SlotRAG 完全持平，因此 v71 只证明移除低精度 action 恢复 Pareto 成本，不证明
新方法质量提升，不允许扩大为 SOTA claim。

## 协议与完整性

* run：`runs/slotrag-qo-no-topk-global-smoke-v71`；
* stage：`qo_no_topk_global_dev_v71_smoke`；
* train / global-corpus / BM25；HotpotQA、2Wiki 各 4 题；四方法共 32 records；
* 32 finals、32 immutable attempts，32/32 `ok`，retry/failure/empty/unsupported=0；
* trace missing=0，schema=31；
* 8/8 imported frozen plans 有效，hash mismatch/inconsistent pair=0；
* sample audit valid，与 v63 development overlap=0；
* gate=`analysis_ready_nonpublication`，仅 blockers=`smoke_stage_not_for_publication`、
  `training_split_not_for_publication`。

运行启动时 manifest 记录 revision `8e7336b85453aecdd04731d601acc99276987736`、`code_dirty=true`；32
records 完成后，当前补丁由外部流程提交为 `da6dedd64f6f3d9d32772c55a08db5d51eea9b97`。提交发生在 run
完成之后，没有触发 v69 首次运行那种中途 provenance mismatch。该 smoke 是 analysis-only，后续扩大
实验必须从干净 `da6dedd...` 或其明确后继 revision 新建目录。

## 2x2 结果

| Dataset | Method | Primary | Evidence recall | nDCG@10 | Calls | Tokens | Wall ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2Wiki | SlotRAG | 0.50 | 0.250 | 0.3066 | 1.25 | 2010 | 5002 |
| 2Wiki | + sufficiency | 0.50 | 0.250 | 0.3066 | 1.25 | 2010 | 5621 |
| 2Wiki | + physical/no-top-k | 0.50 | 0.250 | 0.3066 | 1.25 | 2010 | 5284 |
| 2Wiki | + both/QO/no-top-k | 0.50 | 0.250 | 0.3066 | 1.25 | 2010 | 5612 |
| Hotpot | SlotRAG | 0.25 | 0.500 | 0.4626 | 2.75 | 4281 | 16593 |
| Hotpot | + sufficiency | 0.25 | 0.500 | 0.4626 | 2.75 | 4281 | 17635 |
| Hotpot | + physical/no-top-k | 0.25 | 0.500 | 0.4626 | 2.75 | 4286 | 16675 |
| Hotpot | + both/QO/no-top-k | 0.25 | 0.500 | 0.4626 | 2.75 | 4278 | 16238 |

Latency 只来自 4 题并受服务并发影响，不据此声称加速；calls/tokens 和逐题 outputs 是更稳定的 gate。

## Action 行为

2Wiki physical/QO 分别执行 `ANSWER 4, STOP_SLOT 1`；Hotpot physical 为
`ABSTAIN 1, ANSWER 3, STOP_SLOT 5`，QO 为 `ABSTAIN 1, ANSWER 2, STOP_SLOT 6`。所有 selected actions
execution coverage=`1.0`，但这些 control transitions 未改变 paired outputs。旧 utility 路径保留为
`slotrag-physical-policy-utility`、`slotrag-qo-utility`，用于后续独立消融。

## 验证与 hashes

代码门禁：`323 passed, 1 skipped`；compileall、`git diff --check` 和实际 `BenchmarkSuite.from_yaml`
解析通过。一次手工配置检查曾误导入不存在的 `load_benchmark_suite` helper 并失败，随后使用正式
`BenchmarkSuite.from_yaml` 成功；该诊断错误不属于实验记录失败。

* runtime audit：`3a046068f6ebd448a3cb546030f42eca661d44b5cca17129e181eb99c146cd05`；
* record audit：`9225bd8eaa2288bb7236143d8ebcae09767137b70ecdbba27c8ddbf4f1d22c15`；
* sample audit：`500b22397d24e56e589b93c5f1ff985cf30d8dec4b9dd91dd53a423ce59394bd`；
* publication gate：`5e83854be557d24e073aeeeaeea0faf15a90945fe7874a7f31965e5b3e089468`；
* frozen-plan audit：`d9a70691009dcbc4aa54466d0d0ef5bed73ff883caed677061b5e53ddaa2f0f3`；
* config：`45cbc0c61c749b51e32bc7b8819dc4432bdc2f13b912683b8af10e9ac84ef328`；
* record fingerprint：`b9d95600015786c65c5f2e1a692f2c5ac96b8d5bed2e725171eb48bc91423531`。

## 下一大版本

v66-valid 的 available-answer retrieval-miss proxy 为 32/80 questions，而 top-k candidate recovery 只有
7/150 slots。v72 不再优化 top-k；一次性实现通用 query rewrite、complementary retrieval 和 evidence-gain
stopping，先在冻结 development slices 上验证 retrieval recall 与成本。最多 10 轮 development 迭代，
evaluation 不参与选择；只有通过多 slice/cost/unsupported-answer gate 的候选进入完整矩阵。
