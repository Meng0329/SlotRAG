# STATE.md — SlotRAG-X 研究状态快照

> **最后更新**: 2026-08-13  
> **更新者**: documentation-writer agent  
> **当前阶段**: Phase 4 冻结验证 🔄 进行中 — SEALED strategyqa TIE、4 数据集 SEALED 首次运行 LOSS（budget_exceeded 结构性惩罚），H-029 修复 PASS（n120 双数据集 +18~22pt acc_full），H-030 残留 BE 全回收（n120 配对验证 acc_full 0.883→1.000 / 0.900→1.000，BE 26/26 归零）commit `494af0c`，全量重跑待执行

---

## 项目概况

| 项目 | 状态 |
|------|------|
| 项目名称 | SlotRAG-X: Slot-based Retrieval-Augmented Generation |
| 目标会议 | PVLDB 2027 |
| 当前方法 | SlotRAG v74 hybrid + reranker |
| 核心架构 | Slot Compiler → Adaptive Slot Materializer → Generator |
| LLM | qwen3.6-27b (internal endpoint) |
| Embedding | Qwen3-Embedding-0.6B (1024-dim) |
| Reranker | bge-reranker-v2-m3 |

---

## 当前阶段状态

### Phase 0: 审计 ✅ 已完成
- [x] git checkpoint 创建 (`research/phase0-audit`, `e11d4fc`)
- [x] EXPOSED_SAMPLE_REGISTRY.csv 生成 (3,508 unique samples)
- [x] CURRENT_STATE_AUDIT.md 生成 (12 问全部回答)
- [x] EXPERIMENT_BUDGET.md 生成
- [x] 现有测试运行 (355 pass, 1 fail, 1 skip)
- [x] 数据集校验和验证 (manifest 中已有)

### Phase 1: 研究基础设施 ✅ 已完成
- [x] 9 个子 Agent 定义 (.claude/agents/)
- [x] STATE.md
- [x] HYPOTHESES.md
- [x] EXPERIMENT_LEDGER.csv
- [x] FAILURE_LEDGER.csv
- [x] DECISIONS.md
- [x] SOTA_LEDGER.md
- [x] RELATED_WORK_MATRIX.csv
- [x] Makefile 入口

### Phase 2: SOTA 账本 ✅ 已完成 — 诚实基线
- [x] 三集合构造 (DEVELOPMENT 30% / VALIDATION 30% / TEST 40%, seed=2027)
- [x] 功效分析 (n=100 足够, 所需 n=2-18)
- [x] FROZEN_PROTOCOL.md 冻结
- [x] SOTA_LEDGER.md 诚实填充 (**0/10 = 0% Strongest-Baseline Coverage**)
- [x] 最强 baseline 确定 (ircot/graphrag/planrag/hybrid)
- [x] drop 主指标改为 drop_f1 (EM 对所有方法无效)

### Phase 3: 假设循环 🔄 已恢复（H-012 公平重跑完成，Coverage 40%）
- [x] 深度失败诊断完成
  - **strategyqa EM=0.08 是格式假象**：用 primary_score (accuracy) 实际 0.84
  - **drop EM 无效**：已用 drop_f1 (0.62)
  - **真实瓶颈 (H-004)**: 检索不是瓶颈，是答案生成质量
    - hotpotqa: 21/98 recall=1.0 但 EM=0（检索对，答案错）
    - 2wiki: 21/100 recall=1.0 但 EM=0
    - ~57% 措辞/格式问题 (F1≥0.5)，~43% 明显错误 (F1<0.5)
- [x] 采样一致性 bug 修复 (generate_sealed_samples.py)
- [x] **Tier 1 实验完成**: H-001 rejected (p=0.13), H-002 rejected (p=0.41)
- [x] H-004 validated (生成质量是瓶颈)
- [x] H-005 rejected (entity contract, -0.02~-0.05)
- [x] **3 连续假设拒绝 → STOP_REPORT 触发**
- [x] H-008 SUPPORTED (PerPath 修复 S2, pooled +4.4pt p=0.0105)
- [x] H-009 REJECTED (score-guided 不一致)
- [x] H-010 REJECTED (跨来源投票/compact-value 均不可行, 可行性分析否决)
- [x] **H-012 叠加配置 Tier 1 PASSED** (2026-08-05)
  - `slotrag-grounded-frontier-perpath-guard` 组合 frontier 守卫 + anchor 保护 + per-path 提取
  - Tier 1 (n=20×3): 2wiki +17.6pt, hotpotqa +11.8pt vs 最优现有; musique EM 3:1 净胜
