from __future__ import annotations

import ast
import json
import math
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, Field

from ..config import AppConfig
from ..generation import generate_answer_response
from ..action_policy import PhysicalActionPolicy, TopKExpansionMode
from ..models import EvidenceRecord, ExecutionResult, QuestionRecord, RetrievalResult, RunMetrics, SlotPlan
from ..planner import (
    AdaptiveExecutor,
    ExecutionOptions,
    SlotCompiler,
    SlotMaterializer,
    direct_grounded_relation_anchor_values,
    fold_grounded_entity_anchor,
    substitute_grounded_entity_anchor,
    substitute_grounded_entity_anchor_with_values,
    query_grounded_anchor_values,
    inject_query_grounded_anchor,
)
from ..providers import AgnesClient, ChatResult
from ..qo import PlanValidationError, compile_physical_plan, logical_plan_from_slot_plan
from ..retrieval import HybridRetriever, tokenize
from ..sufficiency import EvidenceSufficiencyCalibrator


@dataclass(frozen=True)
class MethodSpec:
    key: str
    family: str
    strategy: str = "adaptive"
    options: ExecutionOptions = field(default_factory=ExecutionOptions)
    direct_single_document: bool = True
    field_extremum_templates: bool = True
    polar_comparison_templates: bool = True
    polar_row_consensus: bool = True
    typed_extraction_contracts: bool = False
    grounded_entity_anchor_folding: bool = False
    grounded_entity_anchor_substitution: bool = False
    role_projected_extraction: bool = False
    protect_known_binding_values: bool = False
    direct_grounded_anchor_projection: bool = False
    structured_answer_contract: bool = False
    extraction_enable_thinking: bool | None = None
    bound_role_signatures: bool = False
    semantic_role_type_filter: bool = False
    anchor_centered_extraction: bool = False
    normalize_anchor_window_predicates: bool = False
    query_grounded_anchor_context: bool = False
    query_anchor_plan_repair: bool = False
    evidence_surface_grounding_repair: bool = False
    question_grounded_retrieval: bool = False
    dual_query_retrieval: bool = False
    dual_query_unbound_only: bool = False
    dual_query_confidence_threshold: float | None = None
    dual_query_evidence_guard: bool = False
    dual_query_evidence_guard_disjoint_only: bool = True
    physical_plan: bool = False
    adaptive_binding_beam: bool = False
    physical_action_policy: bool = False
    topk_expansion_mode: TopKExpansionMode = "utility"
    evidence_sufficiency: bool = False
    complementary_retrieval: bool = False
    description: str = ""


MAIN_METHODS = [
    "slotrag",
    "slotrag-sufficiency",
    "slotrag-physical-policy",
    "slotrag-qo",
    "hybrid",
    "ircot",
    "react",
    "planrag",
    "srag",
    "graphrag",
]
ABLATION_METHODS = [
    "slotrag-question",
    "slotrag-fixed",
    "slotrag-random",
    "slotrag-oracle",
    "slotrag-no-replan",
    "slotrag-late-join",
    "slotrag-eager",
    "slotrag-no-bindings",
    "slotrag-no-operators",
    "slotrag-no-direct",
    "slotrag-no-extremum-template",
    "slotrag-no-polar-template",
    "slotrag-no-polar-consensus",
    "slotrag-typed-extraction",
    "slotrag-anchor-folding",
    "slotrag-anchor-substitution",
    "slotrag-role-projected-substitution",
    "slotrag-grounded-role-projection",
    "slotrag-grounded-binding-guard",
    "slotrag-grounded-frontier-guard",
    "slotrag-grounded-frontier-answer-contract",
    "slotrag-question-grounded-retrieval",
    "slotrag-grounded-question-retrieval",
    "slotrag-dual-query-retrieval",
    "slotrag-adaptive-dual-query-retrieval",
    "slotrag-grounded-dual-query-retrieval",
    "slotrag-grounded-adaptive-dual-query-retrieval",
    "slotrag-confidence-gated-dual-query-0p5",
    "slotrag-confidence-gated-dual-query-0p75",
    "slotrag-confidence-gated-unbound-dual-query-0p5",
    "slotrag-confidence-guarded-dual-query-0p5",
    "slotrag-confidence-guarded-dual-query-0p5-relaxed",
    "slotrag-grounded-adaptive-confidence-gated-dual-query-0p5",
    "slotrag-grounded-adaptive-confidence-gated-dual-query-0p75",
    "slotrag-grounded-role-type-filter",
    "slotrag-anchor-window-projection",
    "slotrag-normalized-anchor-window-projection",
    "slotrag-context-normalized-anchor-window-projection",
    "slotrag-plan-repaired-context-anchor-window-projection",
    "slotrag-surface-repaired-context-anchor-window-projection",
    "slotrag-repaired-context-anchor-window-projection",
    "slotrag-grounded-role-no-thinking",
    "slotrag-grounded-role-bound-signature",
    "slotrag-lean-grounded-role-projection",
    "slotrag-physical-policy-utility",
    "slotrag-qo-utility",
]


