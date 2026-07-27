import pytest
from pydantic import ValidationError

from slotrag.models import BindingRow, Passage, RelationalOperator, RetrievalResult, RunMetrics, Slot, SlotPlan
from slotrag.action_policy import PhysicalActionPolicy
from slotrag.planner import (
    AdaptiveExecutor,
    ExecutionOptions,
    SlotCompiler,
    SlotMaterializer,
    apply_operators,
    direct_grounded_relation_anchor_values,
    extraction_tool,
    inject_query_grounded_anchor,
    query_grounded_anchor_values,
    substitute_grounded_entity_anchor_with_values,
)
from slotrag.providers import ChatResult, ToolCall, Usage
from slotrag.qo import compile_physical_plan, logical_plan_from_slot_plan
from slotrag.sufficiency import EvidenceSufficiencyCalibrator


class FakeMaterializer:
    def __init__(self):
        self.calls = []

    def materialize(self, slot, bindings):
        self.calls.append((slot.id, dict(bindings)))
        rows = {
            "S1": [BindingRow(slot_id="S1", bindings={"person": "Ada"}, source_id="p1", source_span="Ada founded X", confidence=1)],
            "S2": [BindingRow(slot_id="S2", bindings={"person": "Ada", "company": "X"}, source_id="p2", source_span="Ada founded X", confidence=1)],
        }[slot.id]
        return rows, RunMetrics(documents_accessed=1, passages_processed=1, extraction_llm_calls=1)


class MultiBindingMaterializer(FakeMaterializer):
    def materialize(self, slot, bindings):
        self.calls.append((slot.id, dict(bindings)))
        if slot.id == "S1":
            return [
                BindingRow(slot_id="S1", bindings={"person": "Ada"}, source_id="p1", source_span="Ada founded X", confidence=1),
                BindingRow(slot_id="S1", bindings={"person": "Grace"}, source_id="p3", source_span="Grace founded Y", confidence=1),
            ], RunMetrics(documents_accessed=2, passages_processed=2)
        person = bindings["person"]
        company = {"Ada": "X", "Grace": "Y"}[person]
        return [BindingRow(slot_id="S2", bindings={"person": person, "company": company}, source_id=f"{person}-p2", source_span=f"{person} founded {company}", confidence=1)], RunMetrics(documents_accessed=1, passages_processed=1)

    def materialize_many(self, slot, contexts):
        rows = []
        metrics = RunMetrics()
        for context in contexts:
            current, current_metrics = self.materialize(slot, context)
            rows.extend(current)
            metrics = metrics.model_copy(update={
                "documents_accessed": metrics.documents_accessed + current_metrics.documents_accessed,
                "passages_processed": metrics.passages_processed + current_metrics.passages_processed,
            })
        return rows, metrics


class FakeStructuredClient:
    def __init__(self, arguments):
        self.arguments = list(arguments)

    def complete(self, *_args, **_kwargs):
        arguments = self.arguments.pop(0)
        return ChatResult(
            request_id=f"r{len(self.arguments)}",
            tool_calls=[ToolCall(name="emit_slot_plan", arguments=arguments)],
            usage=Usage(prompt_tokens=2, completion_tokens=1),
        )

    @staticmethod
    def require_tool(result, name):
        return next(call.arguments for call in result.tool_calls if call.name == name)


class FakeExtractionClient:
    def complete(self, *_args, **_kwargs):
        return ChatResult(tool_calls=[ToolCall(name="emit_evidence_rows", arguments={"rows": [{"wrong": "value"}]})])

    @staticmethod
    def require_tool(result, name):
        return next(call.arguments for call in result.tool_calls if call.name == name)


class FakeRetriever:
    def search(self, _query):
        return [RetrievalResult(passage=Passage(id="p", text="Fact"), score=1.0)]


def test_materializer_dual_query_retrieval_merges_and_accounts_for_both_searches():
    class RecordingRetriever:
        def __init__(self):
            self.queries = []

        def search(self, query):
            self.queries.append(query)
            if query.startswith("Who founded Alpha?"):
                return [
                    RetrievalResult(passage=Passage(id="shared", doc_id="d1", text="Shared fact"), score=0.8),
                    RetrievalResult(passage=Passage(id="question", doc_id="d2", text="Question fact"), score=0.7),
                ]
            return [
                RetrievalResult(passage=Passage(id="slot", doc_id="d3", text="Slot fact"), score=0.9),
                RetrievalResult(passage=Passage(id="shared", doc_id="d1", text="Shared fact"), score=0.8),
            ]

    retriever = RecordingRetriever()
    materializer = SlotMaterializer(
        SequenceExtractionClient([[{"founder": "Ada", "source_id": "shared"}]]),
        retriever,
        question_context="Who founded Alpha?",
        dual_query_retrieval=True,
    )

    rows, metrics = materializer.materialize(
        Slot(id="S1", predicate="Founded", arguments=["Alpha", "?founder"]),
        {},
    )

    assert retriever.queries == ["Founded Alpha ?founder", "Who founded Alpha? Founded Alpha ?founder"]
    assert [row.bindings for row in rows] == [{"founder": "Ada"}]
    assert metrics.retrieval_calls == 2
    assert materializer.accessed_passage_ids == {"slot", "shared", "question"}
    assert [item.source_id for item in materializer.last_evidence].count("shared") == 1


def test_materializer_exposes_ranked_retrieval_trace_without_passage_payloads():
    class RankedRetriever:
        def search(self, query):
            assert query == "Founded Alpha ?founder"
            return [
                RetrievalResult(
                    passage=Passage(id="p1", doc_id="d1", text="Ada founded Alpha."),
                    score=0.91,
                    bm25_score=4.2,
                    dense_score=0.82,
                    rerank_score=0.94,
                ),
                RetrievalResult(
                    passage=Passage(id="p2", doc_id="d2", text="An unrelated fact."),
                    score=0.21,
                    bm25_score=1.1,
                    dense_score=0.18,
                    rerank_score=0.20,
                ),
            ]

    materializer = SlotMaterializer(
        SequenceExtractionClient([[{"founder": "Ada", "source_id": "p1"}]]),
        RankedRetriever(),
    )

    rows, _metrics = materializer.materialize(
        Slot(id="S1", predicate="Founded", arguments=["Alpha", "?founder"]),
        {},
    )

    trace = materializer.last_materialization_traces[0]
    assert trace.slot_id == "S1"
    assert trace.predicate == "Founded"
    assert trace.binding_context == {}
    assert trace.retrieval_calls == 1
    assert trace.searches[0].query == "Founded Alpha ?founder"
    assert trace.searches[0].query_variant == "slot"
    assert trace.searches[0].candidates[0].model_dump() == {
        "rank": 1,
        "source_id": "p1",
        "doc_id": "d1",
        "score": 0.91,
        "bm25_score": 4.2,
        "dense_score": 0.82,
        "rerank_score": 0.94,
    }
    assert trace.selected_source_ids == ["p1", "p2"]
    assert [item.model_dump() for item in trace.extracted_rows] == [{
        "source_id": rows[0].source_id,
        "bindings": rows[0].bindings,
        "confidence": rows[0].confidence,
        "retrieval_score": rows[0].retrieval_score,
    }]


def test_executor_persists_materialization_trace_on_execution_result():
    class RankedRetriever:
        def search(self, _query):
            return [RetrievalResult(
                passage=Passage(id="p1", doc_id="d1", text="Ada founded Alpha."),
                score=0.91,
                bm25_score=4.2,
                dense_score=0.82,
                rerank_score=0.94,
            )]

    materializer = SlotMaterializer(
        SequenceExtractionClient([[{"founder": "Ada", "source_id": "p1"}]]),
        RankedRetriever(),
    )
    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "Founded", "arguments": ["Alpha", "?founder"]}],
        "outputs": ["?founder"],
    })

    result = AdaptiveExecutor(materializer).execute(plan)

    assert result.status == "ok"
    assert len(result.slot_traces) == 1
    trace = result.slot_traces[0]
    assert trace.step == 0
    assert trace.slot_id == "S1"
    assert trace.binding_contexts == [{}]
    assert trace.materializations[0].searches[0].candidates[0].rerank_score == 0.94
    assert trace.extracted_row_count == 1
    assert trace.rows_after_join == 1


def test_executor_records_calibrated_sufficiency_and_action_candidates():
    class RankedRetriever:
        def search(self, _query):
            return [RetrievalResult(
                passage=Passage(id="p1", doc_id="d1", text="Ada founded Alpha."),
                score=0.91,
                bm25_score=4.2,
                dense_score=0.82,
                rerank_score=0.94,
            )]

    materializer = SlotMaterializer(
        SequenceExtractionClient([[{"founder": "Ada", "source_id": "p1"}]]),
        RankedRetriever(),
    )
    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "Founded", "arguments": ["Alpha", "?founder"]}],
        "outputs": ["?founder"],
    })
    calibrator = EvidenceSufficiencyCalibrator(
        intercept=2.0,
        sufficient_threshold=0.5,
        partial_threshold=0.3,
    )

    result = AdaptiveExecutor(
        materializer,
        action_policy=PhysicalActionPolicy(),
        sufficiency_calibrator=calibrator,
    ).execute(plan)

    trace = result.slot_traces[0]
    assert trace.sufficiency_model == "development_logistic"
    assert trace.sufficiency_status == "SUFFICIENT"
    assert trace.sufficiency_probability == pytest.approx(0.880797, abs=1e-6)
    assert trace.sufficiency_features["top1_score"] == 0.94
    assert trace.action_selected == "ANSWER"
    assert "EXPAND_TOPK" in {item.action for item in trace.action_candidates}
    assert result.metrics.evidence_sufficiency_decisions == 1


def test_materializer_adaptive_dual_query_skips_question_query_for_bound_slots():
    class RecordingRetriever:
        def __init__(self):
            self.queries = []

        def search(self, query):
            self.queries.append(query)
            return [RetrievalResult(passage=Passage(id="p1", text="Ada founded Alpha"), score=1.0)]

    retriever = RecordingRetriever()
    materializer = SlotMaterializer(
        SequenceExtractionClient([[{"company": "Alpha", "source_id": "p1"}]]),
        retriever,
        question_context="Who founded Alpha?",
        dual_query_retrieval=True,
        dual_query_unbound_only=True,
    )

    _rows, metrics = materializer.materialize(
        Slot(id="S2", predicate="Founded", arguments=["Ada", "?company"]),
        {"person": "Ada"},
    )

    assert retriever.queries == ["Founded Ada ?company"]
    assert metrics.retrieval_calls == 1
    assert metrics.dual_query_expansions == 0
    assert metrics.dual_query_skips == 1


