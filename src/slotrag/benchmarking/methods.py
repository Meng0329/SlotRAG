from __future__ import annotations

import json
import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, Field

from ..config import AppConfig
from ..generation import generate_answer_response
from ..models import EvidenceRecord, ExecutionResult, QuestionRecord, RetrievalResult, RunMetrics
from ..planner import AdaptiveExecutor, ExecutionOptions, SlotCompiler, SlotMaterializer
from ..providers import AgnesClient, ChatResult
from ..retrieval import HybridRetriever, tokenize


@dataclass(frozen=True)
class MethodSpec:
    key: str
    family: str
    strategy: str = "adaptive"
    options: ExecutionOptions = field(default_factory=ExecutionOptions)
    description: str = ""


MAIN_METHODS = ["slotrag", "hybrid", "ircot", "react", "planrag", "srag", "graphrag"]
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
]


METHODS: dict[str, MethodSpec] = {
    "slotrag": MethodSpec("slotrag", "slotrag"),
    "hybrid": MethodSpec("hybrid", "hybrid", description="whole-question hybrid retrieval"),
    "ircot": MethodSpec("ircot", "ircot", description="interleaved reasoning and retrieval, adapted"),
    "react": MethodSpec("react", "react", description="structured search/finish loop, adapted"),
    "planrag": MethodSpec("planrag", "planrag", description="static plan then retrieval, adapted"),
    "srag": MethodSpec(
        "srag",
        "slotrag",
        strategy="question",
        options=ExecutionOptions(runtime_replan=False, incremental_join=False, binding_propagation=False),
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
    additive_lists = {"intermediate_binding_sizes", "slot_selectivity_errors", "provider_request_ids", "plan_validation_errors"}
    max_fields = {"peak_rss_mb", "index_bytes"}
    nullable = {"planner_regret"}
    data = result.model_dump()
    for value in values:
        current = value.model_dump()
        for key, item in current.items():
            if key in additive_lists:
                data[key].extend(item)
            elif key in max_fields:
                data[key] = max(data[key], item)
            elif key in nullable:
                if item is not None:
                    data[key] = item
            elif isinstance(item, (int, float)):
                data[key] += item
    return RunMetrics.model_validate(data)


def _chat_metrics(response: ChatResult) -> RunMetrics:
    return RunMetrics(
        llm_calls=1,
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
        provider_latency_ms=response.latency_ms,
        latency_ms=response.latency_ms,
        provider_request_ids=[response.request_id] if response.request_id else [],
    )


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
                passages_processed=len(ranked),
            ),
        ),
        status="ok" if ranked else "empty",
    )


def _answer_kind(dataset: str) -> str:
    if dataset == "strategyqa":
        return "boolean"
    if dataset == "drop":
        return "number"
    return "short"


def _finalize(client: AgnesClient, dataset: str, question: QuestionRecord, result: ExecutionResult) -> ExecutionResult:
    if result.status not in {"ok", "empty"} or not result.evidence:
        return result
    answer, response = generate_answer_response(client, question.question, result, answer_kind=_answer_kind(dataset))
    metrics = merge_metrics(result.metrics, _chat_metrics(response))
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
    metrics = merge_metrics(_chat_metrics(response), RunMetrics(retrieval_calls=len(plan.queries)))
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
        metrics = merge_metrics(metrics, _chat_metrics(response))
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
        metrics = merge_metrics(metrics, _chat_metrics(response))
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
            "passages_processed": len(question.passages),
        })
    })
    return _finalize(client, dataset, question, result)


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
) -> ExecutionResult:
    plan, compiler_metrics = SlotCompiler(client).compile(question.question, answer_kind=_answer_kind(dataset))
    if len(plan.slots) > max_steps:
        return ExecutionResult(
            status="budget_exceeded",
            error=f"plan contains {len(plan.slots)} slots; budget allows {max_steps}",
            plan=plan,
            metrics=compiler_metrics,
        )
    executor = AdaptiveExecutor(
        SlotMaterializer(client, retriever, max_passages=config.execution.materialization_top_k),
        default_slot_cost=config.execution.default_slot_cost,
        unbound_argument_cost=config.execution.unbound_argument_cost,
        max_replans=min(config.execution.max_replans, max_steps),
        max_retrieval_calls=max_retrieval_calls,
        max_binding_contexts=config.execution.max_binding_contexts,
        random_seed=seed,
        options=spec.options,
    )
    result = executor.execute(plan, strategy=spec.strategy)
    result = result.model_copy(update={"plan": plan, "metrics": merge_metrics(result.metrics, compiler_metrics)})
    if spec.options.typed_operators and plan.operators and result.status == "ok" and len(result.rows) == 1 and len(plan.outputs) == 1:
        output = plan.outputs[0].lstrip("?")
        value = result.rows[0].get(output, "").strip()
        if value:
            return result.model_copy(update={"answer": value})
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
) -> ExecutionResult:
    try:
        spec = METHODS[method]
    except KeyError as exc:
        raise ValueError(f"unknown benchmark method: {method}") from exc
    runners: dict[str, Callable[[], ExecutionResult]] = {
        "hybrid": lambda: _run_hybrid(dataset, question, retriever, client),
        "planrag": lambda: _run_planrag(dataset, question, retriever, client),
        "ircot": lambda: _run_ircot(dataset, question, retriever, client),
        "react": lambda: _run_react(dataset, question, retriever, client),
        "graphrag": lambda: _run_graphrag(dataset, question, client),
        "slotrag": lambda: _run_slotrag(spec, dataset, question, retriever, client, config, seed, max_steps, max_retrieval_calls),
    }
    return runners[spec.family]()
