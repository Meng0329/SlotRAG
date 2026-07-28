# SlotRAG research reset 交接文档（截至 2026-07-28，v73b）

## 任务

继续 SlotRAG 的 research reset：以 `global_corpus` 为主协议，定位真实性能上限，开发具有数据管理与查询优化内涵的 `slotrag-qo`，完成可审计的消融、成本、统计和失败分析。禁止在 evaluation split 调参、按单例堆 guard、隐藏负结果或把 adapted baseline 写成 exact upstream/SOTA。

当前最紧迫的研究问题不是继续扩大 top-k，而是解决“正确证据已进入候选池，但结构化抽取只保留错误/单一 binding”的瓶颈。

## 先读这些文件

1. `docs/slotrag-handoff-2026-07-26.md`
2. `docs/optimization-audit-v54.md`
3. `docs/optimization-audit-v63.md` 至 `docs/optimization-audit-v71.md`
4. `docs/SlotRAG：面向 VLDB 2027 的轻量新型 RAG 方法.md`
5. `src/slotrag/retrieval.py`
6. `src/slotrag/planner.py`
7. `src/slotrag/benchmarking/runner.py`
8. `tools/analyze_slotrag_headroom.py`
9. `tools/analyze_dual_access_bundle.py`

仓库存在 `.codegraph/`，理解或定位代码时必须先运行 `codegraph explore "..."`。仓库指令引用的 `/home/test/.codex/RTK.md` 在本机不存在。

## 当前代码状态

- 工作目录：`/data/mzb/SlotRAG`
- 分支：`main`
- HEAD：`4551e8a feat(retrieval): add heterogeneous dual access sparse retrieval support`
- 工作树：clean
- 全量测试：`PYTHONPATH=src:. pytest -q` -> `343 passed, 1 skipped`
- 已知非失败警告：`pytest-asyncio` 的 `asyncio_default_fixture_loop_scope` 弃用警告
- `git diff --check`：通过

提交 `4551e8a` 包含 v73/v73b 配置、异构稀疏访问路径、预算包装、telemetry、分析工具和测试。可用 `git show --stat 4551e8a` 查看完整修改清单。

## 已完成工作

### 1. 找到并纠正 v73 协议错位

旧离线 headroom 实际组合为：

- `slot`：v63/v66 trace 中的 body-only BM25；
- `question_plus_lexical_slot`：在 v72 BM25F 索引上的重放。

旧 v73 runtime 却把两路都走成 BM25F，原因有两层：

- `HybridRetriever.search_batch()` 不能逐查询指定字段访问模式；
- `_BudgetedRetriever` 没有 `search_batch()`，planner 被迫回退到标量 `search()`。

旧目录 `runs/slotrag-qo-dual-access-gate-v73-global` 必须保留，但不能再解释为异构访问实验，也不能覆盖或删除。

### 2. 实现真实异构物理访问路径

已实现：

- 同一持久化 BM25F 索引中，一路按 body-only 打分，另一路按 configured BM25F 打分；
- 两个逻辑查询共享一次 filtered-postings batch scan；
- planner 固定传递 `sparse_access_modes=["body", "configured"]`；
- dense/reranker 模式若请求异构 sparse access 会显式报错，不会静默忽略；
- `_BudgetedRetriever.search_batch()` 按逻辑查询数扣预算并转发模式；
- trace 记录每条 search 的 `sparse_access_mode`；
- materialization policy 记录为 `heterogeneous_dual_bundle`。

真实 HotpotQA 大索引重放已逐项复现冻结结果：

- body：`Red Stars Theory`, `James Bertram`, `Luckyhorse Industries`, ...
- configured BM25F：`James Bertram`, `Thomas Bertram`, `Bertram Sharp`, ...

### 3. 生成带严格 provenance 的 v73b 离线 headroom

不可变产物：

- `runs/slotrag-qo-heterogeneous-access-headroom-v73b-development`
- `runs/slotrag-qo-heterogeneous-access-headroom-v73b-validation`

工具现在会验证 source-run manifest checksum、source retrieval 默认为 body、BM25F index ID/checksum/title weight，并在 validation 强制使用 development 冻结 spec。

| split | n | baseline recall | bundle recall | full-support baseline -> bundle | gain/tie/loss |
| --- | ---: | ---: | ---: | ---: | ---: |
| development | 80 | 0.509375 | 0.756250 | 0.2625 -> 0.5250 | 38/42/0 |
| disjoint validation | 80 | 0.556250 | 0.756250 | 0.3000 -> 0.5375 | 31/49/0 |

这只是候选证据上界，不是 answer-quality 提升。

Manifest SHA-256：

- development：`78c4e58dd6224bc69307ca3d852ad858d989e3bb9785f3af7f5c63c9eb27e122`
- validation：`8bf9bc44ce1f9cbfc5caf883203c5ac3ac7ad240e2433a42469e971677f96485`

### 4. 完成 v73b global-corpus 端到端 smoke

运行目录：`runs/slotrag-qo-heterogeneous-access-gate-v73b-global`