def test_materializer_confidence_gate_skips_question_query_when_slot_result_is_strong():
    class RecordingRetriever:
        def __init__(self):
            self.queries = []

        def search(self, query):
            self.queries.append(query)
            return [RetrievalResult(passage=Passage(id="p1", text="Ada founded Alpha"), score=0.9)]

    retriever = RecordingRetriever()
    materializer = SlotMaterializer(
        SequenceExtractionClient([[{"company": "Alpha", "source_id": "p1"}]]),
        retriever,
        question_context="Who founded Alpha?",
        dual_query_retrieval=True,
        dual_query_confidence_threshold=0.75,
    )

    _rows, metrics = materializer.materialize(
        Slot(id="S1", predicate="Founded", arguments=["Ada", "?company"]),
        {},
    )

    assert retriever.queries == ["Founded Ada ?company"]
    assert metrics.retrieval_calls == 1
    assert metrics.dual_query_expansions == 0
    assert metrics.dual_query_confidence_skips == 1


def test_materializer_confidence_gate_expands_when_slot_result_is_weak():
    class RecordingRetriever:
        def __init__(self):
            self.queries = []

        def search(self, query):
            self.queries.append(query)
            return [RetrievalResult(passage=Passage(id="p1", text="Ada founded Alpha"), score=0.2)]

    retriever = RecordingRetriever()
    materializer = SlotMaterializer(
        SequenceExtractionClient([[{"company": "Alpha", "source_id": "p1"}]]),
        retriever,
        question_context="Who founded Alpha?",
        dual_query_retrieval=True,
        dual_query_confidence_threshold=0.75,
    )

    _rows, metrics = materializer.materialize(
        Slot(id="S1", predicate="Founded", arguments=["Ada", "?company"]),
        {},
    )

    assert retriever.queries == ["Founded Ada ?company", "Who founded Alpha? Founded Ada ?company"]
    assert metrics.retrieval_calls == 2
    assert metrics.dual_query_expansions == 1
    assert metrics.dual_query_confidence_skips == 0


def test_materializer_evidence_guard_falls_back_when_question_results_are_weaker_and_disjoint():
    class RecordingRetriever:
        def __init__(self):
            self.queries = []

        def search(self, query):
            self.queries.append(query)
            if query.startswith("Who founded Alpha?"):
                return [RetrievalResult(passage=Passage(id="question", text="Unrelated fact"), score=0.1)]
            return [RetrievalResult(passage=Passage(id="slot", text="Weak but relevant fact"), score=0.2)]

    retriever = RecordingRetriever()
    materializer = SlotMaterializer(
        SequenceExtractionClient([[{"company": "Alpha", "source_id": "slot"}]]),
        retriever,
        question_context="Who founded Alpha?",
        dual_query_retrieval=True,
        dual_query_confidence_threshold=0.75,
        dual_query_evidence_guard=True,
    )

    _rows, metrics = materializer.materialize(
        Slot(id="S1", predicate="Founded", arguments=["Ada", "?company"]),
        {},
    )

    assert retriever.queries == ["Founded Ada ?company", "Who founded Alpha? Founded Ada ?company"]
    assert [item.source_id for item in materializer.last_evidence] == ["slot"]
    assert metrics.dual_query_expansions == 1
    assert metrics.dual_query_guard_fallbacks == 1


def test_materializer_relaxed_evidence_guard_falls_back_when_results_overlap_but_question_is_weaker():
    class RecordingRetriever:
        def __init__(self):
            self.queries = []

        def search(self, query):
            self.queries.append(query)
            if query.startswith("Who founded Alpha?"):
                return [
                    RetrievalResult(passage=Passage(id="shared", text="Relevant fact"), score=0.2),
                    RetrievalResult(passage=Passage(id="question", text="Unrelated fact"), score=0.1),
                ]
            return [
                RetrievalResult(passage=Passage(id="shared", text="Relevant fact"), score=0.9),
                RetrievalResult(passage=Passage(id="slot", text="Another relevant fact"), score=0.8),
            ]

    retriever = RecordingRetriever()
    materializer = SlotMaterializer(
        SequenceExtractionClient([[{"company": "Alpha", "source_id": "shared"}]]),
        retriever,
        question_context="Who founded Alpha?",
        dual_query_retrieval=True,
        dual_query_confidence_threshold=0.95,
        dual_query_evidence_guard=True,
        dual_query_evidence_guard_disjoint_only=False,
    )

    _rows, metrics = materializer.materialize(
        Slot(id="S1", predicate="Founded", arguments=["Ada", "?company"]),
        {},
    )

    assert retriever.queries == ["Founded Ada ?company", "Who founded Alpha? Founded Ada ?company"]
    assert [item.source_id for item in materializer.last_evidence] == ["shared", "slot"]
    assert metrics.dual_query_guard_checks == 1
    assert metrics.dual_query_guard_fallbacks == 1


class SequenceExtractionClient:
    def __init__(self, rows):
        self.rows = list(rows)

    def complete(self, *_args, **_kwargs):
        rows = self.rows.pop(0)
        return ChatResult(tool_calls=[ToolCall(name="emit_evidence_rows", arguments={"rows": rows})])

    @staticmethod
    def require_tool(result, name):
        return next(call.arguments for call in result.tool_calls if call.name == name)


class StaticRetriever:
    def __init__(self, passage):
        self.passage = passage

    def search(self, _query):
        return [RetrievalResult(passage=self.passage, score=1.0)]


def test_slot_variable_types_must_reference_exposed_variables():
    with pytest.raises(ValidationError, match="variable_types keys must be slot variables"):
        Slot(
            id="S1",
            predicate="EvidenceAnsweringQuestion",
            arguments=["?answer"],
            variable_types={"other": "boolean"},
        )


def test_boolean_variable_type_constrains_extraction_tool_domain():
    typed = extraction_tool(Slot(
        id="S1",
        predicate="EvidenceAnsweringQuestion",
        arguments=["?answer"],
        variable_types={"answer": "boolean"},
    ), typed_extraction_contracts=True)
    untyped = extraction_tool(Slot(
        id="S1",
        predicate="EvidenceAnsweringQuestion",
        arguments=["?answer"],
    ))

    typed_answer = typed["function"]["parameters"]["properties"]["rows"]["items"]["properties"]["answer"]
    untyped_answer = untyped["function"]["parameters"]["properties"]["rows"]["items"]["properties"]["answer"]

    assert typed_answer == {"type": "string", "enum": ["yes", "no", "unknown"]}
    assert untyped_answer == {"type": "string"}


def test_role_projected_tool_requests_only_unknown_fields_and_describes_argument_role():
    slot = Slot(
        id="S3",
        predicate="MotherOf",
        arguments=["?grandmother", "?mother"],
    )

    tool = extraction_tool(
        slot,
        ["Amice de Clare#0"],
        requested_fields={"grandmother"},
        role_projected=True,
    )

    row_schema = tool["function"]["parameters"]["properties"]["rows"]["items"]
    assert set(row_schema["properties"]) == {"grandmother", "source_id"}
    assert set(row_schema["required"]) == {"grandmother", "source_id"}
    description = row_schema["properties"]["grandmother"]["description"]
    assert "argument 1" in description
    assert "MotherOf(?grandmother, ?mother)" in description


def test_role_projected_tool_can_render_known_bindings_in_ordered_signature():
    slot = Slot(
        id="S2",
        predicate="MotherOf",
        arguments=["?mother", "?grandmother"],
    )

    tool = extraction_tool(
        slot,
        ["Amice de Clare#0"],
        requested_fields={"grandmother"},
        role_projected=True,
        known_bindings={"mother": "Amice de Clare"},
    )

    row_schema = tool["function"]["parameters"]["properties"]["rows"]["items"]
    description = row_schema["properties"]["grandmother"]["description"]
    assert 'MotherOf("Amice de Clare", ?grandmother)' in description
    assert 'known argument 1 is fixed as "Amice de Clare"' in description


def test_anchor_substitution_exposes_exact_grounded_value_for_downstream_role_protection():
    source = SlotPlan.model_validate({
        "slots": [
            {
                "id": "S1",
                "predicate": "Person",
                "arguments": ["Baldwin De Redvers", "7Th Earl Of Devon", "?baldwin"],
            },
            {"id": "S2", "predicate": "MotherOf", "arguments": ["?mother", "?baldwin"]},
            {"id": "S3", "predicate": "MotherOf", "arguments": ["?grandmother", "?mother"]},
        ],
        "joins": [
            ["S1.baldwin", "S2.baldwin"],
            ["S2.mother", "S3.mother"],
        ],
        "outputs": ["?grandmother"],
    })

    effective, values = substitute_grounded_entity_anchor_with_values(
        source,
        "Who is Baldwin De Redvers, 7Th Earl Of Devon's maternal grandmother?",
    )

    assert values == ("Baldwin De Redvers, 7Th Earl Of Devon",)
    assert effective.slots[0].arguments == [
        "?mother",
        "Baldwin De Redvers, 7Th Earl Of Devon",
    ]


def test_direct_grounded_relation_anchor_detects_compact_multihop_root():
    plan = SlotPlan.model_validate({
        "slots": [
            {
                "id": "S1",
                "predicate": "MotherOf",
                "arguments": ["Baldwin De Redvers, 7Th Earl Of Devon", "?mother"],
            },
            {"id": "S2", "predicate": "MotherOf", "arguments": ["?mother", "?grandmother"]},
        ],
        "joins": [["S1.mother", "S2.mother"]],
        "outputs": ["?grandmother"],
    })

    values = direct_grounded_relation_anchor_values(
        plan,
        "Who is Baldwin De Redvers, 7Th Earl Of Devon's maternal grandmother?",
    )

    assert values == ("Baldwin De Redvers, 7Th Earl Of Devon",)


def test_direct_grounded_relation_anchor_accepts_single_token_proper_name():
    plan = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "ComposerOf", "arguments": ["Ayya", "?composer"]},
            {"id": "S2", "predicate": "FatherOf", "arguments": ["?composer", "?father"]},
        ],
        "joins": [["S1.composer", "S2.composer"]],
        "outputs": ["?father"],
    })

    assert direct_grounded_relation_anchor_values(
        plan,
        "Who is the father of the composer of Ayya?",
    ) == ("Ayya",)


@pytest.mark.parametrize(
    ("plan_payload", "question"),
    [
        (
            {
                "slots": [{"id": "S1", "predicate": "DirectorOf", "arguments": ["Film Alpha", "?director"]}],
                "outputs": ["?director"],
            },
            "Who directed Film Alpha?",
        ),
        (
            {
                "slots": [
                    {"id": "S1", "predicate": "DirectorOf", "arguments": ["Film Alpha", "?director"]},
                    {"id": "S2", "predicate": "BornIn", "arguments": ["?director", "?place"]},
                ],
                "joins": [["S1.director", "S2.director"]],
                "outputs": ["?director"],
            },
            "Who directed Film Alpha and where were they born?",
        ),
        (
            {
                "slots": [
                    {"id": "S1", "predicate": "DirectorOf", "arguments": ["Film Beta", "?director"]},
                    {"id": "S2", "predicate": "BornIn", "arguments": ["?director", "?place"]},
                ],
                "joins": [["S1.director", "S2.director"]],
                "outputs": ["?place"],
            },
            "Where was the director of Film Alpha born?",
        ),
        (
            {
                "slots": [
                    {"id": "S1", "predicate": "RelatedTo", "arguments": ["film", "?person"]},
                    {"id": "S2", "predicate": "BornIn", "arguments": ["?person", "?place"]},
                ],
                "joins": [["S1.person", "S2.person"]],
                "outputs": ["?place"],
            },
            "Where was the person related to the film born?",
        ),
    ],
)
def test_direct_grounded_relation_anchor_rejects_unsafe_scope(plan_payload, question):
    assert direct_grounded_relation_anchor_values(
        SlotPlan.model_validate(plan_payload),
        question,
    ) == ()