- [x] **H-012 Tier 2 完整矩阵完成** (2026-08-06, n=100×5 数据集)
  - Coverage **2/5 = 40%**: musique (+9.6pt vs ircot)、strategyqa (+8pt vs graphrag) WIN
  - hotpotqa tie (-0.2pt, p=0.94); **2wiki (-16.5pt)、drop (-13.4pt) LOSS**
  - strategyqa facts 加载回归修复 (commit 8ae9a40)
  - **结论**: 叠加配置部分有效，2wiki/drop 需针对性改进
- [x] **H-013 已拒绝** (union vs per-path 提取, n=20, p=0.786)
- [x] **H-014 已拒绝** (桥接实体重检索回退, Tier 1 n=20, 2wiki)
  - 机制层面有效 (8 触发 7 成功重检索)，但 F1 -9.3pt (0.726→0.633)
  - 根因: 2wiki 答案走 evidence-based 路径，rows 空不影响生成；bridge 修复的 rows 未达生成阶段
  - 追加诊断: 4 个 F1=0 中 3 个 gold 在 evidence 但生成选错（噪声/过量 evidence）
- [x] **H-015a 已拒绝** (生成证据去重+截断, Tier 1 n=20, 2wiki)
  - evidence 7.3→4.5 条，但 0/20 样本答案变化 (F1 0.7262 不变)
  - 洞察: 生成错误不是 evidence 数量/噪声问题，是推理深度问题
- [x] **H-016 已拒绝** (drop 自由文本 short 答案, Tier 1 n=20, drop)
  - short 改 1 样本且变差 (drop_f1 0.581→0.531, gold '70.7' → '70.7%' %破坏 token)
  - 洞察: drop F1=0 是**算术推理失败**（gold 是计算值，仅 3/100 在原文），非格式/证据问题
  - 2wiki+drop 均定位为**推理深度**瓶颈，需显式推理链或接受 LOSS
- [x] **H-017 已拒绝** (生成阶段显式推理链 thinking, Tier 1 n=20×2, 2wiki+drop, commit 7987181)
  - 2wiki 20/20 答案一字不差 (F1 0.7262→0.7262, Δ=0)；drop 19/20 不变、1 样本因 provider SchemaError 变差 (0.6305→0.5805)
  - thinking 机制**已生效** (enable_thinking=True 首次尝试走通) 但 qwen3.6-27b 的 thinking 不改变任何生成决策
  - 与 H-005/H-009 同模式：提示级/模式级干预在生成阶段已穷尽，零效果
- [x] **H-018 已拒绝** (生成证据保真 prompt, Tier 2 n=100, hotpotqa)
  - guard 0.8131 → fidelity 0.8242 (**+1.1pt, p=0.60**), wins=7 losses=6
  - 修复截断 (`east`→`the east of Ireland` +0.5)、错实体 (`English`→`Scottish` 0→1.0) 但**回归 4 个 previously-correct** (Dallas→Dallas Texas, McLaren Vale 过度扩展)
  - 软保真指令无法区分"该完整"与"该简短"（无 gold 信号）→ +1.1pt 不显著，违反零回归门禁
- [x] **H-019 已拒绝** (生成前证据相关性重排序, Tier 1 n=20, 2wiki)
  - guard 0.7262 → rerank 0.7262 (**Δ=0.0000**), 20/20 一字不差
  - 机制生效 (reranker_calls=2)；**10/20 样本 evidence>8 被重排+截断到 8，0/10 答案变化**
  - 决定性证据: 生成器**完全无视 evidence 呈现**（重排 12+→8 无影响），有内部答案先验