- 2 datasets × 3 methods × 4 train questions = 24 records
- `24/24` final、`24/24` immutable attempts、全部 `ok`
- trace 缺失 0、retry 0、timeout 0、infrastructure failure 0
- 8/8 frozen plans 有效，24 次 replay，无 hash/provenance mismatch
- gate：`analysis_ready_nonpublication`
- publication blockers：`smoke_stage_not_for_publication`、`training_split_not_for_publication`

宏平均：

| method | primary | EM | recall@5 | precision@5 | retrieval calls | passages | tokens | wall ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| slotrag | 0.5417 | 0.5000 | 0.4688 | 0.2000 | 1.625 | 8.125 | 3334.9 | 27473 |
| slotrag-dual-access | 0.6250 | 0.6250 | 0.5313 | 0.2250 | 3.750 | 16.375 | 5193.6 | 30134 |
| slotrag-physical-dual-access | 0.6250 | 0.6250 | 0.5313 | 0.2250 | 3.750 | 16.375 | 5193.6 | 32373 |

按数据集：

- 2Wiki：三方法 primary 均 0.75；dual recall@5 从 0.5625 降至 0.4375。
- HotpotQA：primary 0.3333 -> 0.5000；recall@5 0.3750 -> 0.6250。

预注册方向的配对统计（treatment - reference）：

- primary：`+0.08333`，1 win / 7 ties / 0 losses；95% bootstrap CI `[0, 0.25]`；Holm `p=1.0`。
- recall@5：`+0.0625`，3 wins / 3 ties / 2 losses；CI 跨 0。
- retrieval calls：`+2.125`；passages：`+8.25`；tokens：`+1858.75`。
- physical 与 non-physical dual 的质量逐题 8/8 tie，physical 没有独立质量贡献，只增加延迟/LLM 开销。

结论只能写成“小样本正向诊断但 gate 未通过”，不能写稳定提升、SOTA 或投稿主结果。

关键 artifact SHA-256：

- run manifest：`2d1b601c9f994e34a2ebaad9d079e0d548063512295375b9cec2d36bf57bf6bd`
- records audit：`d39b9dfd66429836ad1aa9b9faca6fe4578fdc6e57d57bd838b73ad8aa7b09ff`
- gate status：`b446e9f7c3bde33f2b8b1a53193c7ae07fe53d036d5610b45bac4ee36239e0cd`
- summary：`835ff7ac158220e6d9de8472f6c09a8d075356a52797e7e365560846e34dcfac`
- paired analysis：`fd622bb2d2c88357283167a8ede36cb60b06769c5ad05ae621552fdd4281319f`

### 5. 完成 runtime headroom/error audit

目录：`runs/slotrag-qo-heterogeneous-access-runtime-audit-v73b`

`headroom.json` SHA-256：`f95a269980efee6059f154836f67c166cee086d17b16b490631d4d17012f74cd`

错误计数：

- `EXTRACTION_ERROR`: 5
- `EVIDENCE_PARTIAL`: 3
- `BINDING_PRUNED`: 1
- `RETRIEVAL_MISS`: 1

最大可利用机制为 structured-output/extraction failure：覆盖 25%，乐观平均上限 0.25。当前工具报告的 pairwise delta 是 `left - right`，所以 `slotrag` vs dual 的 `-0.08333` 与 paired tool 的 treatment-reference `+0.08333` 是同一结果，别再读反。

典型 gain：HotpotQA `5a88b65c...`。baseline 检索/回答 `Volusia Mall`；异构双路找到 `Mall of New Hampshire` 与 `Pheasant Lane Mall`，最终回答正确。

典型 failure：HotpotQA `5adeb192...`。候选池已有 `Luckyhorse Industries`，其 passage 明确列出 `Built to Spill`，但 S1 extraction 只输出 `Red Stars Theory`；后续执行得到 `count=1` 而 gold 为 `eight`。这证明下一瓶颈是多 binding extraction/physical evidence processing，而不是检索 guard。

## 重要 gotchas

1. **v73b smoke 的实际 execution profile 不符合用户期望的 Qwen/64 并发。** 虽然 YAML 写 `max_concurrency: 64`，`.env` 覆盖后 manifest 实际为 `agnes-2.0-flash`、每进程 `max_concurrency=4`、provider RPM 30、operational RPM 20。matrix 同时启动了 6 个进程。扩大实验前必须在不打印密钥的前提下修正环境，并检查新 manifest，而不是相信 YAML。
2. `.env` 含凭据；严禁在命令输出、文档或提交中打印值。当前只确认存在 `SLOTRAG_*` 变量，没有在交接中复制任何密钥。
3. v73b run 是在提交前的 dirty worktree 上运行的：manifest 基线 revision 为 `c260504`、`code_dirty=true`、source fingerprint 为 `ed0943aa...`。最终 clean commit `4551e8a` 包含相同实现，但正式扩大实验必须使用新 stage/新目录从 clean HEAD 重跑。
4. `runs/` 是实验产物区，很多文件被 gitignore；`git status` clean 不代表 run 不存在。
5. shared index registry 使用独立 manifest 加指向 v72 大索引的 symlink。新 stage 若未注册会重建近 90 万 chunks；必须先校验 index ID/checksum，不能覆盖旧 registry manifest。
6. provider 输出并非完全确定；跨 run 的 baseline 分数会漂移。只在同一 run、同一 frozen plan、同一问题上做 paired comparison。
7. 旧 sufficiency calibrator 与当前异构访问分布不兼容，尚未运行要求中的完整 sufficiency 2×2；不要直接复用旧阈值。
8. exact upstream baseline 仍未执行；adapted baseline 不能用于 SOTA 声明。
9. local-context v73b smoke 尚未运行；global-corpus 应继续作为主结论协议。