def test_direct_grounded_relation_anchor_rejects_join_cycle():
    plan = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "StartsAt", "arguments": ["Alpha", "?x", "?z"]},
            {"id": "S2", "predicate": "ContinuesTo", "arguments": ["?x", "?y"]},
            {"id": "S3", "predicate": "ReturnsTo", "arguments": ["?y", "?z", "?answer"]},
        ],
        "joins": [
            ["S1.x", "S2.x"],
            ["S2.y", "S3.y"],
            ["S3.z", "S1.z"],
        ],
        "outputs": ["?answer"],
    })

    assert direct_grounded_relation_anchor_values(
        plan,
        "What answer follows the cycle starting at Alpha?",
    ) == ()


class ComparisonMaterializer:
    def __init__(self):
        self.calls = []

    def materialize(self, slot, bindings):
        self.calls.append((slot.id, dict(bindings)))
        rows = {
            "S1": BindingRow(
                slot_id="S1",
                bindings={"d1": "Sidney Lumet"},
                source_id="Find Me Guilty#0",
                source_span="Find Me Guilty was directed by Sidney Lumet.",
                confidence=1,
            ),
            "S2": BindingRow(
                slot_id="S2",
                bindings={"d2": "Terry O. Morse"},
                source_id="Tear Gas Squad#0",
                source_span="Tear Gas Squad was directed by Terry O. Morse.",
                confidence=1,
            ),
            "S3": BindingRow(
                slot_id="S3",
                bindings={"d1": "Sidney Lumet", "bd1": "June 25, 1924"},
                source_id="Sidney Lumet#0",
                source_span="Sidney Lumet was born on June 25, 1924.",
                confidence=1,
            ),
            "S4": BindingRow(
                slot_id="S4",
                bindings={"d2": "Terry O. Morse", "bd2": "January 30, 1906"},
                source_id="Terry O. Morse#0",
                source_span="Terry O. Morse was born on January 30, 1906.",
                confidence=1,
            ),
        }
        return [rows[slot.id]], RunMetrics(documents_accessed=1, passages_processed=1)


def comparison_plan():
    return SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "DirectorOf", "arguments": ["Find Me Guilty", "?d1"]},
            {"id": "S2", "predicate": "DirectorOf", "arguments": ["Tear Gas Squad", "?d2"]},
            {"id": "S3", "predicate": "BirthDate", "arguments": ["?d1", "?bd1"]},
            {"id": "S4", "predicate": "BirthDate", "arguments": ["?d2", "?bd2"]},
        ],
        "joins": [["S1.d1", "S3.d1"], ["S2.d2", "S4.d2"]],
        "operators": [{
            "id": "O1",
            "kind": "field_argmin",
            "fields": ["bd1", "bd2"],
            "labels": ["Find Me Guilty", "Tear Gas Squad"],
            "output": "answer",
        }],
        "outputs": ["?answer"],
    })


def test_adaptive_executor_joins_and_propagates_bindings():
    materializer = FakeMaterializer()
    plan = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "Founder", "arguments": ["?person", "OpenAI"]},
            {"id": "S2", "predicate": "Founded", "arguments": ["?person", "?company"]},
        ],
        "joins": [["S1.person", "S2.person"]],
        "outputs": ["?person", "?company"],
    })
    result = AdaptiveExecutor(materializer).execute(plan)
    assert result.status == "ok"
    assert result.rows == [{"person": "Ada", "company": "X"}]
    assert result.order == ["S1", "S2"]
    assert materializer.calls[1][1] == {"person": "Ada"}
    assert result.metrics.extraction_llm_calls == 2


def test_adaptive_executor_honors_physical_plan_order_and_records_application():
    materializer = FakeMaterializer()
    plan = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "Founder", "arguments": ["?person", "OpenAI"], "estimated_cardinality": 10, "estimated_cost": 2},
            {"id": "S2", "predicate": "Founded", "arguments": ["?person", "?company"], "estimated_cardinality": 1, "estimated_cost": 1},
        ],
        "joins": [["S1.person", "S2.person"]],
        "outputs": ["?person", "?company"],
    })
    physical = compile_physical_plan(logical_plan_from_slot_plan(plan))

    result = AdaptiveExecutor(materializer).execute(plan, physical_plan=physical)

    assert physical.slot_execution_order == ["S1", "S2"]
    assert result.status == "ok"
    assert result.order == ["S1", "S2"]
    assert result.metrics.physical_plan_applied == 1
    assert result.metrics.physical_plan_order_mismatches == 0


def test_adaptive_executor_rejects_physical_plan_order_mismatch():
    plan = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "Founder", "arguments": ["?person", "OpenAI"]},
            {"id": "S2", "predicate": "Founded", "arguments": ["?person", "?company"]},
        ],
        "joins": [["S1.person", "S2.person"]],
        "outputs": ["?person", "?company"],
    })
    physical = compile_physical_plan(logical_plan_from_slot_plan(plan)).model_copy(update={
        "slot_execution_order": ["S1", "S1"],
    })

    result = AdaptiveExecutor(FakeMaterializer()).execute(plan, physical_plan=physical)

    assert result.status == "failed"
    assert result.metrics.physical_plan_order_mismatches == 1
    assert result.error == "physical plan slot order does not match logical plan"


def test_frontier_safe_selection_prevents_transitive_variable_join_failure():
    class HubJoinMaterializer:
        rows = {
            "S1": {"physicist1": "Eugen von Lommel", "physicist2": "Johannes Stark"},
            "S2": {"physicist2": "Johannes Stark"},
            "S3": {"physicist2": "Johannes Stark"},
            "S4": {"physicist1": "Eugen von Lommel"},
            "S5": {"physicist1": "Eugen von Lommel", "equation": "Lommel differential equation"},
        }

        def materialize(self, slot, _bindings):
            return [BindingRow(
                slot_id=slot.id,
                bindings=self.rows[slot.id],
                source_id=f"{slot.id}-source",
                source_span=f"Evidence for {slot.id}",
                confidence=1,
            )], RunMetrics(documents_accessed=1, passages_processed=1)

    plan = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "doctoralAdvisor", "arguments": ["?physicist1", "?physicist2"]},
            {"id": "S2", "predicate": "identified", "arguments": ["?physicist2", "Stark effect"]},
            {"id": "S3", "predicate": "nationality", "arguments": ["?physicist2", "German"]},
            {"id": "S4", "predicate": "nationality", "arguments": ["?physicist1", "German"]},
            {"id": "S5", "predicate": "developed", "arguments": ["?physicist1", "?equation"]},
        ],
        "joins": [
            ["S1.physicist1", "S4.physicist1"],
            ["S1.physicist2", "S2.physicist2"],
            ["S1.physicist2", "S3.physicist2"],
            ["S1.physicist1", "S5.physicist1"],
        ],
        "outputs": ["?equation"],
    })

    unsafe = AdaptiveExecutor(HubJoinMaterializer(), max_replans=5).execute(plan)
    guarded = AdaptiveExecutor(
        HubJoinMaterializer(),
        max_replans=5,
        options=ExecutionOptions(frontier_safe_selection=True),
    ).execute(plan)

    assert unsafe.status == "failed"
    assert unsafe.order == ["S2", "S3"]
    assert unsafe.error == "slot S3 has no join path"
    assert guarded.status == "ok"
    assert guarded.order == ["S2", "S1", "S3", "S4", "S5"]
    assert guarded.rows == [{"equation": "Lommel differential equation"}]
    assert guarded.metrics.frontier_guard_checks == 4
    assert guarded.metrics.frontier_guard_interventions == 1
    assert guarded.metrics.frontier_candidates_pruned == 1


def test_adaptive_executor_propagates_role_projection_metrics():
    class RoleProjectionMaterializer:
        def materialize(self, slot, _bindings):
            return [
                BindingRow(
                    slot_id=slot.id,
                    bindings={"answer": "Isabel Marshal"},
                    source_id="Amice de Clare#0",
                    source_span="Amice de Clare was the daughter of Isabel Marshal.",
                    confidence=1,
                )
            ], RunMetrics(
                role_projected_extraction_contracts=2,
                known_binding_fields_projected=1,
                protected_anchor_rejections=1,
                extraction_thinking_disabled=1,
                bound_role_signatures=1,
                extraction_length_finishes=1,
                semantic_role_type_contracts=1,
                semantic_role_type_rejections=1,
                semantic_role_type_abstentions=1,
                extraction_finish_reasons=["length"],
                extraction_validation_errors=["SchemaError: truncated tool call"],
            )

    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "MotherOf", "arguments": ["?answer", "Amice de Clare"]}],
        "joins": [],
        "outputs": ["?answer"],
    })

    result = AdaptiveExecutor(RoleProjectionMaterializer()).execute(plan)

    assert result.metrics.role_projected_extraction_contracts == 2
    assert result.metrics.known_binding_fields_projected == 1
    assert result.metrics.protected_anchor_rejections == 1
    assert result.metrics.extraction_thinking_disabled == 1
    assert result.metrics.bound_role_signatures == 1
    assert result.metrics.extraction_length_finishes == 1
    assert result.metrics.semantic_role_type_contracts == 1
    assert result.metrics.semantic_role_type_rejections == 1
    assert result.metrics.semantic_role_type_abstentions == 1
    assert result.metrics.extraction_finish_reasons == ["length"]
    assert result.metrics.extraction_validation_errors == ["SchemaError: truncated tool call"]


def test_executor_materializes_each_distinct_binding_context():
    materializer = MultiBindingMaterializer()
    plan = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "Founder", "arguments": ["?person", "OpenAI"]},
            {"id": "S2", "predicate": "Founded", "arguments": ["?person", "?company"]},
        ],
        "joins": [["S1.person", "S2.person"]],
        "outputs": ["?person", "?company"],
    })
    result = AdaptiveExecutor(materializer).execute(plan)
    assert result.rows == [{"person": "Ada", "company": "X"}, {"person": "Grace", "company": "Y"}]
    assert [call for call in materializer.calls if call[0] == "S2"] == [("S2", {"person": "Ada"}), ("S2", {"person": "Grace"})]


def test_executor_prunes_binding_fanout_to_runtime_budget():
    materializer = MultiBindingMaterializer()
    plan = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "Founder", "arguments": ["?person", "OpenAI"]},
            {"id": "S2", "predicate": "Founded", "arguments": ["?person", "?company"]},
        ],
        "joins": [["S1.person", "S2.person"]],
        "outputs": ["?person", "?company"],
    })
    result = AdaptiveExecutor(materializer, max_binding_contexts=1, max_retrieval_calls=2).execute(plan)
    assert result.rows == [{"person": "Ada", "company": "X"}]
    assert result.metrics.binding_contexts_pruned == 1


