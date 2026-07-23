# VLDB 2027 实验执行计划 v31

## 目标

建立可投稿、可复核、可重新分析的实验闭环。任何结果只有在 baseline 入口、数据 split、模型/提示词、答案解析、失败分母和原始调用记录都可追溯时，才允许进入论文主表。现有 `main_comparison` 和 `rescored-v2` 只作为本地适配器诊断，不进入投稿结论。

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
