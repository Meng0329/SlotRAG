# FROZEN_PROTOCOL.md — SlotRAG-X 预注册实验协议（冻结版）

> **协议版本**: v1.0  
> **冻结时间**: 2026-08-04  
> **冻结状态**: 冻结后禁止修改，除非通过修正案流程  
> **协议归属**: SlotRAG-X PVLDB 2027 研究

---

## 1. 研究问题

RQ1: SlotRAG-X 在主要质量指标上是否系统性地领先最强合法 baseline？

RQ2: SlotRAG-X 的领先是否在统计上可支持、在 artifact 上可复现、在机制上可解释？

---

## 2. 主要指标定义

### 2.1 Strongest-Baseline Coverage

**单元格** = dataset × 预注册 primary metric × matched-budget regime

**每格只与该 regime 下最强合法 baseline 比较**（最强 baseline 在看 SlotRAG 结果前冻结）。

```
Strongest_Baseline_Coverage =
    SlotRAG-X 严格领先最强合法 baseline 的单元格数 /
    全部预注册合法可比单元格数
```

### 2.2 预注册指标矩阵

| 数据集 | Primary Metric | 说明 |
|--------|---------------|------|
| hotpotqa | EM, F1 | SQuAD/HotpotQA 标准归一化 |
| 2wikimultihop | EM, F1 | SQuAD/HotpotQA 标准归一化 |
| musique | EM, F1 | SQuAD/HotpotQA 标准归一化 |
| strategyqa | accuracy | 二值分类 |
| drop | **drop_f1** | SQuAD 归一化 EM 对 drop 无效（全部 ~0.01），改用 drop 官方 F1 |

> **审计发现**: drop 的 SQuAD EM 对所有方法均 ~0.01，因为 drop 答案是数字/区间，SQuAD 归一化无法处理。主指标改用 `drop_f1`。

### 2.3 "领先"的统计定义

每主要单元格报告：
- paired delta
- 95% bootstrap CI（1000 次重采样）
- effect size（Cohen's d）
- corrected significance（Bonferroni/Holm）
- valid_n / failed_n / timeout_n / retry 次数 / 实际成本

分级：
1. **Statistically supported win**: p<0.05 且 95% CI 不含 0 且 effect size>0.2
2. **Point-estimate-only win**: 点估计领先但 CI 含 0
3. **Tie/inconclusive**: CI 含 0 且无显著差异
4. **Loss**: 点估计落后

"≥80% 统计支持"只在预注册主要单元格上计算。

---

## 3. 数据与样本治理

### 3.1 已污染样本（不可用于正式评估）

- **CONTAMINATED_EVAL_DIAGNOSTIC_SET**: seed=2040, n=100/dataset 的 eval 样本
- 用途：协议审计 / 历史复核 / 失败分类 / baseline 复现检查 / 开发诊断
- 禁止：Tier4 validation / Tier5 evaluation / 论文主表 / SOTA_Coverage / 首次独立验证

### 3.2 三集合

从从未运行、从未看逐题结果的干净评估样本中构造：

| 集合 | 用途 | 结果可见性 |
|------|------|-----------|
| DEVELOPMENT_SET (30%) | 开发调试，可反复看结果 | 开放 |
| DISJOINT_VALIDATION_SET (30%) | 方法冻结前不看结果 | 封存 |
| SEALED_FINAL_SET (40%) | 封存，方法冻结前完全不读取 | 完全封存 |

构造参数：
- seed = 2027（与 execution.random_seed 一致）
- 采样脚本: `research/build_three_sets.py`
- 产物: `research/eval_sets/{development,validation,test}_set.json`
- 校验和: `research/eval_sets/*_set.sha256`

### 3.3 数据集完整性

dataset checksums 记录于 `runs/vldb2027-submission-qwen36-v3-rescored-v2-final/manifest.json` 的 `dataset_audit` 字段。

---

## 4. Baseline 管理

### 4.1 Baseline 合法性分级

| 级别 | 定义 | 可否进主覆盖率 |
|------|------|---------------|
| exact upstream | 官方实现，exact_upstream_execution_verified=true | ✅ |
| faithful reproduction | 经审计的忠实复现 | ✅ |
| adapted | 相同数据+模型+预算+语料+评分口径，非官方实现 | ❌（只能进补充表或 adapted comparison） |

### 4.2 当前 baseline 状态

**所有 baseline 均为 adapted**（`exact_upstream_execution: false`）。

因此：
- 主覆盖率矩阵中的 baseline 比较为 **adapted comparison**
- 论文必须声明所有 baseline 是 adapted 实现
- 不能声称与官方实现进行了对比

### 4.3 预算一致性