def test_executor_records_adaptive_beam_and_action_policy_telemetry():
    materializer = MultiBindingMaterializer()
    plan = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "Founder", "arguments": ["?person", "OpenAI"]},
            {"id": "S2", "predicate": "Founded", "arguments": ["?person", "?company"]},
        ],
        "joins": [["S1.person", "S2.person"]],
        "outputs": ["?person", "?company"],
    })

    result = AdaptiveExecutor(
        materializer,
        max_binding_contexts=2,
        max_retrieval_calls=2,
        adaptive_binding_beam=True,
        action_policy=PhysicalActionPolicy(),
    ).execute(plan)

    assert result.status == "ok"
    assert result.metrics.binding_beam_decisions == 1
    assert result.metrics.binding_beam_widths == [2]
    assert result.metrics.binding_candidates_considered == 2
    assert result.metrics.binding_candidates_pruned == 0
    assert result.metrics.physical_action_decisions == 2
    assert len(result.metrics.physical_action_selected) == 2
    assert result.metrics.physical_action_policy == "utility"


def test_executor_executes_one_bounded_topk_expansion_and_merges_rows():
    class ExpandableMaterializer:
        max_passages = 1

        def __init__(self):
            self.calls = []
            self.last_evidence = []
            self.last_materialization_traces = []
            self.last_retrieval_results = []

        def materialize(self, slot, bindings):
            self.calls.append(("initial", slot.id, dict(bindings), self.max_passages))
            return [], RunMetrics(retrieval_calls=1, passages_processed=1)

        def materialize_many_with_top_k(self, slot, contexts, *, top_k):
            self.calls.append(("expand", slot.id, list(contexts), top_k))
            return [
                BindingRow(
                    slot_id=slot.id,
                    bindings={"answer": "Ada"},
                    source_id="p2",
                    source_span="Ada is the answer.",
                    confidence=1.0,
                    retrieval_score=1.0,
                )
            ], RunMetrics(retrieval_calls=1, passages_processed=2)

    materializer = ExpandableMaterializer()
    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "Answer", "arguments": ["?answer"]}],
        "joins": [],
        "outputs": ["?answer"],
    })
    physical = compile_physical_plan(logical_plan_from_slot_plan(plan), top_k=2)

    result = AdaptiveExecutor(
        materializer,
        max_retrieval_calls=2,
        action_policy=PhysicalActionPolicy(),
    ).execute(plan, physical_plan=physical)

    assert result.status == "ok"
    assert result.rows == [{"answer": "Ada"}]
    assert [call[0] for call in materializer.calls] == ["initial", "expand"]
    assert result.metrics.retrieval_calls == 2
    assert result.metrics.physical_action_executions == 2
    assert result.metrics.physical_action_executed == ["EXPAND_TOPK", "ANSWER"]
    assert result.metrics.physical_action_rows_added == 1
    assert result.metrics.physical_action_extra_retrieval_calls == 1
    assert result.slot_traces[0].action_executed is True
    assert result.slot_traces[0].action_rows_added == 1
    assert result.slot_traces[0].action_top_k_before == 1
    assert result.slot_traces[0].action_top_k_after == 2


def test_executor_does_not_offer_topk_expansion_after_retrieval_budget_is_spent():
    class BudgetBoundMaterializer:
        max_passages = 1

        def __init__(self):
            self.calls = []
            self.last_evidence = []
            self.last_materialization_traces = []
            self.last_retrieval_results = []

        def materialize(self, slot, bindings):
            self.calls.append(("initial", slot.id, dict(bindings)))
            return [], RunMetrics(retrieval_calls=1, passages_processed=1)

        def materialize_many_with_top_k(self, slot, contexts, *, top_k):
            self.calls.append(("expand", slot.id, list(contexts), top_k))
            return [], RunMetrics(retrieval_calls=1, passages_processed=1)

    materializer = BudgetBoundMaterializer()
    plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "Answer", "arguments": ["?answer"]}],
        "joins": [],
        "outputs": ["?answer"],
    })
    physical = compile_physical_plan(logical_plan_from_slot_plan(plan), top_k=2)

    result = AdaptiveExecutor(
        materializer,
        max_retrieval_calls=1,
        action_policy=PhysicalActionPolicy(),
    ).execute(plan, physical_plan=physical)

    assert result.status == "empty"
    assert [call[0] for call in materializer.calls] == ["initial"]
    assert result.metrics.retrieval_calls == 1
    assert result.metrics.physical_action_extra_retrieval_calls == 0
    assert "EXPAND_TOPK" not in {
        candidate.action for candidate in result.slot_traces[0].action_candidates
    }


def test_slot_compiler_repairs_invalid_plan_once():
    invalid = {"slots": [{"id": "S1", "predicate": "Fact", "arguments": ["constant"]}], "joins": [], "outputs": ["?answer"]}
    valid = {"slots": [{"id": "S1", "predicate": "Fact", "arguments": ["?answer"]}], "joins": [], "outputs": ["?answer"]}
    plan, metrics = SlotCompiler(FakeStructuredClient([invalid, valid])).compile("What?")
    assert plan.outputs == ["?answer"]
    assert metrics.llm_calls == 2
    assert metrics.compilation_llm_calls == 2
    assert metrics.structured_output_failures == 1
    assert metrics.structured_output_repairs == 1
    assert metrics.plan_fallbacks == 0


def test_slot_compiler_repairs_unambiguous_join_key_locally():
    invalid_join = {
        "slots": [
            {"id": "S1", "predicate": "DirectedBy", "arguments": ["Film", "?director"]},
            {"id": "S2", "predicate": "BornIn", "arguments": ["?director", "?place"]},
        ],
        "joins": [{"left_slot": "S1", "left_field": "person", "right_slot": "S2", "right_field": "person"}],
        "outputs": ["?place"],
    }
    plan, metrics = SlotCompiler(FakeStructuredClient([invalid_join])).compile("Where was the director of Film born?")
    assert plan.joins[0].left_field == "director"
    assert plan.joins[0].right_field == "director"
    assert metrics.llm_calls == 1
    assert metrics.compilation_llm_calls == 1
    assert metrics.structured_output_failures == 1
    assert metrics.structured_output_repairs == 1
    assert metrics.local_plan_repairs == 1


def test_slot_compiler_uses_heuristic_plan_for_boolean_question():
    plan, metrics = SlotCompiler(FakeStructuredClient([])).compile(
        "Would Hannah Nixon be proud of Richard Nixon?", answer_kind="boolean"
    )
    assert plan.slots[0].predicate == "EvidenceAnsweringQuestion"
    assert plan.outputs == ["?answer"]
    assert metrics.heuristic_plans == 1
    assert metrics.llm_calls == 0


def test_slot_compiler_falls_back_after_three_invalid_plans():
    invalid = {"slots": [], "joins": [], "outputs": []}
    plan, metrics = SlotCompiler(FakeStructuredClient([invalid, invalid, invalid])).compile("What?")
    assert plan.slots[0].predicate == "EvidenceAnsweringQuestion"
    assert metrics.plan_fallbacks == 1
    assert metrics.llm_calls == 3


def test_slot_compiler_repairs_ungrounded_parametric_constant():
    leaked = {"slots": [{"id": "S1", "predicate": "Wrote", "arguments": ["Hidden Person", "?answer"]}], "joins": [], "outputs": ["?answer"]}
    grounded = {"slots": [{"id": "S1", "predicate": "SubjectOf", "arguments": ["Morecambe", "?answer"]}], "joins": [], "outputs": ["?answer"]}
    plan, metrics = SlotCompiler(FakeStructuredClient([leaked, grounded])).compile("Who is the subject of Morecambe?")
    assert plan.slots[0].arguments == ["Morecambe", "?answer"]
    assert metrics.structured_output_failures == 1


def test_slot_compiler_eliminates_redundant_grounded_anchor_slot():
    plan_payload = {
        "slots": [
            {"id": "S0", "predicate": "Person", "arguments": ["Michael Jordan", "?player"]},
            {"id": "S1", "predicate": "Rebounds", "arguments": ["?player", "?rebounds"]},
            {"id": "S2", "predicate": "Assists", "arguments": ["?player", "?assists"]},
        ],
        "joins": [
            ["S0.player", "S1.player"],
            ["S0.player", "S2.player"],
        ],
        "operators": [{"id": "O1", "kind": "arithmetic", "fields": ["rebounds", "assists"], "operation": "subtract", "output": "difference"}],
        "outputs": ["?difference"],
    }
    plan, _ = SlotCompiler(FakeStructuredClient([plan_payload])).compile(
        "How many more rebounds than assists did Michael Jordan average per game?"
    )
    assert [slot.id for slot in plan.slots] == ["S1", "S2"]
    assert all(slot.constraints["player"] == "Michael Jordan" for slot in plan.slots)
    assert [(join.left_slot, join.right_slot) for join in plan.joins] == [("S1", "S2")]


def test_grounded_entity_anchor_fold_propagates_question_constant_to_single_consumer():
    raw = SlotPlan.model_validate({
        "slots": [
            {
                "id": "S1",
                "predicate": "Person",
                "arguments": ["Baldwin De Redvers", "7Th Earl Of Devon", "?baldwin"],
            },
            {"id": "S2", "predicate": "MotherOf", "arguments": ["?mother", "?baldwin"]},
            {"id": "S3", "predicate": "MotherOf", "arguments": ["?grandmother", "?mother"]},
        ],
        "joins": [
            ["S1.baldwin", "S2.baldwin"],
            ["S2.mother", "S3.mother"],
        ],
        "outputs": ["?grandmother"],
    })

    folded, count = SlotCompiler.fold_grounded_entity_anchor(
        raw,
        "Who is Baldwin De Redvers, 7Th Earl Of Devon's maternal grandmother?",
    )

    assert count == 1
    assert [slot.id for slot in folded.slots] == ["S2", "S3"]
    assert folded.slots[0].constraints == {
        "baldwin": "Baldwin De Redvers, 7Th Earl Of Devon",
    }
    assert [(join.left_slot, join.right_slot, join.left_field) for join in folded.joins] == [
        ("S2", "S3", "mother"),
    ]


def test_grounded_entity_anchor_substitution_replaces_known_variable_argument():
    raw = SlotPlan.model_validate({
        "slots": [
            {
                "id": "S1",
                "predicate": "Person",
                "arguments": ["Baldwin De Redvers", "7Th Earl Of Devon", "?baldwin"],
            },
            {"id": "S2", "predicate": "MotherOf", "arguments": ["?mother", "?baldwin"]},
            {"id": "S3", "predicate": "MotherOf", "arguments": ["?grandmother", "?mother"]},
        ],
        "joins": [
            ["S1.baldwin", "S2.baldwin"],
            ["S2.mother", "S3.mother"],
        ],
        "outputs": ["?grandmother"],
    })

    substituted, count = SlotCompiler.substitute_grounded_entity_anchor(
        raw,
        "Who is Baldwin De Redvers, 7Th Earl Of Devon's maternal grandmother?",
    )

    assert count == 1
    assert [slot.id for slot in substituted.slots] == ["S2", "S3"]
    assert substituted.slots[0].arguments == [
        "?mother",
        "Baldwin De Redvers, 7Th Earl Of Devon",
    ]
    assert substituted.slots[0].constraints == {}
    assert set().union(*(slot.variables for slot in substituted.slots)) == {"mother", "grandmother"}


