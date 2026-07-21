from __future__ import annotations

import json

from .models import ExecutionResult
from .providers import AgnesClient, ChatResult, Usage


def generate_answer_response(
    client: AgnesClient,
    question: str,
    result: ExecutionResult,
    *,
    answer_kind: str = "short",
) -> tuple[str, ChatResult]:
    """Generate an answer from selected evidence and retain provider metadata."""
    evidence = [
        {
            "source_id": item.source_id,
            "source_span": item.source_span,
            "slot_id": item.slot_id,
            "bindings": item.bindings,
        }
        for item in result.evidence
    ]
    format_instruction = {
        "boolean": "Return exactly True or False.",
        "number": "Return only the requested number or short span.",
    }.get(answer_kind, "Return only a concise answer span.")
    messages = [
        {
            "role": "system",
            "content": f"Answer using only the supplied evidence. If it is insufficient, say so. {format_instruction} Do not invent citations.",
        },
        {
            "role": "user",
            "content": (
                f"Question:\n{question}\n\nJoined rows:\n{json.dumps(result.rows, ensure_ascii=False)}"
                f"\n\nEvidence:\n{json.dumps(evidence, ensure_ascii=False)}"
            ),
        },
    ]
    responses: list[ChatResult] = []
    for attempt in range(2):
        response = client.complete(messages, temperature=0.0)
        responses.append(response)
        if response.content and response.content.strip():
            combined = response.model_copy(update={
                "logical_calls": len(responses),
                "usage": Usage(
                    prompt_tokens=sum(item.usage.prompt_tokens for item in responses),
                    completion_tokens=sum(item.usage.completion_tokens for item in responses),
                ),
                "latency_ms": sum(item.latency_ms for item in responses),
            })
            return response.content.strip(), combined
        if attempt == 0:
            messages.append({"role": "user", "content": "Return the requested answer now as non-empty plain text."})
    raise ValueError("Agnes returned an empty answer twice")


def generate_answer(client: AgnesClient, question: str, result: ExecutionResult) -> tuple[str, int, int, float]:
    """Backward-compatible answer generation tuple."""
    answer, response = generate_answer_response(client, question, result)
    return answer, response.usage.prompt_tokens, response.usage.completion_tokens, response.latency_ms
