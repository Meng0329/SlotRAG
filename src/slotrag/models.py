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
    importance: float = Field(default=1.0, gt=0)

    @field_validator("arguments")
    @classmethod
    def non_empty_arguments(cls, value: list[str]) -> list[str]:
        if any(not arg.strip() for arg in value):
            raise ValueError("slot arguments cannot be empty")
        return value

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


class SlotPlan(StrictModel):
    slots: list[Slot] = Field(min_length=1)
    joins: list[JoinSpec] = Field(default_factory=list)
    outputs: list[str] = Field(min_length=1)

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
            adjacency[join.left_slot].add(join.right_slot)
            adjacency[join.right_slot].add(join.left_slot)
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
    passages_processed: int = 0
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    intermediate_binding_sizes: list[int] = Field(default_factory=list)
    reoptimizations: int = 0
    slot_selectivity_errors: list[float] = Field(default_factory=list)
    planner_regret: float | None = None
    provider_request_ids: list[str] = Field(default_factory=list)


class ExecutionResult(StrictModel):
    rows: list[dict[str, str]] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    answer: str | None = None
    order: list[str] = Field(default_factory=list)
    metrics: RunMetrics = Field(default_factory=RunMetrics)
    status: Literal["ok", "empty", "failed"] = "ok"
    error: str | None = None
    plan: SlotPlan | None = None
