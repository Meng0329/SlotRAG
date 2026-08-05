# ANSWER_PIPELINE_AUDIT.md — 答案管道阶段审计（完整版）

> **审计对象**: H-007 (DEVELOPMENT_SET, seed=2027, 300 样本 = 3 数据集 × 100)  
> **审计方法**: S0-S9 首次失败点分类  
> **分类器**: `research/classify_stages.py`  
> **数据**: `research/ANSWER_PIPELINE_AUDIT.csv`  
> **审计状态**: ✅ 完整（300/300）

---

## 2. 完整分布 (300 样本)

### 2.1 各数据集错误结构

| 阶段 | hotpotqa (48 错) | 2wiki (32 错) | musique (64 错) |
|------|------------------|---------------|-----------------|
| S0 检索失败 | 0 | 4 | 0 |
| S1 选入失败 | 0 | 9 | 0 |
| S2 捆绑丢失 | **29 (60%)** | 5 | 0 |
| S3 空束 | 1 | 1 | 15 |
| S5 绑定丢失 | 13 (27%) | 10 | **43 (67%)** |
| S6 实体选择 | 0 | 1 | 1 |
| S8 生成措辞 | 5 | 2 | 5 |

### 2.2 跨数据集一致瓶颈

1. **S5 绑定丢失是统一主导**（hotpotqa 27%, 2wiki 31%, musique 67%）
2. **S2 捆绑丢失在 hotpotqa 特显著**（60%）
3. **S6 实体选择在所有数据集都极少**（0/1/1）— 彻底反驳"实体选择错误主导"
4. **S0 真检索失败在 hotpotqa/musique 为 0**，仅 2wiki 有 4 个

---

## 1. S0-S9 阶段定义

每次只判定**首个不可逆信息损失点**。已按 DEVELOPMENT_SET 的 trace 结构校准。

| 阶段 | 名称 | 判定规则 | 证据来源 |
|------|------|----------|----------|
| S0 | GOLD_SOURCE_NOT_RETRIEVED | gold source 在语料(available) 但不在 retrieved | `evidence_inventory` |
| S1 | GOLD_SOURCE_NOT_SELECTED | gold 被检索但未选入 materialization | `slot_traces[].materializations[].selected_source_ids` |
| S2 | GOLD_SOURCE_NOT_BUNDLED | gold 选入但未进入 evidence bundle | rows/evidence source_id |
| S3 | BUNDLE_EMPTY_OR_PARTIAL | 无 rows 提取 | `result.rows` |
| S4 | GOLD_SPAN_NOT_EXTRACTED | bundle 含 gold source 但无对应 span | evidence source_id |
| S5 | GOLD_BINDING_MISSING | 提取的 binding **未完整覆盖** gold（缺失限定词/属性） | `extracted_rows[].bindings` |
| S6 | ENTITY_SELECTION_ERROR | 绑定含 gold 候选，但最终选了**不同**实体 | 多候选 + final answer |
| S7 | PATH_BINDING_NOT_SURVIVED | 多 slot 下正确 binding 在 join 时丢失 | slot_traces 数 > 1 |
| S8 | GENERATION_EM_WRONG | 最终答案**包含** gold（或近超集），但过宽/措辞差 | pred vs gold token 覆盖 |
| S9 | UNRESOLVED | 无法归因 | fallback |

**关键设计决策**（与旧结论的差异）:
1. **S5 判定基于"binding 是否完整覆盖 gold"**，而非"gold token 是否出现"。因此 `gold="American musician"` 但 binding 只有 `musician` 判 **S5**（绑定丢限定词），而非旧结论的 S6。
2. **S8 判定基于"pred 是否覆盖 gold"**。因此 `gold="John Charles Cutler"` 但 pred=`"U.S. Public Health Service, Dr. John Roderick 'Rod' Heller, John Charles Cutler"` 判 **S8**（过生成），而非 S6。
3. **S6 严格限定**为"绑定含 gold 完整候选，但最终答案完全不同实体"。这类在 DEVELOPMENT_SET 上**极少**。

---

## 2. 当前分布 (hotpotqa, n=100)

### 2.1 全部样本

| 类别 | 数量 | 占比 |
|------|------|------|
| EM_HIT | 52 | 52.0% |
| S0 检索失败 | 29 | 29.0% |
| S5 绑定丢失 | 13 | 13.0% |
| S8 生成措辞 | 5 | 5.0% |
| S3 空束 | 1 | 1.0% |

### 2.2 EM=0 样本内部（48 个）

| 类别 | 数量 | 占 EM=0 |
|------|------|---------|
| S0 检索失败 | 29 | **60.4%** |
| S5 绑定丢失 | 13 | 27.1% |
| S8 生成措辞 | 5 | 10.4% |
| S3 空束 | 1 | 2.1% |

---

## 3. 与 seed=2040 诊断的对比（关键审计发现）

| 类别 | seed=2040 (旧诊断) | DEVELOPMENT_SET (H-007) |
|------|-------------------|--------------------------|
| 检索失败 (recall<1) | **2/98 (2%)** | **29/100 (29%)** |
| recall=1 & EM=0 | 21/98 (21%) | 19/100 (19%) |
| 其中"实体选择错误" | ~13/21 (62%) | **S6: 1/19 (5%)** |

