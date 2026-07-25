from __future__ import annotations

import json
import itertools
import math
import random
import re
import time
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from typing import Any
import unicodedata

from pydantic import BaseModel, Field, ValidationError

from .errors import SchemaError
from .models import BindingRow, EvidenceRecord, ExecutionResult, JoinSpec, RelationalOperator, RetrievalResult, RunMetrics, Slot, SlotPlan
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
                                "variable_types": {
                                    "type": "object",
                                    "additionalProperties": {
                                        "type": "string",
                                        "enum": ["string", "boolean", "number", "date"],
                                    },
                                    "description": "Optional domains keyed by variable name without ?.",
                                },
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
                                    "enum": ["filter", "project", "intersect", "count", "sort", "argmin", "argmax", "field_argmin", "field_argmax", "compare", "boolean", "arithmetic"],
                                },
                                "fields": {"type": "array", "items": {"type": "string"}},
                                "labels": {"type": "array", "items": {"type": "string"}},
                                "field": {"type": ["string", "null"]},
                                "output": {"type": ["string", "null"]},
                                "comparator": {"type": ["string", "null"]},
                                "operation": {
                                    "type": ["string", "null"],
                                    "enum": ["add", "subtract", "multiply", "divide", "date_diff_months", None],
                                },
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


def extraction_tool(
    slot: Slot,
    source_ids: list[str] | None = None,
    *,
    typed_extraction_contracts: bool = False,
    requested_fields: set[str] | None = None,
    role_projected: bool = False,
    known_bindings: dict[str, str] | None = None,
) -> dict[str, Any]:
    selected = slot.variables if requested_fields is None else requested_fields
    if not selected.issubset(slot.variables):
        unknown = ", ".join(sorted(selected - slot.variables))
        raise ValueError(f"requested extraction fields are not slot variables: {unknown}")
    fields = sorted(selected)
    bindings = known_bindings or {}
    rendered_arguments = [
        json.dumps(bindings[argument[1:]], ensure_ascii=False)
        if argument.startswith("?") and argument[1:] in bindings
        else argument
        for argument in slot.arguments
    ]
    signature = f"{slot.predicate}({', '.join(rendered_arguments)})"
    properties: dict[str, dict[str, Any]] = {}
    for field in fields:
        schema: dict[str, Any] = (
            {"type": "string", "enum": ["yes", "no", "unknown"]}
            if typed_extraction_contracts and slot.variable_types.get(field) == "boolean"
            else {"type": "string"}
        )
        if role_projected:
            position = next(
                index
                for index, argument in enumerate(slot.arguments, start=1)
                if argument == f"?{field}"
            )
            schema["description"] = (
                f"Value for ?{field}, ordered argument {position} of {signature}. "
                + "".join(
                    f"The known argument {index} is fixed as {json.dumps(bindings[argument[1:]], ensure_ascii=False)}. "
                    for index, argument in enumerate(slot.arguments, start=1)
                    if argument.startswith("?") and argument[1:] in bindings
                )
                + "Extract only the entity that fills this exact relation role."
            )
        properties[field] = schema
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


def fold_grounded_entity_anchor(plan: SlotPlan, question: str) -> tuple[SlotPlan, int]:
    """Fold one grounded identity leaf into its sole consumer constraint."""
    anchor_predicates = {"person", "entity", "item", "place"}
    payload = plan.model_dump(mode="python")
    question_folded = question.casefold()

    for anchor in payload["slots"]:
        arguments = anchor["arguments"]
        variables = [argument[1:] for argument in arguments if argument.startswith("?")]
        constants = [argument for argument in arguments if not argument.startswith("?")]
        if (
            anchor["predicate"].casefold() not in anchor_predicates
            or len(variables) != 1
            or not constants
            or anchor.get("constraints")
            or anchor.get("variable_types")
        ):
            continue

        variable = variables[0]
        if f"?{variable}" in payload["outputs"]:
            continue
        operator_fields = {
            field
            for operator in payload.get("operators", [])
            for field in [*operator.get("fields", []), operator.get("field"), operator.get("output")]
            if field
        }
        if variable in operator_fields:
            continue

        consumers = [
            slot
            for slot in payload["slots"]
            if slot["id"] != anchor["id"] and f"?{variable}" in slot["arguments"]
        ]
        touching_joins = [
            join
            for join in payload["joins"]
            if anchor["id"] in {join["left_slot"], join["right_slot"]}
        ]
        if len(consumers) != 1 or len(touching_joins) != 1:
            continue
        consumer = consumers[0]
        join = touching_joins[0]
        other_slot = join["right_slot"] if join["left_slot"] == anchor["id"] else join["left_slot"]
        if (
            other_slot != consumer["id"]
            or join["left_field"] != variable
            or join["right_field"] != variable
            or variable in consumer.get("constraints", {})
        ):
            continue

        span_start: int | None = None
        span_end: int | None = None
        cursor = 0
        grounded = True
        for constant in constants:
            normalized = constant.strip()
            if not normalized:
                grounded = False
                break
            start = question_folded.find(normalized.casefold(), cursor)
            if start < 0 or (
                span_end is not None
                and re.fullmatch(r"[\W_]*", question[span_end:start], flags=re.UNICODE) is None
            ):
                grounded = False
                break
            span_start = start if span_start is None else span_start
            span_end = start + len(normalized)
            cursor = span_end
        if not grounded or span_start is None or span_end is None:
            continue

        candidate = deepcopy(payload)
        candidate["slots"] = [slot for slot in candidate["slots"] if slot["id"] != anchor["id"]]
        candidate_consumer = next(slot for slot in candidate["slots"] if slot["id"] == consumer["id"])
        candidate_consumer["constraints"] = {
            **candidate_consumer.get("constraints", {}),
            variable: question[span_start:span_end],
        }
        candidate["joins"] = [
            item
            for item in candidate["joins"]
            if anchor["id"] not in {item["left_slot"], item["right_slot"]}
        ]
        try:
            return SlotPlan.model_validate(candidate), 1
        except ValidationError:
            continue
    return plan, 0


def substitute_grounded_entity_anchor_with_values(
    plan: SlotPlan,
    question: str,
) -> tuple[SlotPlan, tuple[str, ...]]:
    """Return a safely substituted plan and the exact upstream anchor values."""
    folded, count = fold_grounded_entity_anchor(plan, question)
    if not count:
        return plan, ()

    source_slots = {slot.id: slot for slot in plan.slots}
    payload = folded.model_dump(mode="python")
    for slot in payload["slots"]:
        source = source_slots.get(slot["id"])
        if source is None:
            continue
        introduced = [
            field
            for field in slot.get("constraints", {})
            if field not in source.constraints and f"?{field}" in source.arguments
        ]
        if len(introduced) != 1:
            continue
        variable = introduced[0]
        constant = slot["constraints"].pop(variable)
        if not isinstance(constant, str) or not constant:
            return plan, ()
        slot["arguments"] = [constant if argument == f"?{variable}" else argument for argument in slot["arguments"]]
        slot.get("variable_types", {}).pop(variable, None)
        try:
            return SlotPlan.model_validate(payload), (constant,)
        except ValidationError:
            return plan, ()
    return plan, ()


def substitute_grounded_entity_anchor(plan: SlotPlan, question: str) -> tuple[SlotPlan, int]:
    """Fold a safe anchor, then replace its known consumer variable with a constant."""
    effective, values = substitute_grounded_entity_anchor_with_values(plan, question)
    return effective, len(values)


