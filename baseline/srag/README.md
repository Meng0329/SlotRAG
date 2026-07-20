# SRAG (Structured RAG)

Structured Retrieval-Augmented Generation with schema-aware retrieval.

## Implementation

```python
# Core approach:
# 1. Parse question into structured query
# 2. Retrieve based on structured representation
# 3. Execute query operations (join, filter, aggregate)

def structured_rag(query, schema, retriever, llm):
    # Step 1: Parse question into structured query
    structured_query = llm.generate(f"""
        Question: {query}
        Schema: {schema}
        Convert to structured query (JSON):
    """)

    # Step 2: Retrieve relevant documents
    documents = retriever.retrieve(structured_query['entities'])

    # Step 3: Execute operations
    result = execute_operations(documents, structured_query['operations'])

    return result
```

## Key Components

1. **Schema Parser**: Extracts entities and relations from questions
2. **Structured Retriever**: Retrieves based on entity mentions
3. **Query Executor**: Performs join, filter, count operations
4. **Answer Generator**: Formats final answer

## Operation Types

- **Join**: Combining information from multiple documents
- **Filter**: Selecting documents matching criteria
- **Count**: Counting entities/relations
- **Sort**: Ordering results by attribute

## References

- Similar to QO-Bench's query operations approach
