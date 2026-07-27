# SlotRAG Optimization Audit v64

日期：2026-07-27  
状态：shared-index 数据管理门禁通过；质量方法门禁仍失败；development-only，未运行 evaluation 或 2×2。

## 1. 本版本回答的问题

v63 发现 2Wiki shared corpus 即使标记为 reused，仍耗时 `2,487.2s`。v64 只处理该系统瓶颈，未修改
retrieval ranking、planner、executor、generator 或答案指标：

1. passage provenance 是否可从逐重复 `set + sort + model_copy` 改为一次性集合累积；
2. `rank_bm25.BM25Okapi` 是否能以版本和 checksum 可验证的 artifact 真正复用；
3. cold/warm 构建成本是否可审计，并且 warm 检索是否与 cold 完全一致；
4. 该系统优化是否足以解除 2×2 质量实验门禁。

前三项通过，第四项不通过。v64 解决了索引构建与复用问题，但没有任何 answer-quality 增益证据。

## 2. 实现与协议

`_aggregate_passages` 现在只保存每个 unique chunk 的首个结构对象，并在 `set[str]` 中累积所有
`source_question_ids`，最后一次性排序和构造 `Passage`。这消除了高重复组中反复复制、合并和排序
不断增长列表的近二次行为。

新增 `SparseBM25Index` 持久化边界，artifact format 为 `slotrag-rank-bm25-pickle-v1`。加载前校验
SHA-256，加载后校验 format、engine、`rank-bm25` version、passage count 和 BM25 corpus size。passages
与 BM25 都使用同目录临时文件、`fsync` 和原子替换；manifest 锁覆盖兼容性复查、构建和写入，避免并发
进程同时发布半成品。

`CorpusManifest` schema 升为 3，新增 passage/sparse checksum、engine/version、cold/warm reuse reason，
以及 aggregation、sparse、dense、artifact-write 分段延迟。index ID v2 流式哈希完整 passage JSON，包含
provenance metadata；不再只哈希 ID/text。

新增 `tools/build_global_corpus_index.py`。该工具不创建 provider client，`provider_calls=0`；cold 模式
拒绝覆盖已有索引，warm 模式要求三个核心 artifact 全部存在，cold/warm 报告也拒绝覆盖。报告内嵌原始
dataset checksum、Git revision/dirty 状态、相关源码 checksum、运行资源、manifest 快照和无 gold probe。

## 3. 实际命令

```bash
PYTHONPATH=src:. python tools/build_global_corpus_index.py \
  --dataset 2wikimultihop --split train --benchmark-root benchmark \
  --index-dir runs/slotrag-global-index-v64/2wikimultihop/index \
  --report runs/slotrag-global-index-v64/2wikimultihop/cold-build.json \
  --mode cold --repository-root .

PYTHONPATH=src:. python tools/build_global_corpus_index.py \
  --dataset 2wikimultihop --split train --benchmark-root benchmark \
  --index-dir runs/slotrag-global-index-v64/2wikimultihop/index \
  --report runs/slotrag-global-index-v64/2wikimultihop/warm-build.json \
  --mode warm --repository-root .

PYTHONPATH=src:. python tools/build_global_corpus_index.py \
  --dataset hotpotqa --split train --benchmark-root benchmark \
  --index-dir runs/slotrag-global-index-v64/hotpotqa/index \
  --report runs/slotrag-global-index-v64/hotpotqa/cold-build.json \
  --mode cold --repository-root .

PYTHONPATH=src:. python tools/build_global_corpus_index.py \
  --dataset hotpotqa --split train --benchmark-root benchmark \
  --index-dir runs/slotrag-global-index-v64/hotpotqa/index \
  --report runs/slotrag-global-index-v64/hotpotqa/warm-build.json \
  --mode warm --repository-root .
```

四份报告记录 revision `a7c4e0762979c7ec5de796fd0a86de71c889645a`、dirty=`true`，因此不能只靠
revision 复现；四者共同的相关源码 fingerprint 为
`8bf55c02a4395df8c74b3ec2f7a50a208db5261fd758c5a2c7de3d6967eba54b`。

