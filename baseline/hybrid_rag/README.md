# Hybrid RAG

Standard hybrid retrieval baseline combining sparse and dense retrieval.

## Implementation

```python
# Core approach:
# 1. BM25 retrieval (sparse/lexical)
# 2. Dense retrieval (semantic/vector search)
# 3. Reciprocal Rank Fusion (RRF) to combine results

def hybrid_retrieve(query, bm25_index, dense_index, k=10):
    # BM25 results
    bm25_results = bm25_search(query, bm25_index, top_k=k*2)

    # Dense results
    dense_results = dense_search(query, dense_index, top_k=k*2)

    # RRF fusion
    fused = reciprocal_rank_fusion([bm25_results, dense_results], k=60)

    return fused[:k]
```

## Key Components

1. **BM25 Retriever**: Term-based lexical matching
2. **Dense Retriever**: Embedding-based semantic search
3. **Fusion Strategy**: RRF, weighted combination, or learned fusion

## References

- BM25: Robertson & Zaragoza (2009)
- RRF: Cormack et al. (2009)
