# G5 Pre-Registration (草案): 反事实预算敏感性 importance estimator

**编号**: G5-PRE
**状态**: DRAFT (预注册草稿，待 Phase 10 冻结)
**日期**: 2026-08-17
**方向决策依据**: TKDE_DECISIONS 裁决 12-12e (用户裁定"最有顶刊潜力"= 反事实伪标注; 探针链 v1→v2→v3→多问句→真实数据已验证信号)。

## 1. 背景（诊断证据链）

- §11: 真实 `SlotCompiler.compile()` 从不设置 per-slot importance → 所有槽 importance=默认 1.0 (models.py:18) → G3 importance-weighted allocation 退化为 uniform → G3 ≡ static。**G3 requirement-aware allocation 无信号可消费。**
- 裁决 12-12e 探针链:
  - v1 (evidence 基线): 差分 False, calibrator 噪声掩盖。
  - v2 (binding 基线): S1 假阴性。
  - v3 (extracted_rows 基线): **干净差分成立** — 信号源 = `MaterializationTrace.extracted_rows[].bindings`。
  - 多问句: 4/4 稳定 (S1 门槛1/2, S2 门槛3)。
  - 真实数据: **5/6 真实 hotpotqa 链有稀缺槽**, 模式系统性 S1=1 充足 / 下游 S2/S3=3/5 稀缺。

**核心洞察**: per-slot importance 不是"发明", 而是"学习"。真实负载的**依赖链下游槽天然稀缺**(预算敏感), 上游实体解析槽充足。G5 estimator 学"依赖链位置 + 检索状态 → 预算敏感性(恢复门槛)"这个真实规律。

## 2. 假设 (G5-H)

**H-G5-1 (信号): 真实 2-hop 负载上, 链式 plan 的下游槽系统性地比上游槽更预算敏感(恢复门槛更高)。** 已获初步支持 (5/6 真实链, §12e), 待扩充样本正式确认。

**H-G5-2 (规律+机制): 良定义(末槽绑答案值)链上, per-slot 预算敏感性 = 确定性链结构规律 τ=2·depth−1; 喂给 G3 后, G3(chain-rule) 在 matched budget 下同 Coverage 严格优于 G3(flat)。** §17/12j 支持: 三数据 19 良定义链全部 τ=2d−1 零变差。content 特征无可学增量(learned estimator 坍缩为位置查表)。

## 3. Ground truth 定义 (冻结)

**per-slot budget-sensitivity = 恢复门槛阈值** (recovery threshold):
> 对固定 plan, 在真实语料上 sweep 全局检索预算 `B ∈ {1..K}`, 对每槽记录其**目标真值首次恢复的最小预算** `τ_slot = min{B : slot truth recovered in extracted_rows}`。
> - `τ=1`: 槽在 1 次 base call 即恢复 → 充足槽 → 低 importance。
> - `τ>1`: 槽需额外 call (EXPAND) 恢复窗外真值 → 稀缺槽 → 高 importance。
> - `τ=∞` (§14/裁决12g 新增): 槽在任意预算 B≤K 下皆未恢复 → **不可恢复槽** (检索覆盖缺失, 非稀缺; 不能靠加预算, 需换检索策略)。`K` 取决于 sweep 上限(§14 观察 musique/hotpotqa 各出现 2 例 S2=None).

信号源 (必须): `MaterializationTrace.extracted_rows[].bindings` 含该槽目标值 (裁决 12c 锁定)。**禁止**用 `rows` (低预算 abort 空)、`evidence` (calibrator 噪声)、`binding_contexts` (join 签名无目标值)。

**目标真值判定** (冻结):
- 人工语料 (§10 4 问句): 已知 gold 文档 (doc10 的 pop / doc1 的 country), 精确匹配。
- 真实数据 (hotpotqa): 无 per-slot gold → 用"materialize 出非空绑定"作 proxy (裁决 12e 采用), 明确记为 proxy, 限制: 可能高估恢复。**真实数据伪标注的 gold 定义待 Phase 10 前改进** (候选: 用 gold_evidence 的 passage → 若槽的 extracted_rows source_id ∈ gold passages 则真值恢复)。

**proxy 适用边界 (§15-16/裁决12h-12i, 冻结)**:
- τ 良定义 ⇔ **末槽 extracted_rows 绑定目标答案值** (纯实体/属性解析链, 常见 2-3 槽)。实证: 良定义收集器(裁决12i) 2wiki 6/9 链全部 τ={S1:1, S2:3}, 干净一致。
- τ 失效 ⇔ **末槽绑定 join/比较中间量** (分支链, ≥4 槽或答案需跨槽聚合)。实证: 2wiki 4-slot 链 S4 绑定 birthDate/director 中间量, 任何预算不含答案 'El Extraño Viaje', τ=6 是 proxy 冻结在 join 行首次 materialize 点。
- **排除成因(裁决12i)**: (a) 分支链/答案跨槽聚合; (b) **SlotCompiler 语义歧义** (e2a3bf2a: S2 绑定 John V 自身 death date 1551 而非其父的 1516 — 错实体, 答案永不在 bindings, "末槽有 bindings" 是假恢复)。两类都必须过滤, 否则污染 τ 训练标签。
- **采集时必须用良定义收集器(末槽绑定答案值门)**, 否则 τ 分布被 proxy 假象污染 (§14 的 S4=6 误判为 "深度4失准" 即此假象)。

