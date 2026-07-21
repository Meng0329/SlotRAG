from __future__ import annotations

import json
import itertools
import math
import random
import re
import time
from collections import defaultdict
from copy import deepcopy
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from .errors import SchemaError
from .models import BindingRow, EvidenceRecord, ExecutionResult, RelationalOperator, RunMetrics, Slot, SlotPlan
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
                                "arguments": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": {"type": "string"},
                                    "description": "Constants or variables prefixed with ?. Every slot must contain at least one variable.",
                                },
                                "constraints": {"type": "object"},
                                "importance": {"type": "number"},
                                "estimated_cardinality": {"type": "number", "exclusiveMinimum": 0},
                                "estimated_cost": {"type": "number", "exclusiveMinimum": 0},
                            },
                            "required": ["id", "predicate", "arguments"],
                            "additionalProperties": False,
                        },
                    },
                    "joins": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "left_slot": {"type": "string"},
                                "left_field": {"type": "string", "description": "Shared variable name without ?; must equal right_field"},
                                "right_slot": {"type": "string"},
                                "right_field": {"type": "string", "description": "Shared variable name without ?; must equal left_field"},
                            },
                            "required": ["left_slot", "left_field", "right_slot", "right_field"],
                            "additionalProperties": False,
                        },
                    },
                    "outputs": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                        "description": "Output variables, each prefixed with ?.",
                    },
                    "operators": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "kind": {
                                    "type": "string",
                                    "enum": ["filter", "project", "intersect", "count", "sort", "argmin", "argmax", "compare", "boolean", "arithmetic"],
                                },
                                "fields": {"type": "array", "items": {"type": "string"}},
                                "field": {"type": ["string", "null"]},
                                "output": {"type": ["string", "null"]},
                                "comparator": {"type": ["string", "null"]},
                                "operation": {"type": ["string", "null"], "enum": ["add", "subtract", "multiply", "divide", None]},
                                "value": {},
                                "descending": {"type": "boolean"},
                                "limit": {"type": ["integer", "null"]},
                            },
                            "required": ["id", "kind"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["slots", "joins", "outputs"],
                "additionalProperties": False,
            },
        },
    }


def extraction_tool(slot: Slot, source_ids: list[str] | None = None) -> dict[str, Any]:
    fields = sorted(slot.variables)
    properties = {field: {"type": "string"} for field in fields}
    required = list(fields)
    if source_ids:
        properties["source_id"] = {"type": "string", "enum": source_ids}
        required.append("source_id")
    return {
        "type": "function",
        "function": {
            "name": "emit_evidence_rows",
            "description": f"Extract zero or more explicitly supported {slot.predicate} relation rows with source attribution.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rows": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": properties,
                            "required": required,
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["rows"],
                "additionalProperties": False,
            },
        },
    }


class ExtractionRow(BaseModel):
    model_config = {"extra": "forbid"}

    rows: list[dict[str, str]] = Field(default_factory=list)


class ExecutionOptions(BaseModel):
    """Independent switches used by the execution-policy ablations."""

    runtime_replan: bool = True
    incremental_join: bool = True
    binding_propagation: bool = True
    eager_materialization: bool = False
    typed_operators: bool = True


