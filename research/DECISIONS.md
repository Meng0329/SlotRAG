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