METHODS: dict[str, MethodSpec] = {
    "slotrag": MethodSpec("slotrag", "slotrag"),
    "slotrag-sufficiency": MethodSpec(
        "slotrag-sufficiency",
        "slotrag",
        evidence_sufficiency=True,
        description="SlotRAG with development-calibrated evidence sufficiency",
    ),
    "slotrag-physical-policy": MethodSpec(
        "slotrag-physical-policy",
        "slotrag",
        physical_plan=True,
        adaptive_binding_beam=True,
        physical_action_policy=True,
        topk_expansion_mode="disabled",
        complementary_retrieval=True,
        description="SlotRAG with physical planning and bounded complementary query actions",
    ),
    "slotrag-qo": MethodSpec(
        "slotrag-qo",
        "slotrag",
        physical_plan=True,
        adaptive_binding_beam=True,
        physical_action_policy=True,
        topk_expansion_mode="disabled",
        evidence_sufficiency=True,
        complementary_retrieval=True,
        description="Evidence-Sufficiency-Guided Physical SlotRAG Optimizer",
    ),
    "slotrag-physical-policy-utility": MethodSpec(
        "slotrag-physical-policy-utility",
        "slotrag",
        physical_plan=True,
        adaptive_binding_beam=True,
        physical_action_policy=True,
        topk_expansion_mode="utility",
        description="v69 physical-policy utility expansion ablation",
    ),
    "slotrag-qo-utility": MethodSpec(
        "slotrag-qo-utility",
        "slotrag",
        physical_plan=True,
        adaptive_binding_beam=True,
        physical_action_policy=True,
        topk_expansion_mode="utility",
        evidence_sufficiency=True,
        description="v69 SlotRAG-QO utility expansion ablation",
    ),
    "hybrid": MethodSpec("hybrid", "hybrid", description="whole-question hybrid retrieval"),
    "ircot": MethodSpec("ircot", "ircot", description="interleaved reasoning and retrieval, adapted"),
    "react": MethodSpec("react", "react", description="structured search/finish loop, adapted"),
    "planrag": MethodSpec("planrag", "planrag", description="static plan then retrieval, adapted"),
    "srag": MethodSpec(
        "srag",
        "slotrag",
        strategy="question",
        options=ExecutionOptions(runtime_replan=False, incremental_join=False, binding_propagation=False),
        direct_single_document=False,
        description="structured late-join retrieval, adapted",
    ),
    "graphrag": MethodSpec("graphrag", "graphrag", description="per-question lexical entity graph, adapted"),
    "slotrag-question": MethodSpec("slotrag-question", "slotrag", strategy="question"),
    "slotrag-fixed": MethodSpec("slotrag-fixed", "slotrag", strategy="fixed"),
    "slotrag-random": MethodSpec("slotrag-random", "slotrag", strategy="random"),
    "slotrag-oracle": MethodSpec("slotrag-oracle", "slotrag", strategy="oracle"),
    "slotrag-no-replan": MethodSpec("slotrag-no-replan", "slotrag", options=ExecutionOptions(runtime_replan=False)),
    "slotrag-late-join": MethodSpec("slotrag-late-join", "slotrag", options=ExecutionOptions(incremental_join=False)),
    "slotrag-eager": MethodSpec("slotrag-eager", "slotrag", options=ExecutionOptions(eager_materialization=True)),
    "slotrag-no-bindings": MethodSpec("slotrag-no-bindings", "slotrag", options=ExecutionOptions(binding_propagation=False)),
    "slotrag-no-operators": MethodSpec("slotrag-no-operators", "slotrag", options=ExecutionOptions(typed_operators=False)),
    "slotrag-no-direct": MethodSpec("slotrag-no-direct", "slotrag", direct_single_document=False),
    "slotrag-no-extremum-template": MethodSpec(
        "slotrag-no-extremum-template",
        "slotrag",
        field_extremum_templates=False,
    ),
    "slotrag-no-polar-template": MethodSpec(
        "slotrag-no-polar-template",
        "slotrag",
        polar_comparison_templates=False,
    ),
    "slotrag-no-polar-consensus": MethodSpec(
        "slotrag-no-polar-consensus",
        "slotrag",
        polar_row_consensus=False,
    ),
    "slotrag-no-typed-extraction": MethodSpec(
        "slotrag-no-typed-extraction",
        "slotrag",
        typed_extraction_contracts=False,
    ),
    "slotrag-typed-extraction": MethodSpec(
        "slotrag-typed-extraction",
        "slotrag",
        typed_extraction_contracts=True,
    ),
    "slotrag-anchor-folding": MethodSpec(
        "slotrag-anchor-folding",
        "slotrag",
        grounded_entity_anchor_folding=True,
    ),
    "slotrag-anchor-substitution": MethodSpec(
        "slotrag-anchor-substitution",
        "slotrag",
        grounded_entity_anchor_substitution=True,
    ),
    "slotrag-role-projected-substitution": MethodSpec(
        "slotrag-role-projected-substitution",
        "slotrag",
        grounded_entity_anchor_substitution=True,
        role_projected_extraction=True,
    ),
    "slotrag-grounded-role-projection": MethodSpec(
        "slotrag-grounded-role-projection",
        "slotrag",
        grounded_entity_anchor_substitution=True,
        role_projected_extraction=True,
        direct_grounded_anchor_projection=True,
    ),
    "slotrag-grounded-binding-guard": MethodSpec(
        "slotrag-grounded-binding-guard",
        "slotrag",
        grounded_entity_anchor_substitution=True,
        role_projected_extraction=True,
        protect_known_binding_values=True,
        direct_grounded_anchor_projection=True,
        description="grounded role projection with non-reflexive known-binding protection",
    ),
    "slotrag-grounded-frontier-guard": MethodSpec(
        "slotrag-grounded-frontier-guard",
        "slotrag",
        options=ExecutionOptions(frontier_safe_selection=True),
        grounded_entity_anchor_substitution=True,
        role_projected_extraction=True,
        protect_known_binding_values=True,
        direct_grounded_anchor_projection=True,
        description="grounded binding guard with explicit materialized-frontier slot selection",
    ),
    "slotrag-grounded-frontier-answer-contract": MethodSpec(
        "slotrag-grounded-frontier-answer-contract",
        "slotrag",
        options=ExecutionOptions(frontier_safe_selection=True),
        grounded_entity_anchor_substitution=True,
        role_projected_extraction=True,
        protect_known_binding_values=True,
        direct_grounded_anchor_projection=True,
        structured_answer_contract=True,
        description="frontier guard with structured final-answer tool and thinking disabled",
    ),
    "slotrag-question-grounded-retrieval": MethodSpec(
        "slotrag-question-grounded-retrieval",
        "slotrag",
        question_grounded_retrieval=True,
        description="slot retrieval augmented with the original question context",
    ),
    "slotrag-grounded-question-retrieval": MethodSpec(
        "slotrag-grounded-question-retrieval",
        "slotrag",
        grounded_entity_anchor_substitution=True,
        role_projected_extraction=True,
        direct_grounded_anchor_projection=True,
        question_grounded_retrieval=True,
        description="grounded role projection plus original-question retrieval context",
    ),
    "slotrag-dual-query-retrieval": MethodSpec(
        "slotrag-dual-query-retrieval",
        "slotrag",
        question_grounded_retrieval=True,
        dual_query_retrieval=True,
        description="RRF fusion of slot-only and original-question augmented retrieval",
    ),
    "slotrag-adaptive-dual-query-retrieval": MethodSpec(
        "slotrag-adaptive-dual-query-retrieval",
        "slotrag",
        question_grounded_retrieval=True,
        dual_query_retrieval=True,
        dual_query_unbound_only=True,
        description="RRF dual retrieval only for unbound slots; bound slots use slot-only retrieval",
    ),
    "slotrag-grounded-dual-query-retrieval": MethodSpec(
        "slotrag-grounded-dual-query-retrieval",
        "slotrag",
        grounded_entity_anchor_substitution=True,
        role_projected_extraction=True,
        direct_grounded_anchor_projection=True,
        question_grounded_retrieval=True,
        dual_query_retrieval=True,
        description="grounded role projection with dual-query RRF retrieval",
    ),
    "slotrag-grounded-adaptive-dual-query-retrieval": MethodSpec(
        "slotrag-grounded-adaptive-dual-query-retrieval",
        "slotrag",
        grounded_entity_anchor_substitution=True,
        role_projected_extraction=True,
        direct_grounded_anchor_projection=True,
        question_grounded_retrieval=True,
        dual_query_retrieval=True,
        dual_query_unbound_only=True,
        description="grounded role projection with dual retrieval only for unbound slots",
    ),
    "slotrag-confidence-gated-dual-query-0p5": MethodSpec(
        "slotrag-confidence-gated-dual-query-0p5",
        "slotrag",
        question_grounded_retrieval=True,
        dual_query_retrieval=True,
        dual_query_confidence_threshold=0.5,
        description="dual retrieval only when slot-only top reranker score is below 0.5",
    ),
    "slotrag-confidence-gated-dual-query-0p75": MethodSpec(
        "slotrag-confidence-gated-dual-query-0p75",
        "slotrag",
        question_grounded_retrieval=True,
        dual_query_retrieval=True,
        dual_query_confidence_threshold=0.75,
        description="dual retrieval only when slot-only top reranker score is below 0.75",
    ),
    "slotrag-confidence-gated-unbound-dual-query-0p5": MethodSpec(
        "slotrag-confidence-gated-unbound-dual-query-0p5",
        "slotrag",
        question_grounded_retrieval=True,
        dual_query_retrieval=True,
        dual_query_unbound_only=True,
        dual_query_confidence_threshold=0.5,
        description="confidence-gated dual retrieval only for unbound slots",
    ),
    "slotrag-confidence-guarded-dual-query-0p5": MethodSpec(
        "slotrag-confidence-guarded-dual-query-0p5",
        "slotrag",
        question_grounded_retrieval=True,
        dual_query_retrieval=True,
        dual_query_confidence_threshold=0.5,
        dual_query_evidence_guard=True,
        description="confidence-gated dual retrieval with evidence-support fallback",
    ),
    "slotrag-confidence-guarded-dual-query-0p5-relaxed": MethodSpec(
        "slotrag-confidence-guarded-dual-query-0p5-relaxed",
        "slotrag",
        question_grounded_retrieval=True,
        dual_query_retrieval=True,
        dual_query_confidence_threshold=0.5,
        dual_query_evidence_guard=True,
        dual_query_evidence_guard_disjoint_only=False,
        description="confidence-gated dual retrieval with overlap-tolerant evidence-support fallback",
    ),
    "slotrag-grounded-adaptive-confidence-gated-dual-query-0p5": MethodSpec(
        "slotrag-grounded-adaptive-confidence-gated-dual-query-0p5",
        "slotrag",
        grounded_entity_anchor_substitution=True,
        role_projected_extraction=True,
        direct_grounded_anchor_projection=True,
        question_grounded_retrieval=True,
        dual_query_retrieval=True,
        dual_query_unbound_only=True,
        dual_query_confidence_threshold=0.5,
        description="grounded adaptive dual retrieval gated at top slot-only reranker score 0.5",
    ),
    "slotrag-grounded-adaptive-confidence-gated-dual-query-0p75": MethodSpec(
        "slotrag-grounded-adaptive-confidence-gated-dual-query-0p75",
        "slotrag",
        grounded_entity_anchor_substitution=True,
        role_projected_extraction=True,
        direct_grounded_anchor_projection=True,
        question_grounded_retrieval=True,
        dual_query_retrieval=True,
        dual_query_unbound_only=True,
        dual_query_confidence_threshold=0.75,
        description="grounded adaptive dual retrieval gated at top slot-only reranker score 0.75",
    ),
    "slotrag-grounded-role-type-filter": MethodSpec(
        "slotrag-grounded-role-type-filter",
        "slotrag",
        grounded_entity_anchor_substitution=True,
        role_projected_extraction=True,
        direct_grounded_anchor_projection=True,
        semantic_role_type_filter=True,
    ),
    "slotrag-anchor-window-projection": MethodSpec(
        "slotrag-anchor-window-projection",
        "slotrag",
        grounded_entity_anchor_substitution=True,
        role_projected_extraction=True,
        direct_grounded_anchor_projection=True,
        anchor_centered_extraction=True,
    ),
    "slotrag-normalized-anchor-window-projection": MethodSpec(
        "slotrag-normalized-anchor-window-projection",
        "slotrag",
        grounded_entity_anchor_substitution=True,
        role_projected_extraction=True,
        direct_grounded_anchor_projection=True,
        anchor_centered_extraction=True,
        normalize_anchor_window_predicates=True,
    ),
    "slotrag-context-normalized-anchor-window-projection": MethodSpec(
        "slotrag-context-normalized-anchor-window-projection",
        "slotrag",
        grounded_entity_anchor_substitution=True,
        role_projected_extraction=True,
        direct_grounded_anchor_projection=True,
        anchor_centered_extraction=True,
        normalize_anchor_window_predicates=True,
        query_grounded_anchor_context=True,
    ),
    "slotrag-plan-repaired-context-anchor-window-projection": MethodSpec(
        "slotrag-plan-repaired-context-anchor-window-projection",
        "slotrag",
        grounded_entity_anchor_substitution=True,
        role_projected_extraction=True,
        direct_grounded_anchor_projection=True,
        anchor_centered_extraction=True,
        normalize_anchor_window_predicates=True,
        query_grounded_anchor_context=True,
        query_anchor_plan_repair=True,
    ),
    "slotrag-surface-repaired-context-anchor-window-projection": MethodSpec(
        "slotrag-surface-repaired-context-anchor-window-projection",
        "slotrag",
        grounded_entity_anchor_substitution=True,
        role_projected_extraction=True,
        direct_grounded_anchor_projection=True,
        anchor_centered_extraction=True,
        normalize_anchor_window_predicates=True,
        query_grounded_anchor_context=True,
        evidence_surface_grounding_repair=True,
    ),
    "slotrag-repaired-context-anchor-window-projection": MethodSpec(
        "slotrag-repaired-context-anchor-window-projection",
        "slotrag",
        grounded_entity_anchor_substitution=True,
        role_projected_extraction=True,
        direct_grounded_anchor_projection=True,
        anchor_centered_extraction=True,
        normalize_anchor_window_predicates=True,
        query_grounded_anchor_context=True,
        query_anchor_plan_repair=True,
        evidence_surface_grounding_repair=True,
    ),
    "slotrag-grounded-role-no-thinking": MethodSpec(
        "slotrag-grounded-role-no-thinking",
        "slotrag",
        grounded_entity_anchor_substitution=True,
        role_projected_extraction=True,
        direct_grounded_anchor_projection=True,
        extraction_enable_thinking=False,
    ),
    "slotrag-grounded-role-bound-signature": MethodSpec(
        "slotrag-grounded-role-bound-signature",
        "slotrag",
        grounded_entity_anchor_substitution=True,
        role_projected_extraction=True,
        direct_grounded_anchor_projection=True,
        bound_role_signatures=True,
    ),
    "slotrag-lean-grounded-role-projection": MethodSpec(
        "slotrag-lean-grounded-role-projection",
        "slotrag",
        grounded_entity_anchor_substitution=True,
        role_projected_extraction=True,
        direct_grounded_anchor_projection=True,
        extraction_enable_thinking=False,
        bound_role_signatures=True,
    ),
}


