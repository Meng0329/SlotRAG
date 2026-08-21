# NOVELTY_CLAIM_AUDIT — 论文新颖性声明审计

**日期**: 2026-08-19
**来源**: `TKDE_RELATED_WORK_MATRIX.csv` (R1-R22)
**目的**: 确保论文对每个新颖性主张都对照了最接近的 prior work,不重蹈
`reviewer 说 "把 X 当 novelty"` 的覆辙。

## 论文当前新颖性主张 (从 section 5 提炼)

| # | 论文主张 | 最接近 prior | avoid_claim (from matrix) | 审计结论 |
|---|---|---|---|---|
| N1 | typed evidence requirements (condition 而非 action) | R1 (logical query trees), R4 (structured planning) | "first structured planning for RAG" | ✅ 可主张 —— 论文区分 requirement/condition 与 action/plan,R1/R4 未做此分离 |
| N2 | typed evidence state + requirement-aware physical allocation | R2 (DynaKRAG learned evidence control) | "first evidence-state adaptive control" | ✅ 可主张 —— learned estimator 无 control authority,SlotRAG explicit optimizer 决定 |
| N3 | requirement-driven optimizer (importance-weighted τ=2d-1 chain law) | R6 (Abacus cost-based optimizer) | "first cost-based semantic optimizer" | ✅ 可主张 —— 只对 unresolved requirement 计边际效用,非通用 cost model |
| N4 | typed heterogeneous Evidence Algebra | R5 (Semantic Operators), R19/R20 (TableRAG) | "heterogeneous support as novelty" | ⚠️ 需谨慎 —— 异构不是 novelty,typed algebra + requirement-aware selection 才是 |
| N5 | deterministic allocation 而非 learned policy | R2 (learned controller) | "state→learned action policy" | ✅ 可主张 —— 显式优化器,非 learned estimator |

## 禁止主张清单 (definitive no-claims)

以下任何表述若出现在论文中即为**过度声明**,需删除或改写:

1. **"first database-style planning for RAG"** — R1 已做 logical query tree + cost model + DP
2. **"first evidence-state adaptive control"** — R2 已做 evidence state + learned controller
3. **"first executable/programmatic multi-hop RAG"** — R3 已做 program synthesis/execution
4. **"first cost-based semantic optimizer"** — R6 Abacus 已做
5. **"heterogeneous support"** (generic) — R19/R20/R21 已做 text+table+KG
6. **"structured/rule-based cross-hop deterministic execution"** — R22 IReRa 已做
7. **"token efficiency"** (generic) — R9 TeaRAG / R10 FIT-RAG 已做
8. **"retrieve/generate alternation"** — R12 Generate-then-Ground 已做

## 诚实定位 (论文正确写法的基准线)

> SlotRAG 的贡献不是某个"第一次"的组件,而是一个**组合**:typed evidence
> requirements 作为稳定信息需求 + 与之解耦的物理执行 + 显式(非 learned)
> requirement-aware 资源分配 + 匹配预算下的诚实评估。每个组件单独看都有 prior,
> 组合与分离 (requirement/action separation) 是论文的可辩护新颖性。

## 已定位的论文表述检查

- [ ] section5 是否仍写 "optimizer"/"search"/"Pareto"? → 已改为 "physical-plan allocator" (P2 repositioning)
- [ ] section5 是否写 "cost model"? → 无,cost 仅作为 budget 约束
- [ ] abstract 是否写 "novel framework"? → 需检查,应是 "positioned combination"

---

**审计者**: Claude, 2026-08-19
**下次动作**: 将本审计与 `TKDE_ADVERSARIAL_REVIEW_LOOP.md` R1.3 结论交叉,投稿前再跑一次。