def direct_grounded_relation_anchor_values(
    plan: SlotPlan,
    question: str,
) -> tuple[str, ...]:
    """Return conservative question-grounded constants at multi-hop relation roots."""
    if len(plan.slots) < 2 or not plan.joins:
        return ()

    slot_ids = {slot.id for slot in plan.slots}
    adjacency = {slot_id: set() for slot_id in slot_ids}
    joined_fields = {slot_id: set() for slot_id in slot_ids}
    parent = {slot_id: slot_id for slot_id in slot_ids}

    def find(slot_id: str) -> str:
        while parent[slot_id] != slot_id:
            parent[slot_id] = parent[parent[slot_id]]
            slot_id = parent[slot_id]
        return slot_id

    for join in plan.joins:
        left_root = find(join.left_slot)
        right_root = find(join.right_slot)
        if left_root == right_root:
            return ()
        parent[left_root] = right_root
        adjacency[join.left_slot].add(join.right_slot)
        adjacency[join.right_slot].add(join.left_slot)
        joined_fields[join.left_slot].add(join.left_field)
        joined_fields[join.right_slot].add(join.right_field)

    output_fields = {output.removeprefix("?") for output in plan.outputs}
    anchor_predicates = {"person", "entity", "item", "place", "evidenceansweringquestion"}
    generic_values = {
        "answer",
        "book",
        "city",
        "country",
        "entity",
        "film",
        "item",
        "movie",
        "person",
        "place",
        "series",
    }
    values: list[str] = []
    seen: set[str] = set()
    for slot in plan.slots:
        if (
            len(adjacency[slot.id]) != 1
            or slot.predicate.casefold() in anchor_predicates
            or slot.variables & output_fields
            or not (slot.variables & joined_fields[slot.id])
        ):
            continue
        for argument in slot.arguments:
            value = argument.strip()
            if not value or value.startswith("?") or value.casefold() in generic_values:
                continue
            match = re.search(
                rf"(?<!\w){re.escape(value)}(?!\w)",
                question,
                flags=re.IGNORECASE,
            )
            if match is None:
                continue
            grounded_span = question[match.start():match.end()]
            if not any(character.isupper() or character.isdigit() for character in grounded_span):
                continue
            key = value.casefold()
            if key not in seen:
                seen.add(key)
                values.append(value)
    return tuple(values)


def query_grounded_anchor_values(
    plan: SlotPlan,
    question: str,
) -> tuple[str, ...]:
    """Recover only question-grounded entity titles already present in a plan or query."""
    generic_values = {
        "answer", "book", "city", "country", "entity", "film", "item", "movie", "person", "place", "series", "song",
    }
    values: list[str] = []
    seen: set[str] = set()

    def add_candidate(candidate: object) -> None:
        value = str(candidate).strip()
        normalized = SlotMaterializer._normalized_text(value)
        if len(normalized) < 4 or normalized in generic_values:
            return
        match = re.search(rf"(?<!\w){re.escape(value)}(?!\w)", question, flags=re.IGNORECASE)
        if match is None:
            return
        grounded = question[match.start():match.end()]
        if not any(character.isupper() or character.isdigit() for character in grounded):
            return
        key = normalized
        if key not in seen:
            seen.add(key)
            values.append(value)

    for slot in plan.slots:
        for argument in slot.arguments:
            if not argument.startswith("?"):
                add_candidate(argument)
        for constraint in slot.constraints.values():
            if isinstance(constraint, str):
                add_candidate(constraint)
    if values:
        return tuple(values)

    relation_root = any(
        len(re.sub(r"[^a-z0-9]", "", slot.predicate.casefold())) >= 4
        and re.sub(r"[^a-z0-9]", "", slot.predicate.casefold()).endswith("of")
        for slot in plan.slots
    )
    if not relation_root:
        return ()
    title_match = re.search(
        r"\b(?:of|for)\s+(?:the\s+)?(?:film|movie|song)\s+(.+?)(?=\s+(?:is\s+from|from)\b|\?|$)",
        question,
        flags=re.IGNORECASE,
    )
    if title_match is not None:
        add_candidate(title_match.group(1).strip())
    return tuple(values)