@pytest.mark.parametrize(
    ("predicate", "anchor_arguments", "outputs"),
    [
        ("DirectorOf", ["American Daughter", "?director"], ["?father"]),
        ("Person", ["Hallucinated Person", "?director"], ["?father"]),
        ("Person", ["American Daughter", "?director"], ["?director"]),
    ],
)
@pytest.mark.parametrize(
    "rewrite",
    [
        SlotCompiler.fold_grounded_entity_anchor,
        SlotCompiler.substitute_grounded_entity_anchor,
    ],
    ids=["constraint", "constant_argument"],
)
def test_grounded_entity_anchor_fold_rejects_relation_ungrounded_or_output_anchors(
    predicate,
    anchor_arguments,
    outputs,
    rewrite,
):
    raw = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": predicate, "arguments": anchor_arguments},
            {"id": "S2", "predicate": "FatherOf", "arguments": ["?director", "?father"]},
        ],
        "joins": [["S1.director", "S2.director"]],
        "outputs": outputs,
    })

    folded, count = rewrite(
        raw,
        "Who is the father of the director of film American Daughter?",
    )

    assert folded == raw
    assert count == 0


@pytest.mark.parametrize(
    "rewrite",
    [
        SlotCompiler.fold_grounded_entity_anchor,
        SlotCompiler.substitute_grounded_entity_anchor,
    ],
    ids=["constraint", "constant_argument"],
)
def test_grounded_entity_anchor_fold_rejects_multiple_consumers(rewrite):
    raw = SlotPlan.model_validate({
        "slots": [
            {"id": "S0", "predicate": "Person", "arguments": ["Michael Jordan", "?player"]},
            {"id": "S1", "predicate": "Rebounds", "arguments": ["?player", "?rebounds"]},
            {"id": "S2", "predicate": "Assists", "arguments": ["?player", "?assists"]},
        ],
        "joins": [
            ["S0.player", "S1.player"],
            ["S0.player", "S2.player"],
        ],
        "outputs": ["?rebounds", "?assists"],
    })

    folded, count = rewrite(
        raw,
        "How many rebounds and assists did Michael Jordan average?",
    )

    assert folded == raw
    assert count == 0


def test_slot_compiler_rewrites_date_difference_predicate_to_typed_operator():
    plan_payload = {
        "slots": [
            {"id": "S1", "predicate": "BeganTerm", "arguments": ["?person", "?startDate"]},
            {"id": "S2", "predicate": "SworeAllegiance", "arguments": ["?person", "?endDate"]},
            {
                "id": "S3",
                "predicate": "DateDiffInMonths",
                "arguments": ["?startDate", "?endDate", "?months"],
            },
        ],
        "joins": [
            ["S1.person", "S2.person"],
            ["S1.startDate", "S3.startDate"],
            ["S2.endDate", "S3.endDate"],
        ],
        "outputs": ["?months"],
        "operators": [],
    }
    plan, metrics = SlotCompiler(FakeStructuredClient([plan_payload])).compile(
        "What is the difference in months between when he began his term and when Zaimis swore allegiance?",
        answer_kind="number",
    )

    assert [slot.id for slot in plan.slots] == ["S1", "S2"]
    assert [(join.left_slot, join.right_slot) for join in plan.joins] == [("S1", "S2")]
    assert len(plan.operators) == 1
    assert plan.operators[0].operation == "date_diff_months"
    assert plan.operators[0].fields == ["startDate", "endDate"]
    assert plan.operators[0].output == "months"
    assert metrics.operator_rewrites == 1


def test_slot_compiler_rewrites_grounded_birthdate_comparison_to_field_extremum():
    plan_payload = {
        "slots": [
            {"id": "S1", "predicate": "DirectorOf", "arguments": ["Find Me Guilty", "?d1"]},
            {"id": "S2", "predicate": "DirectorOf", "arguments": ["Tear Gas Squad", "?d2"]},
            {"id": "S3", "predicate": "BirthDate", "arguments": ["?d1", "?bd1"]},
            {"id": "S4", "predicate": "BirthDate", "arguments": ["?d2", "?bd2"]},
            {"id": "S5", "predicate": "Compare", "arguments": ["?bd1", "?bd2"]},
        ],
        "joins": [
            ["S1.d1", "S3.d1"],
            ["S2.d2", "S4.d2"],
            ["S3.bd1", "S5.bd1"],
            ["S4.bd2", "S5.bd2"],
        ],
        "outputs": ["?bd1", "?bd2"],
        "operators": [],
    }
    question = "Which film has the director who was born first, Find Me Guilty or Tear Gas Squad?"

    plan, metrics = SlotCompiler(FakeStructuredClient([plan_payload])).compile(
        question,
        field_extremum_templates=False,
    )

    assert [slot.id for slot in plan.slots] == ["S1", "S2", "S3", "S4"]
    assert [(join.left_slot, join.right_slot) for join in plan.joins] == [("S1", "S3"), ("S2", "S4")]
    assert plan.outputs == ["?answer"]
    assert len(plan.operators) == 1
    assert plan.operators[0].kind == "field_argmin"
    assert plan.operators[0].fields == ["bd1", "bd2"]
    assert plan.operators[0].labels == ["Find Me Guilty", "Tear Gas Squad"]
    assert plan.operators[0].output == "answer"
    assert metrics.operator_rewrites == 1


def test_typed_field_extremum_template_skips_llm_compilation():
    question = "Which film has the director who was born first, Find Me Guilty or Tear Gas Squad?"

    plan, metrics = SlotCompiler(FakeStructuredClient([])).compile(question)

    assert metrics.llm_calls == 0
    assert metrics.heuristic_plans == 1
    assert metrics.typed_plan_templates == 1
    assert metrics.field_extremum_templates == 1
    assert metrics.operator_rewrites == 0
    assert [slot.id for slot in plan.slots] == ["S1", "S2", "S3", "S4"]
    assert [slot.predicate for slot in plan.slots] == ["DirectorOf", "BirthDate", "DirectorOf", "BirthDate"]
    assert [slot.arguments for slot in plan.slots] == [
        ["Find Me Guilty", "?director1"],
        ["?director1", "?birthDate1"],
        ["Tear Gas Squad", "?director2"],
        ["?director2", "?birthDate2"],
    ]
    assert [
        (join.left_slot, join.left_field, join.right_slot, join.right_field)
        for join in plan.joins
    ] == [
        ("S1", "director1", "S2", "director1"),
        ("S3", "director2", "S4", "director2"),
    ]
    assert plan.outputs == ["?answer"]
    assert len(plan.operators) == 1
    assert plan.operators[0].kind == "field_argmin"
    assert plan.operators[0].fields == ["birthDate1", "birthDate2"]
    assert plan.operators[0].labels == ["Find Me Guilty", "Tear Gas Squad"]
    assert plan.operators[0].output == "answer"


def test_typed_field_extremum_template_supports_later_as_argmax():
    question = "Which film has the director who was born later, Alpha Film or Beta Film?"

    plan, metrics = SlotCompiler(FakeStructuredClient([])).compile(question)

    assert metrics.llm_calls == 0
    assert metrics.field_extremum_templates == 1
    assert plan.operators[0].kind == "field_argmax"
    assert plan.operators[0].labels == ["Alpha Film", "Beta Film"]


def test_field_extremum_template_compiles_and_executes_within_four_step_budget():
    question = "Which film has the director who was born first, Find Me Guilty or Tear Gas Squad?"
    plan, compiler_metrics = SlotCompiler(FakeStructuredClient([])).compile(question)

    class TemplateMaterializer:
        def __init__(self):
            self.calls = []

        def materialize(self, slot, bindings):
            self.calls.append((slot.id, dict(bindings)))
            rows = {
                "S1": BindingRow(
                    slot_id="S1",
                    bindings={"director1": "Sidney Lumet"},
                    source_id="Find Me Guilty#0",
                    source_span="Find Me Guilty was directed by Sidney Lumet.",
                    confidence=1,
                ),
                "S2": BindingRow(
                    slot_id="S2",
                    bindings={"director1": "Sidney Lumet", "birthDate1": "June 25, 1924"},
                    source_id="Sidney Lumet#0",
                    source_span="Sidney Lumet was born on June 25, 1924.",
                    confidence=1,
                ),
                "S3": BindingRow(
                    slot_id="S3",
                    bindings={"director2": "Terry O. Morse"},
                    source_id="Tear Gas Squad#0",
                    source_span="Tear Gas Squad was directed by Terry O. Morse.",
                    confidence=1,
                ),
                "S4": BindingRow(
                    slot_id="S4",
                    bindings={"director2": "Terry O. Morse", "birthDate2": "January 30, 1906"},
                    source_id="Terry O. Morse#0",
                    source_span="Terry O. Morse was born on January 30, 1906.",
                    confidence=1,
                ),
            }
            return [rows[slot.id]], RunMetrics(
                retrieval_calls=1,
                documents_accessed=1,
                passages_processed=1,
            )

    materializer = TemplateMaterializer()
    result = AdaptiveExecutor(
        materializer,
        max_replans=4,
        max_retrieval_calls=4,
    ).execute(plan)

    assert compiler_metrics.llm_calls == 0
    assert compiler_metrics.field_extremum_templates == 1
    assert result.status == "ok"
    assert result.rows == [{"answer": "Tear Gas Squad"}]
    assert result.order == ["S1", "S2", "S3", "S4"]
    assert materializer.calls == [
        ("S1", {}),
        ("S2", {"director1": "Sidney Lumet"}),
        ("S3", {}),
        ("S4", {"director2": "Terry O. Morse"}),
    ]
    assert result.metrics.retrieval_calls == 4
    assert result.metrics.operators_executed == 1


