from __future__ import annotations

from .generation import generate_answer
from .models import EvidenceRecord, ExecutionResult, QuestionRecord, RunMetrics
from .providers import AgnesClient
from .retrieval import HybridRetriever


def run_whole_question_baseline(question: QuestionRecord, retriever: HybridRetriever, client: AgnesClient) -> ExecutionResult:
    """Run the fair whole-question retrieval baseline with the same services."""
    passages = retriever.search(question.question)
    metrics = RunMetrics(
        documents_accessed=len({item.passage.doc_id or item.passage.id for item in passages}),
        passages_processed=len(passages),
    )
    result = ExecutionResult(
        rows=[{"passage_id": item.passage.id} for item in passages],
        evidence=[EvidenceRecord(source_id=item.passage.id, source_span=item.passage.text, slot_id="baseline", bindings={}) for item in passages],
        metrics=metrics,
        status="ok" if passages else "empty",
    )
    if not passages:
        return result
    answer, prompt, completion, latency = generate_answer(client, question.question, result)
    return result.model_copy(update={
        "answer": answer,
        "metrics": metrics.model_copy(update={
            "llm_calls": 1,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "latency_ms": latency,
        }),
    })
