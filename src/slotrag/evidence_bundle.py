"""Physical evidence bundle abstraction for multi-path extraction.

Provides the ``EvidenceBundle`` data container that preserves per-path retrieval
provenance, and two ``EvidenceBundleExtractor`` adapters:

* ``UnionExtractor`` (control) — the current single-call extraction over all
  fused results, included so the bundle seam can be verified without behaviour
  change.
* ``PerPathExtractor`` (treatment) — independent extraction per retrieval path
  followed by cross-path deduplication, designed to recover bindings that the
  single-call path discards when one retrieval path dominates the fused list.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Literal

from .models import (
    BindingRow,
    MaterializationTrace,
    RetrievalResult,
    RunMetrics,
    Slot,
    StrictModel,
)
from .query_optimization import QueryVariant
from .retrieval import SparseAccessMode


# ── Data models ──────────────────────────────────────────────────────────────


class RetrievalPath(StrictModel):
    """One logical retrieval path within an ``EvidenceBundle``."""

    query: str
    query_variant: QueryVariant
    sparse_access_mode: SparseAccessMode = "configured"
    results: list[RetrievalResult] = []


class EvidenceBundle(StrictModel):
    """A collection of retrieval paths and their fused output for one slot.

    ``paths`` preserves the per-path results so that path-aware extractors
    can operate on each path independently.  ``fused_results`` holds the
    merged/reranked final list used by the existing single-pass extraction.
    """

    slot_id: str
    predicate: str
    binding_context: dict[str, str] = {}
    paths: list[RetrievalPath] = []
    fused_results: list[RetrievalResult] = []
    access_path_policy: Literal[
        "single",
        "dual_bundle",
        "heterogeneous_dual_bundle",
        "per_path_extraction",
    ] = "single"
    physical_retrieval_batches: int = 1
    candidate_pool_size: int = 0
    candidate_overlap: int = 0


class ExtractionOutcome(StrictModel):
    """Raw extraction result before post-processing and binding-row creation."""

    rows: list[tuple[dict[str, str], str]] = []
    """Each tuple is ``(bindings_dict, source_id)``."""

    metrics: RunMetrics = RunMetrics()
    """Per-extraction metrics accumulated across all paths."""

    traces: list[MaterializationTrace] = []
    """Materialization traces — one per path when using per-path extraction."""


# ── Extractor interface ──────────────────────────────────────────────────────


class EvidenceBundleExtractor(ABC):
    """Abstract adapter for extracting structured rows from an evidence bundle.

    Implementations call the LLM with ``emit_evidence_rows``, parse the result,
    and return the raw rows **without** SlotRAG-specific post-processing
    (grounding checks, anchor protection, semantic-role filtering).  The caller
    is responsible for that common post-processing step.
    """

    def __init__(self, enable_thinking: bool = False) -> None:
        self._enable_thinking = enable_thinking

    @abstractmethod
    def extract(
        self,
        client: Any,
        bundle: EvidenceBundle,
        slot: Slot,
        requested_fields: set[str],
        boolean_fields: set[str],
        role_projected: bool,
        protected_output_values: set[str],
        effective_bindings: dict[str, str],
        extraction_tool_fn: Callable[..., dict[str, Any]],
        messages_template: tuple[dict[str, Any], dict[str, Any]],
    ) -> ExtractionOutcome:
        ...


# ── Control: union extraction (existing behaviour) ──────────────────────────


class UnionExtractor(EvidenceBundleExtractor):
    """Single-call extraction over the fused passage list.

    This matches the current ``SlotMaterializer.materialize()`` behaviour:
    all retrieved passages are merged into one ``passage_payload``, and a
    single ``emit_evidence_rows`` call produces all rows.
    """

    def extract(
        self,
        client: Any,
        bundle: EvidenceBundle,
        slot: Slot,
        requested_fields: set[str],
        boolean_fields: set[str],
        role_projected: bool,
        protected_output_values: set[str],
        effective_bindings: dict[str, str],
        extraction_tool_fn: Callable[..., dict[str, Any]],
        messages_template: tuple[dict[str, Any], dict[str, Any]],
    ) -> ExtractionOutcome:
        # Build the passage payload from fused results
        by_source: dict[str, RetrievalResult] = {}
        passage_payload: list[dict[str, str]] = []
        for result in bundle.fused_results:
            sid = result.passage.id
            by_source[sid] = result
            passage_payload.append({"source_id": sid, "text": result.passage.text})

        if not passage_payload:
            return ExtractionOutcome(
                traces=[MaterializationTrace(
                    slot_id=bundle.slot_id,
                    predicate=bundle.predicate,
                    binding_context=dict(bundle.binding_context),
                    access_path_policy=bundle.access_path_policy,
                )],
            )

        source_ids = list(by_source)
        tool = extraction_tool_fn(
            slot,
            source_ids,
            typed_extraction_contracts=bool(boolean_fields),
            requested_fields=requested_fields,
            role_projected=role_projected,
            known_bindings=effective_bindings or None,
        )

        system_msg, user_msg = messages_template
        user_msg = {**user_msg}
        user_msg["content"] = (
            f"Relation: {slot.predicate}\n"
            f"Slot query: {bundle.paths[0].query if bundle.paths else ''}\n"
            f"Known bindings: {repr(effective_bindings)}\n"
            f"Passages: {repr(passage_payload)}"
        )

        response = client.complete(
            [system_msg, user_msg],
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": "emit_evidence_rows"}},
            temperature=0.0,
            enable_thinking=self._enable_thinking,
        )

        args = client.require_tool(response, "emit_evidence_rows")
        if isinstance(args, str):
            import json as _json
            args = _json.loads(args)
        extracted = args.get("rows", [])

        rows: list[tuple[dict[str, str], str]] = []
        for row in extracted:
            source_id = row.get("source_id", "")
            normalized = {
                key.lstrip("?"): value.strip()
                for key, value in row.items()
                if key.lstrip("?") in requested_fields
            }
            if set(normalized) == requested_fields and all(normalized.values()) and source_id:
                rows.append((normalized, source_id))

        prompt_tokens = getattr(response.usage, "prompt_tokens", 0)
        completion_tokens = getattr(response.usage, "completion_tokens", 0)

        metrics = RunMetrics(
            llm_calls=1,
            extraction_llm_calls=1,
            extraction_prompt_tokens=prompt_tokens,
            extraction_completion_tokens=completion_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

        trace = MaterializationTrace(
            slot_id=bundle.slot_id,
            predicate=bundle.predicate,
            binding_context=dict(bundle.binding_context),
            searches=[],
            selected_source_ids=list(by_source),
            access_path_policy=bundle.access_path_policy,
            physical_retrieval_batches=bundle.physical_retrieval_batches,
            candidate_pool_size=bundle.candidate_pool_size,
            candidate_overlap=bundle.candidate_overlap,
            extracted_rows=[],
        )

        return ExtractionOutcome(rows=rows, metrics=metrics, traces=[trace])


# ── Treatment: per-path extraction ──────────────────────────────────────────


class PerPathExtractor(EvidenceBundleExtractor):
    """Independent extraction per retrieval path, then cross-path merge.

    Each path in ``bundle.paths`` gets its own ``emit_evidence_rows`` call.
    Results are merged by ``(source_id, normalized bindings)`` deduplication.
    This recovers bindings that would be lost when one path dominates the
    fused list seen by a single extraction call.

    Telemetry records per-path row counts and the before/after dedup counts.
    """

    def extract(
        self,
        client: Any,
        bundle: EvidenceBundle,
        slot: Slot,
        requested_fields: set[str],
        boolean_fields: set[str],
        role_projected: bool,
        protected_output_values: set[str],
        effective_bindings: dict[str, str],
        extraction_tool_fn: Callable[..., dict[str, Any]],
        messages_template: tuple[dict[str, Any], dict[str, Any]],
    ) -> ExtractionOutcome:
        all_rows: list[tuple[dict[str, str], str]] = []  # (bindings, source_id)
        aggregated_metrics = RunMetrics()
        traces: list[MaterializationTrace] = []

        for path_index, path in enumerate(bundle.paths):
            if not path.results:
                trace = MaterializationTrace(
                    slot_id=bundle.slot_id,
                    predicate=bundle.predicate,
                    binding_context=dict(bundle.binding_context),
                    access_path_policy="per_path_extraction",
                )
                traces.append(trace)
                continue

            by_source: dict[str, RetrievalResult] = {}
            passage_payload: list[dict[str, str]] = []
            for result in path.results:
                sid = result.passage.id
                by_source[sid] = result
                passage_payload.append({"source_id": sid, "text": result.passage.text})

            source_ids = list(by_source)
            tool = extraction_tool_fn(
                slot,
                source_ids,
                typed_extraction_contracts=bool(boolean_fields),
                requested_fields=requested_fields,
                role_projected=role_projected,
                known_bindings=effective_bindings or None,
            )

            system_msg, user_msg = messages_template
            user_msg = {**user_msg}
            user_msg["content"] = (
                f"Relation: {slot.predicate}\n"
                f"Path query: {path.query}\n"
                f"Query variant: {path.query_variant}\n"
                f"Sparse access mode: {path.sparse_access_mode}\n"
                f"Known bindings: {repr(effective_bindings)}\n"
                f"Passages: {repr(passage_payload)}"
            )

            response = client.complete(
                [system_msg, user_msg],
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": "emit_evidence_rows"}},
                temperature=0.0,
                enable_thinking=self._enable_thinking,
            )

            args = client.require_tool(response, "emit_evidence_rows")
            if isinstance(args, str):
                import json as _json
                args = _json.loads(args)
            extracted = args.get("rows", [])

            prompt_tokens = getattr(response.usage, "prompt_tokens", 0)
            completion_tokens = getattr(response.usage, "completion_tokens", 0)

            aggregated_metrics = aggregated_metrics.model_copy(update={
                "llm_calls": aggregated_metrics.llm_calls + 1,
                "extraction_llm_calls": aggregated_metrics.extraction_llm_calls + 1,
                "extraction_prompt_tokens": aggregated_metrics.extraction_prompt_tokens + prompt_tokens,
                "extraction_completion_tokens": aggregated_metrics.extraction_completion_tokens + completion_tokens,
                "prompt_tokens": aggregated_metrics.prompt_tokens + prompt_tokens,
                "completion_tokens": aggregated_metrics.completion_tokens + completion_tokens,
            })

            path_rows: list[tuple[dict[str, str], str]] = []
            for row in extracted:
                source_id = row.get("source_id", "")
                normalized = {
                    key.lstrip("?"): value.strip()
                    for key, value in row.items()
                    if key.lstrip("?") in requested_fields
                }
                if set(normalized) == requested_fields and all(normalized.values()) and source_id:
                    path_rows.append((normalized, source_id))

            all_rows.extend(path_rows)

            path_source_ids = [r.passage.id for r in path.results]
            trace = MaterializationTrace(
                slot_id=bundle.slot_id,
                predicate=bundle.predicate,
                binding_context=dict(bundle.binding_context),
                searches=[],
                selected_source_ids=path_source_ids,
                access_path_policy="per_path_extraction",
                physical_retrieval_batches=1,
                candidate_pool_size=len(passage_payload),
                candidate_overlap=0,
                extracted_rows=[],
            )
            traces.append(trace)

        # Cross-path deduplication by (source_id, sorted(bindings))
        before_dedup = len(all_rows)
        seen: set[tuple[str, frozenset[tuple[str, str]]]] = set()
        deduped: list[tuple[dict[str, str], str]] = []
        for bindings, source_id in all_rows:
            key = (source_id, frozenset(sorted(bindings.items())))
            if key not in seen:
                seen.add(key)
                deduped.append((bindings, source_id))

        aggregated_metrics = aggregated_metrics.model_copy(update={
            "extracted_rows_before_dedup": aggregated_metrics.extracted_rows_before_dedup + before_dedup,
            "extracted_rows_after_dedup": aggregated_metrics.extracted_rows_after_dedup + len(deduped),
        })

        return ExtractionOutcome(rows=deduped, metrics=aggregated_metrics, traces=traces)
