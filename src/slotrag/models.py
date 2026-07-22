from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Slot(StrictModel):
    id: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    arguments: list[str] = Field(min_length=1)
    constraints: dict[str, Any] = Field(default_factory=dict)
    variable_types: dict[str, Literal["string", "boolean", "number", "date"]] = Field(default_factory=dict)
    importance: float = Field(default=1.0, gt=0)
    estimated_cardinality: float = Field(default=100.0, gt=0)
    estimated_cost: float = Field(default=1.0, gt=0)

    @field_validator("arguments")
    @classmethod
    def non_empty_arguments(cls, value: list[str]) -> list[str]:
        if any(not arg.strip() for arg in value):
            raise ValueError("slot arguments cannot be empty")
        return value

    @model_validator(mode="after")
    def requires_variable(self) -> "Slot":
        self.constraints = {key.lstrip("?"): value for key, value in self.constraints.items()}
        self.variable_types = {key.lstrip("?"): value for key, value in self.variable_types.items()}
        if not self.variables:
            raise ValueError("a slot must expose at least one ?variable")
        unknown_types = sorted(set(self.variable_types) - self.variables)
        if unknown_types:
            raise ValueError(f"variable_types keys must be slot variables: {', '.join(unknown_types)}")
        return self

    @property
    def variables(self) -> set[str]:
        return {arg[1:] for arg in self.arguments if arg.startswith("?")}

    def query_text(self, bindings: dict[str, str] | None = None) -> str:
        bindings = bindings or {}
        args = []
        for arg in self.arguments:
            if arg.startswith("?") and arg[1:] in bindings:
                args.append(bindings[arg[1:]])
            else:
                args.append(arg)
        constraint_text = " ".join(f"{k}={v}" for k, v in sorted(self.constraints.items()))
        return " ".join(part for part in (self.predicate, " ".join(args), constraint_text) if part)


class JoinSpec(StrictModel):
    left_slot: str
    left_field: str
    right_slot: str
    right_field: str

    @model_validator(mode="before")
    @classmethod
    def accept_pair_form(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)) and len(value) == 2:
            left_slot, left_field = str(value[0]).split(".", 1)
            right_slot, right_field = str(value[1]).split(".", 1)
            return {
                "left_slot": left_slot,
                "left_field": left_field,
                "right_slot": right_slot,
                "right_field": right_field,
            }
        if isinstance(value, dict):
            if "left" in value and "right" in value:
                left_slot, left_field = str(value["left"]).split(".", 1)
                right_slot, right_field = str(value["right"]).split(".", 1)
                return {
                    "left_slot": left_slot,
                    "left_field": left_field,
                    "right_slot": right_slot,
                    "right_field": right_field,
                }
        return value


class RelationalOperator(StrictModel):
    """A typed post-materialization operation in a SlotPlan."""

    id: str = Field(min_length=1)
    kind: Literal[
        "filter",
        "project",
        "intersect",
        "count",
        "sort",
        "argmin",
        "argmax",
        "field_argmin",
        "field_argmax",
        "compare",
        "boolean",
        "arithmetic",
    ]
    fields: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    field: str | None = None
    output: str | None = None
    comparator: Literal["eq", "ne", "lt", "le", "gt", "ge", "contains"] | None = None
    operation: Literal["add", "subtract", "multiply", "divide", "date_diff_months"] | None = None
    value: str | float | int | bool | None = None
    descending: bool = False
    limit: int | None = Field(default=None, gt=0)

    @field_validator("fields")
    @classmethod
    def normalize_fields(cls, value: list[str]) -> list[str]:
        return [field.lstrip("?") for field in value]

    @field_validator("field", "output")
    @classmethod
    def normalize_optional_field(cls, value: str | None) -> str | None:
        return value.lstrip("?") if value else value

    @model_validator(mode="after")
    def validate_shape(self) -> "RelationalOperator":
        if self.kind == "project" and not self.fields:
            raise ValueError("project requires fields")
        if self.kind in {"filter", "sort", "argmin", "argmax"} and not self.field:
            raise ValueError(f"{self.kind} requires field")
        if self.kind == "filter" and (self.comparator is None or self.value is None):
            raise ValueError("filter requires comparator and value")
        if self.kind in {"count", "compare", "boolean"} and not self.output:
            raise ValueError(f"{self.kind} requires output")
        if self.kind in {"field_argmin", "field_argmax"}:
            if len(self.fields) < 2 or not self.output:
                raise ValueError(f"{self.kind} requires at least two fields and an output")
            if len(self.labels) != len(self.fields) or any(not label.strip() for label in self.labels):
                raise ValueError(f"{self.kind} requires one non-empty label per field")
        elif self.labels:
            raise ValueError("labels are only supported by field extrema operators")
        if self.kind == "arithmetic" and (len(self.fields) < 2 or not self.output or not self.operation):
            raise ValueError("arithmetic requires at least two fields, an operation, and an output")
        return self


