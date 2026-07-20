from __future__ import annotations

import json
import random
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field

from .errors import SchemaError
from .models import BindingRow, EvidenceRecord, ExecutionResult, RunMetrics, Slot, SlotPlan
from .providers import AgnesClient, ChatResult
from .retrieval import HybridRetriever


def slot_plan_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "emit_slot_plan",
            "description": "Compile a natural-language question into query-specific evidence slots and joins.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slots": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "predicate": {"type": "string"},
                                "arguments": {"type": "array", "items": {"type": "string"}},
                                "constraints": {"type": "object"},
                                "importance": {"type": "number"},
                            },
                            "required": ["id", "predicate", "arguments"],
                        },
                    },
                    "joins": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                    "outputs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["slots", "joins", "outputs"],
            },
        },
    }


def extraction_tool(slot: Slot) -> dict[str, Any]:
    fields = sorted(slot.variables)
    properties = {field: {"type": "string"} for field in fields}
    return {
        "type": "function",
        "function": {
            "name": "emit_evidence_rows",
            "description": f"Extract zero or more {slot.predicate} relation rows from the passage.",
            "parameters": {
                "type": "object",
                "properties": {"rows": {"type": "array", "items": {"type": "object", "properties": properties, "required": fields}}},
                "required": ["rows"],
            },
        },
    }


class ExtractionRow(BaseModel):
    model_config = {"extra": "forbid"}

    rows: list[dict[str, str]] = Field(default_factory=list)


class SlotCompiler:
    def __init__(self, client: AgnesClient) -> None:
        self.client = client

    def compile(self, question: str) -> tuple[SlotPlan, ChatResult]:
        if not question.strip():
            raise ValueError("question cannot be empty")
        messages = [
            {"role": "system", "content": "You compile questions into a minimal executable SlotRAG plan. Use ?name for variables. Return only the requested tool call."},
            {"role": "user", "content": question},
        ]
        result = self.client.complete(messages, tools=[slot_plan_tool()], tool_choice={"type": "function", "function": {"name": "emit_slot_plan"}})
        args = self.client.require_tool(result, "emit_slot_plan")
        try:
            return SlotPlan.model_validate(args), result
        except Exception as exc:
            raise SchemaError(f"invalid Slot Plan: {exc}") from exc


class SlotMaterializer:
    def __init__(self, client: AgnesClient, retriever: HybridRetriever) -> None:
        self.client = client
        self.retriever = retriever

    def materialize(self, slot: Slot, bindings: dict[str, str]) -> tuple[list[BindingRow], RunMetrics]:
        query = slot.query_text(bindings)
        passages = self.retriever.search(query)
        metrics = RunMetrics(documents_accessed=len({p.passage.doc_id or p.passage.id for p in passages}), passages_processed=len(passages))
        rows: list[BindingRow] = []
        for result in passages:
            messages = [
                {"role": "system", "content": "Extract only facts explicitly supported by the passage. Use the provided tool; return an empty rows list when unsupported."},
                {"role": "user", "content": f"Relation: {slot.predicate}\nKnown bindings: {json.dumps(bindings, ensure_ascii=False)}\nPassage ID: {result.passage.id}\nPassage:\n{result.passage.text}"},
            ]
            response = self.client.complete(messages, tools=[extraction_tool(slot)], tool_choice={"type": "function", "function": {"name": "emit_evidence_rows"}})
            metrics = metrics.model_copy(update={
                "llm_calls": metrics.llm_calls + 1,
                "prompt_tokens": metrics.prompt_tokens + response.usage.prompt_tokens,
                "completion_tokens": metrics.completion_tokens + response.usage.completion_tokens,
                "latency_ms": metrics.latency_ms + response.latency_ms,
                "provider_request_ids": metrics.provider_request_ids + ([response.request_id] if response.request_id else []),
            })
            args = self.client.require_tool(response, "emit_evidence_rows")
            try:
                extracted = ExtractionRow.model_validate(args)
            except Exception as exc:
                raise SchemaError(f"invalid extracted rows for {slot.id}: {exc}") from exc
            for row in extracted.rows:
                normalized = {key.lstrip("?"): value.strip() for key, value in row.items()}
                expected = slot.variables
                if set(normalized) != expected or any(not value for value in normalized.values()):
                    raise SchemaError(f"extracted row for {slot.id} must contain exactly {sorted(expected)}")
                normalized.update({key: value for key, value in bindings.items() if key not in normalized})
                rows.append(BindingRow(slot_id=slot.id, bindings=normalized, source_id=result.passage.id, source_span=result.passage.text, confidence=1.0, retrieval_score=result.score))
        return rows, metrics

    def materialize_many(self, slot: Slot, contexts: list[dict[str, str]]) -> tuple[list[BindingRow], RunMetrics]:
        """Materialize once per distinct binding context and merge the rows."""
        merged: list[BindingRow] = []
        metrics = RunMetrics()
        seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
        for bindings in contexts or [{}]:
            rows, current_metrics = self.materialize(slot, bindings)
            metrics = metrics.model_copy(update={
                "documents_accessed": metrics.documents_accessed + current_metrics.documents_accessed,
                "passages_processed": metrics.passages_processed + current_metrics.passages_processed,
                "llm_calls": metrics.llm_calls + current_metrics.llm_calls,
                "prompt_tokens": metrics.prompt_tokens + current_metrics.prompt_tokens,
                "completion_tokens": metrics.completion_tokens + current_metrics.completion_tokens,
                "latency_ms": metrics.latency_ms + current_metrics.latency_ms,
                "provider_request_ids": metrics.provider_request_ids + current_metrics.provider_request_ids,
            })
            for row in rows:
                key = (row.source_id, tuple(sorted(row.bindings.items())))
                if key not in seen:
                    seen.add(key)
                    merged.append(row)
        return merged, metrics


