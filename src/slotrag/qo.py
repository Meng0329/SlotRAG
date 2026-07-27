"""Logical/physical planning primitives for the SlotRAG query optimizer.

The module deliberately sits between the existing ``SlotPlan`` compiler and the
runtime executor.  It does not retrieve or execute evidence; it validates a
logical plan, chooses a deterministic initial physical order, and records the
assumptions needed to audit that choice.
"""

from __future__ import annotations

import math
import re
import time
import unicodedata
from collections import defaultdict
from typing import Any, Literal

from pydantic import Field

from .models import JoinSpec, SlotPlan, StrictModel


VariableType = Literal["string", "boolean", "number", "date"]
RetrievalStrategy = Literal["hybrid", "bm25", "dense"]
ExpansionPolicy = Literal["fixed", "adaptive", "backtrack"]


def canonicalize_predicate(predicate: str) -> str:
    """Normalize surface-form predicates without encoding dataset-specific rules."""
    normalized = unicodedata.normalize("NFKC", predicate).casefold().strip()
    tokens = re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
    return "_".join(tokens)


class LogicalVariable(StrictModel):
    name: str = Field(min_length=1)
    type: VariableType = "string"
    source_subgoals: list[str] = Field(default_factory=list)


class LogicalSubgoal(StrictModel):
    id: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    arguments: list[str] = Field(min_length=1)
    variables: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    estimated_cardinality: float = 1.0
    estimated_cost: float = 1.0
    estimated_selectivity: float | None = None


class DependencyEdge(StrictModel):
    source_slot: str = Field(min_length=1)
    target_slot: str = Field(min_length=1)
    variables: list[str] = Field(default_factory=list)


class LogicalJoinEdge(StrictModel):
    left_slot: str = Field(min_length=1)
    left_variable: str = Field(min_length=1)
    right_slot: str = Field(min_length=1)
    right_variable: str = Field(min_length=1)


class LogicalPlan(StrictModel):
    variables: dict[str, LogicalVariable] = Field(default_factory=dict)
    subgoals: list[LogicalSubgoal] = Field(min_length=1)
    dependency_edges: list[DependencyEdge] = Field(default_factory=list)
    join_edges: list[LogicalJoinEdge] = Field(default_factory=list)
    answer_variable: str = Field(min_length=1)
    answer_type: VariableType = "string"
    semantic_constraints: dict[str, Any] = Field(default_factory=dict)


class BudgetAllocation(StrictModel):
    retrieval_calls: int = Field(default=1, ge=0)
    token_budget: int = Field(default=2048, ge=0)
    latency_budget_ms: float = Field(default=1000.0, ge=0)


class PlanTelemetry(StrictModel):
    validation_status: Literal["valid", "invalid"]
    validation_errors: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    canonicalized_predicates: int = 0
    estimated_rows: float = 0.0
    estimated_cost: float = 0.0
    detected_cycles: list[str] = Field(default_factory=list)
    repeated_slots: list[str] = Field(default_factory=list)
    unreachable_variables: list[str] = Field(default_factory=list)
    unexecutable_slots: list[str] = Field(default_factory=list)
    compile_latency_ms: float = 0.0


class PhysicalPlan(StrictModel):
    logical_plan: LogicalPlan
    slot_execution_order: list[str] = Field(min_length=1)
    retrieval_strategy: dict[str, RetrievalStrategy]
    query_formulation: dict[str, str]
    top_k: dict[str, int]
    reranker_usage: dict[str, bool]
    binding_beam_width: dict[str, int]
    expansion_policy: dict[str, ExpansionPolicy]
    stopping_rule: str = Field(min_length=1)
    budget_allocation: dict[str, BudgetAllocation]
    telemetry: PlanTelemetry


class PlanValidationError(ValueError):
    """A compile-time plan error whose telemetry is safe to persist."""

    def __init__(self, telemetry: PlanTelemetry) -> None:
        self.telemetry = telemetry
        message = "; ".join(telemetry.validation_errors) or "logical plan validation failed"
        super().__init__(message)


def _strip_variable(value: str) -> str:
    return value[1:] if value.startswith("?") else value


def _answer_type(
    answer_variable: str,
    variables: dict[str, LogicalVariable],
    operators: list[dict[str, Any]],
) -> VariableType:
    if answer_variable in variables:
        return variables[answer_variable].type
    for operator in operators:
        if _strip_variable(str(operator.get("output", ""))) != answer_variable:
            continue
        if operator.get("kind") in {"count", "arithmetic", "argmin", "argmax", "field_argmin", "field_argmax"}:
            return "number"
        if operator.get("kind") in {"boolean", "compare"}:
            return "boolean"
    return "string"