## 4. Estimator 设计 (冻结草案)

**输入特征** (per-slot, 在单次执行后):
- SufficiencyFeatures 30 特征 (V2, sufficiency.py:44-75): top1/topk score, coverage, budget_fraction, row_count, ...
- 链位置/深度特征 (新增): `chain_depth` (该槽在 topo 序中的位置), `is_downstream` (是否依赖先前槽绑定), `join_edge_count` (依赖的 join 边数), `remaining_plan_depth` (已有, EvidenceContext)。
- 特征 schema 版本: V1 → V2 迁移沿用 sufficiency 的 `feature_names`/`feature_schema_version` 机制 (0 迁移加载已由 §6 验证)。

**模型**:
- 基线: 逻辑回归 (对齐现有 sufficiency calibrator 的 `EvidenceSufficiencyCalibrator` 模式)。
- 目标: 预测 `τ_slot` (回归) 或二分类 "预算敏感 (τ>1)"。
- **训练数据**: 预算 sweep × per-slot 恢复门槛 的观测集 (探针已产出; 正式采集用真实 hotpotqa 扩充)。

**§13-17/裁决12f-12j 的最终更新 — estimator 坍缩为确定性位置查表, chain-rule 是主实验**:
- 规划时可学性探针 (hotpotqa 13 链) 发现 **τ ≈ 2·depth − 1 确定性单调结构** (S1=1, S2=3, S3=5), trivial 位置查表 acc=0.963 ≈ planning AUC 0.979 → 旧"30 特征 estimator"设计过度工程。
- **三数据良定义闭环 (§17/12j)**: 良定义收集器 (末槽绑答案值门) 过滤后, hotpotqa 6 + 2wiki 6 + musique 7 = **19 良定义链全部 τ=2d−1 零变差**。musique S1=2 (12g) 与 hotpotqa S1=2 均是被过滤的代理假象链。**content/执行特征无可学增量, learned estimator 坍缩为位置查表 (12f 原判确认)**。
- **estimator 正确形态 = chain-rule importance (τ=2·depth−1 确定性分配)**: 无 learned 成分。**pre-reg §5 的 G3(chain-rule) 臂从"对照"升为"主实验"**。content 增量仅在"更大样本出现同位置 τ 变差"的开放条件下有意义 — 记为开放问题, 不入当前 claim。

**输出接法**: learned per-slot importance 注入 `PlanObjectiveParams(requirement_importance={slot.id: predicted})` → G3 `search_physical_plans`。

## 5. 评估协议 (冻结草案)

**比较** (matched budget, 真实 hotpotqa 良定义 2+ 槽链, 冻结样本, **分层报告: ≥3-slot 子域 [主] / 2-slot 子域 [预测零]**):
1. **G3(chain-rule importance) [主实验, §17/12j]**: importance = 2·depth−1 确定性分配 → G3。这是 G5 的贡献交付物。
2. **G3(flat importance)**: 当前 §11 状态 (importance 全平 1.0) → G3 ≡ static。
3. **static** (compile_physical_plan): 基线。
4. **G3(learned importance) [开放/如果 content 变差出现]**: 仅在更大样本显示同位置 τ 变差时训练; 当前 19 良定义链无变差 → learned 无独立价值, 不进入主 claim。

**度量** (per dataset×metric×budget cell, 沿用旧协议):
- **Coverage**: 目标真值恢复率 (gold passage 是否在 evidence)。
- **效率**: retrieval calls 差, 在相同 Coverage 下的 calls 节省。
- **统计**: 配对 (同 question, 同 budget 档), bootstrap CI, 需明确不犯 §11 的错 (flat importance 下 G3 ≡ static 是预期, 不算 WIN)。

**门禁** (G5-H-2 成立需, 12p 定稿):
- **G3(chain-rule) 在 ≥3-slot 良定义链子域上, 同 Coverage 下 calls 显著低于 G3(flat) (CI excl 0)**。实证 (12p): n=2 W/T/L=2/0/0 CI[1,1] p<0.001 (Holm), 每条省 1 call (6→5)。**注意**: 门禁按规律预测的**子域**表述 (≥3-slot), 而非全链 — 全链 p=0.178 (4/6 2-slot 被钉死) 是规律预测的必然结果 (12o), 不是门禁失败。
- **确定性 (12p 新增)**: ≥3-slot 收益在 5 重复内零变差 (18/18 intra-chain 零 spread) → 收益是结构性事实, 非采样噪声。n=2 的 p<0.001 靠确定性 (CI 点质量 [1,1]) 而非样本量。
- **2-slot 子域零收益 (规律预测, 12l)**: 2-slot 链全等价 (槽数下界钉死)。此零收益是规律的结构性预测, 需在报告里显式呈现为"预测得到并确认的零"而非"失败"。
- 无 Coverage 回归 (chain-rule 不降低真值恢复率)。
- **chain-rule importance 与良定义真值门槛 τ 的相关性 (Spearman) 显著 > 0** (19 良定义链, 应接近 1 因 τ=2d−1 确定性)。