## 4. Cold/Warm 结果

| Dataset | Questions | Documents | Chunks | Mode | Build call | Aggregation | Sparse build/load | Artifact write | Index | Max RSS | Reuse |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| HotpotQA | 90,447 | 482,021 | 483,921 | cold | 125.65s | 17.66s | 23.54s | 77.60s | 662.16 MiB | 6.64 GiB | new |
| HotpotQA | 90,447 | 482,021 | 483,921 | warm | 31.14s | 18.13s | 5.13s | <0.01s | 662.16 MiB | 4.48 GiB | fully reused |
| 2Wiki | 167,454 | 369,378 | 401,090 | cold | 102.07s | 19.12s | 21.99s | 54.45s | 523.70 MiB | 6.15 GiB | new |
| 2Wiki | 167,454 | 369,378 | 401,090 | warm | 28.73s | 18.04s | 3.65s | <0.01s | 523.70 MiB | 5.02 GiB | fully reused |

相对同一实现的 cold，warm 加速 HotpotQA `4.03x`、2Wiki `3.55x`。相对 v63 manifest 的 build latency：

* 2Wiki cold `102.07s` 对 v63 `2,487.21s`，约 `24.37x`；warm 约 `86.59x`。主要收益来自 provenance
  聚合修复，v63 的所谓 reuse 仍重建 BM25。
* HotpotQA cold `125.65s` 对 v63 `62.92s`，反而慢约 `2.00x`，因为 v63 没有持久化 271.69 MiB 的
  BM25 artifact；warm `31.14s` 才比 v63 快约 `2.02x`。这是持久化一次性写成本，不隐藏该负结果。

两个数据集的 cold/warm index ID、passage checksum、sparse checksum 和 top-10 probe 逐项一致。
HotpotQA cold/warm 报告 SHA-256 分别为
`4076b082fd7d5a83e6489e0fd7b9c0f65e084f43996904219333c803e0242117`、
`be9cd638c21e00c066a486c46618834b443f0a028e304bf2988e62fbfb126513`；2Wiki 分别为
`0caa4c5a0e168ba192e7f0495678e396151ac4c797e3a81b40efb36489453464`、
`35253c791b9118c05189a8ca853d6ec26921e2cc242bdec6143e01f094c61578`。

## 5. 测试与失败注入

新增测试覆盖：高重复 provenance 不得逐 occurrence 调用 `Passage.model_copy`；warm 构建不得调用
`SparseBM25Index.build`；破坏 `bm25.pkl` 后 checksum 必须失败、重建并写明
`sparse_index_invalid:ValueError`；真实工具 cold/warm 报告不可覆盖且 probe 相同。

```text
PYTHONPATH=src:. pytest -q tests/test_global_corpus_index_tool.py \
  tests/test_benchmark_corpus.py tests/test_retrieval.py
11 passed

PYTHONPATH=src:. pytest -q
301 passed, 1 skipped

PYTHONPATH=src:. python -m compileall -q src benchmark tools
git diff --check
均通过
```

`AGENTS.md` 引用的 `/home/test/.codex/RTK.md` 在当前环境不存在，已检查并保留该缺失事实；未据此补写
任何不存在的额外规则。

## 6. Gate 决策

shared-index 数据管理门禁通过，但论文质量门禁仍失败：

* v64 没有改变 BM25 排序，也没有 answer-quality 对比，不能声称 SlotRAG-QO 提升；
* global Evidence Sufficiency 仍在使用无辨识度的 fused RRF score，v63 calibration 仍为 fail；
* physical action 仍主要是 telemetry，尚未真正触发 rewrite/switch/expand/backtrack；
* 没有多个 development slice 的 paired 2×2，也没有 unsupported-answer 与 quality-cost gate；
* 没有运行 frozen evaluation、baseline matrix 或 exact-upstream baseline。

下一版本只改 backend-aware sufficiency 特征并重新做 train/development calibration。该模块独立通过后，
再单独使 physical actions 改变执行路径；两者不能在同一不可消融补丁中同时引入。当前仍禁止昂贵
evaluation/full matrix。