def logical_plan_from_slot_plan(
    plan: SlotPlan,
    *,
    answer_type: VariableType | None = None,
    semantic_constraints: dict[str, Any] | None = None,
) -> LogicalPlan:
    """Convert the existing planner contract into an optimizer-owned logical plan."""
    source_subgoals: dict[str, list[str]] = defaultdict(list)
    variable_types: dict[str, VariableType] = {}
    subgoals: list[LogicalSubgoal] = []
    for slot in plan.slots:
        variables = sorted(slot.variables)
        for variable in variables:
            source_subgoals[variable].append(slot.id)
            variable_types.setdefault(variable, slot.variable_types.get(variable, "string"))
        subgoals.append(
            LogicalSubgoal(
                id=slot.id,
                predicate=slot.predicate,
                arguments=list(slot.arguments),
                variables=variables,
                constraints=dict(slot.constraints),
                estimated_cardinality=slot.estimated_cardinality,
                estimated_cost=slot.estimated_cost,
            )
        )

    variables = {
        name: LogicalVariable(
            name=name,
            type=variable_types.get(name, "string"),
            source_subgoals=source_subgoals[name],
        )
        for name in sorted(source_subgoals)
    }
    joins = [
        LogicalJoinEdge(
            left_slot=join.left_slot,
            left_variable=_strip_variable(join.left_field),
            right_slot=join.right_slot,
            right_variable=_strip_variable(join.right_field),
        )
        for join in plan.joins
    ]
    dependencies = [
        DependencyEdge(
            source_slot=join.left_slot,
            target_slot=join.right_slot,
            variables=[_strip_variable(join.left_field)],
        )
        for join in plan.joins
    ]
    answer_variable = _strip_variable(plan.outputs[0])
    inferred_type = _answer_type(answer_variable, variables, [operator.model_dump(mode="python") for operator in plan.operators])
    return LogicalPlan(
        variables=variables,
        subgoals=subgoals,
        dependency_edges=dependencies,
        join_edges=joins,
        answer_variable=answer_variable,
        answer_type=answer_type or inferred_type,
        semantic_constraints=dict(semantic_constraints or {}),
    )


def _connected_components(plan: LogicalPlan, slot_ids: set[str]) -> list[set[str]]:
    adjacency: dict[str, set[str]] = {slot_id: set() for slot_id in slot_ids}
    for edge in plan.join_edges:
        if edge.left_slot in adjacency and edge.right_slot in adjacency:
            adjacency[edge.left_slot].add(edge.right_slot)
            adjacency[edge.right_slot].add(edge.left_slot)
    components: list[set[str]] = []
    remaining = set(slot_ids)
    while remaining:
        root = next(iter(remaining))
        component: set[str] = set()
        frontier = [root]
        while frontier:
            current = frontier.pop()
            if current in component:
                continue
            component.add(current)
            frontier.extend(adjacency[current] - component)
        components.append(component)
        remaining -= component
    return components


def _cycle_nodes(edges: list[tuple[str, str]]) -> list[str]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for source, target in edges:
        adjacency[source].add(target)
    state: dict[str, int] = {}
    cycles: set[str] = set()

    def visit(node: str, trail: list[str]) -> None:
        state[node] = 1
        for target in adjacency[node]:
            if state.get(target, 0) == 0:
                visit(target, trail + [target])
            elif state.get(target) == 1:
                cycles.update(trail[trail.index(target) :])
        state[node] = 2

    for node in sorted(adjacency):
        if state.get(node, 0) == 0:
            visit(node, [node])
    return sorted(cycles)