def _join_rows(left: list[BindingRow], right: list[BindingRow], left_field: str, right_field: str) -> list[BindingRow]:
    right_index: dict[str, list[BindingRow]] = defaultdict(list)
    for row in right:
        if right_value := row.bindings.get(right_field):
            right_index[right_value].append(row)
    merged: list[BindingRow] = []
    for left_row in left:
        key = left_row.bindings.get(left_field)
        for right_row in right_index.get(key, []):
            bindings = dict(left_row.bindings)
            if any(k in bindings and bindings[k] != value for k, value in right_row.bindings.items()):
                continue
            bindings.update(right_row.bindings)
            merged.append(BindingRow(slot_id=f"{left_row.slot_id}+{right_row.slot_id}", bindings=bindings, source_id=f"{left_row.source_id}|{right_row.source_id}", source_span=f"{left_row.source_span}\n---\n{right_row.source_span}", confidence=min(left_row.confidence, right_row.confidence), retrieval_score=min(left_row.retrieval_score or 0, right_row.retrieval_score or 0)))
    return merged


class AdaptiveExecutor:
    def __init__(self, materializer: SlotMaterializer, *, default_slot_cost: float = 1.0, unbound_argument_cost: float = 2.0, max_replans: int = 16, random_seed: int = 2027) -> None:
        self.materializer = materializer
        self.default_slot_cost = default_slot_cost
        self.unbound_argument_cost = unbound_argument_cost
        self.max_replans = max_replans
        self.random = random.Random(random_seed)

    def _choose_slot(self, remaining: list[Slot], bindings: dict[str, str], plan: SlotPlan, cardinalities: dict[str, int], strategy: str) -> Slot:
        connected = [slot for slot in remaining if not bindings or any(
            slot.id == join.right_slot and join.left_field in bindings
            or slot.id == join.left_slot and join.right_field in bindings
            for join in plan.joins
        )]
        candidates = connected or remaining
        if strategy == "question":
            return candidates[0]
        if strategy == "random":
            return self.random.choice(candidates)
        if strategy == "fixed":
            return sorted(candidates, key=lambda slot: slot.id)[0]
        if strategy == "oracle":
            return min(candidates, key=lambda slot: cardinalities.get(slot.id, 10**9))
        def score(slot: Slot) -> float:
            bound = len(slot.variables & bindings.keys())
            estimated = max(cardinalities.get(slot.id, 1), 1)
            cost = self.default_slot_cost + max(len(slot.variables) - bound, 0) * self.unbound_argument_cost
            return (bound + slot.importance) / (cost * estimated)
        return max(candidates, key=score)

    def execute(self, plan: SlotPlan, *, strategy: str = "adaptive") -> ExecutionResult:
        remaining = list(plan.slots)
        materialized: dict[str, list[BindingRow]] = {}
        cardinalities: dict[str, int] = {}
        all_bindings: dict[str, str] = {}
        evidence: list[EvidenceRecord] = []
        metrics = RunMetrics()
        order: list[str] = []
        current: list[BindingRow] | None = None
        for step in range(self.max_replans):
            if not remaining:
                break
            slot = self._choose_slot(remaining, all_bindings, plan, cardinalities, strategy)
            remaining.remove(slot)
            order.append(slot.id)
            if current is None:
                binding_contexts = [{}]
            else:
                relevant = slot.variables & set(current[0].bindings)
                binding_contexts = []
                seen_contexts: set[tuple[tuple[str, str], ...]] = set()
                for current_row in current:
                    context = {key: value for key, value in current_row.bindings.items() if key in relevant}
                    context_key = tuple(sorted(context.items()))
                    if context_key not in seen_contexts:
                        seen_contexts.add(context_key)
                        binding_contexts.append(context)
                if not binding_contexts:
                    binding_contexts = [{}]
            materialize_many = getattr(self.materializer, "materialize_many", None)
            if materialize_many is not None:
                rows, slot_metrics = materialize_many(slot, binding_contexts)
            else:
                rows, slot_metrics = self.materializer.materialize(slot, binding_contexts[0])
            materialized[slot.id] = rows
            cardinalities[slot.id] = len(rows)
            metrics = metrics.model_copy(update={
                "documents_accessed": metrics.documents_accessed + slot_metrics.documents_accessed,
                "passages_processed": metrics.passages_processed + slot_metrics.passages_processed,
                "llm_calls": metrics.llm_calls + slot_metrics.llm_calls,
                "prompt_tokens": metrics.prompt_tokens + slot_metrics.prompt_tokens,
                "completion_tokens": metrics.completion_tokens + slot_metrics.completion_tokens,
                "latency_ms": metrics.latency_ms + slot_metrics.latency_ms,
                "intermediate_binding_sizes": metrics.intermediate_binding_sizes + [len(rows) if current is None else len(current)],
                "reoptimizations": metrics.reoptimizations + (1 if step else 0),
            })
            if not rows:
                return ExecutionResult(rows=[], evidence=[], order=order, metrics=metrics, status="empty")
            if current is None:
                current = rows
            else:
                join = next((j for j in plan.joins if (j.left_slot in materialized and j.right_slot == slot.id) or (j.right_slot in materialized and j.left_slot == slot.id)), None)
                if join is None:
                    return ExecutionResult(rows=[], evidence=[], order=order, metrics=metrics, status="failed", error=f"slot {slot.id} has no join path")
                elif join.right_slot == slot.id:
                    current = _join_rows(current, rows, join.left_field, join.right_field)
                else:
                    current = _join_rows(rows, current, join.left_field, join.right_field)
            if current:
                # The planner only needs the set of currently bound fields for
                # choosing a connected next slot. Actual values are propagated
                # through binding_contexts above.
                all_bindings = {key: "<bound>" for row in current for key in row.bindings}
            else:
                return ExecutionResult(rows=[], evidence=[], order=order, metrics=metrics, status="empty")
        if remaining:
            return ExecutionResult(rows=[], evidence=[], order=order, metrics=metrics, status="failed", error="maximum replans exceeded")
        output_rows = []
        for row in current or []:
            output_rows.append({key.lstrip("?"): row.bindings.get(key.lstrip("?"), row.bindings.get(key, "")) for key in plan.outputs})
            evidence.append(EvidenceRecord(source_id=row.source_id, source_span=row.source_span, slot_id=row.slot_id, bindings=row.bindings))
        return ExecutionResult(rows=output_rows, evidence=evidence, order=order, metrics=metrics, status="ok" if output_rows else "empty")
