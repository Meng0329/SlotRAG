"""Tests for the physical evidence bundle and per-path extraction."""

import pytest
from slotrag.evidence_bundle import (
    EvidenceBundle,
    EvidenceBundleExtractor,
    ExtractionOutcome,
    PerPathExtractor,
    RetrievalPath,
    UnionExtractor,
)
from slotrag.models import BindingRow, MaterializationTrace, Passage, RetrievalResult, RunMetrics, Slot
from slotrag.providers import ChatResult, ToolCall, Usage


# ── Fake LLM clients ─────────────────────────────────────────────────────────


class DictExtractionClient:
    """Returns pre-configured rows from an ordered list of responses."""

    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.calls = []

    def complete(self, *_args, **_kwargs):
        rows = self.responses.pop(0)
        self.calls.append(rows)
        return ChatResult(
            tool_calls=[ToolCall(name="emit_evidence_rows", arguments={"rows": rows})],
            usage=Usage(prompt_tokens=10, completion_tokens=5),
        )

    @staticmethod
    def require_tool(result, name):
        return next(call.arguments for call in result.tool_calls if call.name == name)


class FakeExtractionClient:
    """Returns empty/unexpected rows to test error handling."""

    def complete(self, *_args, **_kwargs):
        return ChatResult(
            tool_calls=[ToolCall(name="emit_evidence_rows", arguments={"rows": []})],
            usage=Usage(prompt_tokens=2, completion_tokens=1),
        )

    @staticmethod
    def require_tool(result, name):
        return next(call.arguments for call in result.tool_calls if call.name == name)


# ── minimial extraction_tool stand-in ────────────────────────────────────────


def _fake_extraction_tool(
    slot, source_ids=None, *, typed_extraction_contracts=False,
    typed_surface_form=False,
    requested_fields=None, role_projected=False, known_bindings=None,
):
    return {"type": "function", "function": {"name": "emit_evidence_rows"}}


# ── Helpers ──────────────────────────────────────────────────────────────────


_SLOT = Slot(id="S1", predicate="Founded", arguments=["?company", "?founder"])

_MESSAGES = (
    {"role": "system", "content": "Extract facts from passages."},
    {"role": "user", "content": ""},
)

_PASSAGE_A = Passage(id="pA", doc_id="dA", text="Ada founded Acme Corp.")
_PASSAGE_B = Passage(id="pB", doc_id="dB", text="Brett founded Beta Inc.")
_PASSAGE_C = Passage(id="pC", doc_id="dC", text="Ada also founded Gamma Co.")


# ── Tests ────────────────────────────────────────────────────────────────────


class TestEvidenceBundle:
    """EvidenceBundle data model."""

    def test_bundle_builds_from_paths(self):
        path = RetrievalPath(
            query="Founded ?company ?founder",
            query_variant="slot",
            sparse_access_mode="body",
            results=[],
        )
        bundle = EvidenceBundle(
            slot_id="S1",
            predicate="Founded",
            paths=[path],
            fused_results=[],
            access_path_policy="heterogeneous_dual_bundle",
        )
        assert bundle.slot_id == "S1"
        assert len(bundle.paths) == 1
        assert bundle.paths[0].sparse_access_mode == "body"

    def test_bundle_default_policy_is_single(self):
        bundle = EvidenceBundle(slot_id="S1", predicate="Founded")
        assert bundle.access_path_policy == "single"