def test_polar_comparison_template_skips_llm_with_fallback_equivalent_plan():
    question = "Do Alpha Film and Beta Film share the same nationality?"

    plan, metrics = SlotCompiler(FakeStructuredClient([])).compile(question)

    assert metrics.llm_calls == 0
    assert metrics.heuristic_plans == 1
    assert metrics.polar_comparison_templates == 1
    assert metrics.plan_fallbacks == 0
    assert plan == SlotPlan(
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


@pytest.mark.parametrize(
    "question",
    [
        "Can you name both directors?",
        "Do you know which films have the same director?",
        "What films are from the same country?",
        "Are Alpha and Beta related?",
        "Are both Alpha and Beta from the same country",
    ],
)
def test_polar_comparison_template_rejects_non_whitelisted_boundaries(question):
    fallback_payload = {
        "slots": [{
            "id": "S1",
            "predicate": "EvidenceAnsweringQuestion",
            "arguments": ["?answer"],
            "constraints": {"question": question},
        }],
        "joins": [],
        "outputs": ["?answer"],
    }

    _, metrics = SlotCompiler(FakeStructuredClient([fallback_payload])).compile(question)

    assert metrics.llm_calls == 1
    assert metrics.polar_comparison_templates == 0


def test_polar_comparison_template_can_be_disabled_for_ablation():
    question = "Are both Alpha and Beta from the same country?"
    fallback_payload = {
        "slots": [{
            "id": "S1",
            "predicate": "EvidenceAnsweringQuestion",
            "arguments": ["?answer"],
            "constraints": {"question": question},
        }],
        "joins": [],
        "outputs": ["?answer"],
    }

    _, metrics = SlotCompiler(FakeStructuredClient([fallback_payload])).compile(
        question,
        polar_comparison_templates=False,
    )

    assert metrics.llm_calls == 1
    assert metrics.polar_comparison_templates == 0


def test_explicit_boolean_route_is_not_counted_as_inferred_polar_comparison():
    plan, metrics = SlotCompiler(FakeStructuredClient([])).compile(
        "Are both Alpha and Beta from the same country?",
        answer_kind="boolean",
    )

    assert metrics.llm_calls == 0
    assert metrics.heuristic_plans == 1
    assert metrics.polar_comparison_templates == 0
    assert plan.slots[0].estimated_cardinality == 2


@pytest.mark.parametrize(
    ("noun", "extremum", "expected_kind"),
    [
        ("film", "earlier", "field_argmin"),
        ("film", "earliest", "field_argmin"),
        ("film", "latest", "field_argmax"),
        ("movie", "first", "field_argmin"),
    ],
)
def test_typed_field_extremum_template_supports_whitelisted_synonyms(noun, extremum, expected_kind):
    question = f"Which {noun} has the director who was born {extremum}, Alpha Film or Beta Film?"

    plan, metrics = SlotCompiler(FakeStructuredClient([])).compile(question)

    assert metrics.field_extremum_templates == 1
    assert plan.operators[0].kind == expected_kind


def test_typed_field_extremum_template_rejects_duplicate_candidates():
    question = "Which film has the director who was born first, Alpha Film or Alpha Film?"
    fallback_payload = {
        "slots": [{
            "id": "S1",
            "predicate": "EvidenceAnsweringQuestion",
            "arguments": ["?answer"],
            "constraints": {"question": question},
        }],
        "joins": [],
        "outputs": ["?answer"],
    }

    _, metrics = SlotCompiler(FakeStructuredClient([fallback_payload])).compile(question)

    assert metrics.llm_calls == 1
    assert metrics.typed_plan_templates == 0
    assert metrics.field_extremum_templates == 0


def test_typed_field_extremum_template_rejects_more_than_two_candidates():
    question = "Which film has the director who was born first, Alpha Film or Beta Film or Gamma Film?"
    fallback_payload = {
        "slots": [{
            "id": "S1",
            "predicate": "EvidenceAnsweringQuestion",
            "arguments": ["?answer"],
            "constraints": {"question": question},
        }],
        "joins": [],
        "outputs": ["?answer"],
    }

    _, metrics = SlotCompiler(FakeStructuredClient([fallback_payload])).compile(question)

    assert metrics.llm_calls == 1
    assert metrics.field_extremum_templates == 0


def test_field_extremum_template_can_be_disabled_for_ablation():
    question = "Which film has the director who was born first, Alpha Film or Beta Film?"
    fallback_payload = {
        "slots": [{
            "id": "S1",
            "predicate": "EvidenceAnsweringQuestion",
            "arguments": ["?answer"],
            "constraints": {"question": question},
        }],
        "joins": [],
        "outputs": ["?answer"],
    }

    _, metrics = SlotCompiler(FakeStructuredClient([fallback_payload])).compile(
        question,
        field_extremum_templates=False,
    )

    assert metrics.llm_calls == 1
    assert metrics.field_extremum_templates == 0


def test_slot_compiler_does_not_rewrite_ambiguous_field_comparison():
    plan_payload = {
        "slots": [
            {"id": "S1", "predicate": "BirthDate", "arguments": ["Alice", "?bd1"]},
            {"id": "S2", "predicate": "BirthDate", "arguments": ["Bob", "?bd2"]},
            {"id": "S3", "predicate": "Compare", "arguments": ["?bd1", "?bd2"]},
        ],
        "joins": [["S1.bd1", "S3.bd1"], ["S2.bd2", "S3.bd2"]],
        "outputs": ["?bd1", "?bd2"],
    }

    plan, metrics = SlotCompiler(FakeStructuredClient([plan_payload])).compile(
        "Compare the birth dates of Alice and Bob."
    )

    assert [slot.id for slot in plan.slots] == ["S1", "S2", "S3"]
    assert plan.operators == []
    assert metrics.operator_rewrites == 0


def test_field_extremum_operator_selects_label_for_earliest_date():
    rows = apply_operators(
        [{"bd1": "June 25, 1924", "bd2": "January 30, 1906"}],
        [
            RelationalOperator(
                id="O1",
                kind="field_argmin",
                fields=["bd1", "bd2"],
                labels=["Find Me Guilty", "Tear Gas Squad"],
                output="answer",
            )
        ],
    )

    assert rows == [{"answer": "Tear Gas Squad"}]


def test_slot_compiler_rewrites_later_birthdate_comparison_to_field_argmax():
    plan_payload = {
        "slots": [
            {"id": "S1", "predicate": "BirthDate", "arguments": ["Alice", "?bd1"]},
            {"id": "S2", "predicate": "BirthDate", "arguments": ["Bob", "?bd2"]},
            {"id": "S3", "predicate": "DateCompare", "arguments": ["?bd1", "?bd2"]},
        ],
        "joins": [["S1.bd1", "S3.bd1"], ["S2.bd2", "S3.bd2"]],
        "outputs": ["?bd1", "?bd2"],
    }

    plan, metrics = SlotCompiler(FakeStructuredClient([plan_payload])).compile(
        "Who was born later, Alice or Bob?"
    )
    rows = apply_operators(
        [{"bd1": "2000-01-01", "bd2": "1990-01-01"}],
        plan.operators,
    )

    assert [slot.id for slot in plan.slots] == ["S1", "S2"]
    assert plan.operators[0].kind == "field_argmax"
    assert plan.operators[0].labels == ["Alice", "Bob"]
    assert rows == [{"answer": "Alice"}]
    assert metrics.operator_rewrites == 1


def test_field_extremum_operator_rejects_ties_and_mixed_types():
    operator = RelationalOperator(
        id="O1",
        kind="field_argmin",
        fields=["left", "right"],
        labels=["Left", "Right"],
        output="answer",
    )

    assert apply_operators([{"left": "1906-01-30", "right": "1906-01-30"}], [operator]) == []
    assert apply_operators([{"left": "1906-01-30", "right": "unknown"}], [operator]) == []


def test_executor_combines_only_branches_connected_by_field_operator():
    plan = comparison_plan()

    result = AdaptiveExecutor(ComparisonMaterializer(), max_replans=4).execute(plan)

    assert result.status == "ok"
    assert result.rows == [{"answer": "Tear Gas Squad"}]
    assert result.order == ["S1", "S3", "S2", "S4"]
    assert result.metrics.operators_executed == 1


def test_late_join_combines_branches_connected_by_field_operator():
    result = AdaptiveExecutor(
        ComparisonMaterializer(),
        max_replans=4,
        options=ExecutionOptions(incremental_join=False),
    ).execute(comparison_plan())

    assert result.status == "ok"
    assert result.rows == [{"answer": "Tear Gas Squad"}]
    assert result.metrics.operators_executed == 1


def test_plan_still_rejects_disconnected_slots_without_a_connecting_operator():
    with pytest.raises(ValidationError, match="slot join graph must be connected"):
        SlotPlan.model_validate({
            "slots": [
                {"id": "S1", "predicate": "LeftFact", "arguments": ["?left"]},
                {"id": "S2", "predicate": "RightFact", "arguments": ["?right"]},
            ],
            "joins": [],
            "operators": [],
            "outputs": ["?left"],
        })


def test_date_difference_operator_uses_calendar_month_boundaries():
    rows = apply_operators(
        [{"startDate": "18 September 1906", "endDate": "1906-12-02"}],
        [
            RelationalOperator(
                id="O1",
                kind="arithmetic",
                fields=["startDate", "endDate"],
                operation="date_diff_months",
                output="months",
            )
        ],
    )

    assert rows == [{"months": "3"}]


def test_typed_month_difference_template_skips_llm_compilation_and_executes():
    question = "How many months after he began his term did Zaimis swear allegiance to the new constitution?"
    plan, compiler_metrics = SlotCompiler(FakeStructuredClient([])).compile(
        question,
        answer_kind="number",
        document_count=1,
    )

    assert compiler_metrics.llm_calls == 0
    assert compiler_metrics.heuristic_plans == 1
    assert compiler_metrics.typed_plan_templates == 1
    assert len(plan.slots) == 1
    assert plan.slots[0].predicate == "MonthDifferenceDates"
    assert plan.slots[0].arguments == ["?startDate", "?endDate"]
    assert plan.operators[0].operation == "date_diff_months"

    materializer = SlotMaterializer(
        SequenceExtractionClient(
            [[{
                "startDate": "18 September 1906",
                "endDate": "2 December 1906",
                "source_id": "drop_11251#0",
            }]]
        ),
        StaticRetriever(
            Passage(
                id="drop_11251#0",
                doc_id="drop_11251",
                text="Zaimis began his term on 18 September 1906 and swore allegiance on 2 December 1906.",
            )
        ),
    )
    result = AdaptiveExecutor(materializer).execute(plan)

    assert result.status == "ok"
    assert result.rows == [{"months": "3"}]
    assert result.metrics.extraction_llm_calls == 1
    assert result.metrics.operators_executed == 1


def test_typed_month_difference_template_does_not_match_other_numeric_relations():
    questions = [
        "How many months before the oath did the term begin?",
        "How many days after the term began was the oath sworn?",
        "How many years after the term began was the oath sworn?",
        "After the election, how many months did the term last?",
    ]
    for question in questions:
        payload = {
            "slots": [{
                "id": "S1",
                "predicate": "EvidenceAnsweringQuestion",
                "arguments": ["?answer"],
                "constraints": {"question": question},
            }],
            "joins": [],
            "outputs": ["?answer"],
        }

        _, metrics = SlotCompiler(FakeStructuredClient([payload])).compile(question, answer_kind="number")

        assert metrics.llm_calls == 1
        assert metrics.typed_plan_templates == 0


def test_single_document_compilation_uses_direct_evidence_plan():
    question = "Which player caught the first touchdown pass?"

    plan, metrics = SlotCompiler(FakeStructuredClient([])).compile(
        question,
        answer_kind="number",
        document_count=1,
    )

    assert metrics.llm_calls == 0
    assert metrics.heuristic_plans == 1
    assert metrics.direct_plan_templates == 1
    assert plan.slots[0].predicate == "EvidenceAnsweringQuestion"
    assert plan.slots[0].arguments == ["?answer"]
    assert plan.slots[0].constraints == {"question": question}
    assert plan.outputs == ["?answer"]
    assert plan.operators == []


def test_multi_document_compilation_does_not_use_direct_evidence_plan():
    question = "Which player caught the first touchdown pass?"
    payload = {
        "slots": [{
            "id": "S1",
            "predicate": "EvidenceAnsweringQuestion",
            "arguments": ["?answer"],
            "constraints": {"question": question},
        }],
        "joins": [],
        "outputs": ["?answer"],
    }

    _, metrics = SlotCompiler(FakeStructuredClient([payload])).compile(
        question,
        answer_kind="number",
        document_count=2,
    )

    assert metrics.llm_calls == 1
    assert metrics.direct_plan_templates == 0


def test_materializer_rejects_propagated_binding_not_grounded_in_source():
    invalid_row = {
        "person": "Rogério Martins",
        "series": "Holy Avenger",
        "source_id": "Erica Awano#0",
    }
    materializer = SlotMaterializer(
        SequenceExtractionClient([[invalid_row], [invalid_row]]),
        StaticRetriever(
            Passage(
                id="Erica Awano#0",
                doc_id="Erica Awano",
                text="Erica Awano is a comics artist who worked on Holy Avenger.",
            )
        ),
    )

    rows, metrics = materializer.materialize(
        Slot(id="S2", predicate="CreatedComicBookSeries", arguments=["?person", "?series"]),
        {"person": "Rogério Martins"},
    )

    assert rows == []
    assert metrics.grounding_rejections == 2
    assert metrics.structured_output_failures == 2


def test_materializer_accepts_propagated_binding_grounded_by_document_title():
    row = {
        "person": "Erica Awano",
        "series": "Holy Avenger",
        "source_id": "Erica Awano#0",
    }
    materializer = SlotMaterializer(
        SequenceExtractionClient([[row]]),
        StaticRetriever(
            Passage(
                id="Erica Awano#0",
                doc_id="Erica Awano",
                text="She is the artist of Holy Avenger.",
            )
        ),
    )

    rows, metrics = materializer.materialize(
        Slot(id="S2", predicate="CreatedComicBookSeries", arguments=["?person", "?series"]),
        {"person": "Erica Awano"},
    )

    assert [item.bindings for item in rows] == [{"person": "Erica Awano", "series": "Holy Avenger"}]
    assert metrics.grounding_rejections == 0


def test_role_projected_materializer_rejects_copied_anchor_then_repairs_relation_role():
    materializer = SlotMaterializer(
        SequenceExtractionClient([
            [{
                "grandmother": "Baldwin De Redvers, 7Th Earl Of Devon",
                "source_id": "Amice de Clare#0",
            }],
            [{"grandmother": "Isabel Marshal", "source_id": "Amice de Clare#0"}],
        ]),
        StaticRetriever(Passage(
            id="Amice de Clare#0",
            doc_id="Amice de Clare",
            text=(
                "Amice de Clare was the daughter of Gilbert de Clare and Isabel Marshal. "
                "Her grandson was Baldwin De Redvers, 7Th Earl Of Devon."
            ),
        )),
        role_projected_extraction=True,
        protected_anchor_values={"Baldwin De Redvers, 7Th Earl Of Devon"},
    )

    rows, metrics = materializer.materialize(
        Slot(id="S3", predicate="MotherOf", arguments=["?grandmother", "?mother"]),
        {"mother": "Amice de Clare"},
    )

    assert [row.bindings for row in rows] == [{
        "grandmother": "Isabel Marshal",
        "mother": "Amice de Clare",
    }]
    assert metrics.role_projected_extraction_contracts == 1
    assert metrics.known_binding_fields_projected == 1
    assert metrics.protected_anchor_rejections == 1
    assert metrics.structured_output_failures == 1
    assert metrics.structured_output_repairs == 1


def test_role_projected_materializer_rejects_known_binding_copied_into_output_when_guarded():
    materializer = SlotMaterializer(
        SequenceExtractionClient([
            [{"otherMovement": "Pakistan Movement", "source_id": "Mohammad Ali Jouhar#0"}],
            [{"otherMovement": "Khilafat Movement", "source_id": "Mohammad Ali Jouhar#0"}],
        ]),
        StaticRetriever(Passage(
            id="Mohammad Ali Jouhar#0",
            doc_id="Mohammad Ali Jouhar",
            text="Mohammad Ali Jouhar was a leader of the Khilafat Movement and Pakistan Movement.",
        )),
        role_projected_extraction=True,
        protect_known_binding_values=True,
    )

    rows, metrics = materializer.materialize(
        Slot(id="S2", predicate="alsoKnownAs", arguments=["?movement", "?otherMovement"]),
        {"movement": "Pakistan Movement"},
    )

    assert [row.bindings for row in rows] == [{
        "movement": "Pakistan Movement",
        "otherMovement": "Khilafat Movement",
    }]
    assert metrics.protected_anchor_rejections == 1
    assert metrics.structured_output_failures == 1
    assert metrics.structured_output_repairs == 1


def test_typed_boolean_materializer_emits_canonical_supported_rows():
    materializer = SlotMaterializer(
        SequenceExtractionClient([[{"answer": "no", "source_id": "p"}]]),
        StaticRetriever(Passage(id="p", doc_id="d", text="Alpha and Beta are from different countries.")),
        typed_extraction_contracts=True,
    )

    rows, metrics = materializer.materialize(
        Slot(
            id="S1",
            predicate="EvidenceAnsweringQuestion",
            arguments=["?answer"],
            constraints={"question": "Are Alpha and Beta from the same country?"},
            variable_types={"answer": "boolean"},
        ),
        {},
    )

    assert [row.bindings for row in rows] == [{"answer": "no"}]
    assert metrics.typed_extraction_contracts == 1
    assert metrics.typed_extraction_answers == 1
    assert metrics.typed_extraction_abstentions == 0


@pytest.mark.parametrize(
    "extracted_rows",
    [
        [],
        [{"answer": "unknown", "source_id": "p"}],
        [
            {"answer": "yes", "source_id": "p"},
            {"answer": "no", "source_id": "p"},
        ],
    ],
)
def test_typed_boolean_materializer_abstains_on_empty_unknown_or_conflict(extracted_rows):
    materializer = SlotMaterializer(
        SequenceExtractionClient([extracted_rows]),
        StaticRetriever(Passage(id="p", doc_id="d", text="Partial evidence.")),
        typed_extraction_contracts=True,
    )

    rows, metrics = materializer.materialize(
        Slot(
            id="S1",
            predicate="EvidenceAnsweringQuestion",
            arguments=["?answer"],
            variable_types={"answer": "boolean"},
        ),
        {},
    )

    assert rows == []
    assert metrics.llm_calls == 1
    assert metrics.typed_extraction_contracts == 1
    assert metrics.typed_extraction_answers == 0
    assert metrics.typed_extraction_abstentions == 1
    assert metrics.structured_output_failures == 0


def test_typed_boolean_materializer_repairs_invalid_value_then_abstains():
    materializer = SlotMaterializer(
        SequenceExtractionClient([
            [{"answer": "maybe", "source_id": "p"}],
            [{"answer": "unknown", "source_id": "p"}],
        ]),
        StaticRetriever(Passage(id="p", doc_id="d", text="Partial evidence.")),
        typed_extraction_contracts=True,
    )

    rows, metrics = materializer.materialize(
        Slot(
            id="S1",
            predicate="EvidenceAnsweringQuestion",
            arguments=["?answer"],
            variable_types={"answer": "boolean"},
        ),
        {},
    )

    assert rows == []
    assert metrics.llm_calls == 2
    assert metrics.structured_output_failures == 1
    assert metrics.structured_output_repairs == 1
    assert metrics.typed_extraction_abstentions == 1


def test_typed_extraction_is_disabled_by_default_and_keeps_free_text_rows():
    materializer = SlotMaterializer(
        SequenceExtractionClient([[{"answer": "No, Alpha differs from Beta.", "source_id": "p"}]]),
        StaticRetriever(Passage(id="p", doc_id="d", text="Alpha differs from Beta.")),
    )

    rows, metrics = materializer.materialize(
        Slot(
            id="S1",
            predicate="EvidenceAnsweringQuestion",
            arguments=["?answer"],
            variable_types={"answer": "boolean"},
        ),
        {},
    )

    assert [row.bindings for row in rows] == [{"answer": "No, Alpha differs from Beta."}]
    assert metrics.typed_extraction_contracts == 0
    assert metrics.typed_extraction_answers == 0
    assert metrics.typed_extraction_abstentions == 0


def test_materializer_counts_and_skips_repeated_invalid_extractions():
    materializer = SlotMaterializer(FakeExtractionClient(), FakeRetriever())
    rows, metrics = materializer.materialize(
        Slot(id="S1", predicate="Fact", arguments=["?answer"]),
        {},
    )
    assert rows == []
    assert metrics.llm_calls == 2
    assert metrics.extraction_llm_calls == 2
    assert metrics.structured_output_failures == 2
    assert metrics.structured_output_repairs == 1
    assert metrics.extraction_finish_reasons == ["unknown", "unknown"]
    assert len(metrics.extraction_validation_errors) == 2
    assert all("do not match fields" in error for error in metrics.extraction_validation_errors)
    assert materializer.accessed_passage_ids == {"p"}
    assert [item.source_id for item in materializer.last_evidence] == ["p"]


def test_materializer_disables_thinking_and_counts_bound_role_signatures():
    calls = []

    class Client:
        def complete(self, *_args, **kwargs):
            calls.append(kwargs)
            return ChatResult(
                finish_reason="tool_calls",
                tool_calls=[ToolCall(
                    name="emit_evidence_rows",
                    arguments={
                        "rows": [{
                            "grandmother": "Isabel Marshal",
                            "source_id": "Amice de Clare#0",
                        }],
                    },
                )],
            )

        @staticmethod
        def require_tool(result, name):
            return next(call.arguments for call in result.tool_calls if call.name == name)

    materializer = SlotMaterializer(
        Client(),
        StaticRetriever(Passage(
            id="Amice de Clare#0",
            doc_id="Amice de Clare",
            text="Amice de Clare was the daughter of Isabel Marshal.",
        )),
        role_projected_extraction=True,
        protected_anchor_values={"Baldwin De Redvers, 7Th Earl Of Devon"},
        extraction_enable_thinking=False,
        bound_role_signatures=True,
    )

    rows, metrics = materializer.materialize(
        Slot(id="S2", predicate="MotherOf", arguments=["?mother", "?grandmother"]),
        {"mother": "Amice de Clare"},
    )

    assert calls[0]["enable_thinking"] is False
    tool = calls[0]["tools"][0]
    description = tool["function"]["parameters"]["properties"]["rows"]["items"]["properties"]["grandmother"]["description"]
    assert 'MotherOf("Amice de Clare", ?grandmother)' in description
    assert [row.bindings for row in rows] == [{
        "mother": "Amice de Clare",
        "grandmother": "Isabel Marshal",
    }]
    assert metrics.extraction_thinking_disabled == 1
    assert metrics.bound_role_signatures == 1
    assert metrics.extraction_length_finishes == 0
    assert metrics.extraction_finish_reasons == ["tool_calls"]
    assert metrics.extraction_validation_errors == []


def test_anchor_window_uses_lead_entity_context_and_excludes_distant_mentions():
    text = (
        "Andy Warhol was an American artist and director. "
        "He worked in several media. His studio was called The Factory. "
        "His work became highly collectible. A museum in the United States preserves his archive."
    )

    focused = SlotMaterializer._anchor_centered_window(
        text,
        "Andy Warhol",
        {"Andy Warhol"},
        radius=2,
    )

    assert focused is not None
    assert "American" in focused
    assert "United States" not in focused


def test_anchor_window_grounding_rejects_distant_country_then_repairs_surface_form():
    text = (
        "Andy Warhol was an American artist and director. "
        "He worked in several media. His studio was called The Factory. "
        "His work became highly collectible. A museum in the United States preserves his archive."
    )
    materializer = SlotMaterializer(
        SequenceExtractionClient([
            [{"country": "United States", "source_id": "Andy Warhol#0"}],
            [{"country": "American", "source_id": "Andy Warhol#0"}],
        ]),
        StaticRetriever(Passage(id="Andy Warhol#0", doc_id="Andy Warhol", text=text)),
        role_projected_extraction=True,
        protected_anchor_values={"More Milk, Yvette"},
        anchor_centered_extraction=True,
    )

    rows, metrics = materializer.materialize(
        Slot(id="S2", predicate="CountryOf", arguments=["?director", "?country"]),
        {"director": "Andy Warhol"},
    )

    assert [row.bindings for row in rows] == [{"director": "Andy Warhol", "country": "American"}]
    assert "United States" not in rows[0].source_span
    assert metrics.anchor_window_contracts == 1
    assert metrics.anchor_window_selected_passages == 1
    assert metrics.anchor_window_dropped_passages == 0
    assert metrics.anchor_window_input_chars == len(text)
    assert metrics.anchor_window_output_chars < len(text)
    assert metrics.anchor_window_fallbacks == 0
    assert metrics.grounding_rejections == 1
    assert metrics.structured_output_repairs == 1


def test_anchor_window_is_inert_for_unregistered_predicates():
    text = "Andy Warhol was an American artist. A museum in the United States preserves his archive."
    materializer = SlotMaterializer(
        SequenceExtractionClient([[{"place": "United States", "source_id": "Andy Warhol#0"}]]),
        StaticRetriever(Passage(id="Andy Warhol#0", doc_id="Andy Warhol", text=text)),
        role_projected_extraction=True,
        anchor_centered_extraction=True,
    )

    rows, metrics = materializer.materialize(
        Slot(id="S2", predicate="DiedIn", arguments=["?director", "?place"]),
        {"director": "Andy Warhol"},
    )

    assert [row.bindings["place"] for row in rows] == ["United States"]
    assert metrics.anchor_window_contracts == 0
    assert metrics.anchor_window_input_chars == 0
    assert metrics.anchor_window_output_chars == 0


@pytest.mark.parametrize("predicate", ["HasNationality", "CountryOfBirth", "FromCountry", "NationalityOf"])
def test_normalized_anchor_window_accepts_closed_country_nationality_aliases(predicate):
    text = (
        "Washington Phillips was an American singer and instrumentalist. "
        "He recorded gospel blues in the 1920s."
    )
    materializer = SlotMaterializer(
        SequenceExtractionClient([[{"nationality": "American", "source_id": "Washington Phillips#0"}]]),
        StaticRetriever(Passage(id="Washington Phillips#0", doc_id="Washington Phillips", text=text)),
        role_projected_extraction=True,
        anchor_centered_extraction=True,
        normalize_anchor_window_predicates=True,
    )

    rows, metrics = materializer.materialize(
        Slot(id="S2", predicate=predicate, arguments=["?performer", "?nationality"]),
        {"performer": "Washington Phillips"},
    )

    assert [row.bindings["nationality"] for row in rows] == ["American"]
    assert metrics.anchor_window_contracts == 1
    assert metrics.anchor_window_predicate_normalizations == 1


@pytest.mark.parametrize("predicate", ["CountryMusicAwards", "HasCountryClub", "CountryPopulation"])
def test_normalized_anchor_window_rejects_unrelated_country_substrings(predicate):
    slot = Slot(id="S2", predicate=predicate, arguments=["?entity", "?value"])

    assert SlotMaterializer._uses_anchor_window(slot, normalize_predicates=True) is False


def test_query_grounded_anchor_values_uses_constraints_and_title_phrases():
    constrained = SlotPlan.model_validate({
        "slots": [
            {
                "id": "S1",
                "predicate": "PerformerOf",
                "arguments": ["?performer", "?song"],
                "constraints": {"song": "Lift Him Up That's All"},
            },
            {"id": "S2", "predicate": "FromCountry", "arguments": ["?performer", "?country"]},
        ],
        "joins": [["S1.performer", "S2.performer"]],
        "outputs": ["?country"],
    })
    under_specified = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "DirectorOf", "arguments": ["?director"]},
            {"id": "S2", "predicate": "HasNationality", "arguments": ["?director", "?nationality"]},
        ],
        "joins": [["S1.director", "S2.director"]],
        "outputs": ["?nationality"],
    })

    assert query_grounded_anchor_values(
        constrained,
        "Which country the performer of song Lift Him Up That'S All is from?",
    ) == ("Lift Him Up That's All",)
    assert query_grounded_anchor_values(
        under_specified,
        "What nationality is the director of film Claire (1924 Film)?",
    ) == ("Claire (1924 Film)",)