def _validation_telemetry(plan: LogicalPlan, started: float) -> PlanTelemetry:
    errors: list[str] = []
    warnings: list[str] = []
    repeated_slots: list[str] = []
    unreachable_variables: list[str] = []
    unexecutable_slots: list[str] = []
    detected_cycles: list[str] = []
    slot_ids = [subgoal.id for subgoal in plan.subgoals]
    unique_slot_ids = set(slot_ids)
    repeated_slots = sorted({slot_id for slot_id in slot_ids if slot_ids.count(slot_id) > 1})
    if repeated_slots:
        errors.append(f"REPEATED_SLOT: {', '.join(repeated_slots)}")

    declared_variables = set(plan.variables)
    occurrences: dict[str, set[str]] = defaultdict(set)
    for subgoal in plan.subgoals:
        if not subgoal.predicate.strip() or not subgoal.arguments:
            unexecutable_slots.append(subgoal.id)
        argument_variables = {
            _strip_variable(argument)
            for argument in subgoal.arguments
            if argument.startswith("?")
        }
        if not argument_variables:
            unexecutable_slots.append(subgoal.id)
        for variable in argument_variables:
            occurrences[variable].add(subgoal.id)
        for variable in subgoal.variables:
            if variable not in argument_variables:
                warnings.append(f"VARIABLE_METADATA_MISMATCH: {subgoal.id}:{variable}")
    undeclared = sorted(set(occurrences) - declared_variables)
    if undeclared:
        errors.append(f"UNDECLARED_VARIABLE: {', '.join(undeclared)}")
    for variable in sorted(declared_variables):
        if not occurrences.get(variable):
            unreachable_variables.append(variable)
            errors.append(f"VARIABLE_WITHOUT_SOURCE: {variable}")
    if unexecutable_slots:
        errors.append(f"UNEXECUTABLE_SLOT: {', '.join(sorted(set(unexecutable_slots)))}")

    for subgoal in plan.subgoals:
        if not math.isfinite(subgoal.estimated_cardinality) or subgoal.estimated_cardinality <= 0:
            errors.append(f"INVALID_CARDINALITY: {subgoal.id}")
        if not math.isfinite(subgoal.estimated_cost) or subgoal.estimated_cost <= 0:
            errors.append(f"INVALID_COST: {subgoal.id}")
        if subgoal.estimated_selectivity is None:
            warnings.append(f"MISSING_SELECTIVITY: {subgoal.id}")
        elif not math.isfinite(subgoal.estimated_selectivity) or not 0 <= subgoal.estimated_selectivity <= 1:
            errors.append(f"INVALID_SELECTIVITY: {subgoal.id}")

    for edge in plan.join_edges:
        if edge.left_slot not in unique_slot_ids or edge.right_slot not in unique_slot_ids:
            errors.append(f"JOIN_UNKNOWN_SLOT: {edge.left_slot}->{edge.right_slot}")
            continue
        if edge.left_slot == edge.right_slot:
            errors.append(f"JOIN_SELF_REFERENCE: {edge.left_slot}")
        left_variables = next(subgoal.variables for subgoal in plan.subgoals if subgoal.id == edge.left_slot)
        right_variables = next(subgoal.variables for subgoal in plan.subgoals if subgoal.id == edge.right_slot)
        if edge.left_variable not in left_variables or edge.right_variable not in right_variables:
            errors.append(f"JOIN_UNKNOWN_VARIABLE: {edge.left_slot}.{edge.left_variable}->{edge.right_slot}.{edge.right_variable}")
        if edge.left_variable != edge.right_variable:
            errors.append(f"JOIN_VARIABLE_MISMATCH: {edge.left_variable}!={edge.right_variable}")

    for edge in plan.dependency_edges:
        if edge.source_slot not in unique_slot_ids or edge.target_slot not in unique_slot_ids:
            errors.append(f"DEPENDENCY_UNKNOWN_SLOT: {edge.source_slot}->{edge.target_slot}")
        if edge.source_slot == edge.target_slot:
            errors.append(f"DEPENDENCY_SELF_REFERENCE: {edge.source_slot}")
    detected_cycles = _cycle_nodes([(edge.source_slot, edge.target_slot) for edge in plan.dependency_edges])
    if detected_cycles:
        errors.append(f"DEPENDENCY_CYCLE: {', '.join(detected_cycles)}")

    if plan.answer_variable not in declared_variables or not occurrences.get(plan.answer_variable):
        unreachable_variables.append(plan.answer_variable)
        errors.append(f"ANSWER_UNREACHABLE: {plan.answer_variable}")
    components = _connected_components(plan, unique_slot_ids)
    answer_sources = occurrences.get(plan.answer_variable, set())
    if len(unique_slot_ids) > 1 and len(components) > 1:
        errors.append("JOIN_GRAPH_DISCONNECTED")
    if answer_sources and not any(answer_sources & component for component in components):
        errors.append(f"ANSWER_COMPONENT_MISSING: {plan.answer_variable}")

    return PlanTelemetry(
        validation_status="invalid" if errors else "valid",
        validation_errors=errors,
        validation_warnings=warnings,
        canonicalized_predicates=0,
        estimated_rows=sum(max(subgoal.estimated_cardinality, 0) for subgoal in plan.subgoals),
        estimated_cost=sum(max(subgoal.estimated_cost, 0) for subgoal in plan.subgoals),
        detected_cycles=detected_cycles,
        repeated_slots=repeated_slots,
        unreachable_variables=sorted(set(unreachable_variables)),
        unexecutable_slots=sorted(set(unexecutable_slots)),
        compile_latency_ms=(time.perf_counter() - started) * 1000,
    )