- [x] **H-020 已拒绝** (extract-then-select 输出契约, Tier 1 n=20, 2wiki, commit ee4e4b3)
  - guard 0.7262 → select 0.6155 (**Δ=-0.1107**), wins=0 losses=3 ties=17
  - 机制生效 (generation_llm_calls=2 两段式)；**3/20 答案被改变，全部变差**；2 个 previously-correct 被破坏（'Broken Laws'→导演 'Roy William Neill'、'Beji Caid Essebsi'→'Baker Brownell'），8 个 guard-wrong 0 恢复
  - gold 在两个 previously-correct 里都连续在 evidence，但**候选抽取把中间实体（导演名）抽成候选，选择器选了导演而非电影名**——比较类问题选型超出 qwen3.6-27b 能力
  - 决定性证据: 生成器在 grounded 候选中也**选不准**——瓶颈从"输出契约"收敛到"模型选型能力"
- [x] **系统性结论（9 个生成侧干预全失败）**: 检索/证据量/证据排序/提示措辞/thinking/契约（含输出契约）——全部不影响 qwen3.6-27b 生成。**在 current scalar-slot execution architecture 下，局部干预已基本穷尽**（Phase 3X §0.4 修正：不推导"架构空间穷尽"，typed relational execution 是新的未验证方向）
- [x] **H-021 已拒绝** (比较类确定性算子, feasibility 分析, 2026-08-06)
  - 2wiki 25/100 比较类问题, 9 个比较类错误; 离线 regex 模拟仅 **1/9 恢复** (Marius Mitu vs Bea Palya 同 passage)
  - rows 无年份列; 其余 8 个年份无法归属到实体/需跨 passage join 到导演再找导演生日 (H-014 已证失败)
  - **闭环（修正）**: 输入侧 (H-005~H-019) + 输出侧 (H-020) + scalar-rows 确定性算子 (H-021) 在 current scalar-slot architecture 下已局部穷尽; 但 **typed relational execution（物化比较所需属性）未验证**，见 Phase 3X H-023~H-026
- [x] **H-022 诊断完成** (2wiki 错误最终聚类, 2026-08-06)
  - 2wiki n=100: 54 exact / 18 partial / 28 zero
  - **粒度错配 14** (pred⊃gold, evidence 里两种粒度都连续, 如 Konstfack vs Konstfack department of graphic design) → 信息论不可修复
  - **选型失败 20** (gold 连续在 evidence 但生成器选错候选, 27/28 F1=0 全 status='ok') → 纯模型选型天花板
  - 后处理验证: 前缀收窄 +32 回归, 循证收窄 0 改进 → 无架构侧杠杆剩余
  - **结论**: 2wiki LOSS 是"选型能力"模型级天花板, Coverage 维持 40%, 除非模型级生成器升级
- [x] **Phase 3X: H-023 完成** (typed relational 离线编译审计, 2026-08-07)
  - 句型-结构确定性编译器 operator_family 覆盖 11%→**92%**, plan_valid 100%, answer_schema 91%
  - 只证明"编译器能判对算子族"，未解决物化端（见 H-024）
- [x] **Phase 3X: H-024 完成** (Demand-Driven Materialization, typed 契约 date/number, Tier 1, 2026-08-07)
  - **判决: rejected**（从 pass_with_caveats 修正，by typed-attribution）
  - 修复 2 个 pre-existing bugs（独立于 H-024）: (1) bundle 路径 join 锚丢失 → 2wiki join_out 0 修复 (commit 8a40309); (2) bundle 路径 typed_extraction_answers 未计数 → gate metric 不可测量修复 (commit 7767412)
  - aggregate: 2wiki typed_parse_success_rate **100%** (5/5), F1 +0.48pt (guard 0.5786 → typed 0.5833), drop 0 激活 F1 0.4722 平
  - **⚠️ 修正: aggregate +0.48pt 是假象**。3 个 win（6ebdbede0b/fa3e9b640b/89a3abec0b）全 typed_contracts=0 → run 噪声。**typed 净效应 = 帮助 0 题 + 破坏 1 题**（e084 guard 1.0→typed 0.0, ISO 日期 echo）
  - **机制性失败**: typed date 契约指示 LLM "Output as ISO YYYY-MM-DD" → rows 变 ISO → 答案生成器 echo ISO，gold 是表面形式 `"January 26, 1955"`。**提取层强制 ISO 与 2wiki 答案格式天然冲突**
  - drop: 20 样本全 `EvidenceAnsweringQuestion` 单 slot 计划（0 operators/0 joins）→ number-typed 架构性不可用
