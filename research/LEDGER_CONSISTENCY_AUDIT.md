# LEDGER_CONSISTENCY_AUDIT.md — 账本一致性审计

> **审计时间**: 2026-08-05  
> **审计依据**: Phase 3R 纠正协议第二节  
> **状态**: 已修复

---

## 1. 修复项清单

### 1.1 EXPERIMENT_LEDGER.csv

| 问题 | 修复前 | 修复后 | 说明 |
|------|--------|--------|------|
| E2 状态 | running | completed | Tier 1 三配置对比已完成 |
| E6 状态 | running | completed | H-005 已拒绝 |
| E1-E7 split | evaluation | development | DEVELOPMENT_SET 实验不得标记为 evaluation split |
| E6 Tier 标记 | "Tier 2" | "Tier 1" | n=20 是 Tier 1，非 Tier 2 |

**保留项**: D1 仍是 evaluation（它是 diagnostics seed=2040，确实是 evaluation split）。

### 1.2 HYPOTHESES.md 假设重分类

| 假设 | 修复前 | 修复后 | 依据 |
|------|--------|--------|------|
| H-001 | rejected | **stratum_specific_signal** | 不得因 n=20/p=0.13 判死整个检索方向；musique +0.108 是信号 |
| H-002 | rejected | **rejected_exact_budget_configuration** | 只拒绝该具体预算配置 |
| H-003 | deferred | deferred | 未变 |
| H-004 | validated | **provisionally_supported_pending_stage_audit** | recall=1.0 ≠ 生成瓶颈;需阶段级审计 |
| H-005 | rejected | **rejected_exact_intervention** | 只拒绝 entity_answer_contract=True 这一个干预 |
| H-006 | proposed | proposed | 未变 |

### 1.3 STOP_REPORT.md

- 标记为 **PROVISIONAL**
- "62% 实体选择错误"/"生成是唯一根因"/"检索不是瓶颈"/"方向 C 最优"全部降级为**待审计假设**
- commit 引用修正: 撰写时 HEAD `1165faf` → 实际 HEAD `d675aa1`
- 方向 C 不再标记为"当前最优"，改为"待 Oracle 门禁决定"

### 1.4 Git commit 核对

| commit | 内容 | 角色 |
|--------|------|------|
| `1165faf` | H-005 REJECTED | STOP_REPORT 撰写时点 |
| `5bca169` | STATE 标记暂停 | 中间过渡 |
| `d675aa1` | H-005 实验+config | **实际 HEAD** |

**结论**: STOP_REPORT 记录的 `1165faf` 是撰写时的 HEAD，后续又有 2 个 commit，实际 HEAD 为 `d675aa1`。已记录两者关系，非错误，是时间差。

---

## 2. 数字一致性核对

| 数字 | 出处 | 状态 |
|------|------|------|
| 3/4 假设被拒 | STOP_REPORT/HYPOTHESES | ✅ 一致 |
| 21/98 hotpotqa recall=1&EM=0 | seed=2040 诊断 | ✅ 一致 |
| 21/100 2wiki recall=1&EM=0 | seed=2040 诊断 | ✅ 一致 |
| 13/21 (62%) 实体选择 | STOP_REPORT | ⚠️ **需重建**（见 ENTITY_SELECTION_CASES） |
| strategyqa accuracy=0.84 | seed=2040 | ✅ 一致 |

---

## 3. 已识别但未完全解决的问题

1. **13/21 的 62% 结论**: 尚未追溯到具体 question IDs，需 ENTITY_SELECTION_CASES.csv 重建
2. **S0-S9 阶段分类**: 尚未执行，需 ANSWER_PIPELINE_AUDIT
3. **Oracle headroom**: 尚未计算，需 ORACLE_HEADROOM

这些将在 Phase 3R 后续步骤完成。

---

*审计完成时间: 2026-08-05*  
*审计范围: EXPERIMENT_LEDGER / HYPOTHESES / STOP_REPORT / git commit*