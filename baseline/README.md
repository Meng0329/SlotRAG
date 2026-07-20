# SlotRAG Baseline Methods

Baselines for multi-hop RAG evaluation.

## Directory Structure

| Directory | Method | Source | Stars |
|-----------|--------|--------|-------|
| `ircot/` | IRCoT (Interleaved Retrieval + Chain-of-Thought) | [StonyBrookNLP/ircot](https://github.com/StonyBrookNLP/ircot) | 271 |
| `PlanRAG/` | PlanRAG (Plan-then-Retrieval Augmented Generation) | [myeon9h/PlanRAG](https://github.com/myeon9h/PlanRAG) | 154 |
| `graph_rag/` | Microsoft GraphRAG | [microsoft/graphrag](https://github.com/microsoft/graphrag) | 20k+ |
| `hybrid_rag/` | Hybrid RAG (BM25 + Dense) | Custom implementation | - |
| `react_rag/` | ReAct RAG (Reasoning + Acting) | Custom implementation | - |
| `srag/` | SRAG (Structured RAG) | Custom implementation | - |

## Method Descriptions

### IRCoT
Interleaving Retrieval with Chain-of-Thought Reasoning for Knowledge-Intensive Multi-Step Questions (ACL 2023).
- Iteratively retrieves evidence and generates reasoning steps
- Uses CoT to guide retrieval for multi-hop questions

### PlanRAG
A Plan-then-Retrieval Augmented Generation for Generative Large Language Models as Decision Makers (NAACL 2024).
- First generates a plan, then retrieves evidence based on the plan
- Two-stage approach: planning + retrieval

### GraphRAG
Microsoft's GraphRAG uses knowledge graphs for retrieval.
- Builds entity-relationship graphs from documents
- Uses community detection for summarization
- Global + local search modes

### Hybrid RAG
Standard hybrid retrieval combining:
- BM25 (sparse/lexical retrieval)
- Dense retrieval (semantic/vector search)
- Reciprocal Rank Fusion (RRF) or similar combination

### ReAct RAG
Reasoning + Acting framework for RAG:
- Interleaves reasoning traces with action (retrieval) steps
- Uses tool use paradigm for evidence gathering

### SRAG
Structured RAG approach:
- Parses questions into structured queries
- Executes queries against document索引
- Often involves schema-aware retrieval

## Usage

Each baseline has its own setup instructions. See individual README files.

## References

```bibtex
@inproceedings{trivedi2023interleaving,
  title={Interleaving Retrieval with Chain-of-Thought Reasoning for Knowledge-Intensive Multi-Step Questions},
  author={Trivedi, Harsh and Balasubramanian, Niranjan and Khot, Tushar and Sabharwal, Ashish},
  booktitle={ACL},
  year={2023}
}

@inproceedings{baek2024planrag,
  title={PlanRAG: A Plan-then-Retrieval Augmented Generation for Generative Large Language Models as Decision Makers},
  author={Baek, Junghyun and Aji, Ahmad Fauzi and Saffari, Amir},
  booktitle={NAACL},
  year={2024}
}

@article{edge2024local,
  title={From Local to Global: A Graph RAG Approach to Query-Focused Summarization},
  author={Edge, Darren and Trinh, Ha and Cheng, Nathan and others},
  journal={arXiv preprint arXiv:2404.16130},
  year={2024}
}
```
