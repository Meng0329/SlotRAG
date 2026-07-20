from __future__ import annotations

import json

from .models import ExecutionResult
from .providers import AgnesClient


def generate_answer(client: AgnesClient, question: str, result: ExecutionResult) -> tuple[str, int, int, float]:
    """Generate an answer from joined rows and their source spans only."""
    evidence = [
        {
            "bindings": row,
            "source_id": item.source_id,
            "source_span": item.source_span,
        }
        for row, item in zip(result.rows, result.evidence)
    ]
    messages = [
        {
            "role": "system",
            "content": "Answer the question using only the supplied joined evidence. If the evidence is insufficient, say so. Keep the answer concise and do not invent citations.",
        },
        {
            "role": "user",
            "content": f"Question:\n{question}\n\nJoined evidence:\n{json.dumps(evidence, ensure_ascii=False)}",
        },
    ]
    response = client.complete(messages, temperature=0.0)
    if not response.content:
        raise ValueError("Agnes returned an empty answer")
    return response.content.strip(), response.usage.prompt_tokens, response.usage.completion_tokens, response.latency_ms
