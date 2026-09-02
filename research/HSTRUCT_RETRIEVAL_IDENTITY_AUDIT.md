# HSTRUCT_RETRIEVAL_IDENTITY_AUDIT.md — Retrieval Protocol Comparison

> **Created:** 2026-09-01 (H-STRUCT-1 Frozen-Plan Semantics Repair)
> **Purpose:** Confirm exploratory and confirmatory use identical retrieval protocol

---

## Sealed Exploratory Run (tkde-sealed-test-q35)

Config: `configs/experiments/tkde-sealed-test-q35.yaml`
Stage: `g7-sealed`

| Parameter | Value |
|-----------|-------|
| retrieval_backend | hybrid |
| bm25_k | 50 |
| dense_k | 50 |
| final_k | 10 |
| rrf_k | 60 |
| bm25_weight | 0.5 |
| dense_weight | 0.5 |
| chunk_tokens | 384 |
| chunk_overlap | 64 |
| embedding_model | Qwen/Qwen3-Embedding-0.6B |
| embedding_dimension | 1024 |
| reranker_model | bge-reranker-v2-m3 |
| reranker_top_n | 10 |

---

## Confirmatory Protocol

Source: `configs/default.yaml` (same config file used by runner)

| Parameter | Value |
|-----------|-------|
| retrieval_backend | hybrid (via BenchmarkRunner) |
| bm25_k | 50 |
| dense_k | 50 |
| final_k | 10 |
| rrf_k | 60 |
| bm25_weight | 0.5 |
| dense_weight | 0.5 |
| chunk_tokens | 384 |
| chunk_overlap | 64 |
| embedding_model | Qwen/Qwen3-Embedding-0.6B |
| embedding_dimension | 1024 |
| reranker_model | bge-reranker-v2-m3 |
| reranker_top_n | 10 |

---

## Identity Check

| Parameter | Exploratory | Confirmatory | Match |
|-----------|-------------|-------------|-------|
| retrieval_backend | hybrid | hybrid | ✅ |
| bm25_k | 50 | 50 | ✅ |
| dense_k | 50 | 50 | ✅ |
| final_k | 10 | 10 | ✅ |
| rrf_k | 60 | 60 | ✅ |
| bm25_weight | 0.5 | 0.5 | ✅ |
| dense_weight | 0.5 | 0.5 | ✅ |
| chunk_tokens | 384 | 384 | ✅ |
| chunk_overlap | 64 | 64 | ✅ |
| embedding_model | Qwen3-Embedding-0.6B | Qwen3-Embedding-0.6B | ✅ |
| embedding_dimension | 1024 | 1024 | ✅ |
| reranker_model | bge-reranker-v2-m3 | bge-reranker-v2-m3 | ✅ |
| reranker_top_n | 10 | 10 | ✅ |

**Result: ALL PARAMETERS IDENTICAL** ✅

---

## Note on Corpus Scope

Both exploratory and confirmatory use:
- Same `benchmark_root: benchmark` directory
- Same dataset files (hotpotqa, 2wikimultihop, musique)
- Same chunking (384 tokens, 64 overlap)
- Same embedding model and dimension
- Same reranker model
- Same RRF fusion (k=60, 50/50 weight)

The corpus is built identically. No corpus-scope differences between exploratory and confirmatory.