def inject_query_grounded_anchor(
    plan: SlotPlan,
    question: str,
) -> tuple[SlotPlan, int, tuple[str, ...]]:
    """Add one question-grounded title only to one unambiguous relation root."""
    values = query_grounded_anchor_values(plan, question)
    if len(values) != 1:
        return plan, 0, values
    value = values[0]
    normalized_value = SlotMaterializer._normalized_text(value)
    existing_values = {
        SlotMaterializer._normalized_text(candidate)
        for slot in plan.slots
        for candidate in [
            *(argument for argument in slot.arguments if not argument.startswith("?")),
            *(item for item in slot.constraints.values() if isinstance(item, str)),
        ]
    }
    if normalized_value in existing_values:
        return plan, 0, values

    degrees = {slot.id: 0 for slot in plan.slots}
    joined_fields = {slot.id: set() for slot in plan.slots}
    for join in plan.joins:
        degrees[join.left_slot] += 1
        degrees[join.right_slot] += 1
        joined_fields[join.left_slot].add(join.left_field)
        joined_fields[join.right_slot].add(join.right_field)
    outputs = {output.removeprefix("?") for output in plan.outputs}
    candidates = []
    for slot in plan.slots:
        predicate = re.sub(r"[^a-z0-9]", "", slot.predicate.casefold())
        variables = [argument.removeprefix("?") for argument in slot.arguments if argument.startswith("?")]
        if (
            predicate.endswith("of")
            and len(variables) == 1
            and degrees[slot.id] == 1
            and variables[0] in joined_fields[slot.id]
            and variables[0] not in outputs
            and not slot.constraints
            and all(argument.startswith("?") for argument in slot.arguments)
        ):
            candidates.append(slot.id)
    if len(candidates) != 1:
        return plan, 0, values

    payload = plan.model_dump(mode="python")
    target = next(slot for slot in payload["slots"] if slot["id"] == candidates[0])
    target["arguments"].append(value)
    try:
        return SlotPlan.model_validate(payload), 1, values
    except ValidationError:
        return plan, 0, values


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
            for label in operator.labels:
                require_grounded(label)

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
    def fold_grounded_entity_anchor(plan: SlotPlan, question: str) -> tuple[SlotPlan, int]:
        return fold_grounded_entity_anchor(plan, question)

    @staticmethod
    def substitute_grounded_entity_anchor(plan: SlotPlan, question: str) -> tuple[SlotPlan, int]:
        return substitute_grounded_entity_anchor(plan, question)

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

    @staticmethod
    def _rewrite_functional_predicates(plan: SlotPlan, question: str = "") -> tuple[SlotPlan, int]:
        """Rewrite only functional slots whose inputs already come from other slots."""
        payload = plan.model_dump(mode="python")
        rewritten = 0

        def next_operator_id(slot_id: str) -> str:
            operator_ids = {operator["id"] for operator in payload.get("operators", [])}
            operator_id = f"normalize_{slot_id}"
            suffix = 2
            while operator_id in operator_ids:
                operator_id = f"normalize_{slot_id}_{suffix}"
                suffix += 1
            return operator_id

        date_difference_aliases = {
            "datediffinmonths",
            "monthdifference",
            "monthsdifference",
            "monthsbetween",
        }
        for slot in list(payload["slots"]):
            predicate = re.sub(r"[^a-z0-9]", "", slot["predicate"].casefold())
            arguments = slot["arguments"]
            if predicate not in date_difference_aliases or slot.get("constraints") or len(arguments) != 3:
                continue
            if any(not isinstance(argument, str) or not argument.startswith("?") for argument in arguments):
                continue
            start_field, end_field, output = (argument[1:] for argument in arguments)
            other_slots = [item for item in payload["slots"] if item["id"] != slot["id"]]
            other_variables = {
                argument[1:]
                for item in other_slots
                for argument in item["arguments"]
                if isinstance(argument, str) and argument.startswith("?")
            }
            if not {start_field, end_field}.issubset(other_variables) or output in other_variables:
                continue
            candidate = deepcopy(payload)
            candidate["slots"] = [item for item in candidate["slots"] if item["id"] != slot["id"]]
            candidate["joins"] = [
                join
                for join in candidate["joins"]
                if join["left_slot"] != slot["id"] and join["right_slot"] != slot["id"]
            ]
            candidate.setdefault("operators", []).append({
                "id": next_operator_id(slot["id"]),
                "kind": "arithmetic",
                "fields": [start_field, end_field],
                "output": output,
                "operation": "date_diff_months",
                "field": None,
                "comparator": None,
                "value": None,
                "descending": False,
                "limit": None,
            })
            try:
                normalized = SlotPlan.model_validate(candidate)
            except ValidationError:
                continue
            payload = normalized.model_dump(mode="python")
            rewritten += 1

        normalized_question = " ".join(re.findall(r"\w+", question.casefold()))
        minimum_requested = bool(re.search(
            r"\bborn\b.{0,80}\b(?:first|earlier|earliest)\b",
            normalized_question,
        ))
        maximum_requested = bool(re.search(
            r"\bborn\b.{0,80}\b(?:later|latest)\b",
            normalized_question,
        ))
        extremum_kind = None
        if minimum_requested != maximum_requested:
            extremum_kind = "field_argmin" if minimum_requested else "field_argmax"

        def grounded_label(field: str, slots: list[dict[str, Any]]) -> str | None:
            frontier = [field]
            visited: set[str] = set()
            while frontier:
                candidates: list[str] = []
                next_frontier: list[str] = []
                for variable in frontier:
                    if variable in visited:
                        continue
                    visited.add(variable)
                    for item in slots:
                        arguments = item.get("arguments", [])
                        if f"?{variable}" not in arguments:
                            continue
                        for argument in arguments:
                            if not isinstance(argument, str):
                                continue
                            if argument.startswith("?"):
                                linked = argument[1:]
                                if linked not in visited:
                                    next_frontier.append(linked)
                            else:
                                normalized = " ".join(re.findall(r"\w+", argument.casefold()))
                                if normalized and normalized in normalized_question:
                                    candidates.append(argument)
                unique_candidates = list(dict.fromkeys(candidates))
                if len(unique_candidates) == 1:
                    return unique_candidates[0]
                if unique_candidates:
                    return None
                frontier = list(dict.fromkeys(next_frontier))
            return None

        if extremum_kind is not None:
            comparison_aliases = {"compare", "datecompare"}
            for slot in list(payload["slots"]):
                predicate = re.sub(r"[^a-z0-9]", "", slot["predicate"].casefold())
                arguments = slot["arguments"]
                if predicate not in comparison_aliases or slot.get("constraints") or len(arguments) != 2:
                    continue
                if any(not isinstance(argument, str) or not argument.startswith("?") for argument in arguments):
                    continue
                fields = [argument[1:] for argument in arguments]
                other_slots = [item for item in payload["slots"] if item["id"] != slot["id"]]
                other_variables = {
                    argument[1:]
                    for item in other_slots
                    for argument in item["arguments"]
                    if isinstance(argument, str) and argument.startswith("?")
                }
                if not set(fields).issubset(other_variables):
                    continue
                output_fields = {
                    output[1:] if output.startswith("?") else output
                    for output in payload["outputs"]
                }
                if output_fields != set(fields):
                    continue
                labels = [grounded_label(field, other_slots) for field in fields]
                if any(label is None for label in labels) or len(set(labels)) != len(labels):
                    continue
                candidate = deepcopy(payload)
                candidate["slots"] = [item for item in candidate["slots"] if item["id"] != slot["id"]]
                candidate["joins"] = [
                    join
                    for join in candidate["joins"]
                    if join["left_slot"] != slot["id"] and join["right_slot"] != slot["id"]
                ]
                candidate["outputs"] = ["?answer"]
                candidate.setdefault("operators", []).append({
                    "id": next_operator_id(slot["id"]),
                    "kind": extremum_kind,
                    "fields": fields,
                    "labels": labels,
                    "output": "answer",
                    "field": None,
                    "comparator": None,
                    "operation": None,
                    "value": None,
                    "descending": False,
                    "limit": None,
                })
                try:
                    normalized = SlotPlan.model_validate(candidate)
                except ValidationError:
                    continue
                payload = normalized.model_dump(mode="python")
                rewritten += 1
        return SlotPlan.model_validate(payload), rewritten

    @staticmethod
    def _field_extremum_template(question: str) -> SlotPlan | None:
        match = re.fullmatch(
            r"\s*which\s+(?:film|movie)\s+has\s+the\s+director\s+who\s+was\s+born\s+"
            r"(?P<extremum>first|earlier|earliest|later|latest)\s*,\s*"
            r"(?P<left>.+)\s+or\s+(?P<right>.+?)\s*\?\s*",
            question,
            flags=re.IGNORECASE,
        )
        if match is None:
            return None
        left_label = match.group("left").strip()
        right_label = match.group("right").strip()
        normalized_labels = [
            " ".join(re.findall(r"\w+", label.casefold()))
            for label in (left_label, right_label)
        ]
        if (
            not all(normalized_labels)
            or len(set(normalized_labels)) != 2
            or any(re.search(r"\bor\b", label, flags=re.IGNORECASE) for label in (left_label, right_label))
        ):
            return None
        operator_kind = (
            "field_argmin"
            if match.group("extremum").casefold() in {"first", "earlier", "earliest"}
            else "field_argmax"
        )
        return SlotPlan(
            slots=[
                Slot(id="S1", predicate="DirectorOf", arguments=[left_label, "?director1"], estimated_cardinality=1),
                Slot(id="S2", predicate="BirthDate", arguments=["?director1", "?birthDate1"], estimated_cardinality=1),
                Slot(id="S3", predicate="DirectorOf", arguments=[right_label, "?director2"], estimated_cardinality=1),
                Slot(id="S4", predicate="BirthDate", arguments=["?director2", "?birthDate2"], estimated_cardinality=1),
            ],
            joins=[
                JoinSpec(left_slot="S1", left_field="director1", right_slot="S2", right_field="director1"),
                JoinSpec(left_slot="S3", left_field="director2", right_slot="S4", right_field="director2"),
            ],
            operators=[RelationalOperator(
                id="O1",
                kind=operator_kind,
                fields=["birthDate1", "birthDate2"],
                labels=[left_label, right_label],
                output="answer",
            )],
            outputs=["?answer"],
        )

    @staticmethod
    def _polar_comparison_template(question: str) -> SlotPlan | None:
        auxiliary = r"(?:do|does|did|is|are|was|were|has|have|had|can|could|would|will)"
        if re.fullmatch(rf"\s*{auxiliary}\b.+\?\s*", question, flags=re.IGNORECASE) is None:
            return None
        if re.match(r"\s*(?:can|could|would|will)\s+you\b", question, flags=re.IGNORECASE):
            return None
        if re.search(
            r"\b(?:what|which|who|whom|whose|where|when|why|how)\b",
            question,
            flags=re.IGNORECASE,
        ):
            return None
        if re.search(r"\b(?:same|both)\b", question, flags=re.IGNORECASE) is None:
            return None
        return SlotPlan(
            slots=[Slot(
                id="S1",
                predicate="EvidenceAnsweringQuestion",
                arguments=["?answer"],
                constraints={"question": question},
                variable_types={"answer": "boolean"},
                estimated_cardinality=5,
            )],
            outputs=["?answer"],
        )

    def compile(
        self,
        question: str,
        *,
        answer_kind: str = "short",
        document_count: int | None = None,
        field_extremum_templates: bool = True,
        polar_comparison_templates: bool = True,
    ) -> tuple[SlotPlan, RunMetrics]:
        if not question.strip():
            raise ValueError("question cannot be empty")
        if (
            answer_kind == "number"
            and re.search(r"\bhow\s+many\s+months?\s+after\b", question, flags=re.IGNORECASE)
        ):
            return SlotPlan(
                slots=[Slot(
                    id="S1",
                    predicate="MonthDifferenceDates",
                    arguments=["?startDate", "?endDate"],
                    constraints={"question": question},
                    estimated_cardinality=1,
                )],
                operators=[RelationalOperator(
                    id="O1",
                    kind="arithmetic",
                    fields=["startDate", "endDate"],
                    operation="date_diff_months",
                    output="months",
                )],
                outputs=["?months"],
            ), RunMetrics(heuristic_plans=1, typed_plan_templates=1)
        if answer_kind == "short" and field_extremum_templates:
            field_extremum_plan = self._field_extremum_template(question)
            if field_extremum_plan is not None:
                return field_extremum_plan, RunMetrics(
                    heuristic_plans=1,
                    typed_plan_templates=1,
                    field_extremum_templates=1,
                )
        if answer_kind == "short" and polar_comparison_templates:
            polar_comparison_plan = self._polar_comparison_template(question)
            if polar_comparison_plan is not None:
                return polar_comparison_plan, RunMetrics(
                    heuristic_plans=1,
                    polar_comparison_templates=1,
                )
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
        if document_count == 1:
            return SlotPlan(
                slots=[Slot(
                    id="S1",
                    predicate="EvidenceAnsweringQuestion",
                    arguments=["?answer"],
                    constraints={"question": question},
                    estimated_cardinality=1,
                )],
                outputs=["?answer"],
            ), RunMetrics(heuristic_plans=1, direct_plan_templates=1)
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
                plan, operator_rewrites = self._rewrite_functional_predicates(plan, question)
                plan = self._eliminate_anchor_slots(plan)
                if operator_rewrites:
                    metrics = metrics.model_copy(update={
                        "operator_rewrites": metrics.operator_rewrites + operator_rewrites,
                    })
                return plan, metrics
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
                            repaired_plan, operator_rewrites = self._rewrite_functional_predicates(repaired_plan, question)
                            repaired_plan = self._eliminate_anchor_slots(repaired_plan)
                        except (ValidationError, ValueError):
                            pass
                        else:
                            metrics = metrics.model_copy(update={
                                "structured_output_repairs": metrics.structured_output_repairs + 1,
                                "local_plan_repairs": metrics.local_plan_repairs + 1,
                                "operator_rewrites": metrics.operator_rewrites + operator_rewrites,
                            })
                            return repaired_plan, metrics
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
    def __init__(
        self,
        client: AgnesClient,
        retriever: HybridRetriever,
        *,
        max_passages: int = 5,
        typed_extraction_contracts: bool = False,
        role_projected_extraction: bool = False,
        protected_anchor_values: set[str] | None = None,
        extraction_enable_thinking: bool | None = None,
        bound_role_signatures: bool = False,
        semantic_role_type_filter: bool = False,
        anchor_centered_extraction: bool = False,
        normalize_anchor_window_predicates: bool = False,
        evidence_surface_grounding_repair: bool = False,
        question_context: str | None = None,
        dual_query_retrieval: bool = False,
        dual_query_unbound_only: bool = False,
        dual_query_confidence_threshold: float | None = None,
        dual_query_evidence_guard: bool = False,
        dual_query_evidence_guard_disjoint_only: bool = True,
    ) -> None:
        self.client = client
        self.retriever = retriever
        self.max_passages = max_passages
        self.typed_extraction_contracts = typed_extraction_contracts
        self.role_projected_extraction = role_projected_extraction
        self.protected_anchor_values = set(protected_anchor_values or ())
        self.extraction_enable_thinking = extraction_enable_thinking
        self.bound_role_signatures = bound_role_signatures
        self.semantic_role_type_filter = semantic_role_type_filter
        self.anchor_centered_extraction = anchor_centered_extraction
        self.normalize_anchor_window_predicates = normalize_anchor_window_predicates
        self.evidence_surface_grounding_repair = evidence_surface_grounding_repair
        self.question_context = question_context.strip() if question_context else None
        self.dual_query_retrieval = dual_query_retrieval
        self.dual_query_unbound_only = dual_query_unbound_only
        self.dual_query_confidence_threshold = dual_query_confidence_threshold
        self.dual_query_evidence_guard = dual_query_evidence_guard
        self.dual_query_evidence_guard_disjoint_only = dual_query_evidence_guard_disjoint_only
        self.last_evidence: list[EvidenceRecord] = []
        self.accessed_passage_ids: set[str] = set()
        self.accessed_document_ids: set[str] = set()

    @staticmethod
    def _normalized_text(value: object) -> str:
        ascii_value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
        return " ".join(re.findall(r"[a-z0-9]+", ascii_value.casefold()))

    @classmethod
    def _binding_is_grounded(cls, value: str, source_id: str, source_span: str, doc_id: str | None) -> bool:
        needle = cls._normalized_text(value)
        haystack = cls._normalized_text(" ".join(part for part in (source_id, doc_id or "", source_span) if part))
        return bool(needle and f" {needle} " in f" {haystack} ")

    @classmethod
    def _anchor_centered_window(
        cls,
        text: str,
        doc_id: str,
        anchor_values: set[str],
        *,
        radius: int = 2,
    ) -> str | None:
        sentences = [
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+(?=[\"'A-Z0-9])", text)
            if part.strip()
        ]
        if not sentences:
            return None
        anchors = [cls._normalized_text(value) for value in anchor_values]
        anchors = [value for value in anchors if value]
        if not anchors:
            return None
        normalized_doc = cls._normalized_text(doc_id.split("#chunk-", 1)[0])
        title_match = any(
            anchor == normalized_doc
            or (len(anchor) >= 4 and anchor in normalized_doc)
            or (len(normalized_doc) >= 4 and normalized_doc in anchor)
            for anchor in anchors
        )
        center: int | None = 0 if title_match else None
        if center is None:
            for index, sentence in enumerate(sentences):
                normalized_sentence = f" {cls._normalized_text(sentence)} "
                if any(f" {anchor} " in normalized_sentence for anchor in anchors):
                    center = index
                    break
        if center is None:
            return None
        start = max(0, center - radius)
        end = min(len(sentences), center + radius + 1)
        return " ".join(sentences[start:end])

    @classmethod
    def _uses_anchor_window(cls, slot: Slot, *, normalize_predicates: bool = False) -> bool:
        predicate = cls._normalized_text(slot.predicate).replace(" ", "")
        exact_predicates = {
            "countryof",
            "countryoforigin",
            "countryofcitizenship",
            "nationality",
        }
        if predicate in exact_predicates:
            return True
        return normalize_predicates and predicate in {
            "hasnationality",
            "countryofbirth",
            "fromcountry",
            "nationalityof",
        }

    @classmethod
    def _is_normalized_anchor_window_predicate(cls, slot: Slot) -> bool:
        predicate = cls._normalized_text(slot.predicate).replace(" ", "")
        return predicate in {"hasnationality", "countryofbirth", "fromcountry", "nationalityof"}

    @classmethod
    def _evidence_surface_variant(cls, value: str, source_text: str) -> str | None:
        needle = cls._normalized_text(value)
        if len(needle) < 5 or " " in needle:
            return None
        for match in re.finditer(r"[A-Za-z][A-Za-z'-]*", source_text):
            candidate = cls._normalized_text(match.group(0))
            if (
                candidate != needle
                and abs(len(candidate) - len(needle)) <= 2
                and (candidate.startswith(needle) or needle.startswith(candidate))
            ):
                return match.group(0)
        return None

    @classmethod
    def _semantic_role_gender(cls, field: str) -> str | None:
        tokens = set(cls._normalized_text(field).split())
        female_roles = {
            "mother", "grandmother", "wife", "daughter", "sister", "aunt", "niece", "woman", "female",
        }
        male_roles = {
            "father", "grandfather", "husband", "son", "brother", "uncle", "nephew", "man", "male",
        }
        if tokens & female_roles:
            return "female"
        if tokens & male_roles:
            return "male"
        return None

    @classmethod
    def _semantic_role_type_conflict(cls, field: str, value: str) -> str | None:
        expected = cls._semantic_role_gender(field)
        if expected is None:
            return None
        tokens = set(cls._normalized_text(value).split())
        male_markers = {
            "mr", "mister", "sir", "lord", "earl", "king", "prince", "duke", "baron", "emperor",
            "father", "husband", "son", "brother", "uncle", "nephew",
        }
        female_markers = {
            "mrs", "ms", "miss", "lady", "queen", "princess", "duchess", "countess", "baroness", "empress",
            "mother", "wife", "daughter", "sister", "aunt", "niece",
        }
        observed_male = bool(tokens & male_markers)
        observed_female = bool(tokens & female_markers)
        if expected == "female" and observed_male and not observed_female:
            return f"{field} requires a female role but {value!r} has an explicit male marker"
        if expected == "male" and observed_female and not observed_male:
            return f"{field} requires a male role but {value!r} has an explicit female marker"
        return None

    def materialize(self, slot: Slot, bindings: dict[str, str]) -> tuple[list[BindingRow], RunMetrics]:
        slot_query = slot.query_text(bindings)
        retrieval_calls = 1
        query = slot_query
        dual_query_requested = bool(
            self.question_context
            and self.dual_query_retrieval
            and (not self.dual_query_unbound_only or not bindings)
        )
        dual_query_skipped = bool(
            self.question_context
            and self.dual_query_retrieval
            and self.dual_query_unbound_only
            and bindings
        )
        use_dual_query = False
        dual_query_confidence_skip = False
        dual_query_guard_check = False
        dual_query_guard_fallback = False
        if dual_query_requested:
            question_query = f"{self.question_context} {slot_query}"
            slot_ranked = self.retriever.search(slot_query)
            if self.dual_query_confidence_threshold is not None and slot_ranked:
                top_confidence = max(
                    result.rerank_score if result.rerank_score is not None else result.score
                    for result in slot_ranked
                )
                dual_query_confidence_skip = top_confidence >= self.dual_query_confidence_threshold
            if dual_query_confidence_skip:
                retrieved_passages = slot_ranked[:self.max_passages]
                query = slot_query
            else:
                question_ranked = self.retriever.search(question_query)
                ranked_lists = [slot_ranked, question_ranked]
                retrieval_calls = 2
                use_dual_query = True
                query = f"{slot_query} || {question_query}"
                rrf_scores: dict[str, float] = {}
                representatives: dict[str, RetrievalResult] = {}
                for ranked in ranked_lists:
                    for rank, result in enumerate(ranked, start=1):
                        passage_id = result.passage.id
                        rrf_scores[passage_id] = rrf_scores.get(passage_id, 0.0) + 1.0 / (60 + rank)
                        current = representatives.get(passage_id)
                        if current is None or result.score > current.score:
                            representatives[passage_id] = result
                retrieved_passages = [
                    representatives[passage_id].model_copy(update={"score": rrf_scores[passage_id]})
                    for passage_id in sorted(
                        representatives,
                        key=lambda item: (-rrf_scores[item], -representatives[item].score, item),
                    )[:self.max_passages]
                ]
                if self.dual_query_evidence_guard and slot_ranked and question_ranked:
                    slot_ids = {result.passage.id for result in slot_ranked[:self.max_passages]}
                    question_ids = {result.passage.id for result in question_ranked[:self.max_passages]}
                    confidence = lambda result: result.rerank_score if result.rerank_score is not None else result.score
                    slot_confidence = max(confidence(result) for result in slot_ranked[:self.max_passages])
                    question_confidence = max(confidence(result) for result in question_ranked[:self.max_passages])
                    dual_query_guard_check = True
                    disjoint = not slot_ids.intersection(question_ids)
                    if question_confidence < slot_confidence and (
                        not self.dual_query_evidence_guard_disjoint_only or disjoint
                    ):
                        retrieved_passages = slot_ranked[:self.max_passages]
                        query = slot_query
                        dual_query_guard_fallback = True
        else:
            if self.question_context and not self.dual_query_retrieval:
                query = f"{self.question_context} {slot_query}"
            retrieved_passages = self.retriever.search(query)[:self.max_passages]
        self.accessed_passage_ids.update(result.passage.id for result in retrieved_passages)
        self.accessed_document_ids.update(result.passage.doc_id or result.passage.id for result in retrieved_passages)
        self.last_evidence = [
            EvidenceRecord(source_id=result.passage.id, source_span=result.passage.text, slot_id=slot.id, bindings={})
            for result in retrieved_passages
        ]
        constraint_bindings = {
            key.lstrip("?"): str(value)
            for key, value in slot.constraints.items()
            if key.lstrip("?") in slot.variables
        }
        effective_bindings = {**constraint_bindings, **bindings}
        passages = retrieved_passages
        anchor_window_contract = bool(
            self.anchor_centered_extraction
            and self._uses_anchor_window(
                slot,
                normalize_predicates=self.normalize_anchor_window_predicates,
            )
            and retrieved_passages
            and (effective_bindings or self.protected_anchor_values)
        )
        anchor_window_predicate_normalization = bool(
            anchor_window_contract
            and self.normalize_anchor_window_predicates
            and self._is_normalized_anchor_window_predicate(slot)
        )
        anchor_window_fallback = False
        anchor_window_input_chars = 0
        anchor_window_output_chars = 0
        anchor_window_dropped_passages = 0
        if anchor_window_contract:
            anchor_values = self.protected_anchor_values | set(effective_bindings.values())
            anchor_window_input_chars = sum(len(result.passage.text) for result in retrieved_passages)
            focused_passages: list[RetrievalResult] = []
            for result in retrieved_passages:
                focused_text = self._anchor_centered_window(
                    result.passage.text,
                    result.passage.doc_id or result.passage.id,
                    anchor_values,
                )
                if focused_text is None:
                    continue
                focused_passages.append(result.model_copy(update={
                    "passage": result.passage.model_copy(update={"text": focused_text}),
                }))
            if focused_passages:
                passages = focused_passages
                anchor_window_output_chars = sum(len(result.passage.text) for result in passages)
                anchor_window_dropped_passages = len(retrieved_passages) - len(passages)
            else:
                anchor_window_fallback = True
                anchor_window_output_chars = anchor_window_input_chars
        requested_fields = (
            slot.variables - effective_bindings.keys()
            if self.role_projected_extraction
            else slot.variables
        )
        semantic_role_fields = {
            field for field in requested_fields
            if self._semantic_role_gender(field) is not None
        }
        boolean_fields = {
            field
            for field, value_type in slot.variable_types.items()
            if self.typed_extraction_contracts and value_type == "boolean" and field in requested_fields
        }
        metrics = RunMetrics(
            retrieval_calls=retrieval_calls,
            dual_query_expansions=int(use_dual_query),
            dual_query_skips=int(dual_query_skipped),
            dual_query_confidence_skips=int(dual_query_confidence_skip),
            dual_query_guard_checks=int(dual_query_guard_check),
            dual_query_guard_fallbacks=int(dual_query_guard_fallback),
            documents_accessed=len({p.passage.doc_id or p.passage.id for p in passages}),
            passages_processed=len(passages),
            typed_extraction_contracts=int(bool(boolean_fields and passages)),
            role_projected_extraction_contracts=int(self.role_projected_extraction and bool(passages)),
            known_binding_fields_projected=(
                len(slot.variables & effective_bindings.keys())
                if self.role_projected_extraction and passages
                else 0
            ),
            extraction_thinking_disabled=int(
                self.extraction_enable_thinking is False and bool(passages)
            ),
            bound_role_signatures=int(self.bound_role_signatures and bool(passages)),
            semantic_role_type_contracts=int(
                self.semantic_role_type_filter and bool(passages) and bool(semantic_role_fields)
            ),
            anchor_window_contracts=int(anchor_window_contract),
            anchor_window_selected_passages=(len(passages) if anchor_window_contract else 0),
            anchor_window_dropped_passages=anchor_window_dropped_passages,
            anchor_window_input_chars=anchor_window_input_chars,
            anchor_window_output_chars=anchor_window_output_chars,
            anchor_window_fallbacks=int(anchor_window_fallback),
            anchor_window_predicate_normalizations=int(anchor_window_predicate_normalization),
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
                    + (
                        "Boolean fields must be exactly yes, no, or unknown. Use unknown when the passages are insufficient or conflicting. "
                        if boolean_fields else ""
                    )
                    + (
                        f"Respect the ordered relation signature {slot.predicate}({', '.join(slot.arguments)}). "
                        f"Only emit unresolved fields {sorted(requested_fields)}; known arguments are merged by the executor. "
                        + (
                            "These upstream anchors are protected inputs, never values for unresolved fields: "
                            f"{json.dumps(sorted(self.protected_anchor_values), ensure_ascii=False)}. "
                            if self.protected_anchor_values else ""
                        )
                        if self.role_projected_extraction else ""
                    )
                    + "Return an empty rows list when no passage supports the relation."
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
                completion_options: dict[str, Any] = {
                    "tools": [extraction_tool(
                        slot,
                        list(by_source),
                        typed_extraction_contracts=bool(boolean_fields),
                        requested_fields=set(requested_fields),
                        role_projected=self.role_projected_extraction,
                        known_bindings=(effective_bindings if self.bound_role_signatures else None),
                    )],
                    "tool_choice": {"type": "function", "function": {"name": "emit_evidence_rows"}},
                    "temperature": 0.0,
                }
                if self.extraction_enable_thinking is not None:
                    completion_options["enable_thinking"] = self.extraction_enable_thinking
                response = self.client.complete(messages, **completion_options)
                metrics = SlotCompiler._record_response(metrics, response, phase="extraction")
                finish_reason = response.finish_reason or "unknown"
                metrics = metrics.model_copy(update={
                    "extraction_finish_reasons": metrics.extraction_finish_reasons + [finish_reason],
                    "extraction_length_finishes": (
                        metrics.extraction_length_finishes + int(finish_reason == "length")
                    ),
                })
                args = self.client.require_tool(response, "emit_evidence_rows")
                extracted = ExtractionRow.model_validate(args)
                expected = slot.variables
                if boolean_fields:
                    verdicts: dict[str, set[str]] = {field: set() for field in boolean_fields}
                    for row in extracted.rows:
                        for field in boolean_fields:
                            value = row.get(field, "").strip().casefold()
                            if value not in {"yes", "no", "unknown"}:
                                raise SchemaError(f"boolean field {field} must be yes, no, or unknown")
                            row[field] = value
                            verdicts[field].add(value)
                    should_abstain = (
                        not extracted.rows
                        or any("unknown" in values or len(values) != 1 for values in verdicts.values())
                    )
                    if should_abstain:
                        metrics = metrics.model_copy(update={
                            "typed_extraction_abstentions": metrics.typed_extraction_abstentions + 1,
                        })
                        break
                if not extracted.rows and attempt == 0:
                    raise SchemaError(f"empty extraction for {slot.id}; review the retrieved passages once")
                rejection_reasons: list[str] = []
                semantic_rejections = 0
                accepted_before = len(extracted_rows)
                for row in extracted.rows:
                    source_id = row.get("source_id", "")
                    normalized = {
                        key.lstrip("?"): value.strip()
                        for key, value in row.items()
                        if key.lstrip("?") in requested_fields
                    }
                    source = by_source.get(source_id)
                    propagated = {key: value for key, value in bindings.items() if key in expected}
                    invalid_bindings = []
                    for key, value in propagated.items():
                        extracted_value = normalized.get(key)
                        if (
                            not self.role_projected_extraction
                            and (
                                extracted_value is None
                                or self._normalized_text(extracted_value) != self._normalized_text(value)
                            )
                        ):
                            invalid_bindings.append(f"{key} does not match propagated value")
                        elif source is None or not self._binding_is_grounded(
                            value,
                            source_id,
                            source.passage.text,
                            source.passage.doc_id,
                        ):
                            invalid_bindings.append(f"{key} is not grounded in source {source_id}")
                    if self.role_projected_extraction:
                        for key, value in normalized.items():
                            if any(
                                self._normalized_text(value) == self._normalized_text(anchor)
                                for anchor in self.protected_anchor_values
                            ):
                                invalid_bindings.append(f"{key} copies a protected upstream anchor")
                                metrics = metrics.model_copy(update={
                                    "protected_anchor_rejections": metrics.protected_anchor_rejections + 1,
                                })
                            elif source is None:
                                invalid_bindings.append(f"{key} is not grounded in source {source_id}")
                            elif not self._binding_is_grounded(
                                value,
                                source_id,
                                source.passage.text,
                                source.passage.doc_id,
                            ):
                                repaired_value = (
                                    self._evidence_surface_variant(value, source.passage.text)
                                    if self.evidence_surface_grounding_repair
                                    and key in {"country", "nationality", "citizenship"}
                                    and self._uses_anchor_window(slot, normalize_predicates=True)
                                    else None
                                )
                                if repaired_value is None:
                                    invalid_bindings.append(f"{key} is not grounded in source {source_id}")
                                else:
                                    normalized[key] = repaired_value
                                    metrics = metrics.model_copy(update={
                                        "evidence_surface_grounding_repairs": (
                                            metrics.evidence_surface_grounding_repairs + 1
                                        ),
                                    })
                    if invalid_bindings:
                        rejection_reasons.extend(invalid_bindings)
                        metrics = metrics.model_copy(update={
                            "grounding_rejections": metrics.grounding_rejections + 1,
                        })
                        continue
                    semantic_conflicts = [
                        conflict
                        for key, value in normalized.items()
                        if (conflict := self._semantic_role_type_conflict(key, value)) is not None
                    ] if self.semantic_role_type_filter else []
                    if semantic_conflicts:
                        rejection_reasons.extend(semantic_conflicts)
                        semantic_rejections += 1
                        metrics = metrics.model_copy(update={
                            "semantic_role_type_rejections": metrics.semantic_role_type_rejections + 1,
                        })
                        continue
                    normalized.update({key: value for key, value in effective_bindings.items() if key in expected})
                    if source_id in by_source and set(normalized) == expected and all(normalized.values()):
                        extracted_rows.append((normalized, source_id))
                if (
                    extracted.rows
                    and len(extracted_rows) == accepted_before
                    and semantic_rejections == len(extracted.rows)
                ):
                    metrics = metrics.model_copy(update={
                        "semantic_role_type_abstentions": metrics.semantic_role_type_abstentions + 1,
                    })
                    break
                if extracted.rows and not extracted_rows:
                    detail = f"; {'; '.join(rejection_reasons)}" if rejection_reasons else ""
                    raise SchemaError(
                        f"extracted rows for {slot.id} do not match fields {sorted(expected)} and source IDs{detail}"
                    )
                if boolean_fields:
                    metrics = metrics.model_copy(update={
                        "typed_extraction_answers": metrics.typed_extraction_answers + 1,
                    })
                break
            except (SchemaError, ValidationError, ValueError) as exc:
                metrics = metrics.model_copy(update={
                    "structured_output_failures": metrics.structured_output_failures + 1,
                    "structured_output_repairs": metrics.structured_output_repairs + (1 if attempt == 0 else 0),
                    "extraction_validation_errors": metrics.extraction_validation_errors + [
                        f"{exc.__class__.__name__}: {exc}"[:2000]
                    ],
                })
                if attempt == 0:
                    role_context = (
                        f" Ordered relation: {slot.predicate}({', '.join(slot.arguments)}). "
                        f"Known bindings: {json.dumps(effective_bindings, ensure_ascii=False)}. "
                        f"Protected upstream anchors: {json.dumps(sorted(self.protected_anchor_values), ensure_ascii=False)}."
                        if self.role_projected_extraction else ""
                    )
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Correct the extraction. Required unresolved relation fields: {sorted(requested_fields)}. "
                            f"Error: {exc}.{role_context}"
                        ),
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
                "dual_query_expansions": metrics.dual_query_expansions + current_metrics.dual_query_expansions,
                "dual_query_skips": metrics.dual_query_skips + current_metrics.dual_query_skips,
                "dual_query_confidence_skips": metrics.dual_query_confidence_skips + current_metrics.dual_query_confidence_skips,
                "dual_query_guard_checks": metrics.dual_query_guard_checks + current_metrics.dual_query_guard_checks,
                "llm_calls": metrics.llm_calls + current_metrics.llm_calls,
                "prompt_tokens": metrics.prompt_tokens + current_metrics.prompt_tokens,
                "completion_tokens": metrics.completion_tokens + current_metrics.completion_tokens,
                "extraction_llm_calls": metrics.extraction_llm_calls + current_metrics.extraction_llm_calls,
                "extraction_prompt_tokens": metrics.extraction_prompt_tokens + current_metrics.extraction_prompt_tokens,
                "extraction_completion_tokens": metrics.extraction_completion_tokens + current_metrics.extraction_completion_tokens,
                "latency_ms": metrics.latency_ms + current_metrics.latency_ms,
                "structured_output_failures": metrics.structured_output_failures + current_metrics.structured_output_failures,
                "structured_output_repairs": metrics.structured_output_repairs + current_metrics.structured_output_repairs,
                "grounding_rejections": metrics.grounding_rejections + current_metrics.grounding_rejections,
                "evidence_surface_grounding_repairs": metrics.evidence_surface_grounding_repairs + current_metrics.evidence_surface_grounding_repairs,
                "typed_extraction_contracts": metrics.typed_extraction_contracts + current_metrics.typed_extraction_contracts,
                "typed_extraction_answers": metrics.typed_extraction_answers + current_metrics.typed_extraction_answers,
                "typed_extraction_abstentions": metrics.typed_extraction_abstentions + current_metrics.typed_extraction_abstentions,
                "role_projected_extraction_contracts": metrics.role_projected_extraction_contracts + current_metrics.role_projected_extraction_contracts,
                "known_binding_fields_projected": metrics.known_binding_fields_projected + current_metrics.known_binding_fields_projected,
                "protected_anchor_rejections": metrics.protected_anchor_rejections + current_metrics.protected_anchor_rejections,
                "extraction_thinking_disabled": metrics.extraction_thinking_disabled + current_metrics.extraction_thinking_disabled,
                "bound_role_signatures": metrics.bound_role_signatures + current_metrics.bound_role_signatures,
                "extraction_length_finishes": metrics.extraction_length_finishes + current_metrics.extraction_length_finishes,
                "semantic_role_type_contracts": metrics.semantic_role_type_contracts + current_metrics.semantic_role_type_contracts,
                "semantic_role_type_rejections": metrics.semantic_role_type_rejections + current_metrics.semantic_role_type_rejections,
                "semantic_role_type_abstentions": metrics.semantic_role_type_abstentions + current_metrics.semantic_role_type_abstentions,
                "anchor_window_contracts": metrics.anchor_window_contracts + current_metrics.anchor_window_contracts,
                "anchor_window_selected_passages": metrics.anchor_window_selected_passages + current_metrics.anchor_window_selected_passages,
                "anchor_window_dropped_passages": metrics.anchor_window_dropped_passages + current_metrics.anchor_window_dropped_passages,
                "anchor_window_input_chars": metrics.anchor_window_input_chars + current_metrics.anchor_window_input_chars,
                "anchor_window_output_chars": metrics.anchor_window_output_chars + current_metrics.anchor_window_output_chars,
                "anchor_window_fallbacks": metrics.anchor_window_fallbacks + current_metrics.anchor_window_fallbacks,
                "anchor_window_predicate_normalizations": metrics.anchor_window_predicate_normalizations + current_metrics.anchor_window_predicate_normalizations,
                "provider_request_ids": metrics.provider_request_ids + current_metrics.provider_request_ids,
                "extraction_finish_reasons": metrics.extraction_finish_reasons + current_metrics.extraction_finish_reasons,
                "extraction_validation_errors": metrics.extraction_validation_errors + current_metrics.extraction_validation_errors,
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


def _as_date(value: object) -> datetime | None:
    text = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", str(value).strip(), flags=re.IGNORECASE)
    text = text.replace(",", "")
    for date_format in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d %Y",
        "%b %d %Y",
    ):
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            continue
    return None