## 6. 风险与边界 (诚实)

- **真实 gold 判定 proxy**: 非空绑定 ≠ 真值。改进用 gold_evidence passage 匹配。若 proxy 引入噪声导致不可学, 回退到人工语料 (§10 4 问句 + 扩充)。
- **SlotCompiler 语义歧义 (裁决12i)**: 某些链 slot 解析错实体(e2a3bf2a: John V 的 father 的 death date 被编译成 John V 自身 death date), 导致末槽绑定错误目标属性, 答案永不在 bindings → 假恢复/假 τ。**这类链必须用良定义收集器排除**, 是编译质量问题不在 G5 论域, 但会污染 τ 训练标签。
- **q2 式灾难 (裁决9/10)**: 学出 importance 不能把稀缺槽预算压太低导致 ABSTAIN 丢真值 — 需门禁 "无 Coverage 回归" 捕获。
- **calibrator 伪影**: 训练数据若用低预算 abort 段 (budget_exceeded, rows/evidence 空), 会污染; 必须只用 extracted_rows (不受 abort 影响)。
- **泛化**: 4 问句人工 + 6 真实链样本小, estimator 可能过拟合链位置 (S1=1/S2=3 太规则); 需多样数据 (不同 depth, 不同 query) 防"只学深度特征"。**§13/裁决12f 已实证**: 真实 hotpotqa 上稀缺性**就是**位置查表 (τ≈2·depth−1, trivial acc 0.963≈AUC 0.979), "只学深度特征"不是风险而是当前实证状态——所以必须加 chain-rule 对照臂(§5 第4项)并在 2wiki/musique 验证此规律是否通用。

## 7. 与论文弧的关系

G3 (mechanism) + G5 (signal) = 单一贡献弧:
> "Requirement-aware physical optimization is suspended on the reliability of per-slot cost/value estimates; an LLM compiler emits none. We learn them counterfactually from execution trajectories — a slot's importance is its measured budget-sensitivity (truth lost when its allocation is cut). Counterfactual budget scanning (§13-17) discovers a **deterministic chain law**: on well-defined chains (last slot binds the answer value), per-slot recovery threshold τ = 2·depth−1 across three datasets (19 well-defined chains, zero variance). This law, not a learned estimator, provides G3's missing importance signal (content features add no increment). Empirically (§18-19), G3(chain-rule) saves 16.7% calls on 3-slot chains with 100% evidence-quality parity and no abstention disaster — the structural minimum-budget guarantee of τ=2·depth−1 avoids the catastrophic-loss face of learned/heuristic importance. Honest boundary: the benefit domain is ≥3-slot chains with budget surplus (2-slot chains are pinned by the slot-count lower bound; musique shows G3 cannot repair retrieval-coverage scarcity). In standard 2-hop benchmarks this domain is **rare** (a 30-problem scan added 0 well-defined 3-slot chains; ~10.5% across ~55 real chains). **Deep-chain load is the broad-value scenario and is now empirically supported (12q): on real musique 3-hop train questions, 10/12 compile to 3-slot chains and the 2 well-defined ones reproduce the law τ={1,3,5} and G3(chain-rule)'s deterministic +1-call/16.7% savings with full parity (p<0.001, CI[1,1], 6/6 zero-spread) — though well-defined yield is low (2/10; 70% hit the S3 retrieval-coverage ceiling, consistent with 12m's coverage-scarcity boundary)."

**当前状态 (12k-12o, G5 线收束)**: 正收益 = 2 条 hotpotqa 3-slot 链 (n=2), 统计薄弱; **n=30 扫描 (resume-log 保留 13 题) 新增 7 qid 但 0 新增良定义链 → 跨数据 ~55 真实链中 3-slot 良定义仅 2 条 (10.5%)**。claim 定为"**结构稀有的结构性收益**" — 收益域 = ≥3 槽链, 在标准 2-hop 基准天然稀缺; 深链负载 (未来工作) 是 G3 广泛价值的场景。G5 贡献弧完整 (规律 τ=2d−1 + G3(chain-rule) 解锁 allocation + 稀有收益域边界)。

---

*本预注册为 DRAFT, 待 Phase 10 与 FROZEN_PROTOCOL 一起冻结。所有结论在冻结前视为 NEEDS_EVIDENCE。*