class TestUnionExtractor:
    """Union extractor — control adapter matching current behaviour."""

    def test_empty_bundle_returns_empty(self):
        client = FakeExtractionClient()
        extractor = UnionExtractor()
        bundle = EvidenceBundle(slot_id="S1", predicate="Founded", fused_results=[])

        outcome = extractor.extract(
            client, bundle, _SLOT,
            requested_fields={"company", "founder"},
            boolean_fields=set(),
            role_projected=False,
            protected_output_values=set(),
            effective_bindings={},
            extraction_tool_fn=_fake_extraction_tool,
            messages_template=_MESSAGES,
            typed_surface_form=False,
        )
        assert outcome.rows == []
        assert len(outcome.traces) == 1
        assert outcome.traces[0].slot_id == "S1"

    def test_union_extracts_rows_from_fused_results(self):
        client = DictExtractionClient([
            [{"company": "Acme Corp", "founder": "Ada", "source_id": "pA"}],
        ])
        extractor = UnionExtractor()
        bundle = EvidenceBundle(
            slot_id="S1",
            predicate="Founded",
            fused_results=[
                RetrievalResult(passage=_PASSAGE_A, score=0.9),
            ],
            paths=[],
        )

        outcome = extractor.extract(
            client, bundle, _SLOT,
            requested_fields={"company", "founder"},
            boolean_fields=set(),
            role_projected=False,
            protected_output_values=set(),
            effective_bindings={},
            extraction_tool_fn=_fake_extraction_tool,
            messages_template=_MESSAGES,
            typed_surface_form=False,
        )
        assert len(outcome.rows) == 1
        bindings, source_id = outcome.rows[0]
        assert bindings == {"company": "Acme Corp", "founder": "Ada"}
        assert source_id == "pA"
        assert outcome.metrics.llm_calls == 1

    def test_union_skips_incomplete_rows(self):
        """Rows missing required fields should be filtered out."""
        client = DictExtractionClient([
            [{"company": "Acme Corp", "source_id": "pA"}],  # missing founder
        ])
        extractor = UnionExtractor()
        bundle = EvidenceBundle(
            slot_id="S1",
            predicate="Founded",
            fused_results=[RetrievalResult(passage=_PASSAGE_A, score=0.9)],
            paths=[],
        )

        outcome = extractor.extract(
            client, bundle, _SLOT,
            requested_fields={"company", "founder"},
            boolean_fields=set(),
            role_projected=False,
            protected_output_values=set(),
            effective_bindings={},
            extraction_tool_fn=_fake_extraction_tool,
            messages_template=_MESSAGES,
            typed_surface_form=False,
        )
        assert outcome.rows == []