def _ordered_scalar(value: object) -> tuple[str, datetime | float] | None:
    if parsed_date := _as_date(value):
        return "date", parsed_date
    if (parsed_number := _as_number(value)) is not None:
        return "number", parsed_number
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
        elif operator.kind in {"field_argmin", "field_argmax"}:
            selections: list[str] = []
            if len(operator.fields) != len(operator.labels):
                result = []
                continue
            for row in result:
                parsed = [_ordered_scalar(row.get(field)) for field in operator.fields]
                if any(value is None for value in parsed):
                    selections = []
                    break
                typed_values = [value for value in parsed if value is not None]
                if len({value[0] for value in typed_values}) != 1:
                    selections = []
                    break
                ordered_values = [value[1] for value in typed_values]
                selected_value = (
                    min(ordered_values) if operator.kind == "field_argmin" else max(ordered_values)
                )
                selected_indices = [
                    index for index, value in enumerate(ordered_values) if value == selected_value
                ]
                if len(selected_indices) != 1:
                    selections = []
                    break
                selections.append(operator.labels[selected_indices[0]])
            if not selections or len(set(selections)) != 1:
                result = []
            else:
                result = [{operator.output or "answer": selections[0]}]
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
            if operator.operation == "date_diff_months":
                dates = [_as_date(result[0].get(field)) for field in fields] if result else []
                if len(dates) != 2 or any(value is None for value in dates):
                    result = []
                    continue
                start, end = dates
                assert start is not None and end is not None
                result = [{operator.output or "result": str((end.year - start.year) * 12 + end.month - start.month)}]
                continue
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


