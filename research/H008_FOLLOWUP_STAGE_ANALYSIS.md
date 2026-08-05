# H-008 后续根因分析 — 三数据集阶段分解（2026-08-05）

> 基于 H-008 treatment (`slotrag-per-path-extraction`) 数据，使用 gold_ids 驱动的精确阶段分类。
> 背景：H-008 (PerPath) 已 SUPPORTED（修复 S2），本分析定位 H-008 后的下一瓶颈。

## 方法：三阶段分类（gold_ids 驱动）

- **EM_HIT**: 答案正确
- **NOT_SELECTED_TO_EVIDENCE**（≈S1/S2）: gold 的 passage 在检索候选池但未进最终 evidence
- **BINDING_OR_GEN**（≈S4-S8）: gold 的 passage 已进 evidence 但绑定/生成错误
- **S0_NOT_RETRIEVED**: gold 未进检索候选池

hotpotqa/2wiki 有 gold_evidence_ids 标注，分类可靠。musique 无 gold_ids，用 text-based 补充分析。

## 结果

### hotpotqa treatment (n=100)
| 阶段 | 数量 | 占比 |
|------|------|------|
| EM_HIT | 50 | 50% |
| **BINDING_OR_GEN** | **43** | **43%** |
| NOT_SELECTED_TO_EVIDENCE | 7 | 7% |
| S0_NOT_RETRIEVED | 0 | 0% |

**解读**: S2 修复后（H-007 的 S2=29 → 现在 NOT_SELECTED=7），检索零失败，最大瓶颈是 BINDING_OR_GEN (43%)。

### 2wikimultihop treatment (n=100)
| 阶段 | 数量 | 占比 |
|------|------|------|
| EM_HIT | 71 | 71% |
| **BINDING_OR_GEN** | **28** | **28%** |
| NOT_SELECTED_TO_EVIDENCE | 1 | 1% |

### musique treatment (n=99, text-based 无 gold_ids)
| 阶段 | 数量 | 占比 |
|------|------|------|
| **EVIDENCE_NOT_SELECTED** | **37** | **37%** |
| EM_HIT | 35 | 35% |
| BINDING_OR_GEN | 27 | 27% |

对比 control (Union): EVIDENCE_NOT_SELECTED 40→37（-3），EM_HIT 28→35（+7）。
**musique 的 evidence 选择问题（37%）PerPath 几乎未修复**，这是 musique 特有瓶颈。

## BINDING_OR_GEN 细分（hotpotqa, gold 全进 evidence 的 23 样本）
| 模式 | 数量 | 占比 |
|------|------|------|
| **S5_WRONG_VALUE**（f1<0.5 绑定值完全错）| 12 | 52% |
| S8_PARTIAL_WORDING（f1 0.5-0.8）| 6 | 26% |
| S8_NEAR_CORRECT_WORDING（f1≥0.8）| 5 | 22% |

**核心**: 52% 是绑定值完全错（gold 在 evidence 但提取/传播了错误值），48% 是措辞问题。

## 三数据集统一结论

1. **hotpotqa/2wiki 下一瓶颈 = BINDING_OR_GEN (43%/28%)**，其中 52% 是 S5 绑定值错误
2. **musique 下一瓶颈 = EVIDENCE_NOT_SELECTED (37%)**，PerPath 未修复
3. **检索（S0）已非瓶颈**（hotpotqa 0%）
4. 干预方向：
   - 绑定值选择/传播改进（hotpotqa/2wiki 的 52%）
   - evidence 选入改进（musique 的 37%）
   - 措辞规范化（48% 的 S8，已被 H-005 证明无效）

## 相关假设状态
- H-006（生成推理）: 绑定值错误范畴，proposed 未验证
- H-005（答案措辞）: 已拒绝（只覆盖 S8 48%，且证明无效）
- H-003（evidence quality）: deferred，musique 37% 属此范畴