所有 baseline 共享相同预算和模型（qwen3.6-27b, max_tokens=2048, temperature=0.0, max_steps=4, max_llm_calls=64, max_retrieval_calls=4, question_timeout=300s）。

---

## 5. 实验分级 (Tier)

| Tier | 用途 | 样本量 | 集合 | 结果可见性 |
|------|------|--------|------|-----------|
| Tier 0 | 冒烟测试（管道正确性） | 5 | DEVELOPMENT | 开放 |
| Tier 1 | 快速迭代（假设验证） | 20 | DEVELOPMENT | 开放 |
| Tier 2 | 初步验证 | 100 | DEVELOPMENT | 开放 |
| Tier 3 | 扩展验证 | 500 | DISJOINT_VALIDATION | 封存（方法冻结前不看） |
| Tier 4 | 预注册验证 | 完整官方 | SEALED_FINAL | 完全封存 |
| Tier 5 | 最终评估 | 完整官方 | SEALED_FINAL | 一次性运行 |

---

## 6. 样本量（功效分析结论）

基于 seed=2040 baseline 结果，α=0.05, power=0.80, δ=5%：

| 数据集 | EM 所需 n | F1 所需 n | 当前 n | 结论 |
|--------|----------|----------|--------|------|
| hotpotqa | 16 | 11 | 100 | ✅ 足够 |
| 2wikimultihop | 16 | 14 | 100 | ✅ 足够 |
| musique | 18 | 15 | 100 | ✅ 足够 |
| strategyqa | 8 | 8 | 100 | ✅ 足够 |
| drop | 2 | 6 | 100 | ✅ 足够 |

**结论**: n=100 已满足功效要求。当前可检测效应约 1-2%，非常敏感。完整官方集为 Tier4/5 首选，n=100 可作为快速初步验证。

**约束**: baseline 与 SlotRAG 必须完全同 sample IDs；不得只扩大 SlotRAG 样本量。

---

## 7. 失败处理

### 7.1 失败分类

| 状态 | 含义 | 处理 |
|------|------|------|
| ok | 正常 | 计入有效样本 |
| timeout | LLM 超时 | 重试 2 次，失败标记 |
| planning_failed | 规划失败 | 保留，标记 |
| retrieval_failed | 检索失败 | 保留，标记 |
| generation_failed | 生成失败 | 保留，标记 |

### 7.2 规则

- 不排除失败样本，保留在结果中
- 统计分析用 valid_n（非 failed）
- 主表报告 valid_n / total_n
- 失败率 > 10% 的方法需标注并解释

---

## 8. 统计分析流程

1. **描述统计**: mean, std, median, min, max, valid_n
2. **Bootstrap CI**: 1000 次重采样，95% CI
3. **配对检验**: Wilcoxon signed-rank test（非正态）
4. **效应量**: Cohen's d 或 Cliff's delta
5. **多重比较校正**: Holm-Bonferroni

统计软件: scipy.stats, numpy

---

## 9. Artifact 完整性

### 9.1 每个实验必须生成

- manifest.json（seed, sample_size, methods, datasets, budget, code_revision, environment）
- per_question.csv（逐题结果）
- summary.json（聚合统计）
- adapter-audit.json（如适用）

### 9.2 可复现性

- 记录 git commit + dirty 状态
- 记录 data checksums
- 记录 model/temperature/seed
- 记录 environment（python, packages）

---

## 10. 工程隔离

### 10.1 写入前
1. 确认 git commit
2. 保存 git diff + dirty 状态
3. 创建独立研究分支或 worktree
4. 创建审计前 checkpoint/tag
5. 不覆盖/移动/删除历史 runs
6. 新结果写入带时间+commit+experiment_id 的新目录

### 10.2 禁止命令
`git reset --hard` / `git clean -fd|-fdx` / `git push --force` / `rm -rf` 指向仓库根/数据目录/历史 runs / 删除 checkpoint / 修改原始数据 / 覆盖历史产物

### 10.3 门禁
- 全程不用 bypass permissions，手动审批或受限 sandbox
- Tier 2+ 在线实验前停下来等批准
- 费用超限时停下来
- 下载大模型或数据前停下来
- 修改数据划分前停下来
- 运行 sealed final eval 前停下来
- 上传远程前停下来

---

## 11. 停止条件

触发 STOP_REPORT.md 的条件：
- 连续 5 假设未过 gate
- Strongest-Baseline Coverage < 目标（在预算内无法达到）
- 重大数据完整性/污染问题无法修复
- 用户明确要求停止

---

## 12. 修正案流程

协议冻结后，任何修改必须：
1. 记录修改理由（证据）
2. 记录修改内容
3. 记录修改对结论的影响
4. 由用户审批

---

*协议版本: v1.0*  
*冻结时间: 2026-08-04T21:40:00Z*  
*冻结人: SlotRAG-X 研究团队*