class SearchPlan(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=4)


class SearchStep(BaseModel):
    query: str = ""
    stop: bool = False


class ReactStep(BaseModel):
    action: str
    query: str = ""


def _plan_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "emit_search_plan",
            "description": "Emit up to four concise retrieval queries in execution order.",
            "parameters": {
                "type": "object",
                "properties": {"queries": {"type": "array", "minItems": 1, "maxItems": 4, "items": {"type": "string"}}},
                "required": ["queries"],
            },
        },
    }


def _search_step_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "emit_search_step",
            "description": "Choose the next search query or stop when the evidence is sufficient.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}, "stop": {"type": "boolean"}},
                "required": ["query", "stop"],
            },
        },
    }


def _react_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "emit_action",
            "description": "Choose search with a concise query, or finish when enough evidence is present.",
            "parameters": {
                "type": "object",
                "properties": {"action": {"type": "string", "enum": ["search", "finish"]}, "query": {"type": "string"}},
                "required": ["action", "query"],
            },
        },
    }


def merge_metrics(*values: RunMetrics) -> RunMetrics:
    result = RunMetrics()
    additive_lists = {
        "intermediate_binding_sizes",
        "slot_selectivity_errors",
        "provider_request_ids",
        "plan_validation_errors",
        "physical_plan_validation_errors",
        "physical_plan_validation_warnings",
        "extraction_finish_reasons",
        "extraction_validation_errors",
        "binding_beam_widths",
        "binding_pruned_source_ids",
        "physical_action_selected",
        "physical_action_executed",
        "physical_action_utilities",
        "physical_action_candidate_counts",
        "evidence_sufficiency_statuses",
        "evidence_sufficiency_probabilities",
    }
    replace_lists = {"physical_plan_order"}
    max_fields = {
        "peak_rss_mb",
        "index_bytes",
        "unique_documents_accessed",
        "unique_passages_accessed",
        "plan_slot_count",
        "plan_join_count",
        "plan_variable_count",
        "plan_output_count",
        "plan_operator_count",
        "plan_complexity",
        "steps_executed",
        "llm_budget_utilization",
        "retrieval_budget_utilization",
        "step_budget_utilization",
    }
    nullable = {"planner_regret"}
    data = result.model_dump()
    for value in values:
        current = value.model_dump()
        for key, item in current.items():
            if key in additive_lists:
                data[key].extend(item)
            elif key in replace_lists:
                if item:
                    data[key] = list(item)
            elif key in max_fields:
                data[key] = max(data[key], item)
            elif key in nullable:
                if item is not None:
                    data[key] = item
            elif key in {"physical_action_policy", "evidence_sufficiency_model"}:
                if item:
                    data[key] = item
            elif isinstance(item, (int, float)):
                data[key] += item
    return RunMetrics.model_validate(data)