- [x] **Phase 3X: H-025 完成** (typed 契约保留表面形式, Tier 1, 2026-08-07)
  - **判决: pass（有保留）**。H-024 ISO 重写是纯破坏：`_ordered_scalar`/`_as_number` 本就能从表面形式解析，typed 契约正确形态是 validate-only 不改写
  - 决定性证据: **e084 从 H-024 的 0.0 恢复到 1.0**（answer 保持 `"January 26, 1955"` surface）；parse rate 100% (5/5)；join_output_rows 两侧一致 (35=35) 算子零退化
  - 唯一 F1 回归 `6ebdbede` (-0.333) typed_contracts=0 → plan 不稳定噪声（`BuriedIn` vs `BurialPlace`），非 H-025 因果
  - **保留原因**: n=20 typed 契约仅激活 5 次、aggregate 中性；治疗相对"无契约"的真实增益未测出（guard 侧 e084 本就 1.0）
  - drop 维持未激活（0 number/date typed slots 编译，与 H-024 同根因）
- [x] **Phase 3X: H-026 停止（未构建, 方向重估, 2026-08-07）**
  - **typed relational execution 在 DEVELOPMENT_SET 上暂停**。关闭的是：把 H-023 的审计分类器升级为运行时编译器的方向（超出 Phase 3X 干预假设框架）
  - 根因: 编译→算子激活缺口——`slot_plan_tool` schema 允许 typed operators 但 LLM 几乎不产出；仅 2 个硬编码模板激活（2wiki typed 契约 5 次, drop 0）
  - 算子执行层不是瓶颈（H-025 证表面形式解析无退化）；瓶颈是被审计分类器证明存在、但运行时无路可达的激活缺口
  - **Coverage 维持 40%**（musique/strategyqa WIN, 2wiki/drop LOSS, hotpotqa TIE）。typed relational 不构成覆盖提升路径
- [x] **Phase 3X: H-027 已拒绝** (sampled majority-vote answer aggregation, Tier 1 n=20, 2wiki+drop, 2026-08-07)
  - 干预: N=5 temp=0.7 采样 + `_majority_vote`（case/punct-insensitive），`sample_majority_vote=True`，新方法 `slotrag-grounded-frontier-perpath-guard-samplevote`
  - **2wiki Δ=-6.07pt**（0.6869→0.6262, p=0.46），wins=2 losses=2 ties=16；drop 0.00pt（0/20 不变）
  - 关键证据: **真回收 1/20**（`89a3abec` 0.571→1.0, gold `Bello of Carcassonne`，贪心选错，多数票矫正）；**once-correct 翻转 2/20**（`f02e0a34` 1.0→0.0 `Domangart Réti`→`Fergus Mór`；`fa3e9b64` 1.0→budget_exceeded→None）
  - 成本: generation_llm_calls 2wiki **5.45×**（guard 11→treat 60），drop 5.00×（5→25）
  - **结论**: qwen3.6-27b "稳定地错"时多数票**加剧而非矫正**（1 例回收以 2 例回归为代价，aggregate -6.07pt 远超 -2pt 红线）。**H-022 选型天花板确认，majority-vote 不构成回收杠杆**。drop gold=计算值，采样无候选多样性。
  - Coverage 维持 **40%**，采样聚合方向关闭；剩余方向: (a) 接受 Coverage 40% 转论文；或 (b) 架构级"审计分类器→运行时编译器"新方向（超出 Phase 3X 干预假设）
