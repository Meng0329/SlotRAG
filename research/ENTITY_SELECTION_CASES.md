# ENTITY_SELECTION_CASES 重建报告

> **重建对象**: 旧 STOP_REPORT 声称的 "13/21 (62%) 实体选择错误"  
> **数据源**: seed=2040, split=evaluation, n=100 (hotpotqa), `slotrag-grounded-binding-guard`  
> **判定方法**: 基于 `result.answer` 的逐样本失败类型裁决（含 pred/gold 全貌）  
> **结论**: ⚠️ **62% 结论无法重建** — 详见第 3 节

---

## 1. 重建的 22 个样本（recall=1 & EM=0）

> 旧诊断记 21 个，本次扫描到 22 个（f1 口径差异）。完整表见 `ENTITY_SELECTION_CASES.csv`。

### 1.1 失败类型分布

| 类型 | 数量 | 占比 | 说明 |
|------|------|------|------|
| S8_THINKING_LEAK | 14 | 64% | pred 是思考过程文本（Thinking Process / The user wants...） |
| S8_WORDING_SUPERSET | 5 | 23% | pred 是 gold 的超集/子集（措辞粒度差异） |
| S5_BINDING_WRONG_VALUE | 3 | 14% | 绑定值错误（含 1 个 yes/no 相反） |
| **S6_ENTITY_SELECTION** | **0** | **0%** | **无真实体选择错误** |

### 1.2 代表性案例

| qid | f1 | gold | pred | 真实失败类型 |
|-----|-----|------|------|-------------|
| 5a739b19 | 0.80 | Crown Holdings Incorporated | The user wants to know which company... | 思考泄漏 |
| 5a7be294 | 0.00 | December 19, 1998 | The user wants to know the start date... | 思考泄漏 |
| 5a80b9e8 | 0.00 | Rå | Thinking Process: 1. Analyze the Request... | 思考泄漏 |
| 5a749e18 | 0.67 | Emilio Ángel Sánchez Vicario | Thinking Process:... | 思考泄漏 |
| 5a9094ba | 0.57 | Richard Gerald "Dick" Purcell Jr. | Dick Purcell | 措辞子集（丢全名） |
| 5ab412da | 0.67 | eight | eight legs | 措辞超集 |
| 5ae3fd2c | 0.00 | no | yes | 绑定相反值 |

---

## 2. 为什么旧结论误判

旧统计（"F1≥0.5 → 接近正确 → 实体选择错误"）的错误机制：

1. **思考泄漏样本的 F1 虚高**：`The user wants to know which company... Crown Holdings Incorporated` 包含答案实体，所以 F1≈0.80。但**这不是有效答案**——它是推理文本泄漏。旧统计把这些计为"接近正确"。
2. **措辞差异被误判为"实体选择"**：pred 是 gold 的超集（`eight legs` vs `eight`）或子集（`Dick Purcell` vs 全名），本质是**答案粒度/措辞**问题，不是"从多个候选里选错实体"。
3. **无 trace 验证**：seed=2040 的旧 schema run 没有 slot_traces，无法验证"绑定里是否有正确候选"这一 S6 判定的前提。旧结论未经此验证就断言 S6。

---

## 3. 正式结论

> **"13/21 (62%) 实体选择错误" 无法重建，正式撤销。**

- 22 个 recall=1&EM=0 样本中，**0 个**符合 S6（绑定含正确候选但选错实体）的严格定义。
- 真实主导失败是 **思考过程泄漏（14/22, 64%）** —— 生成阶段输出格式失败，答案提取到了思考文本。
- 这与 DEVELOPMENT_SET (H-007) 的发现一致：**S6 实体选择在两类样本上都极少见**。

### 3.1 对 H-004 的影响
H-004（生成是瓶颈）的验证依赖"recall=1&EM=0 中 43% 明显错误、57% 接近正确"的统计。但：
- 若 57% 的"接近正确"实际是思考泄漏 → 不是"措辞可回收"，是**格式失败**
- 若 43% 的"明显错误"含思考泄漏（f1=0 的思考泄漏如 5a7be294）→ 分布需重估
- **H-004 的"生成是瓶颈"结论方向对，但具体归因（实体选择/措辞）错误**

### 3.2 对方向选择的影响
- 思考泄漏 → **答案提取/输出契约**问题，不是检索、不是绑定
- 这与 H-005（答案契约）被拒的相关性需重估：H-005 是"强制规范实体名"，但真实问题是"提取到思考文本"
- **方向 C（答案消歧）不直接解决思考泄漏**

---

*重建完成时间: 2026-08-05*  
*复核人: Phase 3R 审计（单审查者初裁，待第二位独立审查者确认）*  
*数据: runs/slotrag-binding-guard-fixed-main-eval-v1/* (seed=2040)