class SlotCompiler:
    def __init__(self, client: AgnesClient) -> None:
        self.client = client

    @staticmethod
    def _record_response(metrics: RunMetrics, response: ChatResult, *, phase: str) -> RunMetrics:
        update = {
            "llm_calls": metrics.llm_calls + response.logical_calls,
            "prompt_tokens": metrics.prompt_tokens + response.usage.prompt_tokens,
            "completion_tokens": metrics.completion_tokens + response.usage.completion_tokens,
            "latency_ms": metrics.latency_ms + response.latency_ms,
            "provider_request_ids": metrics.provider_request_ids + ([response.request_id] if response.request_id else []),
            f"{phase}_llm_calls": getattr(metrics, f"{phase}_llm_calls") + response.logical_calls,
            f"{phase}_prompt_tokens": getattr(metrics, f"{phase}_prompt_tokens") + response.usage.prompt_tokens,
            f"{phase}_completion_tokens": getattr(metrics, f"{phase}_completion_tokens") + response.usage.completion_tokens,
        }
        return metrics.model_copy(update=update)

    @staticmethod
    def _validate_grounding(plan: SlotPlan, question: str) -> None:
        normalized_question = " ".join(re.findall(r"\w+", question.casefold()))

        def require_grounded(value: object) -> None:
            if value is None or isinstance(value, bool):
                return
            normalized = " ".join(re.findall(r"\w+", str(value).strip('"\'').casefold()))
            if normalized and normalized not in normalized_question:
                raise ValueError(f"plan constant is not grounded in the question: {value!r}")

        for slot in plan.slots:
            for argument in slot.arguments:
                if not argument.startswith("?"):
                    require_grounded(argument)
            for value in slot.constraints.values():
                if isinstance(value, (list, tuple, set)):
                    for item in value:
                        require_grounded(item)
                elif not isinstance(value, dict):
                    require_grounded(value)
        for operator in plan.operators:
            require_grounded(operator.value)

    @staticmethod
    def _eliminate_anchor_slots(plan: SlotPlan) -> SlotPlan:
        payload = plan.model_dump(mode="python")
        anchor_predicates = {"person", "entity", "item", "place"}
        for anchor in list(payload["slots"]):
            arguments = anchor["arguments"]
            variables = [argument[1:] for argument in arguments if argument.startswith("?")]
            constants = [argument for argument in arguments if not argument.startswith("?")]
            if anchor["predicate"].casefold() not in anchor_predicates or len(variables) != 1 or len(constants) != 1:
                continue
            variable = variables[0]
            consumers = [
                slot for slot in payload["slots"]
                if slot["id"] != anchor["id"] and f"?{variable}" in slot["arguments"]
            ]
            if len(consumers) < 2 or f"?{variable}" in payload["outputs"]:
                continue
            payload["slots"] = [slot for slot in payload["slots"] if slot["id"] != anchor["id"]]
            for consumer in consumers:
                consumer["constraints"] = {**consumer.get("constraints", {}), variable: constants[0]}
            payload["joins"] = [
                join for join in payload["joins"]
                if join["left_slot"] != anchor["id"] and join["right_slot"] != anchor["id"]
            ]
            existing = {
                (join["left_slot"], join["right_slot"], join["left_field"])
                for join in payload["joins"]
            }
            for left, right in zip(consumers, consumers[1:]):
                key = (left["id"], right["id"], variable)
                reverse = (right["id"], left["id"], variable)
                if key not in existing and reverse not in existing:
                    payload["joins"].append({
                        "left_slot": left["id"],
                        "left_field": variable,
                        "right_slot": right["id"],
                        "right_field": variable,
                    })
            return SlotPlan.model_validate(payload)
        return plan

    @staticmethod
    def _repair_join_keys(payload: dict[str, Any]) -> dict[str, Any] | None:
        """Repair only joins whose shared variable is unambiguous from slot arguments."""
        slots = payload.get("slots")
        joins = payload.get("joins")
        if not isinstance(slots, list) or not isinstance(joins, list):
            return None
        variables: dict[str, set[str]] = {}
        for slot in slots:
            if not isinstance(slot, dict) or not isinstance(slot.get("id"), str) or not isinstance(slot.get("arguments"), list):
                return None
            variables[slot["id"]] = {
                argument[1:]
                for argument in slot["arguments"]
                if isinstance(argument, str) and argument.startswith("?")
            }

        candidate = deepcopy(payload)
        repaired_joins: list[dict[str, str]] = []
        changed = False
        for raw_join in joins:
            try:
                if isinstance(raw_join, (list, tuple)) and len(raw_join) == 2:
                    left_slot, left_field = str(raw_join[0]).split(".", 1)
                    right_slot, right_field = str(raw_join[1]).split(".", 1)
                elif isinstance(raw_join, dict) and "left" in raw_join and "right" in raw_join:
                    left_slot, left_field = str(raw_join["left"]).split(".", 1)
                    right_slot, right_field = str(raw_join["right"]).split(".", 1)
                elif isinstance(raw_join, dict):
                    left_slot = str(raw_join.get("left_slot", ""))
                    right_slot = str(raw_join.get("right_slot", ""))
                    left_field = str(raw_join.get("left_field", "")).lstrip("?")
                    right_field = str(raw_join.get("right_field", "")).lstrip("?")
                else:
                    return None
            except ValueError:
                return None
            if left_slot not in variables or right_slot not in variables or left_slot == right_slot:
                return None
            common = variables[left_slot] & variables[right_slot]
            if left_field == right_field and left_field in common:
                field = left_field
            elif len(common) == 1:
                field = next(iter(common))
                changed = True
            else:
                return None
            repaired_joins.append({
                "left_slot": left_slot,
                "left_field": field,
                "right_slot": right_slot,
                "right_field": field,
            })

        joined_pairs = {frozenset((join["left_slot"], join["right_slot"])) for join in repaired_joins}
        slot_ids = list(variables)
        for left_index, left_slot in enumerate(slot_ids):
            for right_slot in slot_ids[left_index + 1:]:
                pair = frozenset((left_slot, right_slot))
                common = variables[left_slot] & variables[right_slot]
                if pair not in joined_pairs and len(common) == 1:
                    field = next(iter(common))
                    repaired_joins.append({
                        "left_slot": left_slot,
                        "left_field": field,
                        "right_slot": right_slot,
                        "right_field": field,
                    })
                    joined_pairs.add(pair)
                    changed = True
        if not changed:
            return None
        candidate["joins"] = repaired_joins
        return candidate

    def compile(self, question: str, *, answer_kind: str = "short") -> tuple[SlotPlan, RunMetrics]:
        if not question.strip():
            raise ValueError("question cannot be empty")
        if answer_kind == "boolean":
            return SlotPlan(
                slots=[Slot(
                    id="S1",
                    predicate="EvidenceAnsweringQuestion",
                    arguments=["?answer"],
                    constraints={"question": question},
                    estimated_cardinality=2,
                )],
                outputs=["?answer"],
            ), RunMetrics(heuristic_plans=1)
        type_guidance = ""
        if answer_kind == "boolean":
            type_guidance = (
                " This is a yes/no question: use exactly one EvidenceAnsweringQuestion slot with argument ?answer, "
                "no joins, and no invented relation predicates; let the evidence answerer combine the supplied facts."
            )
        elif answer_kind == "number":
            type_guidance = (
                " This is a numeric question: use explicit numeric fields and an arithmetic operator when the question asks for a difference, sum, product, or quotient."
            )
        messages = [
            {
                "role": "system",
                "content": (
                    "Compile the question into a minimal connected SlotRAG plan and return only emit_slot_plan. "
                    "Every slot must contain at least one ?variable. Join fields are variable names without ?. "
                    "A join is an object like {\"left_slot\":\"S1\",\"left_field\":\"person\","
                    "\"right_slot\":\"S2\",\"right_field\":\"person\"}. "
                    "Use no joins for a one-slot plan. Outputs must be ?variables declared by slots. "
                    "Reuse the exact same variable name for the same entity across slots and on both sides of a join. "
                    "Represent entities stated in the question as constants inside a relation; do not create a unary slot merely to restate a known constant. "
                    "Never introduce a constant, entity name, date, or fact that is not stated verbatim in the question; represent every unknown as a ?variable to be retrieved. "
                    "Predicates must be concise relation names, not natural-language claims. "
                    "Example: to find where the partner of PersonX was born, use "
                    "S1 PartnerOf(PersonX, ?partner), S2 BornIn(?partner, ?place), join S1.partner to S2.partner, output ?place. "
                    "Use typed operators for explicit filter, count, sort, extremum, comparison, boolean, or arithmetic operations. "
                    "For 'how many more X than Y', extract ?x and ?y in a slot, then use arithmetic operation subtract with fields [x,y], output difference, and plan output ?difference."
                    + type_guidance
                ),
            },
            {"role": "user", "content": question},
        ]
        metrics = RunMetrics()
        last_error = "unknown validation error"
        invalid_args: dict[str, Any] = {}
        max_attempts = 3
        for attempt in range(max_attempts):
            result = self.client.complete(
                messages,
                tools=[slot_plan_tool()],
                tool_choice={"type": "function", "function": {"name": "emit_slot_plan"}},
                temperature=0.0,
            )
            metrics = self._record_response(metrics, result, phase="compilation")
            try:
                invalid_args = self.client.require_tool(result, "emit_slot_plan")
                plan = SlotPlan.model_validate(invalid_args)
                self._validate_grounding(plan, question)
                return self._eliminate_anchor_slots(plan), metrics
            except (SchemaError, ValidationError, ValueError) as exc:
                last_error = str(exc)
                metrics = metrics.model_copy(update={
                    "structured_output_failures": metrics.structured_output_failures + 1,
                    "plan_validation_errors": metrics.plan_validation_errors + [last_error[:2000]],
                })
                if attempt < max_attempts - 1:
                    repaired_payload = self._repair_join_keys(invalid_args)
                    if repaired_payload is not None:
                        try:
                            repaired_plan = SlotPlan.model_validate(repaired_payload)
                            self._validate_grounding(repaired_plan, question)
                        except (ValidationError, ValueError):
                            pass
                        else:
                            metrics = metrics.model_copy(update={
                                "structured_output_repairs": metrics.structured_output_repairs + 1,
                                "local_plan_repairs": metrics.local_plan_repairs + 1,
                            })
                            return self._eliminate_anchor_slots(repaired_plan), metrics
                    metrics = metrics.model_copy(update={
                        "structured_output_repairs": metrics.structured_output_repairs + 1,
                    })
                    messages.append({
                        "role": "user",
                        "content": (
                            "The previous tool arguments were invalid. Correct them without changing the question. "
                            f"Validation error: {last_error}\nInvalid arguments: "
                            f"{json.dumps(invalid_args, ensure_ascii=False)[:6000]}"
                        ),
                    })
        fallback = SlotPlan(
            slots=[Slot(
                id="S1",
                predicate="EvidenceAnsweringQuestion",
                arguments=["?answer"],
                constraints={"question": question},
                estimated_cardinality=5,
            )],
            outputs=["?answer"],
        )
        metrics = metrics.model_copy(update={"plan_fallbacks": metrics.plan_fallbacks + 1})
        return fallback, metrics


