from slotrag.binding import AdaptiveBindingBeam
from slotrag.models import BindingRow


def _row(source_id: str, person: str, confidence: float, *, extra: str = "") -> BindingRow:
    return BindingRow(
        slot_id="S1",
        bindings={"person": person, **({"extra": extra} if extra else {})},
        source_id=source_id,
        source_span=f"Evidence for {person}",
        confidence=confidence,
        retrieval_score=confidence,
    )


def test_beam_prefers_evidence_confidence_and_deduplicates_contexts():
    selector = AdaptiveBindingBeam(min_width=1, max_width=3)
    decision = selector.select(
        [
            _row("weak", "Grace", 0.35),
            _row("strong", "Ada", 0.95),
            _row("duplicate", "Ada", 0.80),
        ],
        relevant_variables={"person"},
        budget_remaining=3,
    )

    assert decision.width == 1
    assert [candidate.source_id for candidate in decision.selected] == ["strong"]
    assert decision.considered_count == 2
    assert decision.pruned_count == 2
    assert set(decision.pruned_source_ids) == {"weak", "duplicate"}


def test_uncertainty_expands_beam_and_records_pruned_candidates():
    selector = AdaptiveBindingBeam(min_width=1, max_width=3)
    decision = selector.select(
        [
            _row("a", "Ada", 0.32),
            _row("b", "Grace", 0.36),
            _row("c", "Lin", 0.40),
        ],
        relevant_variables={"person"},
        budget_remaining=3,
    )

    assert decision.width == 3
    assert len(decision.selected) == 3
    assert decision.pruned_count == 0
    assert decision.uncertainty > 0.5