def _chat_metrics(response: ChatResult, *, phase: str) -> RunMetrics:
    payload = {
        "llm_calls": response.logical_calls,
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
        "provider_latency_ms": response.latency_ms,
        "latency_ms": response.latency_ms,
        "provider_request_ids": [response.request_id] if response.request_id else [],
        f"{phase}_llm_calls": response.logical_calls,
        f"{phase}_prompt_tokens": response.usage.prompt_tokens,
        f"{phase}_completion_tokens": response.usage.completion_tokens,
    }
    return RunMetrics.model_validate(payload)


def _dedupe(items: list[RetrievalResult]) -> list[RetrievalResult]:
    best: dict[str, RetrievalResult] = {}
    for item in items:
        existing = best.get(item.passage.id)
        if existing is None or item.score > existing.score:
            best[item.passage.id] = item
    return sorted(best.values(), key=lambda item: item.score, reverse=True)


def _retrieval_result(items: list[RetrievalResult], *, slot_id: str, metrics: RunMetrics | None = None) -> ExecutionResult:
    ranked = _dedupe(items)
    return ExecutionResult(
        rows=[{"passage_id": item.passage.id} for item in ranked],
        evidence=[
            EvidenceRecord(source_id=item.passage.id, source_span=item.passage.text, slot_id=slot_id, bindings={})
            for item in ranked
        ],
        metrics=merge_metrics(
            metrics or RunMetrics(),
            RunMetrics(
                documents_accessed=len({item.passage.doc_id or item.passage.id for item in ranked}),
                unique_documents_accessed=len({item.passage.doc_id or item.passage.id for item in ranked}),
                passages_processed=len(ranked),
                unique_passages_accessed=len(ranked),
            ),
        ),
        status="ok" if ranked else "empty",
    )


def _answer_kind(dataset: str, question: QuestionRecord | None = None) -> str:
    if dataset == "strategyqa":
        return "boolean"
    if dataset == "drop":
        if question is not None and str(question.metadata.get("operation_type", "")).casefold() == "listing":
            return "list"
        return "number"
    return "short"