## 尚未完成

- `docs/optimization-audit-v72.md` 与 v73/v73b 独立审计文档尚未写。
- 主方法文档尚未同步 v72/v73b；目前尾部只到 v71。
- v74 path-aware extraction 尚未实现，当前没有相关代码。
- 尚未完成新方法的正式 2×2 sufficiency × physical policy。
- 尚未在 clean、冻结、较大 development slice 上复现 v73b 的 answer gain。
- 尚未运行 evaluation split、完整 global-corpus 主结果或 exact upstream baseline。
- 当前远未达到 VLDB 可投稿实验状态，也没有证据支持 80% SOTA 覆盖。

## 下一步（按顺序）

1. 先同步文档：新增 `docs/optimization-audit-v72-v73b.md`，并将 v72 null、v73 协议错位、v73b 正负结果和上述 hash 追加到主方法文档。
2. 校正运行环境：安全加载 Qwen3.6 配置（若仍按用户要求），让新 manifest 明确记录目标 model、RPM 30/20 和预期并发；不要输出 key。
3. 用新版本号（建议 v73c）从 clean `4551e8a` 重跑同一 8 题诊断，只验证 provenance 和 v73b 可复现性。旧目录不可覆盖。
4. 设计 v74 的 deep module：在 retrieval 与 extraction 之间建立“physical evidence bundle” seam。至少保留两个真实 adapter：现有 single-union extraction（control）和 path-aware extraction/structured merge（treatment）。不要再给 `SlotMaterializer` 堆布尔 guard。
5. v74 必须支持一对多 binding：分路抽取、按 source/binding 去重、保留多个可达 binding，并记录正确路径是否在抽取或 beam 阶段丢失。先写接口级测试，再接 runtime。
6. 用冻结 plans、相同 train questions 做小型 paired smoke；主 gate 同时检查 primary、unsupported answers、candidate->extraction retention、binding recall、calls/tokens/latency。
7. 只有多个 development slice/seed 均复现、CI 不再完全由单例驱动且成本收益合理，才扩大样本并重训兼容的 sufficiency calibrator，然后跑正式 2×2。
8. evaluation split 在配置冻结前保持完全不触碰。

## 复现命令

测试：

```bash
cd /data/mzb/SlotRAG
PYTHONPATH=src:. pytest -q
```

离线 headroom（provider-free）：

```bash
PYTHONPATH=src:. python tools/analyze_dual_access_bundle.py \
  --headroom-dir runs/slotrag-qo-query-headroom-v72-development \
  --output-dir <new-empty-development-dir> \
  --role development_selection --per-path-top-k 5 --project-root .

PYTHONPATH=src:. python tools/analyze_dual_access_bundle.py \
  --headroom-dir runs/slotrag-qo-query-headroom-v72-validation \
  --output-dir <new-empty-validation-dir> \
  --role disjoint_validation --per-path-top-k 5 \
  --frozen-spec <development-dir>/bundle-spec.json --project-root .
```

标准审计：

```bash
PYTHONPATH=src:. python -m slotrag.cli benchmark records-audit <stage> \
  --output-dir <run-dir> --require-trace --output <run-dir>/records-audit.json

PYTHONPATH=src:. python -m slotrag.cli benchmark gate <stage> \
  --output-dir <run-dir> --require-trace --allow-diagnostic-adapters \
  --output <run-dir>/gate-status.json

PYTHONPATH=src:. python -m slotrag.cli benchmark summarize <stage> \
  --output-dir <run-dir>
```

## 建议 skills

- `codebase-design`：设计 v74 physical evidence bundle seam 时使用；已读 `SKILL.md` 和 `DEEPENING.md`。
- `results-analysis`：每个版本完成后做配对统计、null result 和成本分析。
- `diagnosing-bugs`：若 batch budget、index reuse、trace provenance 或 provider profile 再次不一致时使用。
- `academic-paper` / `paper-self-review`：仅在冻结评测和 exact/upstream 可比实验完成后使用，不要提前包装当前 smoke。

## 交接边界

本交接生成时没有后台实验进程。不要覆盖任何现有 run；所有新实验使用新 stage 和新输出目录。性能没有提高时应停止堆补丁，记录 null result 和瓶颈。