class SlotPlan(StrictModel):
    slots: list[Slot] = Field(min_length=1)
    joins: list[JoinSpec] = Field(default_factory=list)
    outputs: list[str] = Field(min_length=1)
    operators: list[RelationalOperator] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "SlotPlan":
        slot_ids = {slot.id for slot in self.slots}
        if len(slot_ids) != len(self.slots):
            raise ValueError("slot ids must be unique")
        slot_fields = {slot.id: slot.variables for slot in self.slots}
        adjacency = {slot_id: set() for slot_id in slot_ids}
        for join in self.joins:
            if join.left_slot not in slot_ids or join.right_slot not in slot_ids:
                raise ValueError("join references an unknown slot")
            if join.left_field not in slot_fields[join.left_slot] or join.right_field not in slot_fields[join.right_slot]:
                raise ValueError("join references a field that is not a slot variable")
            if join.left_slot == join.right_slot:
                raise ValueError("a slot cannot join with itself")
            if join.left_field != join.right_field:
                raise ValueError("joined fields must reuse the same variable name for the same entity")
            adjacency[join.left_slot].add(join.right_slot)
            adjacency[join.right_slot].add(join.left_slot)
        for operator in self.operators:
            if operator.kind not in {"field_argmin", "field_argmax"}:
                continue
            field_sources: list[set[str]] = []
            for field in operator.fields:
                sources = {
                    slot_id
                    for slot_id, variables in slot_fields.items()
                    if field in variables
                }
                if not sources:
                    raise ValueError("field extrema operator references an unknown slot variable")
                field_sources.append(sources)
            operator_slots = set().union(*field_sources)
            for left_slot in operator_slots:
                adjacency[left_slot].update(operator_slots - {left_slot})
        if len(slot_ids) > 1:
            visited = set()
            frontier = [self.slots[0].id]
            while frontier:
                slot_id = frontier.pop()
                if slot_id in visited:
                    continue
                visited.add(slot_id)
                frontier.extend(adjacency[slot_id] - visited)
            if visited != slot_ids:
                raise ValueError("slot join graph must be connected")
        available = set().union(*(slot.variables for slot in self.slots))
        available.update(operator.output for operator in self.operators if operator.output)
        if any(output.startswith("?") and output[1:] not in available for output in self.outputs):
            raise ValueError("output references an unknown variable")
        return self


class Passage(StrictModel):
    id: str
    text: str = Field(min_length=1)
    doc_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BindingRow(StrictModel):
    slot_id: str
    bindings: dict[str, str]
    source_id: str
    source_span: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    retrieval_score: float | None = None


class EvidenceRecord(StrictModel):
    source_id: str
    source_span: str
    slot_id: str
    bindings: dict[str, str]


class QuestionRecord(StrictModel):
    id: str
    question: str
    passages: list[Passage] = Field(default_factory=list)
    answers: list[str] = Field(default_factory=list)
    gold_evidence: list[str] = Field(default_factory=list)
    gold_plan: SlotPlan | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResult(StrictModel):
    passage: Passage
    score: float
    bm25_score: float | None = None
    dense_score: float | None = None
    rerank_score: float | None = None