def _evidence_boolean(result: ExecutionResult) -> str | None:
    """Prefer an explicitly extracted boolean binding over a conflicting verbalizer."""
    for row in result.rows:
        value = row.get("answer", "")
        match = re.match(r"^\s*(yes|no|true|false)\b", value, flags=re.IGNORECASE)
        if match:
            token = match.group(1).casefold()
            return "True" if token in {"yes", "true"} else "False"
    return None


def _normalize_direct_answer_rows(result: ExecutionResult) -> ExecutionResult:
    if result.metrics.direct_plan_templates <= 0:
        return result
    normalized_rows: list[dict[str, str]] = []
    normalization_count = 0
    for row in result.rows:
        normalized_row = dict(row)
        answer = row.get("answer", "").strip()
        match = re.fullmatch(r"(?P<head>[^()\n]+?)\s+\((?P<body>[^()\n]+)\)\s*", answer)
        if match:
            head = match.group("head").strip()
            body = match.group("body").strip()
            normalized_head = " ".join(re.findall(r"\w+", head.casefold()))
            normalized_body = " ".join(re.findall(r"\w+", body.casefold()))
            if (
                normalized_head
                and re.match(r"^[+-]?(?:\d|\.\d)", body)
                and normalized_head in normalized_body
            ):
                normalized_row["answer"] = head
                normalization_count += 1
        normalized_rows.append(normalized_row)
    if not normalization_count:
        return result
    metrics = result.metrics.model_copy(update={
        "answer_span_normalizations": (
            result.metrics.answer_span_normalizations + normalization_count
        ),
    })
    return result.model_copy(update={"rows": normalized_rows, "metrics": metrics})


def _is_polar_question(question: str) -> bool:
    return question.rstrip().endswith("?") and re.match(
        r"^\s*(?:do|does|did|is|are|was|were|can|could|would|will|has|have|had)\b",
        question,
        flags=re.IGNORECASE,
    ) is not None


def _normalize_polar_answer(question: str, result: ExecutionResult) -> ExecutionResult:
    if result.status != "ok" or not result.answer or not _is_polar_question(question):
        return result
    match = re.match(r"^\s*(yes|no|true|false)\b", result.answer, flags=re.IGNORECASE)
    if not match:
        return result
    answer = "yes" if match.group(1).casefold() in {"yes", "true"} else "no"
    if result.answer == answer:
        return result
    metrics = result.metrics.model_copy(update={
        "polar_answer_normalizations": result.metrics.polar_answer_normalizations + 1,
    })
    return result.model_copy(update={"answer": answer, "metrics": metrics})


def _polar_row_consensus(question: str, plan: Any, result: ExecutionResult) -> str | None:
    if result.status != "ok" or not _is_polar_question(question) or len(plan.outputs) != 1:
        return None
    output = plan.outputs[0].lstrip("?")
    values = [
        row.get(output, "").strip()
        for row in result.rows
        if row.get(output, "").strip()
    ]
    if len(set(values)) <= 1:
        return None
    polarities: list[str] = []
    for value in values:
        match = re.match(r"^\s*(yes|no|true|false)\b", value, flags=re.IGNORECASE)
        if match is None:
            return None
        polarities.append("yes" if match.group(1).casefold() in {"yes", "true"} else "no")
    if len(set(polarities)) != 1:
        return None
    return "Yes" if polarities[0] == "yes" else "No"


def _deterministic_output(dataset: str, plan: Any, result: ExecutionResult) -> str | None:
    if result.status != "ok" or len(plan.outputs) != 1:
        return None
    output = plan.outputs[0].lstrip("?")
    values = {row.get(output, "").strip() for row in result.rows if row.get(output, "").strip()}
    if len(values) != 1:
        return None
    value = next(iter(values))
    if value[:1] in {"{", "["}:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return None
        if isinstance(parsed, (dict, list, tuple, set)):
            return None
    if dataset == "strategyqa":
        match = re.match(r"^\s*(yes|no|true|false)\b", value, flags=re.IGNORECASE)
        if not match:
            return None
        return "True" if match.group(1).casefold() in {"yes", "true"} else "False"
    return value


def _finalize(
    client: AgnesClient,
    dataset: str,
    question: QuestionRecord,
    result: ExecutionResult,
    *,
    structured_answer_contract: bool = False,
) -> ExecutionResult:
    if result.status not in {"ok", "empty"} or not result.evidence:
        return result
    started = time.perf_counter()
    answer, response = generate_answer_response(
        client,
        question.question,
        result,
        answer_kind=(
            _answer_kind(dataset, question)
            if structured_answer_contract
            else _answer_kind(dataset)
        ),
        structured_output=structured_answer_contract,
    )
    metrics = merge_metrics(
        result.metrics,
        _chat_metrics(response, phase="generation"),
        RunMetrics(generation_latency_ms=(time.perf_counter() - started) * 1000),
    )
    if dataset == "strategyqa":
        evidence_answer = _evidence_boolean(result)
        if evidence_answer is not None and evidence_answer != answer:
            answer = evidence_answer
            metrics = metrics.model_copy(update={"answer_reconciliations": metrics.answer_reconciliations + 1})
    if result.status == "empty":
        metrics = metrics.model_copy(update={"evidence_only_fallbacks": metrics.evidence_only_fallbacks + 1})
    return result.model_copy(update={"answer": answer, "status": "ok", "metrics": metrics})


def _evidence_digest(items: list[RetrievalResult]) -> str:
    payload = [
        {"id": item.passage.id, "text": item.passage.text[:500]}
        for item in _dedupe(items)[:8]
    ]
    return json.dumps(payload, ensure_ascii=False)


def _run_hybrid(dataset: str, question: QuestionRecord, retriever: HybridRetriever, client: AgnesClient) -> ExecutionResult:
    items = retriever.search(question.question)
    return _finalize(client, dataset, question, _retrieval_result(items, slot_id="hybrid", metrics=RunMetrics(retrieval_calls=1)))


def _run_planrag(dataset: str, question: QuestionRecord, retriever: HybridRetriever, client: AgnesClient) -> ExecutionResult:
    response = client.complete(
        [
            {"role": "system", "content": "Create a static retrieval plan for the question. Return only the tool call."},
            {"role": "user", "content": question.question},
        ],
        tools=[_plan_tool()],
        tool_choice={"type": "function", "function": {"name": "emit_search_plan"}},
        temperature=0.0,
    )
    plan = SearchPlan.model_validate(client.require_tool(response, "emit_search_plan"))
    items: list[RetrievalResult] = []
    for query in plan.queries:
        if query.strip():
            items.extend(retriever.search(query))
    metrics = merge_metrics(_chat_metrics(response, phase="planning"), RunMetrics(retrieval_calls=len(plan.queries)))
    return _finalize(client, dataset, question, _retrieval_result(items, slot_id="planrag", metrics=metrics))