- [x] **Phase 3X: H-028 已拒绝** (deterministic runtime operator-plan repair, Tier 1 n=20, 2wiki+drop, 2026-08-08)
  - 干预: `_repair_plan_operators`（planner.py）在 compile 后确定性注入 field_argmin/argmax/count + outputs 对齐 `?answer`，`_deterministic_output` 短路生成。`runtime_compiler=True`，新方法 `slotrag-grounded-frontier-perpath-runtime-compiler`
  - **2wiki Δ=-2.50pt**（0.6286→0.6036, 95% CI [-0.075, 0.000]），wins=0 losses=1 ties=19；drop 0.00pt（0/20 一字不差）
  - **关键证据: 修复零激活**——全部 40 个 rc item `runtime_operator_repairs=0`。n=20 样本无任何 plan 同时具备 "≥2 typed date/number 字段"+"缺 operator"。唯一比较模板题 `b081` 已带正确 field_argmin（labels=Bat*21/Lunatic），不 double-repair 且两侧都 budget_exceeded。**H-026 激活缺口第二次确认**。
  - **唯一回归 `a344d746`**: plan 参数顺序不稳定 → retrieval 稀疏 → BornIn 折叠成 single `{Madrid}` → **pre-existing `_deterministic_output` 单唯一行短路** 返回 `Madrid`（错, gold 是 Castejón）。非 H-028 repair 因果（repairs=0）。
  - **结论**: 确定性执行器本身正确（单测证明 field_argmin 确定性算出 Bat*21），但运行时无物化目标。H-022 选型天花板第三次确认（H-025/H-026/H-028）。Coverage 维持 **40%**，Phase 3X 全部 6 个假设（H-023~H-028）收束到同一根因。
- [ ] **架构级下一步（超出 Phase 3X 干预假设）**: 若要覆盖 2wiki/drop, 需把"审计分类器→运行时编译器"做成架构级新方向（非单假设干预）。或接受 qwen3.6-27b 选型天花板（H-022）→ Coverage 顶在 40%, 除非模型级生成器升级

---

## 金句 1: "之前还能 90% SOTA" 的准确解释（2026-08-06 澄清）

**Phase 0 审计判定那些 >90% 结论无效**（`research/CURRENT_STATE_AUDIT.md`, commit e11d4fc）：
- **split 错配**: V6c train (seed=314159) 与 baseline eval (seed=2040) **0% 重叠** → "超90% SOTA"对比不同分布，不可比
- **eval 暴露**: seed=2040 n=100/dataset 已污染，只能作 diagnostic
- **撤销列表**: "超90% SOTA"、"question_grounded_retrieval 突破90%"、"V6b 200样本验证通过"
- 当前 40% 是**同一套系统在干净 DEVELOPMENT_SET 上的严格重测**，musique/strategyqa WIN 是真实存在的

## 金句 2: 生成瓶颈的准确边界（2026-08-06 诊断细化）

**不是所有 LOSS 都是生成器天花板**。gold 连续性诊断（n=100/dataset）：

| 数据集 | correct 时 gold 连续% | wrong 时 gold 连续% | 判定 |
|--------|----------------------|---------------------|------|
| musique | **96%** | 63% | ✅ WIN — 正确性=gold 可读性 |
| strategyqa | 0% (boolean) | 0% | ✅ WIN — facts 存在即答 |
| 2wiki | 87% | **74%** | ❌ LOSS — gold 连续仍在 74% wrong 里出错 |
| drop | 6% | 2% | ❌ LOSS — gold 是计算值，几乎永不连续 |
| hotpotqa | 94% | 86% | TIE — 正确性大致=gold 可读性 |

- **drop = 架构级不可能**（gold 是计算值，仅 6% 在原文连续）——非生成器问题
- **2wiki = 真生成失败**（74% gold 连续却仍错）——musique 同样情况却能对
- **musique/hotpotqa/strategyqa = 架构+检索领先**，生成器能读 gold 就答对
- [ ] **下一步**: 显式推理链生成（2wiki 多跳 / drop 算术），或接受 2wiki+drop LOSS 保 Coverage 3/5

### Phase 4: 冻结验证 🔄 进行中（SEALED_FINAL strategyqa 已完成，非确定性噪声暴露）
- [x] **generate_sealed_samples.py all 模式** 完成（`--size all` 写全量干净 test 样本）
- [x] **Tier 3 SEALED 样本生成**（hotpotqa 1000 / 2wiki 1000 / musique 867 / strategyqa 180 / drop 1000）
- [x] **strategyqa SEALED 180 全量评估完成（publication-grade, trace enabled）** (run1=`runs/slotrag-phase4-trace`)
  - run1: guard=0.8833, ircot=0.8833, graphrag=0.8722, react=0.8444
  - **SEALED strategyqa = TIE（guard vs ircot Δ=0.00pt, p=1.0）**，非 WIN