def test_inject_query_grounded_anchor_repairs_one_under_specified_relation_root():
    plan = SlotPlan.model_validate({
        "slots": [
            {"id": "S1", "predicate": "DirectorOf", "arguments": ["?director"]},
            {"id": "S2", "predicate": "HasNationality", "arguments": ["?director", "?nationality"]},
        ],
        "joins": [["S1.director", "S2.director"]],
        "outputs": ["?nationality"],
    })

    repaired, count, values = inject_query_grounded_anchor(
        plan,
        "What nationality is the director of film Claire (1924 Film)?",
    )

    assert count == 1
    assert values == ("Claire (1924 Film)",)
    assert repaired.slots[0].arguments == ["?director", "Claire (1924 Film)"]


def test_evidence_surface_grounding_repair_uses_exact_source_word():
    text = "Tom Cowan (born 31 October 1942) is an Australian filmmaker."
    materializer = SlotMaterializer(
        SequenceExtractionClient([[{
            "country": "Australia",
            "source_id": "Tom Cowan (director)#0",
        }]]),
        StaticRetriever(Passage(id="Tom Cowan (director)#0", doc_id="Tom Cowan (director)", text=text)),
        role_projected_extraction=True,
        protected_anchor_values={"Journey Among Women"},
        anchor_centered_extraction=True,
        normalize_anchor_window_predicates=True,
        evidence_surface_grounding_repair=True,
    )

    rows, metrics = materializer.materialize(
        Slot(id="S2", predicate="CountryOfBirth", arguments=["?director", "?country"]),
        {"director": "Tom Cowan"},
    )

    assert [row.bindings["country"] for row in rows] == ["Australian"]
    assert metrics.evidence_surface_grounding_repairs == 1
    assert metrics.grounding_rejections == 0