def _run_ircot(dataset: str, question: QuestionRecord, retriever: HybridRetriever, client: AgnesClient) -> ExecutionResult:
    items: list[RetrievalResult] = []
    metrics = RunMetrics()
    for step_index in range(4):
        response = client.complete(
            [
                {"role": "system", "content": "Interleave evidence-guided reasoning and retrieval. Emit only the next search step; stop only when evidence is sufficient."},
                {"role": "user", "content": f"Question: {question.question}\nEvidence: {_evidence_digest(items)}"},
            ],
            tools=[_search_step_tool()],
            tool_choice={"type": "function", "function": {"name": "emit_search_step"}},
            temperature=0.0,
        )
        metrics = merge_metrics(metrics, _chat_metrics(response, phase="reasoning"))
        decision = SearchStep.model_validate(client.require_tool(response, "emit_search_step"))
        if decision.stop and items:
            metrics = merge_metrics(metrics, RunMetrics(early_stops=1))
            break
        query = decision.query.strip() or (question.question if step_index == 0 else "")
        if not query:
            break
        items.extend(retriever.search(query))
        metrics = merge_metrics(metrics, RunMetrics(retrieval_calls=1))
    return _finalize(client, dataset, question, _retrieval_result(items, slot_id="ircot", metrics=metrics))


def _run_react(dataset: str, question: QuestionRecord, retriever: HybridRetriever, client: AgnesClient) -> ExecutionResult:
    items: list[RetrievalResult] = []
    metrics = RunMetrics()
    for step_index in range(4):
        response = client.complete(
            [
                {"role": "system", "content": "Act through the structured search tool. Choose finish only when the observations answer the question."},
                {"role": "user", "content": f"Question: {question.question}\nObservations: {_evidence_digest(items)}"},
            ],
            tools=[_react_tool()],
            tool_choice={"type": "function", "function": {"name": "emit_action"}},
            temperature=0.0,
        )
        metrics = merge_metrics(metrics, _chat_metrics(response, phase="reasoning"))
        decision = ReactStep.model_validate(client.require_tool(response, "emit_action"))
        if decision.action == "finish" and items:
            metrics = merge_metrics(metrics, RunMetrics(early_stops=1))
            break
        query = decision.query.strip() or (question.question if step_index == 0 else "")
        if not query:
            break
        items.extend(retriever.search(query))
        metrics = merge_metrics(metrics, RunMetrics(retrieval_calls=1))
    return _finalize(client, dataset, question, _retrieval_result(items, slot_id="react", metrics=metrics))


def _graph_terms(text: str) -> set[str]:
    stop = {"the", "and", "for", "that", "with", "from", "was", "were", "are", "this", "what", "which", "who", "how"}
    return {token for token in tokenize(text) if len(token) >= 3 and token not in stop}


def _pagerank(adjacency: dict[int, set[int]], personalization: dict[int, float], iterations: int = 30, damping: float = 0.85) -> dict[int, float]:
    nodes = sorted(adjacency)
    if not nodes:
        return {}
    total_seed = sum(personalization.values()) or 1.0
    seed = {node: personalization.get(node, 0.0) / total_seed for node in nodes}
    if not any(seed.values()):
        seed = {node: 1.0 / len(nodes) for node in nodes}
    scores = dict(seed)
    for _ in range(iterations):
        updated = {node: (1.0 - damping) * seed[node] for node in nodes}
        dangling = sum(scores[node] for node in nodes if not adjacency[node])
        for node in nodes:
            updated[node] += damping * dangling * seed[node]
        for source in nodes:
            neighbors = adjacency[source]
            if not neighbors:
                continue
            share = damping * scores[source] / len(neighbors)
            for target in neighbors:
                updated[target] += share
        scores = updated
    return scores


def _run_graphrag(dataset: str, question: QuestionRecord, client: AgnesClient) -> ExecutionResult:
    started = time.perf_counter()
    passage_terms = [_graph_terms(f"{passage.doc_id or ''} {passage.text}") for passage in question.passages]
    term_documents: dict[str, list[int]] = defaultdict(list)
    for index, terms in enumerate(passage_terms):
        for term in terms:
            term_documents[term].append(index)
    adjacency = {index: set() for index in range(len(question.passages))}
    for documents in term_documents.values():
        if 1 < len(documents) <= 20:
            for source in documents:
                adjacency[source].update(target for target in documents if target != source)
    query_terms = _graph_terms(question.question)
    personalization = {index: float(len(query_terms & terms)) for index, terms in enumerate(passage_terms)}
    scores = _pagerank(adjacency, personalization)
    order = sorted(range(len(question.passages)), key=lambda index: (scores.get(index, 0.0), personalization[index], -index), reverse=True)[:10]
    items = [RetrievalResult(passage=question.passages[index], score=scores.get(index, 0.0)) for index in order]
    elapsed = (time.perf_counter() - started) * 1000
    graph_bytes = sum(len(passage.text.encode("utf-8")) for passage in question.passages) + sum(len(values) for values in adjacency.values()) * 8
    metrics = RunMetrics(
        retrieval_calls=1,
        index_build_latency_ms=elapsed,
        index_bytes=graph_bytes,
    )
    result = _retrieval_result(items, slot_id="graphrag", metrics=metrics)
    result = result.model_copy(update={
        "metrics": result.metrics.model_copy(update={
            "documents_accessed": len({passage.doc_id or passage.id for passage in question.passages}),
            "unique_documents_accessed": len({passage.doc_id or passage.id for passage in question.passages}),
            "passages_processed": len(question.passages),
            "unique_passages_accessed": len(question.passages),
        })
    })
    return _finalize(client, dataset, question, result)


def slotrag_compiler_signature(spec: MethodSpec) -> dict[str, bool]:
    """Return only method switches that can change the compiled SlotPlan."""
    return {
        "direct_single_document": spec.direct_single_document,
        "field_extremum_templates": spec.field_extremum_templates,
        "polar_comparison_templates": spec.polar_comparison_templates,
    }