class SlotMaterializer:
    def __init__(self, client: AgnesClient, retriever: HybridRetriever, *, max_passages: int = 5) -> None:
        self.client = client
        self.retriever = retriever
        self.max_passages = max_passages
        self.last_evidence: list[EvidenceRecord] = []
        self.accessed_passage_ids: set[str] = set()
        self.accessed_document_ids: set[str] = set()

    def materialize(self, slot: Slot, bindings: dict[str, str]) -> tuple[list[BindingRow], RunMetrics]:
        query = slot.query_text(bindings)
        passages = self.retriever.search(query)[:self.max_passages]
        self.accessed_passage_ids.update(result.passage.id for result in passages)
        self.accessed_document_ids.update(result.passage.doc_id or result.passage.id for result in passages)
        self.last_evidence = [
            EvidenceRecord(source_id=result.passage.id, source_span=result.passage.text, slot_id=slot.id, bindings={})
            for result in passages
        ]
        constraint_bindings = {
            key.lstrip("?"): str(value)
            for key, value in slot.constraints.items()
            if key.lstrip("?") in slot.variables
        }
        effective_bindings = {**constraint_bindings, **bindings}
        metrics = RunMetrics(
            retrieval_calls=1,
            documents_accessed=len({p.passage.doc_id or p.passage.id for p in passages}),
            passages_processed=len(passages),
        )
        rows: list[BindingRow] = []
        if not passages:
            return rows, metrics
        by_source = {result.passage.id: result for result in passages}
        passage_payload = [
            {"source_id": result.passage.id, "text": result.passage.text}
            for result in passages
        ]
        messages = [
            {
                "role": "system",
                "content": (
                    "Extract only facts explicitly supported by the supplied passages. "
                    "Every row must use one listed source_id and exactly the requested relation fields. "
                    "Return an empty rows list when no passage supports the relation."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Relation: {slot.predicate}\nSlot query: {query}\nKnown bindings: {json.dumps(effective_bindings, ensure_ascii=False)}\n"
                    f"Passages: {json.dumps(passage_payload, ensure_ascii=False)}"
                ),
            },
        ]
        extracted_rows: list[tuple[dict[str, str], str]] = []
        for attempt in range(2):
            try:
                response = self.client.complete(
                    messages,
                    tools=[extraction_tool(slot, list(by_source))],
                    tool_choice={"type": "function", "function": {"name": "emit_evidence_rows"}},
                    temperature=0.0,
                )
                metrics = SlotCompiler._record_response(metrics, response, phase="extraction")
                args = self.client.require_tool(response, "emit_evidence_rows")
                extracted = ExtractionRow.model_validate(args)
                expected = slot.variables
                if not extracted.rows and attempt == 0:
                    raise SchemaError(f"empty extraction for {slot.id}; review the retrieved passages once")
                for row in extracted.rows:
                    source_id = row.get("source_id", "")
                    normalized = {
                        key.lstrip("?"): value.strip()
                        for key, value in row.items()
                        if key.lstrip("?") in expected
                    }
                    normalized.update({key: value for key, value in effective_bindings.items() if key in expected})
                    if source_id in by_source and set(normalized) == expected and all(normalized.values()):
                        extracted_rows.append((normalized, source_id))
                if extracted.rows and not extracted_rows:
                    raise SchemaError(f"extracted rows for {slot.id} do not match fields {sorted(expected)} and source IDs")
                break
            except (SchemaError, ValidationError, ValueError) as exc:
                metrics = metrics.model_copy(update={
                    "structured_output_failures": metrics.structured_output_failures + 1,
                    "structured_output_repairs": metrics.structured_output_repairs + (1 if attempt == 0 else 0),
                })
                if attempt == 0:
                    messages.append({
                        "role": "user",
                        "content": f"Correct the extraction. Required relation fields: {sorted(slot.variables)}. Error: {exc}",
                    })
        for normalized, source_id in extracted_rows:
            source = by_source[source_id]
            rows.append(BindingRow(
                slot_id=slot.id,
                bindings=normalized,
                source_id=source_id,
                source_span=source.passage.text,
                confidence=1.0,
                retrieval_score=source.score,
            ))
        return rows, metrics

    def materialize_many(self, slot: Slot, contexts: list[dict[str, str]]) -> tuple[list[BindingRow], RunMetrics]:
        """Materialize once per distinct binding context and merge the rows."""
        merged: list[BindingRow] = []
        metrics = RunMetrics()
        all_evidence: list[EvidenceRecord] = []
        seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
        for bindings in contexts or [{}]:
            rows, current_metrics = self.materialize(slot, bindings)
            all_evidence.extend(self.last_evidence)
            metrics = metrics.model_copy(update={
                "documents_accessed": metrics.documents_accessed + current_metrics.documents_accessed,
                "passages_processed": metrics.passages_processed + current_metrics.passages_processed,
                "retrieval_calls": metrics.retrieval_calls + current_metrics.retrieval_calls,
                "llm_calls": metrics.llm_calls + current_metrics.llm_calls,
                "prompt_tokens": metrics.prompt_tokens + current_metrics.prompt_tokens,
                "completion_tokens": metrics.completion_tokens + current_metrics.completion_tokens,
                "extraction_llm_calls": metrics.extraction_llm_calls + current_metrics.extraction_llm_calls,
                "extraction_prompt_tokens": metrics.extraction_prompt_tokens + current_metrics.extraction_prompt_tokens,
                "extraction_completion_tokens": metrics.extraction_completion_tokens + current_metrics.extraction_completion_tokens,
                "latency_ms": metrics.latency_ms + current_metrics.latency_ms,
                "structured_output_failures": metrics.structured_output_failures + current_metrics.structured_output_failures,
                "structured_output_repairs": metrics.structured_output_repairs + current_metrics.structured_output_repairs,
                "provider_request_ids": metrics.provider_request_ids + current_metrics.provider_request_ids,
            })
            for row in rows:
                key = (row.source_id, tuple(sorted(row.bindings.items())))
                if key not in seen:
                    seen.add(key)
                    merged.append(row)
        self.last_evidence = all_evidence
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


