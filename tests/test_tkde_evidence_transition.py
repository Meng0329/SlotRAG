"""G1 formal status-transition semantics: apply_observation.

These tests exercise the pure state-transition function in
``slotrag.evidence_algebra`` — the "状态转换语义" (state-transition semantics)
piece of the Evidence Algebra that ``derive_evidence_state`` (a snapshot) does
not provide. Offline-only, no services.
"""

import pytest

from slotrag.evidence_algebra import apply_observation
from slotrag.models import EvidenceRequirement, EvidenceState


def _state(*reqs) -> EvidenceState:
    return EvidenceState(requirements=list(reqs))


def _obs(requirement_id, covered_vars, total_vars=None, evidence_seen=False, source_ids=None):
    d = {"covered_vars": covered_vars, "evidence_seen": evidence_seen}
    if total_vars is not None:
        d["total_vars"] = total_vars
    if source_ids is not None:
        d["source_ids"] = source_ids
    return {requirement_id: d}


# --- Monotone progressions -------------------------------------------------

def test_unresolved_to_partial_on_partial_coverage():
    st = _state(EvidenceRequirement(id="r1", slot_id="s1", variables=["?x", "?y"]))
    out = apply_observation(st, _obs("r1", covered_vars=1))
    assert out.changed is True
    assert out.state.status_of("r1") == "partial"
    assert len(out.transitions) == 1
    assert out.transitions[0].from_status == "unresolved"
    assert out.transitions[0].to_status == "partial"


def test_unresolved_to_satisfied_on_full_coverage():
    st = _state(EvidenceRequirement(id="r1", slot_id="s1", variables=["?x", "?y"]))
    out = apply_observation(st, _obs("r1", covered_vars=2))
    assert out.state.status_of("r1") == "satisfied"
    assert out.transitions[0].from_status == "unresolved"
    assert out.transitions[0].to_status == "satisfied"


def test_partial_to_satisfied_on_completion():
    st = _state(EvidenceRequirement(id="r1", slot_id="s1", variables=["?x", "?y"], status="partial"))
    out = apply_observation(st, _obs("r1", covered_vars=2))
    assert out.state.status_of("r1") == "satisfied"
    assert out.transitions[0].from_status == "partial"
    assert out.transitions[0].to_status == "satisfied"


def test_evidence_seen_alone_lifts_unresolved_to_partial():
    st = _state(EvidenceRequirement(id="r1", slot_id="s1", variables=["?x"]))
    out = apply_observation(st, _obs("r1", covered_vars=0, evidence_seen=True, source_ids=["d1"]))
    assert out.state.status_of("r1") == "partial"
    assert out.transitions[0].cause == "verdict"


def test_no_progress_stays_unresolved():
    st = _state(EvidenceRequirement(id="r1", slot_id="s1", variables=["?x", "?y"]))
    out = apply_observation(st, _obs("r1", covered_vars=0))
    assert out.changed is False
    assert out.transitions == []
    assert out.state.status_of("r1") == "unresolved"


# --- Monotonicity / no regression ------------------------------------------

def test_satisfied_never_regresses_even_if_coverage_probe_drops():
    st = _state(EvidenceRequirement(id="r1", slot_id="s1", variables=["?x"], status="satisfied"))
    out = apply_observation(st, _obs("r1", covered_vars=0, evidence_seen=False))
    assert out.changed is False
    assert out.state.status_of("r1") == "satisfied"


def test_partial_never_regresses_to_unresolved():
    st = _state(EvidenceRequirement(id="r1", slot_id="s1", variables=["?x", "?y"], status="partial"))
    out = apply_observation(st, _obs("r1", covered_vars=0))
    assert out.state.status_of("r1") == "partial"
    assert out.transitions == []


# --- Observation shape / edge cases ----------------------------------------

def test_requirement_absent_from_observation_is_untouched():
    st = _state(
        EvidenceRequirement(id="r1", slot_id="s1", variables=["?x"], status="partial"),
        EvidenceRequirement(id="r2", slot_id="s2", variables=["?y"]),
    )
    out = apply_observation(st, _obs("r1", covered_vars=1))
    assert out.changed is True
    assert out.state.status_of("r1") == "satisfied"
    assert out.state.status_of("r2") == "unresolved"  # untouched
    assert all(t.requirement_id == "r1" for t in out.transitions)


def test_total_vars_defaults_to_requirement_variables_length():
    st = _state(EvidenceRequirement(id="r1", slot_id="s1", variables=["?x", "?y", "?z"]))
    out = apply_observation(st, _obs("r1", covered_vars=3))
    assert out.state.status_of("r1") == "satisfied"


def test_explicit_total_vars_override():
    # total_vars larger than the declared variable list: full coverage is judged
    # against the explicit total, not the requirement's variable count.
    st = _state(EvidenceRequirement(id="r1", slot_id="s1", variables=["?x"]))
    out = apply_observation(st, _obs("r1", covered_vars=1, total_vars=3))
    assert out.state.status_of("r1") == "partial"


def test_empty_requirement_list_is_identity():
    out = apply_observation(EvidenceState(), {})
    assert out.changed is False
    assert out.state.requirements == []
    assert out.transitions == []


def test_preserves_budget_and_binding_context():
    st = EvidenceState(
        requirements=[EvidenceRequirement(id="r1", slot_id="s1", variables=["?x", "?y"])],
        bound_evidence={"r1": ["d1"]},
        bindings={"r1": {"x": "v"}},
        budget_used_retrieval=3,
        budget_used_tokens=120,
    )
    out = apply_observation(st, _obs("r1", covered_vars=2, source_ids=["d1", "d2"]))
    ns = out.state
    assert ns.budget_used_retrieval == 3
    assert ns.budget_used_tokens == 120
    assert ns.bound_evidence == {"r1": ["d1"]}
    assert ns.bindings == {"r1": {"x": "v"}}
    assert out.transitions[0].source_ids == ["d1", "d2"]


def test_apply_is_chainable_and_converges():
    """Chaining observations drives r1 through the full lattice, then the
    second apply is a no-op (idempotent at satisfaction)."""
    st = _state(EvidenceRequirement(id="r1", slot_id="s1", variables=["?x", "?y"]))
    out1 = apply_observation(st, _obs("r1", covered_vars=1))
    assert out1.state.status_of("r1") == "partial"
    out2 = apply_observation(out1.state, _obs("r1", covered_vars=2))
    assert out2.state.status_of("r1") == "satisfied"
    out3 = apply_observation(out2.state, _obs("r1", covered_vars=2))
    assert out3.changed is False
    assert out3.state.status_of("r1") == "satisfied"


def test_apply_drives_dependency_chain_in_order():
    """r2 depends_on r1: satisfying r1 then probing r2 full coverage satisfies
    both — the observation is per-requirement, so r2 can advance independently,
    but the transition list preserves application order."""
    st = _state(
        EvidenceRequirement(id="r1", slot_id="s1", variables=["?x"]),
        EvidenceRequirement(id="r2", slot_id="s2", variables=["?y"], depends_on=["r1"]),
    )
    out1 = apply_observation(st, _obs("r1", covered_vars=1))
    assert out1.state.status_of("r1") == "satisfied"
    out2 = apply_observation(out1.state, _obs("r2", covered_vars=1))
    assert out2.state.status_of("r1") == "satisfied"
    assert out2.state.status_of("r2") == "satisfied"
    assert [t.requirement_id for t in out2.transitions] == ["r2"]