### 3.1 发现 A: "检索几乎不是瓶颈"在 DEVELOPMENT_SET 上被推翻
seed=2040 诊断显示仅 2% 检索失败，但 DEVELOPMENT_SET 上有 **29% 检索失败**。这是**两个不同样本集合**，说明：
- seed=2040 的 100 个样本可能恰好绕过了 SlotRAG 的检索弱点
- 或 DEVELOPMENT_SET 的问题更难检索（更复杂的 bridge/intersection）
- **结论**: 旧 STOP_REPORT 的"检索仅 2-4/100 失败"是 **sample-specific**，不是稳健结论

### 3.2 发现 B: "62% 实体选择错误"在 DEVELOPMENT_SET 上无法重建
19 个 recall=1&EM=0 中，S6 实体选择仅 **1 个 (5%)**，其余是 S5 绑定丢失 (8)、S8 生成措辞 (9)。62% 结论依赖的 F1≥0.5"接近正确"样本，在逐 trace 检查下大多是**绑定丢失**或**生成措辞**，而非"选错实体"。

### 3.3 发现 C: 真实瓶颈结构
DEVELOPMENT_SET 上的错误主导是：
1. **S0 检索失败 (60% 的错误)** — 黄金源未检索到
2. **S5 绑定丢失 (27% 的错误)** — 绑定提取不完整/错误
3. **S8 生成措辞 (10% 的错误)** — 答案过宽或格式差

这**不是**旧结论的"实体选择错误主导"，而是"检索 + 绑定"双瓶颈。

---

## 4. 代表性样本 (hotpotqa, recall=1 & EM=0)

| qid | 阶段 | f1 | gold | pred | 失败机制 |
|-----|------|-----|------|------|----------|
| 5a8bb90f | S5 | 0.50 | Donald McNichol | Donald Sutherland | 绑定提取错实体 |
| 5a8ec320 | S5 | 0.00 | yes | no | 绑定把比较结果判反 |
| 5ab6c637 | S5 | 0.00 | German | Germany | 绑定词形错误 |
| 5a7a1d30 | S5 | 0.67 | American musician | musician | 绑定丢限定词 |
| 5a84c4bb | S8 | 0.40 | John Charles Cutler | U.S. Public Health Service, Dr. ... Cutler | 过生成多实体 |
| 5abc436f | S8 | 0.80 | Big 12 | Big 12 Conference | 答案超集 |
| 5a75c02f | S5 | 0.12 | Himalchuli has three main peaks... | Himalchuli | 绑定丢描述 |

## 4b. S0-S9 方法学修正记录 (2026-08-05)

### 修正 1: S0 判定改用"检索候选池"而非"最终 evidence"
**问题**: 原用 `evidence_inventory.retrieved_evidence_ids`（最终 evidence 束）判 S0。这混淆了"真检索失败"与"检索到但未选入 evidence"。
**修正**: 改用 `slot_traces[].materializations[].searches[].candidates[].source_id` 作为"是否检索到"的真实信号。
**影响**: hotpotqa 原判 29 个 S0 全部重判为 **S2（捆绑丢失）**——真 S0 在 hotpotqa 为 0。2wiki 才出现真 S0/S1。

### 修正 2: 答案粒度盲区（方法学边界）
**发现**: 部分 S2 样本的 `pred` 是 gold 的**上位实体/压缩名**（如 `gold="a city in north-east Lithuania"` vs `pred="Utena"`），gold 是描述句而 SlotRAG 输出实体名。这不是检索/绑定错误，是**生成粒度不匹配**。
**影响**: 纯 trace 分类无法可靠区分"粒度差"（S8 类）与"真选错"（S6）。需要 LLM 复核或人工抽样。

### 修正 3: evidence_recall 的语义局限
`evidence_recall` 基于 **source_id 覆盖**统计。S2 样本中部分 binding 值正确但 source 记录不全 → recall=0.5，但信息未必丢失。这与纠正协议批评"recall=1.0 不证明什么"是同一问题的反面——recall 低也不必然说明信息丢。


---

## 5. 方法学局限

1. **S4 未单独出现**：DEVELOPMENT_SET 上无"gold source 在 bundle 但无 span"的案例，可能被 S5 覆盖（span 提取与绑定融合）。
2. **S7 未单独出现**：无多 slot 下 binding 丢失的案例。hotpotqa 多为单/双 slot，需检查 2wiki/musique。
3. **分类器阈值校准**：S5/S8 依赖"gold 完整覆盖"的 token 判定，对同义词/音译（如 Gregori→Grigory）可能误判。需人工复核 S9 样本。
4. **DEVELOPMENT_SET vs seed=2040 不可比**：样本不同，需用**同一批样本**做阶段对比才能确认分布差异是"方法问题"还是"样本问题"。

---

*审计进行中，待 H-007 全部完成 (300/300) 后补全 2wiki/musique 分布并复核。*