def compile_physical_plan(
    logical_plan: LogicalPlan,
    *,
    retrieval_strategy: RetrievalStrategy = "hybrid",
    top_k: int = 10,
    reranker_enabled: bool = True,
    binding_beam_width: int = 2,
    expansion_policy: ExpansionPolicy = "adaptive",
    stopping_rule: str = "answerable_or_budget",
) -> PhysicalPlan:
    """Validate a logical plan and produce a deterministic initial physical plan."""
    started = time.perf_counter()
    canonicalized = logical_plan.model_copy(update={
        "subgoals": [
            subgoal.model_copy(update={"predicate": canonicalize_predicate(subgoal.predicate)})
            for subgoal in logical_plan.subgoals
        ]
    })
    telemetry = _validation_telemetry(canonicalized, started)
    telemetry = telemetry.model_copy(update={
        "canonicalized_predicates": sum(
            original.predicate != normalized.predicate
            for original, normalized in zip(logical_plan.subgoals, canonicalized.subgoals)
        ),
        "compile_latency_ms": (time.perf_counter() - started) * 1000,
    })
    if telemetry.validation_errors:
        raise PlanValidationError(telemetry)
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if binding_beam_width <= 0:
        raise ValueError("binding_beam_width must be positive")

    def physical_priority(subgoal: LogicalSubgoal) -> tuple[float, float, str]:
        selectivity = subgoal.estimated_selectivity if subgoal.estimated_selectivity is not None else 1.0
        return (subgoal.estimated_cost * subgoal.estimated_cardinality * selectivity, -len(subgoal.variables), subgoal.id)

    subgoals_by_id = {subgoal.id: subgoal for subgoal in canonicalized.subgoals}
    children: dict[str, set[str]] = {
        subgoal.id: set() for subgoal in canonicalized.subgoals
    }
    incoming = {subgoal.id: 0 for subgoal in canonicalized.subgoals}
    for edge in canonicalized.dependency_edges:
        if edge.target_slot in children[edge.source_slot]:
            continue
        children[edge.source_slot].add(edge.target_slot)
        incoming[edge.target_slot] += 1

    ready = [
        subgoals_by_id[slot_id]
        for slot_id, dependency_count in incoming.items()
        if dependency_count == 0
    ]
    ordered: list[LogicalSubgoal] = []
    while ready:
        subgoal = min(ready, key=physical_priority)
        ready.remove(subgoal)
        ordered.append(subgoal)
        for target in sorted(children[subgoal.id]):
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(subgoals_by_id[target])
    slot_ids = [subgoal.id for subgoal in ordered]
    query_formulation = {
        subgoal.id: " ".join(
            part
            for part in (
                subgoal.predicate,
                " ".join(subgoal.arguments),
                " ".join(f"{key}={value}" for key, value in sorted(subgoal.constraints.items())),
            )
            if part
        )
        for subgoal in ordered
    }
    policies = {
        subgoal.id: BudgetAllocation(
            retrieval_calls=(2 * binding_beam_width if expansion_policy == "adaptive" else binding_beam_width),
            token_budget=2048,
            latency_budget_ms=1000.0,
        )
        for subgoal in ordered
    }
    return PhysicalPlan(
        logical_plan=canonicalized,
        slot_execution_order=slot_ids,
        retrieval_strategy={slot_id: retrieval_strategy for slot_id in slot_ids},
        query_formulation=query_formulation,
        top_k={slot_id: top_k for slot_id in slot_ids},
        reranker_usage={slot_id: reranker_enabled for slot_id in slot_ids},
        binding_beam_width={slot_id: binding_beam_width for slot_id in slot_ids},
        expansion_policy={slot_id: expansion_policy for slot_id in slot_ids},
        stopping_rule=stopping_rule,
        budget_allocation=policies,
        telemetry=telemetry,
    )


__all__ = [
    "BudgetAllocation",
    "DependencyEdge",
    "LogicalJoinEdge",
    "LogicalPlan",
    "LogicalSubgoal",
    "LogicalVariable",
    "PhysicalPlan",
    "PlanTelemetry",
    "PlanValidationError",
    "canonicalize_predicate",
    "compile_physical_plan",
    "logical_plan_from_slot_plan",
]