- [x] **⚠️ 服务端非确定性噪声暴露**（Phase 4 关键发现）
  - 内部 Qwen（10.200.37.71:8801）temperature=0 仍非确定性：同一 question 检索证据逐字节相同，但 LLM 布尔答案在运行间翻转
  - flip 率：guard 7/180 (3.9%)，ircot/react 3/180 (1.7%)，graphrag 0/180
  - 影响：guard 0.9→0.8833（pilot→trace，-1.7pt），噪声与 guard-vs-baseline WIN 幅度同量级
  - **含义：SEALED 单次运行的 WIN/LOSS 判定不可靠，需多次运行或报告 CI**
- [x] **⚠️ 非确定性根因已诊断**（2026-08-10）
  - **不是并发/检索/代码**：检索证据逐字节相同；单题 5 次串行 + 6 次并发重跑全错（yes），trace run 却答对（no）
  - **根因：qwen3.6-27b 在 strategyqa 推理边界题上 flip-flop**（需算术/多跳的布尔题，~50/50）；7 个翻转题全是这类
  - **决策（用户拍板）**: strategyqa 3 次取均值，报告 mean ± run-to-run range，稳健判定 WIN/TIE/LOSS
- [x] **strategyqa 3 次取均值完成**（run1=`-trace`, run2=`-r2`, run3=`-r3`，180×4 方法）
  - **mean**: guard **0.8815** / ircot **0.8833** / graphrag 0.8722 / react 0.8481
  - **range**: guard 0.0056 (flips 4/180) / ircot 0.0000 (0) / graphrag 0.0000 (0) / react 0.0056 (2)
  - **稳健判定: guard vs ircot Δmean=-0.19pt, wins 16/ties 149/losses 15 → TIE（guard 略落后）**；guard vs graphrag +0.93pt TIE；guard vs react +3.33pt TIE
  - **⚠️ strategyqa coverage 单元不再计入 Coverage**（TIE/LOSS，非 WIN）。pilot 0.9 WIN 是幸运抽样（trace 暴露 flip-flop 噪声后不可复现）
- [x] **Tier 3 其余数据集 SEALED 首次运行完成**（run1=`runs/slotrag-phase4-trace-b1`，n=1000/集，musique 867）
  - **guard 4/4 LOSS**（acc_full vs 最强 baseline）：hotpotqa 0.5312 vs graphrag 0.8124（-0.2812）、2wiki 0.6644 vs ircot 0.7449（-0.0805）、musique 0.3171 vs ircot 0.5263（-0.2092）、drop 0.6393 vs graphrag 0.7246（-0.0853）
  - **关键诊断**：guard **acc_ok 有竞争力**（musique 0.626 / hotpotqa 0.788 / 2wiki 0.718），**LOSS 几乎全部来自 budget 惩罚**——musique 49.4% BE、hotpotqa 32.6% BE 项按协议记 0.0 拉垮 acc_full。BE 是**结构性**（dual_access_bundle 2-query batch 物理计费 + 预算跨 slot/binding-context 累计），不是质量问题
  - **run2 (b2) 部分完成**（launcher 中断）：hotpotqa/2wiki 1000，musique 585，drop 976；**run3 (b3) 未启动**。多运行取均值要求部分满足
- [x] **H-029 budget 结构性修复（Phase 4 loop 迭代优化第 1 轮，PASS）**（2026-08-13）
  - 干预：`MethodSpec.dual_access_bundle_bound_single`——bound slot 从 2-query bundle 降级为 1 个 question+lexical-slot query（1 物理调用）。绑定值已锚定检索，lexical slot query 在此路径冗余。commit `43e34d6`
  - **n120 双数据集验证**（`runs/slotrag-phase4-h029-n120`）：musique acc_full **0.472→0.655 (+18.3pt)**、hotpotqa **0.474→0.690 (+21.6pt)**；acc_ok 均**略升**（+2.3/+2.8pt）；BE 回收 30/33 项（mean 0.734/0.870）；both-ok 对净中性（musique 8w/7l/69t，hotpotqa 1w/3l/75t——质量零回归）
  - cost：rc 均在预算 4 内（3.06/2.69），llm musique 5.24→4.81（**下降**）。**H-029 严格更便宜且更好**
  - 判定：**PASS**，§4.3 budget_exceeded 结构性损失已解决。n120 是全量 guard-BE 回收的保守下限（n120 musique BE 率 29.2% < 全量 49.4%，全量预计回收更多）