def _cross_join_rows(left: list[BindingRow], right: list[BindingRow]) -> list[BindingRow]:
    merged: list[BindingRow] = []
    for left_row in left:
        for right_row in right:
            bindings = dict(left_row.bindings)
            if any(key in bindings and bindings[key] != value for key, value in right_row.bindings.items()):
                continue
            bindings.update(right_row.bindings)
            merged.append(BindingRow(
                slot_id=f"{left_row.slot_id}+{right_row.slot_id}",
                bindings=bindings,
                source_id=f"{left_row.source_id}|{right_row.source_id}",
                source_span=f"{left_row.source_span}\n---\n{right_row.source_span}",
                confidence=min(left_row.confidence, right_row.confidence),
                retrieval_score=min(left_row.retrieval_score or 0, right_row.retrieval_score or 0),
            ))
    return merged


def _join_components(plan: SlotPlan) -> dict[str, int]:
    adjacency = {slot.id: set() for slot in plan.slots}
    for join in plan.joins:
        adjacency[join.left_slot].add(join.right_slot)
        adjacency[join.right_slot].add(join.left_slot)
    components: dict[str, int] = {}
    component_id = 0
    for slot_id in adjacency:
        if slot_id in components:
            continue
        frontier = [slot_id]
        while frontier:
            current = frontier.pop()
            if current in components:
                continue
            components[current] = component_id
            frontier.extend(adjacency[current] - components.keys())
        component_id += 1
    return components


