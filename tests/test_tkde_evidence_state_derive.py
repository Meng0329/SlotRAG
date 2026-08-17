"""G1 wiring: derive_evidence_state maps a real ExecutionResult to an EvidenceState.

Pure post-processing; never called from the execute() hot loop, so legacy
execution paths are unaffected.
"""

from slotrag.models import (
    EvidenceRecord,
    EvidenceState,
    ExecutionResult,
    JoinSpec,
    RunMetrics,
    Slot,
    SlotExecutionTrace,
    SlotPlan,
)
from slotrag.planner import derive_evidence_state


def _plan() -> SlotPlan:
    return SlotPlan(
        slots=[
            Slot(id="s1", predicate="birth", arguments=["?p", "Where born"]),
            Slot(id="s2", predicate="nationality", arguments=["?p", "What nationality"]),
        ],
        joins=[
            JoinSpec(left_slot="s1", left_field="p", right_slot="s2", right_field="p"),
        ],
        outputs=["?p"],
    )


def _suff_trace(step, slot_id, status, contexts, prob=0.9) -> SlotExecutionTrace:
    return SlotExecutionTrace(
        step=step,
        slot_id=slot_id,
        predicate="p",
        binding_contexts=[dict(c) for c in contexts],
        materializations=[],
        sufficiency_model="development_logistic",
        sufficiency_status=status,
        sufficiency_probability=prob,
        sufficiency_features={},
    )


def test_derives_requirements_from_sufficiency():
    plan = _plan()
    result = ExecutionResult(
        rows=[{"p": "x"}],
        evidence=[EvidenceRecord(source_id="docA", source_span="sp", slot_id="s1", bindings={"p": "x"})],
        order=["s1", "s2"],
        metrics=RunMetrics(retrieval_calls=2, prompt_tokens=10, completion_tokens=5),
        slot_traces=[
            _suff_trace(0, "s1", "SUFFICIENT", [{"p": "x"}]),
            _suff_trace(1, "s2", "INSUFFICIENT", [], prob=0.2),
        ],
        status="ok",
        plan=plan,
    )
    st = derive_evidence_state(plan, result)
    assert isinstance(st, EvidenceState)
    assert st.satisfied_count() == 1
    by_slot = {r.slot_id: r for r in st.requirements}
    assert by_slot["s1"].status == "satisfied"
    assert by_slot["s2"].status == "unresolved"
    assert st.bound_evidence["s1"] == ["docA"]
    assert st.bindings["s1"] == {"p": "x"}
    assert st.budget_used_retrieval == 2
    assert st.budget_used_tokens == 15


def test_derives_partial_status():
    plan = _plan()
    result = ExecutionResult(
        rows=[],
        evidence=[],
        order=[],
        metrics=RunMetrics(),
        slot_traces=[
            _suff_trace(0, "s1", "PARTIAL", [{"p": "x"}], prob=0.5),
        ],
        status="ok",
        plan=plan,
    )
    st = derive_evidence_state(plan, result)
    assert st.requirements[0].status == "partial"
    assert st.requirements[1].status == "unresolved"  # s2 never materialized


def test_unmaterialized_slot_is_unresolved_with_reason():
    plan = _plan()
    result = ExecutionResult(rows=[], evidence=[], order=[], metrics=RunMetrics(), status="empty", plan=plan)
    st = derive_evidence_state(plan, result)
    assert all(r.status == "unresolved" for r in st.requirements)
    assert st.requirements[0].unsatisfied_reason is not None


def test_requirements_carry_slot_importance_and_variables():
    plan = _plan()
    result = ExecutionResult(rows=[], evidence=[], order=[], metrics=RunMetrics(),
                             slot_traces=[_suff_trace(0, "s1", "SUFFICIENT", [{"p": "x"}])],
                             status="ok", plan=plan)
    st = derive_evidence_state(plan, result)
    s1 = next(r for r in st.requirements if r.slot_id == "s1")
    assert s1.importance == 1.0
    assert "p" in s1.variables
    # s1 and s2 join on p -> mutual dependency
    assert "s1" in s1.depends_on or "s2" in s1.depends_on