# DECISIONS.md — 决策日志

> **维护者**: documentation-writer agent  
> **最后更新**: 2026-08-04T21:00:00Z

---

## 决策记录

### D-001: Phase 0 审计方法
- **日期**: 2026-08-04
- **决策**: 只读审计，不修改核心代码
- **理由**: 确保审计结果的客观性，避免污染历史数据
- **证据**: CURRENT_STATE_AUDIT.md
- **影响**: 所有历史结论基于 contaminated eval，需撤销

### D-002: Split 错配处理
- **日期**: 2026-08-04
- **决策**: 撤销所有 "超 90% SOTA" 结论
- **理由**: V6c train split (seed=314159) 与 baseline eval split (seed=2040) 0% 重叠
- **证据**: agent 2 逐 qid 验证
- **影响**: 必须在 SEALED_FINAL_SET 上重新评估

### D-003: Eval 暴露处理
- **日期**: 2026-08-04
- **决策**: seed=2040 eval 样本标记为 CONTAMINATED
- **理由**: 已运行多个 baseline，不能用于 Tier4/Tier5
- **证据**: EXPOSED_SAMPLE_REGISTRY.csv
- **影响**: 需要构造新的 SEALED_FINAL_SET

### D-004: Baseline 适配状态
- **日期**: 2026-08-04
- **决策**: 所有 baseline 标记为 adapted
- **理由**: exact_upstream_execution: false, manifest UNVERIFIED
- **证据**: manifest.json
- **影响**: adapted baseline 不能作为 exact upstream 用于主覆盖率

### D-005: 有效样本数处理
- **日期**: 2026-08-04
- **决策**: 主表必须报告 valid_n / total_n
- **理由**: planrag 有 6% timeout failures，有效样本数不一致
- **证据**: per_question.csv
- **影响**: 统计分析需处理不同有效样本数

### D-006: drop 主指标改用 drop_f1
- **日期**: 2026-08-04
- **决策**: drop 数据集主指标从 EM 改为 drop_f1
- **理由**: SQuAD EM 对所有方法均 ~0.01，因为 drop 答案是数字/区间，SQuAD 归一化无法处理
- **证据**: seed=2040 诊断结果（hybrid/ircot/react/srag/graphrag/slotrag 均 0.01）
- **影响**: drop 单元格在覆盖率矩阵中使用 drop_f1

### D-007: 诚实负结果记录（Phase 2 诊断）
- **日期**: 2026-08-04
- **决策**: 在 eval split 上 SlotRAG Strongest-Baseline Coverage = 0/10，如实记录
- **理由**: 预注册协议要求诚实记录，绝不修改统计口径
- **证据**: SOTA_LEDGER.md 诊断矩阵（seed=2040, n=100）
- **影响**: 所有"超90% SOTA"结论最终撤销；Phase 3 假设循环必须从 0/10 基线开始改进

### D-008: 三集合构造参数冻结
- **日期**: 2026-08-04
- **决策**: 采用 30/30/40 划分，seed=2027，三集合互斥（31,381 唯一样本）
- **理由**: 与执行配置 random_seed=2027 一致，确保可复现
- **证据**: research/eval_sets/{development,validation,test}_set.json + checksums
- **影响**: 任何方法冻结前不得访问 validation/test 集

### D-009: 功效分析结论
- **日期**: 2026-08-04
- **决策**: n=100 已满足统计功效（α=0.05, power=0.80, δ=5% 所需 n=2-18）
- **理由**: EM/F1 是低方差指标，当前可检测效应约 1-2%
- **证据**: research/power_analysis.json
- **影响**: n=100 可作为快速初步验证；Tier4/5 仍优先完整官方集

---

## 决策模板

```markdown
### D-XXX: [决策标题]
- **日期**: [ISO-8601]
- **决策**: [具体决策]
- **理由**: [为什么做这个决策]
- **证据**: [支持决策的证据]
- **影响**: [这个决策的影响]
```

---

*本文件由 documentation-writer agent 维护。*