def _as_number(value: object) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _compare(left: object, right: object, comparator: str) -> bool:
    left_number = _as_number(left)
    right_number = _as_number(right)
    lhs: object = left_number if left_number is not None and right_number is not None else str(left).casefold()
    rhs: object = right_number if left_number is not None and right_number is not None else str(right).casefold()
    if comparator == "eq":
        return lhs == rhs
    if comparator == "ne":
        return lhs != rhs
    if comparator == "lt":
        return lhs < rhs  # type: ignore[operator]
    if comparator == "le":
        return lhs <= rhs  # type: ignore[operator]
    if comparator == "gt":
        return lhs > rhs  # type: ignore[operator]
    if comparator == "ge":
        return lhs >= rhs  # type: ignore[operator]
    return str(rhs) in str(lhs)


def apply_operators(rows: list[dict[str, str]], operators: list[RelationalOperator]) -> list[dict[str, str]]:
    result = [dict(row) for row in rows]
    for operator in operators:
        if operator.kind == "filter":
            result = [row for row in result if operator.field in row and _compare(row[operator.field], operator.value, operator.comparator or "eq")]
        elif operator.kind == "project":
            result = [{field: row[field] for field in operator.fields if field in row} for row in result]
        elif operator.kind == "intersect":
            fields = operator.fields or sorted({field for row in result for field in row})
            seen: set[tuple[str, ...]] = set()
            deduplicated: list[dict[str, str]] = []
            for row in result:
                key = tuple(row.get(field, "") for field in fields)
                if key not in seen:
                    seen.add(key)
                    deduplicated.append(row)
            result = deduplicated
        elif operator.kind == "count":
            result = [{operator.output or "count": str(len(result))}]
        elif operator.kind == "sort":
            field = operator.field or ""
            result.sort(key=lambda row: (_as_number(row.get(field)) is None, _as_number(row.get(field)) or str(row.get(field, "")).casefold()), reverse=operator.descending)
            if operator.limit:
                result = result[:operator.limit]
        elif operator.kind in {"argmin", "argmax"}:
            field = operator.field or ""
            candidates = [row for row in result if field in row]
            if candidates:
                key = lambda row: (_as_number(row[field]) is None, _as_number(row[field]) or str(row[field]).casefold())
                result = [min(candidates, key=key) if operator.kind == "argmin" else max(candidates, key=key)]
            else:
                result = []
        elif operator.kind == "compare":
            fields = operator.fields
            value = False
            if result and len(fields) >= 2:
                value = _compare(result[0].get(fields[0], ""), result[0].get(fields[1], ""), operator.comparator or "eq")
            result = [{operator.output or "comparison": str(value)}]
        elif operator.kind == "boolean":
            result = [{operator.output or "answer": str(bool(result))}]
        elif operator.kind == "arithmetic":
            fields = operator.fields
            values = [_as_number(result[0].get(field)) for field in fields] if result else []
            if len(values) < 2 or any(value is None for value in values):
                result = []
                continue
            numbers = [float(value) for value in values if value is not None]
            if operator.operation == "add":
                computed = sum(numbers)
            elif operator.operation == "subtract":
                computed = numbers[0] - sum(numbers[1:])
            elif operator.operation == "multiply":
                computed = math.prod(numbers)
            elif operator.operation == "divide":
                if any(value == 0 for value in numbers[1:]):
                    result = []
                    continue
                computed = numbers[0]
                for value in numbers[1:]:
                    computed /= value
            else:
                result = []
                continue
            rendered = str(int(computed)) if computed.is_integer() else f"{computed:.10f}".rstrip("0").rstrip(".")
            result = [{operator.output or "result": rendered}]
    return result


