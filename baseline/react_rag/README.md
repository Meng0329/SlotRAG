# ReAct RAG

Reasoning + Acting framework for multi-hop RAG.

## Implementation

```python
# Core approach:
# 1. Generate reasoning trace
# 2. Decide action (retrieve/search)
# 3. Execute action and observe result
# 4. Repeat until answer is ready

def react_rag(query, retriever, llm, max_steps=5):
    context = ""
    for step in range(max_steps):
        # Reason about what information is needed
        reasoning = llm.generate(f"""
            Question: {query}
            Current context: {context}
            What should I search for next?
        """)

        # Decide action
        if "FINISH" in reasoning:
            break

        # Execute retrieval
        evidence = retriever.search(extract_search_query(reasoning))
        context += f"\n{evidence}"

    # Generate final answer
    return llm.generate(f"Question: {query}\nContext: {context}\nAnswer:")
```

## Key Components

1. **Reasoning Module**: Generates thought traces
2. **Action Module**: Decides retrieval actions
3. **Observation Module**: Processes retrieved evidence
4. **Stop Criterion**: Determines when to stop retrieving

## References

- ReAct: Yao et al. (2023) - "ReAct: Synergizing Reasoning and Acting in Language Models"