def slotrag_compile_options(
    spec: MethodSpec,
    dataset: str,
    question: QuestionRecord,
) -> dict[str, Any]:
    options: dict[str, Any] = {
        "answer_kind": _answer_kind(dataset),
        "field_extremum_templates": spec.field_extremum_templates,
        "polar_comparison_templates": spec.polar_comparison_templates,
    }
    if spec.direct_single_document and question.passages:
        options["document_count"] = len({
            passage.doc_id or passage.id
            for passage in question.passages
        })
    return options


def _slot_plan_metrics(
    plan: SlotPlan,
    *,
    compilation_latency_ms: float = 0.0,
    frozen_plan_replays: int = 0,
) -> RunMetrics:
    plan_variables = set().union(*(slot.variables for slot in plan.slots))
    return RunMetrics(
        compilation_latency_ms=compilation_latency_ms,
        frozen_plan_replays=frozen_plan_replays,
        plan_slot_count=len(plan.slots),
        plan_join_count=len(plan.joins),
        plan_variable_count=len(plan_variables),
        plan_output_count=len(plan.outputs),
        plan_operator_count=len(plan.operators),
        plan_complexity=len(plan.slots) + len(plan.joins) + len(plan_variables) + len(plan.outputs) + len(plan.operators),
    )


def compile_slotrag_plan(
    spec: MethodSpec,
    dataset: str,
    question: QuestionRecord,
    client: AgnesClient,
) -> tuple[SlotPlan, RunMetrics]:
    compile_started = time.perf_counter()
    plan, compiler_metrics = SlotCompiler(client).compile(
        question.question,
        **slotrag_compile_options(spec, dataset, question),
    )
    return plan, merge_metrics(
        compiler_metrics,
        _slot_plan_metrics(
            plan,
            compilation_latency_ms=(time.perf_counter() - compile_started) * 1000,
        ),
    )


