from __future__ import annotations

import json

from .models import ExecutionResult
from .providers import AgnesClient, ChatResult, Usage


def _answer_tool(answer_kind: str) -> dict[str, object]:
    answer_schema: dict[str, object] = {"type": "string"}
    if answer_kind == "boolean":
        answer_schema["enum"] = ["True", "False"]
    elif answer_kind == "list":
        answer_schema["description"] = "Return only the requested comma-separated answer list."
    return {
        "type": "function",
        "function": {
            "name": "emit_final_answer",
            "description": "Return only the final answer span; never include reasoning or citations.",
            "parameters": {
                "type": "object",
                "properties": {"answer": answer_schema},
                "required": ["answer"],
                "additionalProperties": False,
            },
        },
    }


def _tool_answer(client: AgnesClient, response: ChatResult) -> str:
    if response.tool_calls:
        arguments = client.require_tool(response, "emit_final_answer")
        answer = arguments.get("answer")
        if isinstance(answer, str):
            return answer.strip()
        return ""
    return (response.content or "").strip()


def _structured_thinking_enabled(result: ExecutionResult, *, enabled: bool = False) -> bool:
    """Generation thinking is off by default (V5c fix: thinking caused over-caution).

    H-017: when ``enabled`` (a per-method flag), turn thinking ON so the
    generator can reason step-by-step (multi-hop for 2wiki, arithmetic for
    drop) before emitting the final span. The empty-answer retry in
    generate_answer_response guards against the old over-caution refusal mode.
    """
    return enabled


def generate_answer_response(
    client: AgnesClient,
    question: str,
    result: ExecutionResult,
    *,
    answer_kind: str = "short",
    structured_output: bool = False,
    generation_thinking: bool = False,
    generation_fidelity: bool = False,
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
    # H-018: evidence-fidelity instruction for short/number answers — prefer the
    # fuller form present in evidence (full name, qualifiers, complete phrase)
    # instead of the shortest form. Soft guidance, not a hard contract (unlike
    # H-005 entity contract, which over-truncated multi-entity answers).
    fidelity_instruction = (
        "Return the answer as a contiguous span taken from the supplied evidence. "
        "If the evidence contains a fuller form that answers the question (a full name, "
        "disambiguating qualifiers, or a complete phrase), return that fuller form rather "
        "than a shortened version. Do not shorten names or drop qualifiers."
    )
    if structured_output:
        format_instruction = {
            "boolean": "The answer must be exactly True or False.",
            "list": "The answer must contain only the requested comma-separated list.",
            "number": "The answer must contain only the requested number or short span.",
            "entity": (
                "The answer must be exactly one canonical entity name as it appears in the "
                "supplied evidence, with no extra qualifiers, articles, or descriptive text. "
                "If the evidence gives a full name, return the full name."
            ),
        }.get(answer_kind, "The answer must contain only a concise answer span.")
        if generation_fidelity and answer_kind in {"short", "number"}:
            format_instruction = fidelity_instruction
        system_instruction = (
            "Answer the question based on the supplied evidence. "
            f"{format_instruction} Call emit_final_answer exactly once."
        )
    else:
        format_instruction = {
            "boolean": "Return exactly True or False.",
            "number": "Return only the requested number or short span.",
            "entity": (
                "Return exactly one canonical entity name as it appears in the supplied "
                "evidence, with no extra qualifiers, articles, or descriptive text."
            ),
        }.get(answer_kind, "Return only a concise answer span.")
        if generation_fidelity and answer_kind in {"short", "number"}:
            format_instruction = fidelity_instruction
        system_instruction = (
            "Answer the question based on the supplied evidence. "
            f"{format_instruction} Do not invent citations."
        )
    messages = [
        {
            "role": "system",
            "content": system_instruction,
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
        # H-017: thinking on first attempt (multi-hop/arithmetic reasoning),
        # disabled on the retry to recover from over-caution refusal.
        use_thinking = generation_thinking and attempt == 0
        if structured_output:
            response = client.complete(
                messages,
                tools=[_answer_tool(answer_kind)],
                tool_choice={"type": "function", "function": {"name": "emit_final_answer"}},
                temperature=0.0,
                enable_thinking=_structured_thinking_enabled(result, enabled=use_thinking),
            )
        else:
            response = client.complete(
                messages,
                temperature=0.0,
                enable_thinking=_structured_thinking_enabled(result, enabled=use_thinking),
            )
        responses.append(response)
        answer = _tool_answer(client, response) if structured_output else (response.content or "").strip()
        if answer:
            combined = response.model_copy(update={
                "logical_calls": len(responses),
                "usage": Usage(
                    prompt_tokens=sum(item.usage.prompt_tokens for item in responses),
                    completion_tokens=sum(item.usage.completion_tokens for item in responses),
                ),
                "latency_ms": sum(item.latency_ms for item in responses),
            })
            return answer, combined
        if attempt == 0:
            messages.append({
                "role": "user",
                "content": (
                    "Return exactly one emit_final_answer tool call with a non-empty answer field now."
                    if structured_output
                    else "Return the requested answer now as non-empty plain text."
                ),
            })
    raise ValueError("Agnes returned an empty answer twice")


def generate_answer(client: AgnesClient, question: str, result: ExecutionResult) -> tuple[str, int, int, float]:
    """Backward-compatible answer generation tuple."""
    answer, response = generate_answer_response(client, question, result)
    return answer, response.usage.prompt_tokens, response.usage.completion_tokens, response.latency_ms