class TestPerPathExtractor:
    """Per-path extractor — treatment adapter with path-level isolation."""

    def test_empty_paths_returns_empty(self):
        client = FakeExtractionClient()
        extractor = PerPathExtractor()
        bundle = EvidenceBundle(slot_id="S1", predicate="Founded", paths=[], fused_results=[])

        outcome = extractor.extract(
            client, bundle, _SLOT,
            requested_fields={"company", "founder"},
            boolean_fields=set(),
            role_projected=False,
            protected_output_values=set(),
            effective_bindings={},
            extraction_tool_fn=_fake_extraction_tool,
            messages_template=_MESSAGES,
            typed_surface_form=False,
        )
        assert outcome.rows == []

    def test_each_path_extracted_independently(self):
        """Each path gets its own LLM call and produces its own rows."""
        path_a = RetrievalPath(
            query="Founded ?company ?founder",
            query_variant="slot",
            sparse_access_mode="body",
            results=[RetrievalResult(passage=_PASSAGE_A, score=0.9)],
        )
        path_b = RetrievalPath(
            query="Who founded what?",
            query_variant="question_plus_lexical_slot",
            sparse_access_mode="configured",
            results=[RetrievalResult(passage=_PASSAGE_B, score=0.8)],
        )

        client = DictExtractionClient([
            [{"company": "Acme Corp", "founder": "Ada", "source_id": "pA"}],
            [{"company": "Beta Inc", "founder": "Brett", "source_id": "pB"}],
        ])
        extractor = PerPathExtractor()
        bundle = EvidenceBundle(slot_id="S1", predicate="Founded", paths=[path_a, path_b], fused_results=[])

        outcome = extractor.extract(
            client, bundle, _SLOT,
            requested_fields={"company", "founder"},
            boolean_fields=set(),
            role_projected=False,
            protected_output_values=set(),
            effective_bindings={},
            extraction_tool_fn=_fake_extraction_tool,
            messages_template=_MESSAGES,
            typed_surface_form=False,
        )
        assert len(client.calls) == 2  # two LLM calls
        assert len(outcome.rows) == 2

        result_dicts = [dict(sorted(r[0].items())) for r in outcome.rows]
        assert {"company": "Acme Corp", "founder": "Ada"} in result_dicts
        assert {"company": "Beta Inc", "founder": "Brett"} in result_dicts

    def test_union_loses_binding_per_path_recovers(self):
        """Simulate scenario: Path A + B fused together → LLM only outputs A."""
        path_a = RetrievalPath(
            query="Founded ?company ?founder",
            query_variant="slot",
            sparse_access_mode="body",
            results=[RetrievalResult(passage=_PASSAGE_A, score=0.9)],
        )
        path_b = RetrievalPath(
            query="Who founded what?",
            query_variant="question_plus_lexical_slot",
            sparse_access_mode="configured",
            results=[RetrievalResult(passage=_PASSAGE_B, score=0.8)],
        )
        fused = [
            RetrievalResult(passage=_PASSAGE_A, score=0.9),
            RetrievalResult(passage=_PASSAGE_B, score=0.8),
        ]

        # Union sees both passages but only returns one binding
        union_client = DictExtractionClient([
            [{"company": "Acme Corp", "founder": "Ada", "source_id": "pA"}],
        ])
        union_extractor = UnionExtractor()
        union_bundle = EvidenceBundle(
            slot_id="S1", predicate="Founded",
            paths=[], fused_results=fused,
        )
        union_outcome = union_extractor.extract(
            union_client, union_bundle, _SLOT,
            requested_fields={"company", "founder"},
            boolean_fields=set(),
            role_projected=False,
            protected_output_values=set(),
            effective_bindings={},
            extraction_tool_fn=_fake_extraction_tool,
            messages_template=_MESSAGES,
            typed_surface_form=False,
        )

        # PerPath extracts each path independently
        pp_client = DictExtractionClient([
            [{"company": "Acme Corp", "founder": "Ada", "source_id": "pA"}],
            [{"company": "Beta Inc", "founder": "Brett", "source_id": "pB"}],
        ])
        pp_extractor = PerPathExtractor()
        pp_bundle = EvidenceBundle(
            slot_id="S1", predicate="Founded",
            paths=[path_a, path_b], fused_results=[],
        )
        pp_outcome = pp_extractor.extract(
            pp_client, pp_bundle, _SLOT,
            requested_fields={"company", "founder"},
            boolean_fields=set(),
            role_projected=False,
            protected_output_values=set(),
            effective_bindings={},
            extraction_tool_fn=_fake_extraction_tool,
            messages_template=_MESSAGES,
            typed_surface_form=False,
        )

        # Union loses Beta Inc (only 1 row, only Ada)
        assert len(union_outcome.rows) == 1

        # PerPath recovers both (2 rows, Ada + Brett)
        assert len(pp_outcome.rows) == 2

    def test_deduplicates_across_paths(self):
        """Same (source_id, bindings) from two paths → one row after merge."""
        path_a = RetrievalPath(
            query="Founded ?company ?founder",
            query_variant="slot",
            sparse_access_mode="body",
            results=[RetrievalResult(passage=_PASSAGE_A, score=0.9)],
        )
        # Path B returns the *same* binding from the *same* source
        path_b = RetrievalPath(
            query="Who founded Acme?",
            query_variant="question_plus_slot",
            sparse_access_mode="configured",
            results=[RetrievalResult(passage=_PASSAGE_A, score=0.85)],
        )

        client = DictExtractionClient([
            [{"company": "Acme Corp", "founder": "Ada", "source_id": "pA"}],
            [{"company": "Acme Corp", "founder": "Ada", "source_id": "pA"}],  # same
        ])
        extractor = PerPathExtractor()
        bundle = EvidenceBundle(slot_id="S1", predicate="Founded", paths=[path_a, path_b], fused_results=[])

        outcome = extractor.extract(
            client, bundle, _SLOT,
            requested_fields={"company", "founder"},
            boolean_fields=set(),
            role_projected=False,
            protected_output_values=set(),
            effective_bindings={},
            extraction_tool_fn=_fake_extraction_tool,
            messages_template=_MESSAGES,
            typed_surface_form=False,
        )
        assert len(outcome.rows) == 1  # dedup to 1

    def test_preserves_different_span_same_binding(self):
        """Same bindings from different source spans → both kept."""
        passage_c = Passage(id="pC", doc_id="dC", text="Ada founded Acme Corp (different source).")
        path_a = RetrievalPath(
            query="Founded ?company ?founder",
            query_variant="slot",
            results=[RetrievalResult(passage=_PASSAGE_A, score=0.9)],
        )
        path_b = RetrievalPath(
            query="Find Ada",
            query_variant="question_plus_slot",
            results=[RetrievalResult(passage=passage_c, score=0.7)],
        )

        client = DictExtractionClient([
            [{"company": "Acme Corp", "founder": "Ada", "source_id": "pA"}],
            [{"company": "Acme Corp", "founder": "Ada", "source_id": "pC"}],
        ])
        extractor = PerPathExtractor()
        bundle = EvidenceBundle(slot_id="S1", predicate="Founded", paths=[path_a, path_b], fused_results=[])

        outcome = extractor.extract(
            client, bundle, _SLOT,
            requested_fields={"company", "founder"},
            boolean_fields=set(),
            role_projected=False,
            protected_output_values=set(),
            effective_bindings={},
            extraction_tool_fn=_fake_extraction_tool,
            messages_template=_MESSAGES,
            typed_surface_form=False,
        )
        # Same bindings but different source_id → kept (not exact duplicate)
        assert len(outcome.rows) == 2

    def test_records_per_path_traces(self):
        """Each path generates its own MaterializationTrace."""
        path_a = RetrievalPath(
            query="Founded ?company ?founder",
            query_variant="slot",
            results=[],
        )
        path_b = RetrievalPath(
            query="Who founded?",
            query_variant="question_plus_slot",
            results=[],
        )

        client = FakeExtractionClient()
        extractor = PerPathExtractor()
        bundle = EvidenceBundle(slot_id="S1", predicate="Founded", paths=[path_a, path_b], fused_results=[])

        outcome = extractor.extract(
            client, bundle, _SLOT,
            requested_fields={"company", "founder"},
            boolean_fields=set(),
            role_projected=False,
            protected_output_values=set(),
            effective_bindings={},
            extraction_tool_fn=_fake_extraction_tool,
            messages_template=_MESSAGES,
            typed_surface_form=False,
        )
        assert len(outcome.traces) == 2
        for trace in outcome.traces:
            assert trace.access_path_policy == "per_path_extraction"
            assert trace.slot_id == "S1"