def _run_slotrag(
    spec: MethodSpec,
    dataset: str,
    question: QuestionRecord,
    retriever: HybridRetriever,
    client: AgnesClient,
    config: AppConfig,
    seed: int,
    max_steps: int,
    max_retrieval_calls: int,
    frozen_plan: SlotPlan | None = None,
    sufficiency_calibrator: EvidenceSufficiencyCalibrator | None = None,
) -> ExecutionResult:
    protected_anchor_values: set[str] = set()
    if frozen_plan is None:
        plan, compiler_metrics = compile_slotrag_plan(spec, dataset, question, client)
    else:
        plan = frozen_plan
        compiler_metrics = _slot_plan_metrics(plan, frozen_plan_replays=1)
    if spec.query_anchor_plan_repair:
        plan, plan_repairs, repair_anchor_values = inject_query_grounded_anchor(plan, question.question)
        protected_anchor_values.update(repair_anchor_values)
        effective_metrics = _slot_plan_metrics(plan)
        compiler_metrics = compiler_metrics.model_copy(update={
            "query_anchor_plan_repairs": plan_repairs,
            "plan_slot_count": effective_metrics.plan_slot_count,
            "plan_join_count": effective_metrics.plan_join_count,
            "plan_variable_count": effective_metrics.plan_variable_count,
            "plan_output_count": effective_metrics.plan_output_count,
            "plan_operator_count": effective_metrics.plan_operator_count,
            "plan_complexity": effective_metrics.plan_complexity,
        })
    if spec.grounded_entity_anchor_folding:
        plan, anchor_folds = fold_grounded_entity_anchor(plan, question.question)
        effective_metrics = _slot_plan_metrics(plan)
        compiler_metrics = compiler_metrics.model_copy(update={
            "grounded_entity_anchor_folds": anchor_folds,
            "plan_slot_count": effective_metrics.plan_slot_count,
            "plan_join_count": effective_metrics.plan_join_count,
            "plan_variable_count": effective_metrics.plan_variable_count,
            "plan_output_count": effective_metrics.plan_output_count,
            "plan_operator_count": effective_metrics.plan_operator_count,
            "plan_complexity": effective_metrics.plan_complexity,
        })
    if spec.grounded_entity_anchor_substitution:
        if spec.role_projected_extraction:
            plan, substituted_values = substitute_grounded_entity_anchor_with_values(plan, question.question)
            anchor_substitutions = len(substituted_values)
            protected_anchor_values.update(substituted_values)
        else:
            plan, anchor_substitutions = substitute_grounded_entity_anchor(plan, question.question)
        effective_metrics = _slot_plan_metrics(plan)
        compiler_metrics = compiler_metrics.model_copy(update={
            "grounded_entity_anchor_substitutions": anchor_substitutions,
            "plan_slot_count": effective_metrics.plan_slot_count,
            "plan_join_count": effective_metrics.plan_join_count,
            "plan_variable_count": effective_metrics.plan_variable_count,
            "plan_output_count": effective_metrics.plan_output_count,
            "plan_operator_count": effective_metrics.plan_operator_count,
            "plan_complexity": effective_metrics.plan_complexity,
        })
    if spec.direct_grounded_anchor_projection and not protected_anchor_values:
        direct_anchor_values = direct_grounded_relation_anchor_values(plan, question.question)
        protected_anchor_values.update(direct_anchor_values)
        compiler_metrics = compiler_metrics.model_copy(update={
            "direct_grounded_anchor_projections": len(direct_anchor_values),
        })
    if spec.query_grounded_anchor_context:
        query_anchor_values = query_grounded_anchor_values(plan, question.question)
        protected_anchor_values.update(query_anchor_values)
        compiler_metrics = compiler_metrics.model_copy(update={
            "query_grounded_anchor_contexts": len(query_anchor_values),
        })
    if len(plan.slots) > max_steps:
        return ExecutionResult(
            status="budget_exceeded",
            error=f"plan contains {len(plan.slots)} slots; budget allows {max_steps}",
            plan=plan,
            metrics=compiler_metrics,
        )
    physical_plan = None
    if spec.physical_plan:
        try:
            physical_plan = compile_physical_plan(logical_plan_from_slot_plan(plan))
        except PlanValidationError as exc:
            return ExecutionResult(
                status="failed",
                error=f"physical plan validation failed: {exc}",
                plan=plan,
                metrics=compiler_metrics.model_copy(update={
                    "physical_plan_validation_errors": exc.telemetry.validation_errors,
                    "physical_plan_validation_warnings": exc.telemetry.validation_warnings,
                }),
            )
        compiler_metrics = compiler_metrics.model_copy(update={
            "physical_plan_validation_errors": physical_plan.telemetry.validation_errors,
            "physical_plan_validation_warnings": physical_plan.telemetry.validation_warnings,
        })
    materializer_options: dict[str, Any] = {
        "max_passages": config.execution.materialization_top_k,
        "typed_extraction_contracts": spec.typed_extraction_contracts,
    }
    if spec.question_grounded_retrieval or spec.complementary_retrieval:
        materializer_options["question_context"] = question.question
    if spec.dual_query_retrieval:
        materializer_options["dual_query_retrieval"] = True
    if spec.dual_query_unbound_only:
        materializer_options["dual_query_unbound_only"] = True
    if spec.dual_query_confidence_threshold is not None:
        materializer_options["dual_query_confidence_threshold"] = spec.dual_query_confidence_threshold
    if spec.dual_query_evidence_guard:
        materializer_options["dual_query_evidence_guard"] = True
        materializer_options["dual_query_evidence_guard_disjoint_only"] = spec.dual_query_evidence_guard_disjoint_only
    if spec.role_projected_extraction and protected_anchor_values:
        materializer_options.update({
            "role_projected_extraction": True,
            "protected_anchor_values": protected_anchor_values,
        })
        if spec.protect_known_binding_values:
            materializer_options["protect_known_binding_values"] = True
        if spec.extraction_enable_thinking is not None:
            materializer_options["extraction_enable_thinking"] = spec.extraction_enable_thinking
        if spec.bound_role_signatures:
            materializer_options["bound_role_signatures"] = True
        if spec.semantic_role_type_filter:
            materializer_options["semantic_role_type_filter"] = True
        if spec.anchor_centered_extraction:
            materializer_options["anchor_centered_extraction"] = True
        if spec.normalize_anchor_window_predicates:
            materializer_options["normalize_anchor_window_predicates"] = True
        if spec.evidence_surface_grounding_repair:
            materializer_options["evidence_surface_grounding_repair"] = True
    materializer = SlotMaterializer(client, retriever, **materializer_options)
    executor = AdaptiveExecutor(
        materializer,
        default_slot_cost=config.execution.default_slot_cost,
        unbound_argument_cost=config.execution.unbound_argument_cost,
        max_replans=min(config.execution.max_replans, max_steps),
        max_retrieval_calls=max_retrieval_calls,
        max_binding_contexts=config.execution.max_binding_contexts,
        adaptive_binding_beam=spec.adaptive_binding_beam,
        action_policy=(
            PhysicalActionPolicy(topk_expansion_mode=spec.topk_expansion_mode)
            if spec.physical_action_policy
            else None
        ),
        sufficiency_calibrator=(sufficiency_calibrator if spec.evidence_sufficiency else None),
        complementary_retrieval=spec.complementary_retrieval,
        retrieval_backend=("bm25" if getattr(retriever, "dense_enabled", None) is False else "hybrid"),
        random_seed=seed,
        options=spec.options,
    )
    execution_started = time.perf_counter()
    if physical_plan is None:
        # Preserve the legacy call contract for existing methods and test doubles.
        result = executor.execute(plan, strategy=spec.strategy)
    else:
        result = executor.execute(plan, strategy=spec.strategy, physical_plan=physical_plan)
    execution_metrics = RunMetrics(
        execution_latency_ms=(time.perf_counter() - execution_started) * 1000,
        steps_executed=len(result.order),
        unique_documents_accessed=len(materializer.accessed_document_ids),
        unique_passages_accessed=len(materializer.accessed_passage_ids),
    )
    result = result.model_copy(update={"plan": plan, "metrics": merge_metrics(result.metrics, compiler_metrics, execution_metrics)})
    result = _normalize_direct_answer_rows(result)
    if not spec.options.typed_operators and plan.operators and result.status in {"ok", "empty"}:
        return result.model_copy(update={
            "answer": None,
            "status": "unsupported_operation",
            "error": "typed operators disabled for an operator-dependent plan",
        })
    consensus_answer = (
        _polar_row_consensus(question.question, plan, result)
        if spec.polar_row_consensus
        else None
    )
    deterministic_answer = consensus_answer or _deterministic_output(dataset, plan, result)
    if deterministic_answer is not None:
        metrics = result.metrics.model_copy(update={
            "deterministic_answers": result.metrics.deterministic_answers + 1,
            "polar_row_consensus": result.metrics.polar_row_consensus + int(consensus_answer is not None),
        })
        return result.model_copy(update={"answer": deterministic_answer, "metrics": metrics})
    if spec.structured_answer_contract:
        return _finalize(
            client,
            dataset,
            question,
            result,
            structured_answer_contract=True,
        )
    return _finalize(client, dataset, question, result)


def run_method(
    method: str,
    *,
    dataset: str,
    question: QuestionRecord,
    retriever: HybridRetriever,
    client: AgnesClient,
    config: AppConfig,
    seed: int,
    max_steps: int = 4,
    max_retrieval_calls: int = 4,
    frozen_plan: SlotPlan | None = None,
    sufficiency_calibrator: EvidenceSufficiencyCalibrator | None = None,
) -> ExecutionResult:
    try:
        spec = METHODS[method]
    except KeyError as exc:
        raise ValueError(f"unknown benchmark method: {method}") from exc
    if frozen_plan is not None and spec.family != "slotrag":
        raise ValueError(f"frozen plans are only supported by SlotRAG-family methods: {method}")
    if spec.evidence_sufficiency and sufficiency_calibrator is None:
        raise ValueError(f"{method} requires a frozen development calibrator")
    runners: dict[str, Callable[[], ExecutionResult]] = {
        "hybrid": lambda: _run_hybrid(dataset, question, retriever, client),
        "planrag": lambda: _run_planrag(dataset, question, retriever, client),
        "ircot": lambda: _run_ircot(dataset, question, retriever, client),
        "react": lambda: _run_react(dataset, question, retriever, client),
        "graphrag": lambda: _run_graphrag(dataset, question, client),
        "slotrag": lambda: _run_slotrag(
            spec,
            dataset,
            question,
            retriever,
            client,
            config,
            seed,
            max_steps,
            max_retrieval_calls,
            frozen_plan=frozen_plan,
            sufficiency_calibrator=sufficiency_calibrator,
        ),
    }
    return _normalize_polar_answer(question.question, runners[spec.family]())
