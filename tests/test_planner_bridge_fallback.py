"""H-014: bridge-entity re-retrieval fallback for join-chain repair.

The bridge fallback fires only when (a) the option is enabled, (b) the current
slot has a non-empty propagated binding context, (c) the slot materialization
returned no rows, and (d) a question context is available. On trigger, an LLM
call infers candidate values for the slot's missing variable and the slot is
re-materialized with those candidates as anchors.
"""

import pytest
from pydantic import ValidationError

from slotrag.models import BindingRow, Passage, RetrievalResult, RunMetrics, Slot, SlotPlan
from slotrag.planner import AdaptiveExecutor, ExecutionOptions, SlotCompiler, SlotMaterializer
from slotrag.providers import ChatResult, ToolCall, Usage


class _FakeClient:
    """Returns a bridge tool response; records every complete() call."""

    def __init__(self, bridge_entities):
        self.bridge_entities = list(bridge_entities)
        self.calls = 0
        self.tool_names = []

    def complete(self, messages, **kwargs):
        self.calls += 1
        tool_name = kwargs["tool_choice"]["function"]["name"]
        self.tool_names.append(tool_name)
        if tool_name == "emit_bridge_entities":
            arguments = {"bridge_entities": self.bridge_entities}
        else:
            arguments = {"rows": []}
        return ChatResult(
            request_id=f"r{self.calls}",
            tool_calls=[ToolCall(name=tool_name, arguments=arguments)],
            usage=Usage(prompt_tokens=3, completion_tokens=1),
        )

    @staticmethod
    def require_tool(result, name):
        return next(call.arguments for call in result.tool_calls if call.name == name)


class _BridgeMaterializer:
    """S1 is empty on the first call (triggering the fallback), then returns
    a row once the bridge entity is bound as the S1 person value."""

    def __init__(self, question_context="Who founded OpenAI?"):
        self.question_context = question_context
        self.calls = []
        self.client = _FakeClient(["Dell Henderson"])
        self.last_evidence = []
        self.last_materialization_traces = []
        self.last_retrieval_results = []

    def materialize(self, slot, bindings, *, retrieval_strategy='hybrid'):
        self.calls.append((slot.id, dict(bindings)))
        if slot.id == "S1":
            if bindings.get("person"):
                row = BindingRow(
                    slot_id="S1", bindings={"person": bindings["person"]},
                    source_id="p1", source_span="Dell Henderson founded OpenAI", confidence=1,
                )
                return [row], RunMetrics(documents_accessed=1, passages_processed=1, extraction_llm_calls=1)
            return [], RunMetrics(documents_accessed=1, passages_processed=1, extraction_llm_calls=1)
        person = bindings.get("person", "")
        if not person:
            return [], RunMetrics()
        return [BindingRow(
            slot_id="S2", bindings={"person": person, "company": "OpenAI"},
            source_id=f"{person}-p2", source_span=f"{person} founded OpenAI", confidence=1,
        )], RunMetrics(documents_accessed=1, passages_processed=1, extraction_llm_calls=1)

    def materialize_many(self, slot, contexts, *, retrieval_strategy='hybrid'):
        rows = []
        metrics = RunMetrics()
        for context in contexts or [{}]:
            current, current_metrics = self.materialize(slot, context)
            rows.extend(current)
            metrics = metrics.model_copy(update={
                "documents_accessed": metrics.documents_accessed + current_metrics.documents_accessed,
                "passages_processed": metrics.passages_processed + current_metrics.passages_processed,
                "extraction_llm_calls": metrics.extraction_llm_calls + current_metrics.extraction_llm_calls,
            })
        return rows, metrics


def _plan():
    return SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "Founder", "arguments": ["?person", "OpenAI"]},
            {"id": "S2", "predicate": "Founded", "arguments": ["?person", "?company"]},
        ],
        "joins": [["S1.person", "S2.person"]],
        "outputs": ["?person", "?company"],
    })


def test_bridge_fallback_off_leaves_empty_status_untouched():
    materializer = _BridgeMaterializer()
    executor = AdaptiveExecutor(materializer, options=ExecutionOptions(bridge_entity_fallback=False))
    result = executor.execute(_plan())
    assert result.status == "empty"
    assert result.rows == []
    assert materializer.client.calls == 0  # no LLM bridge call
    assert result.metrics.bridge_fallbacks == 0