class TestMaterializerIntegration:
    """Integration tests: SlotMaterializer dispatches to evidence bundle extractor."""

    def test_materializer_union_extractor_produces_rows(self):
        """SlotMaterializer with UnionExtractor produces correct BindingRows."""
        from slotrag.planner import SlotMaterializer

        class BatchRetriever:
            def search_batch(self, queries, *, top_k=None, sparse_access_modes=None):
                return [
                    [RetrievalResult(passage=_PASSAGE_A, score=0.9)],
                    [RetrievalResult(passage=_PASSAGE_A, score=0.85)],
                ]

        client = DictExtractionClient([
            [{"company": "Acme Corp", "founder": "Ada", "source_id": "pA"}],
        ])
        materializer = SlotMaterializer(
            client, BatchRetriever(),
            max_passages=5,
            question_context="Who founded what?",
            dual_access_bundle=True,
            evidence_bundle_extractor=UnionExtractor(),
        )

        rows, metrics = materializer.materialize(_SLOT, {})
        assert len(rows) == 1
        assert rows[0].bindings == {"company": "Acme Corp", "founder": "Ada"}
        assert rows[0].source_id == "pA"
        assert metrics.extraction_bundles == 1

    def test_materializer_per_path_extractor_produces_rows(self):
        """SlotMaterializer with PerPathExtractor produces correct BindingRows."""
        from slotrag.planner import SlotMaterializer

        class BatchRetriever:
            def search_batch(self, queries, *, top_k=None, sparse_access_modes=None):
                return [
                    [RetrievalResult(passage=_PASSAGE_A, score=0.9)],
                    [RetrievalResult(passage=_PASSAGE_B, score=0.8)],
                ]

        client = DictExtractionClient([
            [{"company": "Acme Corp", "founder": "Ada", "source_id": "pA"}],
            [{"company": "Beta Inc", "founder": "Brett", "source_id": "pB"}],
        ])
        materializer = SlotMaterializer(
            client, BatchRetriever(),
            max_passages=5,
            question_context="Who founded what?",
            dual_access_bundle=True,
            evidence_bundle_extractor=PerPathExtractor(),
        )

        rows, metrics = materializer.materialize(_SLOT, {})
        # PerPathExtractor preserves bindings from both paths
        assert len(rows) >= 1
        assert metrics.extraction_bundles == 1
        assert metrics.per_path_extractions == 1
