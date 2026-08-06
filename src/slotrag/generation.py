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


def _candidate_spans_tool() -> dict[str, object]:
    """H-020: enumerate candidate answer spans, grounded in evidence by construction."""
    return {
        "type": "function",
        "function": {
            "name": "emit_candidate_spans",
            "description": (
                "List up to 5 candidate answer spans, each a contiguous substring of the "
                "supplied evidence. Do not paraphrase; copy spans verbatim from the passages."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "spans": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Candidate answer spans, verbatim from evidence.",
                        "maxItems": 5,
                    },
                    "passage_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Source ids of the passages each span came from.",
                        "maxItems": 5,
                    },
                },
                "required": ["spans", "passage_ids"],
                "additionalProperties": False,
            },
        },
    }


def _select_answer_tool() -> dict[str, object]:
    """H-020: select the single candidate that best answers the question."""
    return {
        "type": "function",
        "function": {
            "name": "emit_selected_answer",
            "description": (
                "Select the single candidate span that best answers the question. If none "
                "of the candidates answer the question, emit an empty string."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                },
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


def _extract_then_select_answer(
    client: AgnesClient,
    question: str,
    result: ExecutionResult,
    messages: list[dict[str, object]],
) -> tuple[str | None, list[ChatResult]]:
    """H-020 two-stage output contract: enumerate grounded candidates, then select.

    Step 1 — ``emit_candidate_spans``: the generator may only emit contiguous
    spans copied verbatim from the supplied evidence, so the answer is grounded
    by construction and there is no room for the internal answer prior to leak.

    Step 2 — ``emit_selected_answer``: given the candidates, the generator picks
    the single span that best answers the question (or emits an empty string if
    none match).

    Returns ``(answer, responses)`` where ``answer`` is ``None`` when the
    contract failed (no candidates emitted, empty selection, tool error) so the
    caller falls back to the free-generation path.
    """
    responses: list[ChatResult] = []
    response = client.complete(
        messages,
        tools=[_candidate_spans_tool()],
        tool_choice={"type": "function", "function": {"name": "emit_candidate_spans"}},
        temperature=0.0,
    )
    responses.append(response)
    arguments = client.require_tool(response, "emit_candidate_spans")
    spans = arguments.get("spans") or []
    passage_ids = arguments.get("passage_ids") or []
    spans = [
        str(span).strip()
        for span in (spans if isinstance(spans, list) else [])
        if isinstance(span, str) and span.strip()
    ]
    if not spans:
        return None, responses
    step2_messages = list(messages) + [
        {
            "role": "user",
            "content": (
                "The following candidate answer spans were extracted verbatim from the evidence:\n"
                f"{json.dumps({'spans': spans, 'passage_ids': passage_ids}, ensure_ascii=False)}\n\n"
                "Select the single candidate span that best answers the question. "
                "Call emit_selected_answer exactly once."
            ),
        },
    ]
    response = client.complete(
        step2_messages,
        tools=[_select_answer_tool()],
        tool_choice={"type": "function", "function": {"name": "emit_selected_answer"}},
        temperature=0.0,
    )
    responses.append(response)
    arguments = client.require_tool(response, "emit_selected_answer")
    answer = arguments.get("answer")
    if isinstance(answer, str) and answer.strip():
        return answer.strip(), responses
    return None, responses


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
    extract_then_select: bool = False,
) -> tuple[str, ChatResult]:
    """Generate an answer from selected evidence and retain provider metadata.

    H-020: when ``extract_then_select`` is set, run the two-stage output
    contract (grounded candidate extraction, then selection). If the contract
    fails (no candidates / empty selection / tool error), fall back to the
    normal free-generation path so H-020 can only add grounded answers, never
    remove an answer.
    """
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
    if extract_then_select:
        # H-020: two-stage output contract. Fall back to free generation on
        # any contract failure so the method never loses an answer it could
        # already produce.
        answer, select_responses = _extract_then_select_answer(client, question, result, messages)
        if answer is not None:
            combined = select_responses[-1].model_copy(update={
                "logical_calls": len(select_responses),
                "usage": Usage(
                    prompt_tokens=sum(item.usage.prompt_tokens for item in select_responses),
                    completion_tokens=sum(item.usage.completion_tokens for item in select_responses),
                ),
                "latency_ms": sum(item.latency_ms for item in select_responses),
            })
            return answer, combined
        # fall through to free generation below
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
