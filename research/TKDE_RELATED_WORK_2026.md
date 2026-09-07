# TKDE_RELATED_WORK_2026.md — 2026 Verified Literature for TKDE Paper v4

> **Date**: 2026-09-07
> **Status**: All entries verified via arXiv API (no fabricated citations)
> **Differentiation focus**: decision point, decision input, plan explicitness, global budget feasibility

---

## Verified 2026 Papers

| # | Paper | Authors | Venue/ID | Relevance to SlotRAG | Differentiation |
|---|-------|---------|----------|---------------------|-----------------|
| 1 | PlanRAG: Logical Query Planning for Scalable RAG | Liu et al. | arXiv:2607.00508 | Logical query trees + cost optimization | Upstream: constructs/optimizes the reasoning tree; SlotRAG is downstream (physical allocation for an already-compiled plan) |
| 2 | PyRAG | Sun et al. | arXiv:2605.12975 | Executable programs composing retrieval + reasoning | Upstream program composition; SlotRAG addresses allocation over typed requirements, not program synthesis |
| 3 | DynaKRAG | Zhou et al. | arXiv:2607.06507 | Learned evidence control for multi-hop retrieval | Learned controller; SlotRAG gate is deterministic/structural/non-parametric |
| 4 | PAGE-RAG: Provenance-Aware Graph Evidence | Deng et al. | arXiv:2608.29753 | Evidence promotion through provenance graphs under fixed budgets | Candidate-level promotion; SlotRAG allocates over compiled slot requirements (different abstraction) |
| 5 | Know Before You Fetch | Dong et al. | arXiv:2606.29959 | Retrieval-budget calibration to reduce waste | Calibration of retrieval triggering; SlotRAG tests global feasibility of an explicit plan |

## Verified Pre-2026 Foundations

| # | Paper | Authors | Venue | Role in v4 |
|---|-------|---------|-------|------------|
| 6 | Adaptive-RAG | Jeong et al. 2024 | arXiv:2403.14403 | Learned query-complexity classifier — different decision point (raw question vs compiled plan) |
| 7 | IRCoT | Trivedi et al. 2023 | ACL | Interleaved retrieval+CoT — trajectory-based, no pre-committed plan |
| 8 | ReAct | Yao et al. 2023 | ICLR | Agentic loop — no explicit evidence plan |
| 9 | GraphRAG | Edge et al. 2024 | — | KG-based retrieval — different retrieval substrate |
| 10 | HotpotQA / 2Wiki / MuSiQue / StrategyQA / DROP | Yang 2018 / Ho 2020 / Trivedi 2022 / Geva 2021 / Dua 2019 | EMNLP / ECAI / TACL / TACL / NAACL | Benchmark datasets |
| 11 | Sema / LOTUS | — | — | Semantic query processing with typed operators — shared principle, different target |

## Dropped (Unverifiable)

| Paper | Reason |
|-------|--------|
| RAG-on-a-Diet (Chen et al. 2024) | Not found on arXiv by title, author, or keyword search; no DOI or proceedings entry located. Replaced with verified budget-aware class (PAGE-RAG, Know Before You Fetch). No fabricated citation. |

## Comparison Table (§20 in paper)

6 methods × 5 columns: Decision input | Decision point | Learned? | Explicit plan? | Global budget feasibility? — entries based on the cited papers' own descriptions, verified against abstracts.