- [x] **H-030 跨 slot 预算预留（Phase 4 loop 迭代优化第 2 轮，PASS）**（2026-08-13，commit `494af0c`）
  - 背景：H-029 后 n120 仍 11 项 BE（5 musique + 6 hotpotqa），6 项一致 BE
  - 根因（live trace）：**跨 slot 预算饥饿**——首 slot unbound bundle（2 calls）+ 第二 slot 2 binding context（2 calls）= 4，后续 slot 在 `remaining_retrieval_calls <= 0` BE 于物化前。4-slot plan 在 4-call 预算下结构不可行（2+3×1=5>4）
  - 干预：Stage A executor 前视预留 `slot_call_cap = remaining - len(remaining)`；Stage B `_prune_plan_to_max_slots` 按 articulation point 降级 + `budget_fit = max_retrieval_calls - 1` 触发
  - 验证：**11/11 残留 BE 项恢复 OK，10/11 F1=1.0**（1 F1=0 为 LLM 生成错误非预算）；both-ok 质量中性（变化全为 LLM 非确定性）
  - **n120 完整配对验证**（`runs/slotrag-phase4-h030-n120`）：musique acc_full **0.883→1.000 (+11.7pt)**、hotpotqa **0.900→1.000 (+10.0pt)**；**BE 26/26 全回收**（guard 26 项 BE → budget 0 项）；both-ok 质量噪声级（musique ΔF1 -0.0086 / hotpotqa +0.0279，符号相反 = 非确定性，非系统性退化）
  - 判定：**PASS**。与 H-029 合璧后 §4.3 budget_exceeded 结构性损失完整解决
- [ ] **全量 guard-budget 重跑待执行**（n=1000/集，或直接扩 b2 剩余 + b3 补全）；完成后重算主表 acc_full + Coverage
### Phase 5: 论文 + Artifact ⏳ 待启动

---

## 关键指标

### 诊断基线 (seed=2040, eval split, n=100, contaminated)
| 数据集 | 指标 | SlotRAG | 最强 Baseline | Delta | 判定 |
|--------|------|---------|---------------|-------|------|
| hotpotqa | EM | 0.5612 | ircot (0.6800) | -0.1188 | ❌ LOSS |
| hotpotqa | F1 | 0.6887 | graphrag (0.8087) | -0.1200 | ❌ LOSS |
| 2wikimultihop | EM | 0.5900 | graphrag (0.7300) | -0.1400 | ❌ LOSS |
| 2wikimultihop | F1 | 0.6872 | graphrag (0.8199) | -0.1327 | ❌ LOSS |
| musique | EM | 0.3736 | planrag (0.4828) | -0.1092 | ❌ LOSS |
| musique | F1 | 0.4818 | planrag (0.5748) | -0.0930 | ❌ LOSS |
| strategyqa | EM | 0.0800 | hybrid (0.9000) | -0.8200 | ❌ LOSS |
| strategyqa | F1 | 0.0800 | hybrid (0.9000) | -0.8200 | ❌ LOSS |
| drop | EM | 0.0100 | planrag (0.0102) | -0.0002 | ❌ LOSS |
| drop | F1 | 0.4405 | planrag (0.5419) | -0.1014 | ❌ LOSS |

**Strongest-Baseline Coverage: 0/10 = 0%**

### 评估集可用性
| 数据集 | 总 eval | 已暴露 | 干净可用 | 干净% |
|--------|---------|--------|----------|-------|
| hotpotqa | 7,405 | 250 | 7,155 | 96.6% |
| 2wikimultihop | 12,576 | 249 | 12,327 | 98.0% |
| musique | 2,417 | ~500 | ~1,900 | ~79% |
| strategyqa | 687 | ~500 | ~187 | ~27% |
| drop | 9,535 | ~500 | ~9,000 | ~95% |

