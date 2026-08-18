"""G1 formal status-transition semantics for the Evidence Algebra.

``derive_evidence_state`` (planner.py) produces a *snapshot*: which
:class:`EvidenceRequirement` s are satisfied/partial/unresolved after an
execution. That snapshot alone does not say HOW a requirement changed state —
i.e. which observation (a bindable row, provenance-clean evidence, a
sufficiency verdict) drove the transition unresolved -> partial -> satisfied.

This module adds the missing "状态转换语义" (state-transition semantics) as a
first-class, pure function:

    apply_observation(state, observation) -> state'

It maps an observed coverage probe to a new :class:`EvidenceState`, advancing
each affected requirement one legal step (unresolved -> partial -> satisfied).
It is *additive and non-breaking*: it never mutates the legacy models, and the
transition rule is monotone (a satisfied requirement never regresses), mirroring
the invariant already tested in ``tests/test_tkde_evidence_objects.py``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .models import (
    EvidenceRequirement,
    EvidenceState,
    RequirementStatus,
)


class Transition(BaseModel):
    """One requirement's status change driven by an observation."""

    requirement_id: str = Field(min_length=1)
    from_status: RequirementStatus
    to_status: RequirementStatus
    cause: Literal["covered", "evidence_seen", "verdict"] = "covered"
    source_ids: list[str] = Field(default_factory=list)


class StatusTransitionResult(BaseModel):
    """The outcome of applying one observation to an EvidenceState."""

    state: EvidenceState
    transitions: list[Transition]
    changed: bool


# Monotone lattice rank: unresolved < partial < satisfied. A transition only
# fires when the observation advances a requirement up this lattice; nothing
# ever moves down (evidence only accumulates in the real pipeline, and the
# object tests pin that once-satisfied-is-forever). _next_status clamps the
# probe-derived candidate to this rank so no step can regress.
_RANK: dict[RequirementStatus, int] = {"unresolved": 0, "partial": 1, "satisfied": 2}


_RANK: dict[RequirementStatus, int] = {"unresolved": 0, "partial": 1, "satisfied": 2}


def _next_status(
    current: RequirementStatus,
    covered_vars: int,
    total_vars: int,
    any_evidence: bool,
) -> RequirementStatus:
    """Transition rule for a single requirement given its observed coverage.

    Monotone: the returned status is the probe-derived candidate clamped to
    never rank below the current status. Evidence only accumulates in the real
    pipeline, so a stale/partial re-probe must not undo progress (unresolved ->
    partial -> satisfied, and never back).
    """
    if total_vars > 0 and covered_vars >= total_vars:
        candidate: RequirementStatus = "satisfied"
    elif any_evidence or covered_vars > 0:
        candidate = "partial"
    else:
        candidate = "unresolved"
    if _RANK[candidate] >= _RANK[current]:
        return candidate
    return current


def apply_observation(
    state: EvidenceState,
    observation: dict[str, dict[str, object]],
) -> StatusTransitionResult:
    """Advance requirements from per-requirement observed coverage.

    ``observation`` maps ``requirement_id`` -> ``{"covered_vars": int,
    "total_vars": int, "evidence_seen": bool, "source_ids": list[str]}``.
    Requirements absent from the observation, or already satisfied, are left
    unchanged. Returns the new state plus the transitions actually applied
    (a requirement that did not move contributes no transition).
    """
    transitions: list[Transition] = []
    changed = False
    new_reqs: list[EvidenceRequirement] = []

    for req in state.requirements:
        obs = observation.get(req.id)
        if obs is None or req.status == "satisfied":
            new_reqs.append(req)
            continue
        covered = int(obs.get("covered_vars", 0))
        total = int(obs.get("total_vars", len(req.variables)))
        ev_seen = bool(obs.get("evidence_seen", False))
        source_ids = [str(s) for s in obs.get("source_ids", [])]
        nxt = _next_status(req.status, covered, total, ev_seen)
        if nxt != req.status:
            changed = True
            transitions.append(
                Transition(
                    requirement_id=req.id,
                    from_status=req.status,
                    to_status=nxt,
                    cause="verdict" if ev_seen else ("covered" if covered > 0 else "evidence_seen"),
                    source_ids=source_ids,
                )
            )
            new_reqs.append(req.model_copy(update={"status": nxt}))
        else:
            new_reqs.append(req)

    return StatusTransitionResult(
        state=EvidenceState(
            requirements=new_reqs,
            bound_evidence=state.bound_evidence,
            bindings=state.bindings,
            budget_used_retrieval=state.budget_used_retrieval,
            budget_used_tokens=state.budget_used_tokens,
        ),
        transitions=transitions,
        changed=changed,
    )