def _operator_connects_branches(plan: SlotPlan, materialized_slots: set[str], incoming_slot: str) -> bool:
    components = _join_components(plan)
    incoming_component = components[incoming_slot]
    current_components = {components[slot_id] for slot_id in materialized_slots}
    if incoming_component in current_components:
        return False
    slot_fields = {slot.id: slot.variables for slot in plan.slots}
    for operator in plan.operators:
        if operator.kind not in {"field_argmin", "field_argmax"}:
            continue
        operator_components = {
            components[slot_id]
            for field in operator.fields
            for slot_id, variables in slot_fields.items()
            if field in variables
        }
        if incoming_component in operator_components and current_components & operator_components:
            return True
    return False


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
                "dual_query_expansions": metrics.dual_query_expansions + slot_metrics.dual_query_expansions,
                "dual_query_skips": metrics.dual_query_skips + slot_metrics.dual_query_skips,
                "dual_query_confidence_skips": metrics.dual_query_confidence_skips + slot_metrics.dual_query_confidence_skips,
                "dual_query_guard_checks": metrics.dual_query_guard_checks + slot_metrics.dual_query_guard_checks,
                "dual_query_guard_fallbacks": metrics.dual_query_guard_fallbacks + slot_metrics.dual_query_guard_fallbacks,
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
                "grounding_rejections": metrics.grounding_rejections + slot_metrics.grounding_rejections,
                "evidence_surface_grounding_repairs": metrics.evidence_surface_grounding_repairs + slot_metrics.evidence_surface_grounding_repairs,
                "typed_extraction_contracts": metrics.typed_extraction_contracts + slot_metrics.typed_extraction_contracts,
                "typed_extraction_answers": metrics.typed_extraction_answers + slot_metrics.typed_extraction_answers,
                "typed_extraction_abstentions": metrics.typed_extraction_abstentions + slot_metrics.typed_extraction_abstentions,
                "role_projected_extraction_contracts": metrics.role_projected_extraction_contracts + slot_metrics.role_projected_extraction_contracts,
                "known_binding_fields_projected": metrics.known_binding_fields_projected + slot_metrics.known_binding_fields_projected,
                "protected_anchor_rejections": metrics.protected_anchor_rejections + slot_metrics.protected_anchor_rejections,
                "extraction_thinking_disabled": metrics.extraction_thinking_disabled + slot_metrics.extraction_thinking_disabled,
                "bound_role_signatures": metrics.bound_role_signatures + slot_metrics.bound_role_signatures,
                "extraction_length_finishes": metrics.extraction_length_finishes + slot_metrics.extraction_length_finishes,
                "semantic_role_type_contracts": metrics.semantic_role_type_contracts + slot_metrics.semantic_role_type_contracts,
                "semantic_role_type_rejections": metrics.semantic_role_type_rejections + slot_metrics.semantic_role_type_rejections,
                "semantic_role_type_abstentions": metrics.semantic_role_type_abstentions + slot_metrics.semantic_role_type_abstentions,
                "anchor_window_contracts": metrics.anchor_window_contracts + slot_metrics.anchor_window_contracts,
                "anchor_window_selected_passages": metrics.anchor_window_selected_passages + slot_metrics.anchor_window_selected_passages,
                "anchor_window_dropped_passages": metrics.anchor_window_dropped_passages + slot_metrics.anchor_window_dropped_passages,
                "anchor_window_input_chars": metrics.anchor_window_input_chars + slot_metrics.anchor_window_input_chars,
                "anchor_window_output_chars": metrics.anchor_window_output_chars + slot_metrics.anchor_window_output_chars,
                "anchor_window_fallbacks": metrics.anchor_window_fallbacks + slot_metrics.anchor_window_fallbacks,
                "anchor_window_predicate_normalizations": metrics.anchor_window_predicate_normalizations + slot_metrics.anchor_window_predicate_normalizations,
                "plan_fallbacks": metrics.plan_fallbacks + slot_metrics.plan_fallbacks,
                "materialization_requests": metrics.materialization_requests + len(binding_contexts),
                "intermediate_binding_sizes": metrics.intermediate_binding_sizes + [len(rows) if current is None else len(current)],
                "reoptimizations": metrics.reoptimizations + (1 if step and self.options.runtime_replan else 0),
                "slot_selectivity_errors": metrics.slot_selectivity_errors + [selectivity_error],
                "extraction_finish_reasons": metrics.extraction_finish_reasons + slot_metrics.extraction_finish_reasons,
                "extraction_validation_errors": metrics.extraction_validation_errors + slot_metrics.extraction_validation_errors,
            })
            if not rows:
                return ExecutionResult(rows=[], evidence=retrieved_evidence, order=order, metrics=metrics, status="empty")
            if current is None:
                current = rows
            elif self.options.incremental_join:
                join = next((j for j in plan.joins if (j.left_slot in materialized and j.right_slot == slot.id) or (j.right_slot in materialized and j.left_slot == slot.id)), None)
                if join is None:
                    previous_slots = set(materialized) - {slot.id}
                    if not _operator_connects_branches(plan, previous_slots, slot.id):
                        return ExecutionResult(rows=[], evidence=retrieved_evidence, order=order, metrics=metrics, status="failed", error=f"slot {slot.id} has no join path")
                    join_input = len(current) + len(rows)
                    current = _cross_join_rows(current, rows)
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
                    if not _operator_connects_branches(plan, joined_slots, slot_id):
                        return ExecutionResult(rows=[], evidence=retrieved_evidence, order=order, metrics=metrics, status="failed", error=f"slot {slot_id} has no late join path")
                    incoming = materialized[slot_id]
                    join_input = len(joined) + len(incoming)
                    joined = _cross_join_rows(joined, incoming)
                else:
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