def test_role_type_filter_rejects_explicit_gender_contradiction_without_retry():
    materializer = SlotMaterializer(
        SequenceExtractionClient([[
            {
                "grandmother": "Gilbert de Clare, 4th Earl of Hertford",
                "source_id": "Amice de Clare#0",
            },
            {
                "grandmother": "Isabel Marshal",
                "source_id": "Amice de Clare#0",
            },
        ]]),
        StaticRetriever(Passage(
            id="Amice de Clare#0",
            doc_id="Amice de Clare",
            text=(
                "Amice de Clare was the daughter of Gilbert de Clare, "
                "4th Earl of Hertford, and Isabel Marshal."
            ),
        )),
        role_projected_extraction=True,
        semantic_role_type_filter=True,
    )

    rows, metrics = materializer.materialize(
        Slot(id="S2", predicate="MotherOf", arguments=["?mother", "?grandmother"]),
        {"mother": "Amice de Clare"},
    )

    assert [row.bindings for row in rows] == [{
        "mother": "Amice de Clare",
        "grandmother": "Isabel Marshal",
    }]
    assert metrics.semantic_role_type_contracts == 1
    assert metrics.semantic_role_type_rejections == 1
    assert metrics.semantic_role_type_abstentions == 0
    assert metrics.structured_output_failures == 0
    assert metrics.structured_output_repairs == 0
    assert metrics.grounding_rejections == 0


def test_role_type_filter_is_conservative_without_an_explicit_contradiction():
    materializer = SlotMaterializer(
        SequenceExtractionClient([[
            {"grandfather": "Muhammad al-Baqir", "source_id": "p"},
        ]]),
        StaticRetriever(Passage(
            id="p",
            doc_id="Muhammad al-Baqir",
            text="Isma'il ibn Ja'far was the son of Ja'far al-Sadiq, son of Muhammad al-Baqir.",
        )),
        role_projected_extraction=True,
        semantic_role_type_filter=True,
    )

    rows, metrics = materializer.materialize(
        Slot(id="S2", predicate="FatherOf", arguments=["?father", "?grandfather"]),
        {"father": "Ja'far al-Sadiq"},
    )

    assert [row.bindings["grandfather"] for row in rows] == ["Muhammad al-Baqir"]
    assert metrics.semantic_role_type_contracts == 1
    assert metrics.semantic_role_type_rejections == 0
    assert metrics.semantic_role_type_abstentions == 0


def test_role_type_filter_abstains_without_repair_when_every_row_contradicts():
    materializer = SlotMaterializer(
        SequenceExtractionClient([[
            {
                "grandmother": "Gilbert de Clare, 4th Earl of Hertford",
                "source_id": "p",
            },
        ]]),
        StaticRetriever(Passage(
            id="p",
            doc_id="Amice de Clare",
            text="Amice de Clare was the daughter of Gilbert de Clare, 4th Earl of Hertford.",
        )),
        role_projected_extraction=True,
        semantic_role_type_filter=True,
    )

    rows, metrics = materializer.materialize(
        Slot(id="S2", predicate="MotherOf", arguments=["?mother", "?grandmother"]),
        {"mother": "Amice de Clare"},
    )

    assert rows == []
    assert metrics.semantic_role_type_contracts == 1
    assert metrics.semantic_role_type_rejections == 1
    assert metrics.semantic_role_type_abstentions == 1
    assert metrics.structured_output_failures == 0
    assert metrics.structured_output_repairs == 0