### 三集合（Phase 2 已构造）
| 集合 | 比例 | seed | 样本数 | checksum |
|------|------|------|--------|----------|
| DEVELOPMENT | 30% | 2027 | ~9,412 | e914456d... |
| VALIDATION | 30% | 2027 | ~9,412 | 88dffd52... |
| TEST (SEALED) | 40% | 2027 | ~12,557 | 3eceb4f5... |

### Baseline 覆盖率 (seed=2040, n=100/dataset)
| 方法 | valid_n | failed | coverage |
|------|---------|--------|----------|
| graphrag | 500 | 0 | 100% |
| hybrid | 500 | 0 | 100% |
| ircot | 500 | 0 | 100% |
| react | 500 | 0 | 100% |
| planrag | 470 | **30** | 94% |
| slotrag | 489 | 11 | 97.8% |
| srag | 494 | 6 | 98.8% |

### SlotRAG V6c 训练集 (train split)
| 数据集 | valid_n | failed | total |
|--------|---------|--------|-------|
| hotpotqa | 834 | 4 | 838 |
| 2wikimultihop | 4 | 0 | 4 |

---

## 已确认的事实

### 代码级事实
1. V5c generation fix 有效 (thinking → over-caution)
2. baseline 归一化一致 (SQuAD/HotpotQA 标准)
3. publication_gate.py 有 train split 防护

### 必须撤销的结论
1. ❌ "超 90% SOTA" (train/eval split 错配)
2. ❌ "question_grounded_retrieval 突破 90% SOTA" (contaminated eval)
3. ❌ "V6b 200 样本规模验证通过" (contaminated eval)

### 诚实基线 (Phase 2, 诊断性)
- **Strongest-Baseline Coverage = 0/10 (0%)** — 在 eval split 上全面落后
- strategyqa 近乎失效 (0.08 vs 0.90, -0.82)
- drop 的 SQuAD EM 对所有方法无效 (~0.01)，主指标用 drop_f1

### 风险点
1. 所有 baseline 是 adapted (exact_upstream_execution: false)
2. eval 暴露 (seed=2040 样本已污染)
3. 有效样本数不一致 (planrag 94% vs graphrag 100%)

---

## 下一步行动

### 决策点（Phase 4 中期，需用户裁定）
**SEALED 现状**：strategyqa TIE、4 数据集 SEALED 首次运行 guard 4/4 LOSS（budget_exceeded 结构性惩罚：musique 49.4% BE / hotpotqa 32.6% BE），H-029 修复已 PASS（n120 双数据集 acc_full +18~22pt，质量净中性，cost 预算内）。
- **当前 Coverage 口径**：40%（Phase 3 混合集合点估计，非严格 SEALED）+ strategyqa coverage 单元取消后名义上 2/5=40%。**Phase 4 SEALED 严格口径下**：strategyqa TIE、4 数据集 LOSS（修正前）——需等 H-029 全量重跑后重算。
- 两条路径二选一：
1. **全量 guard-budget 重跑**（n=1000/集 或扩 b2/b3），重算 SEALED 主表 + Coverage，再转 Phase 5 论文
2. **模型级生成器升级**（换更强 LLM / 微调 qwen3.6-27b 选型），超出当前研究约束（"不换模型"不变量），需先撤销约束

### 短期 (Phase 4)
1. **全量 guard-budget 运行**（H-029 已 PASS，需 n=1000/集 确认主表翻正幅度；b2 部分完成、b3 未启动——注意 launcher 中断）
2. 2wiki/drop 验证 H-029 无回归（BE 率低，预期影响小）
3. 三集合一致性 + FROZEN_PROTOCOL 复核

### 中期 (Phase 5)
1. 论文 + Artifact（诚实叙事：Clean DEVELOPMENT_SET 严格重测，40% = 真实 Coverage）
2. 投稿 PVLDB 2027

---

*本文件由 documentation-writer agent 维护，每次实验后更新。*