def _order_cost(order: list[str], cardinalities: dict[str, int]) -> float:
    cumulative = 1.0
    total = 0.0
    for slot_id in order:
        cumulative *= max(cardinalities.get(slot_id, 1), 1)
        total += cumulative
    return total


class AdaptiveExecutor:
    def __init__(
        self,
        materializer: SlotMaterializer,
        *,
        default_slot_cost: float = 1.0,
        unbound_argument_cost: float = 2.0,
        max_replans: int = 16,
        max_retrieval_calls: int = 4,
        max_binding_contexts: int = 2,
        random_seed: int = 2027,
        options: ExecutionOptions | None = None,
    ) -> None:
        self.materializer = materializer
        self.default_slot_cost = default_slot_cost
        self.unbound_argument_cost = unbound_argument_cost
        self.max_replans = max_replans
        self.max_retrieval_calls = max_retrieval_calls
        self.max_binding_contexts = max_binding_contexts
        self.random = random.Random(random_seed)
        self.options = options or ExecutionOptions()

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
            return min(candidates, key=lambda slot: cardinalities.get(slot.id, slot.estimated_cardinality))
        def score(slot: Slot) -> float:
            bound = len(slot.variables & bindings.keys())
            estimated = max(cardinalities.get(slot.id, slot.estimated_cardinality), 1)
            cost = slot.estimated_cost + self.default_slot_cost + max(len(slot.variables) - bound, 0) * self.unbound_argument_cost
            return (bound + slot.importance) / (cost * estimated)
        return max(candidates, key=score)

    def execute(self, plan: SlotPlan, *, strategy: str = "adaptive") -> ExecutionResult:
        remaining = list(plan.slots)
        materialized: dict[str, list[BindingRow]] = {}
        cardinalities: dict[str, int] = {}
        all_bindings: dict[str, str] = {}
        evidence: list[EvidenceRecord] = []
        retrieved_evidence: list[EvidenceRecord] = []
        metrics = RunMetrics()
        order: list[str] = []
        current: list[BindingRow] | None = None
        frozen_order: list[Slot] = []
        if not self.options.runtime_replan:
            pending = list(remaining)
            frozen_bindings: dict[str, str] = {}
            while pending:
                chosen = self._choose_slot(pending, frozen_bindings, plan, {}, strategy)
                pending.remove(chosen)
                frozen_order.append(chosen)
                frozen_bindings.update({name: "<estimated>" for name in chosen.variables})
        for step in range(self.max_replans):
            if not remaining:
                break
            slot = frozen_order[step] if frozen_order else self._choose_slot(remaining, all_bindings, plan, cardinalities, strategy)
            remaining.remove(slot)
            order.append(slot.id)
            if current is None or not self.options.binding_propagation or self.options.eager_materialization:
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
            remaining_retrieval_calls = self.max_retrieval_calls - metrics.retrieval_calls
            if remaining_retrieval_calls <= 0:
                return ExecutionResult(
                    rows=[],
                    evidence=evidence,
                    order=order,
                    metrics=metrics,
                    status="budget_exceeded",
                    error=f"retrieval call budget exceeded ({self.max_retrieval_calls})",
                )
            context_limit = min(self.max_binding_contexts, remaining_retrieval_calls)
            if len(binding_contexts) > context_limit:
                metrics = metrics.model_copy(update={
                    "binding_contexts_pruned": metrics.binding_contexts_pruned + len(binding_contexts) - context_limit,
                })
                binding_contexts = binding_contexts[:context_limit]
            materialize_many = getattr(self.materializer, "materialize_many", None)
            materialization_started = time.perf_counter()
            if materialize_many is not None:
                rows, slot_metrics = materialize_many(slot, binding_contexts)
            else:
                rows, slot_metrics = self.materializer.materialize(slot, binding_contexts[0])
            materialization_ms = (time.perf_counter() - materialization_started) * 1000
            retrieved_evidence.extend(getattr(self.materializer, "last_evidence", []))
            materialized[slot.id] = rows
            cardinalities[slot.id] = len(rows)
            selectivity_error = abs(math.log1p(len(rows)) - math.log1p(slot.estimated_cardinality))
            metrics = metrics.model_copy(update={
                "documents_accessed": metrics.documents_accessed + slot_metrics.documents_accessed,
                "passages_processed": metrics.passages_processed + slot_metrics.passages_processed,
                "llm_calls": metrics.llm_calls + slot_metrics.llm_calls,
                "retrieval_calls": metrics.retrieval_calls + slot_metrics.retrieval_calls,
                "prompt_tokens": metrics.prompt_tokens + slot_metrics.prompt_tokens,
                "completion_tokens": metrics.completion_tokens + slot_metrics.completion_tokens,
                "compilation_llm_calls": metrics.compilation_llm_calls + slot_metrics.compilation_llm_calls,
                "compilation_prompt_tokens": metrics.compilation_prompt_tokens + slot_metrics.compilation_prompt_tokens,
                "compilation_completion_tokens": metrics.compilation_completion_tokens + slot_metrics.compilation_completion_tokens,
                "extraction_llm_calls": metrics.extraction_llm_calls + slot_metrics.extraction_llm_calls,
                "extraction_prompt_tokens": metrics.extraction_prompt_tokens + slot_metrics.extraction_prompt_tokens,
                "extraction_completion_tokens": metrics.extraction_completion_tokens + slot_metrics.extraction_completion_tokens,
                "planning_llm_calls": metrics.planning_llm_calls + slot_metrics.planning_llm_calls,
                "planning_prompt_tokens": metrics.planning_prompt_tokens + slot_metrics.planning_prompt_tokens,
                "planning_completion_tokens": metrics.planning_completion_tokens + slot_metrics.planning_completion_tokens,
                "reasoning_llm_calls": metrics.reasoning_llm_calls + slot_metrics.reasoning_llm_calls,
                "reasoning_prompt_tokens": metrics.reasoning_prompt_tokens + slot_metrics.reasoning_prompt_tokens,
                "reasoning_completion_tokens": metrics.reasoning_completion_tokens + slot_metrics.reasoning_completion_tokens,
                "generation_llm_calls": metrics.generation_llm_calls + slot_metrics.generation_llm_calls,
                "generation_prompt_tokens": metrics.generation_prompt_tokens + slot_metrics.generation_prompt_tokens,
                "generation_completion_tokens": metrics.generation_completion_tokens + slot_metrics.generation_completion_tokens,
                "latency_ms": metrics.latency_ms + slot_metrics.latency_ms,
                "materialization_latency_ms": metrics.materialization_latency_ms + materialization_ms,
                "structured_output_failures": metrics.structured_output_failures + slot_metrics.structured_output_failures,
                "structured_output_repairs": metrics.structured_output_repairs + slot_metrics.structured_output_repairs,
                "plan_fallbacks": metrics.plan_fallbacks + slot_metrics.plan_fallbacks,
                "materialization_requests": metrics.materialization_requests + len(binding_contexts),
                "intermediate_binding_sizes": metrics.intermediate_binding_sizes + [len(rows) if current is None else len(current)],
                "reoptimizations": metrics.reoptimizations + (1 if step and self.options.runtime_replan else 0),
                "slot_selectivity_errors": metrics.slot_selectivity_errors + [selectivity_error],
            })
            if not rows:
                return ExecutionResult(rows=[], evidence=retrieved_evidence, order=order, metrics=metrics, status="empty")
            if current is None:
                current = rows
            elif self.options.incremental_join:
                join = next((j for j in plan.joins if (j.left_slot in materialized and j.right_slot == slot.id) or (j.right_slot in materialized and j.left_slot == slot.id)), None)
                if join is None:
                    return ExecutionResult(rows=[], evidence=retrieved_evidence, order=order, metrics=metrics, status="failed", error=f"slot {slot.id} has no join path")
                elif join.right_slot == slot.id:
                    join_input = len(current) + len(rows)
                    current = _join_rows(current, rows, join.left_field, join.right_field)
                else:
                    join_input = len(current) + len(rows)
                    current = _join_rows(rows, current, join.left_field, join.right_field)
                metrics = metrics.model_copy(update={
                    "join_input_rows": metrics.join_input_rows + join_input,
                    "join_output_rows": metrics.join_output_rows + len(current),
                })
            else:
                current = rows
            if current:
                # The planner only needs the set of currently bound fields for
                # choosing a connected next slot. Actual values are propagated
                # through binding_contexts above.
                all_bindings = {key: "<bound>" for row in current for key in row.bindings}
            else:
                return ExecutionResult(rows=[], evidence=retrieved_evidence, order=order, metrics=metrics, status="empty")
        if remaining:
            return ExecutionResult(rows=[], evidence=retrieved_evidence, order=order, metrics=metrics, status="failed", error="maximum replans exceeded")
        if not self.options.incremental_join and len(order) > 1:
            joined = materialized[order[0]]
            joined_slots = {order[0]}
            for slot_id in order[1:]:
                join = next((item for item in plan.joins if (item.left_slot in joined_slots and item.right_slot == slot_id) or (item.right_slot in joined_slots and item.left_slot == slot_id)), None)
                if join is None:
                    return ExecutionResult(rows=[], evidence=retrieved_evidence, order=order, metrics=metrics, status="failed", error=f"slot {slot_id} has no late join path")
                incoming = materialized[slot_id]
                join_input = len(joined) + len(incoming)
                joined = _join_rows(joined, incoming, join.left_field, join.right_field) if join.right_slot == slot_id else _join_rows(incoming, joined, join.left_field, join.right_field)
                joined_slots.add(slot_id)
                metrics = metrics.model_copy(update={
                    "join_input_rows": metrics.join_input_rows + join_input,
                    "join_output_rows": metrics.join_output_rows + len(joined),
                })
            current = joined
        raw_rows = [dict(row.bindings) for row in current or []]
        if self.options.typed_operators:
            raw_rows = apply_operators(raw_rows, plan.operators)
            metrics = metrics.model_copy(update={"operators_executed": metrics.operators_executed + len(plan.operators)})
        output_rows = [{key.lstrip("?"): row.get(key.lstrip("?"), row.get(key, "")) for key in plan.outputs} for row in raw_rows]
        seen_evidence: set[tuple[str, str, tuple[tuple[str, str], ...]]] = set()
        for slot_id in order:
            for row in materialized[slot_id]:
                evidence_key = (row.source_id, slot_id, tuple(sorted(row.bindings.items())))
                if evidence_key in seen_evidence:
                    continue
                seen_evidence.add(evidence_key)
                evidence.append(EvidenceRecord(source_id=row.source_id, source_span=row.source_span, slot_id=slot_id, bindings=row.bindings))
        if not evidence:
            evidence = retrieved_evidence
        if order and len(order) <= 8:
            valid_orders = list(itertools.permutations(order))
            oracle_cost = min(_order_cost(list(candidate), cardinalities) for candidate in valid_orders)
            actual_cost = _order_cost(order, cardinalities)
            regret = max(actual_cost - oracle_cost, 0.0) / max(oracle_cost, 1.0)
            metrics = metrics.model_copy(update={"planner_regret": regret})
        has_output = any(any(str(value).strip() for value in row.values()) for row in output_rows)
        return ExecutionResult(rows=output_rows, evidence=evidence, order=order, metrics=metrics, status="ok" if has_output else "empty")