def test_bridge_fallback_on_repairs_join_chain():
    materializer = _BridgeMaterializer()
    executor = AdaptiveExecutor(materializer, options=ExecutionOptions(bridge_entity_fallback=True))
    result = executor.execute(_plan())
    assert result.status == "ok"
    assert result.rows == [{"person": "Dell Henderson", "company": "OpenAI"}]
    assert result.metrics.bridge_fallbacks == 1
    assert result.metrics.bridge_successes == 1
    assert result.metrics.bridge_llm_calls == 1
    assert result.metrics.bridge_candidates == 1
    # The bridge entity became the S1 person binding
    assert ("S1", {"person": "Dell Henderson"}) in materializer.calls


def test_bridge_fallback_with_empty_candidates_still_empty():
    materializer = _BridgeMaterializer()
    materializer.client = _FakeClient([])
    executor = AdaptiveExecutor(materializer, options=ExecutionOptions(bridge_entity_fallback=True))
    result = executor.execute(_plan())
    assert result.status == "empty"
    assert result.metrics.bridge_fallbacks == 1
    assert result.metrics.bridge_successes == 0
    assert result.metrics.bridge_candidates == 0


def test_bridge_fallback_requires_question_context():
    materializer = _BridgeMaterializer(question_context=None)
    executor = AdaptiveExecutor(materializer, options=ExecutionOptions(bridge_entity_fallback=True))
    result = executor.execute(_plan())
    # No question context → fallback does not fire
    assert result.status == "empty"
    assert materializer.client.calls == 0
    assert result.metrics.bridge_fallbacks == 0


class _JoinRepairMaterializer(_BridgeMaterializer):
    """S1 returns person Ada; S2 extracts rows with a *different* person
    (simulating the 2wiki join-chain break: S2's intermediate entity extraction
    disagrees with S1's anchor). The bridge retry infers the correct person so
    the join on `person` succeeds."""

    def materialize(self, slot, bindings, *, retrieval_strategy='hybrid'):
        self.calls.append((slot.id, dict(bindings)))
        if slot.id == "S1":
            return [BindingRow(
                slot_id="S1", bindings={"person": "Ada"},
                source_id="p1", source_span="Ada founded X", confidence=1,
            )], RunMetrics(documents_accessed=1, passages_processed=1, extraction_llm_calls=1)
        # S2: after the bridge retry (client called emit_bridge_entities), return
        # the matching person Ada. Otherwise return the wrong person Grace so the
        # join on `person` yields nothing on the first attempt.
        if any("emit_bridge_entities" in tool for tool in getattr(self.client, "tool_names", [])):
            return [BindingRow(
                slot_id="S2", bindings={"person": "Ada", "company": "X"},
                source_id="p2", source_span="Ada founded X", confidence=1,
            )], RunMetrics(documents_accessed=1, passages_processed=1, extraction_llm_calls=1)
        return [BindingRow(
            slot_id="S2", bindings={"person": "Grace", "company": "Y"},
            source_id="p2", source_span="Grace led Y", confidence=1,
        )], RunMetrics(documents_accessed=1, passages_processed=1, extraction_llm_calls=1)

    def materialize_many(self, slot, contexts, *, retrieval_strategy='hybrid'):
        rows = []; metrics = RunMetrics()
        for context in contexts or [{}]:
            current, current_metrics = self.materialize(slot, context)
            rows.extend(current)
            metrics = metrics.model_copy(update={
                "documents_accessed": metrics.documents_accessed + current_metrics.documents_accessed,
                "passages_processed": metrics.passages_processed + current_metrics.passages_processed,
                "extraction_llm_calls": metrics.extraction_llm_calls + current_metrics.extraction_llm_calls,
            })
        return rows, metrics


def test_bridge_fallback_repairs_join_break():
    materializer = _JoinRepairMaterializer()
    executor = AdaptiveExecutor(materializer, options=ExecutionOptions(bridge_entity_fallback=True))
    result = executor.execute(_plan())
    assert result.status == "ok"
    assert result.rows == [{"person": "Ada", "company": "X"}]
    assert result.metrics.bridge_fallbacks == 1
    assert result.metrics.bridge_successes == 1
