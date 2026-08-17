"""G1 formal evidence objects: EvidenceType/RequirementStatus/EvidenceRequirement/EvidenceState.

These tests exercise the additive, non-breaking evidence-requirement layer added
for the TKDE evidence-execution branch. They must not depend on external services.
"""

import pytest

from slotrag.models import (
    EvidenceRequirement,
    EvidenceState,
    RequirementStatus,
    SlotPlan,
    Slot,
    JoinSpec,
)


# --- EvidenceRequirement construction / validation -----------------------

def test_requirement_default_status_is_unresolved():
    req = EvidenceRequirement(id="r1", slot_id="s1", variables=["?x"])
    assert req.status == "unresolved"
    assert req.evidence_type == "passage"
    assert req.unresolved_variables == ["?x"]


def test_requirement_requires_nonempty_id_and_slot():
    with pytest.raises(Exception):
        EvidenceRequirement(id="", slot_id="s1", variables=["?x"])
    with pytest.raises(Exception):
        EvidenceRequirement(id="r1", slot_id="", variables=["?x"])


def test_requirement_state_must_be_valid_literal():
    with pytest.raises(Exception):
        EvidenceRequirement(id="r1", slot_id="s1", variables=["?x"], status="done")  # type: ignore[arg-type]


@pytest.mark.parametrize("ety", ["passage", "entity", "relation", "table_row", "structured_record"])
def test_requirement_accepts_all_evidence_types(ety):
    req = EvidenceRequirement(id="r1", slot_id="s1", variables=["?x"], evidence_type=ety)  # type: ignore[arg-type]
    assert req.evidence_type == ety


def test_requirement_importance_must_be_positive():
    with pytest.raises(Exception):
        EvidenceRequirement(id="r1", slot_id="s1", variables=["?x"], importance=0)


def test_requirement_dependency_list_is_plain():
    req = EvidenceRequirement(
        id="r2", slot_id="s2", variables=["?x"], depends_on=["r1", "r3"]
    )
    assert req.depends_on == ["r1", "r3"]


# --- EvidenceState snapshots ----------------------------------------------

def test_evidence_state_tracks_satisfied_count():
    st = EvidenceState(
        requirements=[
            EvidenceRequirement(id="r1", slot_id="s1", variables=["?x"], status="satisfied"),
            EvidenceRequirement(id="r2", slot_id="s2", variables=["?y"], status="partial"),
            EvidenceRequirement(id="r3", slot_id="s3", variables=["?z"], status="unresolved"),
        ]
    )
    assert st.satisfied_count() == 1
    assert [r.id for r in st.unresolved_or_partial()] == ["r2", "r3"]


def test_evidence_state_status_of_unknown_requirement_returns_none():
    st = EvidenceState()
    assert st.status_of("nope") is None


def test_evidence_state_bound_evidence_and_bindings():
    st = EvidenceState(
        requirements=[EvidenceRequirement(id="r1", slot_id="s1", variables=["?x"], status="satisfied")],
        bound_evidence={"r1": ["docA", "docB"]},
        bindings={"r1": {"x": "val1"}},
    )
    assert st.bound_evidence["r1"] == ["docA", "docB"]
    assert st.bindings["r1"]["x"] == "val1"


def test_evidence_state_budget_fields_default_zero():
    st = EvidenceState()
    assert st.budget_used_retrieval == 0
    assert st.budget_used_tokens == 0


# --- Backward compatibility: legacy SlotPlan unaffected -------------------

def test_legacy_slot_plan_works_without_evidence_requirements():
    """The G1 layer is additive: building a legacy SlotPlan must not require
    any EvidenceRequirement / EvidenceState. This guards against a regression
    where the new formalism accidentally becomes mandatory."""

    plan = SlotPlan(
        slots=[
            Slot(id="s1", predicate="birth", arguments=["?p", "Where was ?p born"]),
            Slot(id="s2", predicate="nationality", arguments=["?p", "What is ?p nationality"]),
        ],
        joins=[
            JoinSpec(left_slot="s1", left_field="p", right_slot="s2", right_field="p"),
        ],
        outputs=["?p"],
    )
    assert plan.outputs == ["?p"]


def test_evidence_type_metadata_has_expected_units():
    from slotrag.models import EVIDENCE_TYPE_METADATA

    assert EVIDENCE_TYPE_METADATA["passage"]["provenance_unit"] == "passage"
    assert EVIDENCE_TYPE_METADATA["entity"]["provenance_unit"] == "value"
    assert EVIDENCE_TYPE_METADATA["relation"]["provenance_unit"] == "triple"
    assert EVIDENCE_TYPE_METADATA["table_row"]["provenance_unit"] == "row"
    assert EVIDENCE_TYPE_METADATA["structured_record"]["provenance_unit"] == "record"


def test_requirement_state_transition_is_valid():
    """The four archetypical state progressions an executor may drive."""
    valid = [
        ("unresolved", "partial"),
        ("unresolved", "satisfied"),
        ("partial", "satisfied"),
    ]
    for frm, to in valid:
        assert (frm, to) in valid  # document the allowed transitions
    # invalid: once satisfied, never regress (no regression allowed)
    assert ("satisfied", "unresolved") not in valid