class RunMetrics(StrictModel):
    documents_accessed: int = 0
    unique_documents_accessed: int = 0
    passages_processed: int = 0
    unique_passages_accessed: int = 0
    llm_calls: int = 0
    retrieval_calls: int = 0
    embedding_calls: int = 0
    reranker_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    compilation_llm_calls: int = 0
    compilation_prompt_tokens: int = 0
    compilation_completion_tokens: int = 0
    extraction_llm_calls: int = 0
    extraction_prompt_tokens: int = 0
    extraction_completion_tokens: int = 0
    planning_llm_calls: int = 0
    planning_prompt_tokens: int = 0
    planning_completion_tokens: int = 0
    reasoning_llm_calls: int = 0
    reasoning_prompt_tokens: int = 0
    reasoning_completion_tokens: int = 0
    generation_llm_calls: int = 0
    generation_prompt_tokens: int = 0
    generation_completion_tokens: int = 0
    latency_ms: float = 0.0
    provider_latency_ms: float = 0.0
    wall_latency_ms: float = 0.0
    index_build_latency_ms: float = 0.0
    index_provider_latency_ms: float = 0.0
    index_embedding_calls: int = 0
    index_cache_hits: int = 0
    index_cache_misses: int = 0
    compilation_latency_ms: float = 0.0
    execution_latency_ms: float = 0.0
    materialization_latency_ms: float = 0.0
    generation_latency_ms: float = 0.0
    retry_count: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    materialization_requests: int = 0
    materialization_cache_hits: int = 0
    binding_contexts_pruned: int = 0
    evidence_only_fallbacks: int = 0
    answer_reconciliations: int = 0
    answer_span_normalizations: int = 0
    polar_answer_normalizations: int = 0
    polar_row_consensus: int = 0
    typed_extraction_contracts: int = 0
    typed_extraction_answers: int = 0
    typed_extraction_abstentions: int = 0
    frozen_plan_replays: int = 0
    grounded_entity_anchor_folds: int = 0
    grounded_entity_anchor_substitutions: int = 0
    direct_grounded_anchor_projections: int = 0
    query_grounded_anchor_contexts: int = 0
    query_anchor_plan_repairs: int = 0
    role_projected_extraction_contracts: int = 0
    known_binding_fields_projected: int = 0
    protected_anchor_rejections: int = 0
    extraction_thinking_disabled: int = 0
    bound_role_signatures: int = 0
    extraction_length_finishes: int = 0
    semantic_role_type_contracts: int = 0
    semantic_role_type_rejections: int = 0
    semantic_role_type_abstentions: int = 0
    anchor_window_contracts: int = 0
    anchor_window_selected_passages: int = 0
    anchor_window_dropped_passages: int = 0
    anchor_window_input_chars: int = 0
    anchor_window_output_chars: int = 0
    anchor_window_fallbacks: int = 0
    anchor_window_predicate_normalizations: int = 0
    deterministic_answers: int = 0
    join_input_rows: int = 0
    join_output_rows: int = 0
    early_stops: int = 0
    structured_output_failures: int = 0
    structured_output_repairs: int = 0
    grounding_rejections: int = 0
    evidence_surface_grounding_repairs: int = 0
    local_plan_repairs: int = 0
    operator_rewrites: int = 0
    plan_fallbacks: int = 0
    heuristic_plans: int = 0
    typed_plan_templates: int = 0
    field_extremum_templates: int = 0
    polar_comparison_templates: int = 0
    direct_plan_templates: int = 0
    operators_executed: int = 0
    plan_slot_count: int = 0
    plan_join_count: int = 0
    plan_variable_count: int = 0
    plan_output_count: int = 0
    plan_operator_count: int = 0
    plan_complexity: int = 0
    steps_executed: int = 0
    llm_budget_utilization: float = 0.0
    retrieval_budget_utilization: float = 0.0
    step_budget_utilization: float = 0.0
    peak_rss_mb: float = 0.0
    index_bytes: int = 0
    intermediate_binding_sizes: list[int] = Field(default_factory=list)
    reoptimizations: int = 0
    slot_selectivity_errors: list[float] = Field(default_factory=list)
    planner_regret: float | None = None
    provider_request_ids: list[str] = Field(default_factory=list)
    plan_validation_errors: list[str] = Field(default_factory=list)
    extraction_finish_reasons: list[str] = Field(default_factory=list)
    extraction_validation_errors: list[str] = Field(default_factory=list)


class ExecutionResult(StrictModel):
    rows: list[dict[str, str]] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    answer: str | None = None
    order: list[str] = Field(default_factory=list)
    metrics: RunMetrics = Field(default_factory=RunMetrics)
    status: Literal["ok", "empty", "failed", "budget_exceeded", "unsupported_operation"] = "ok"
    error: str | None = None
    plan: SlotPlan | None = None
