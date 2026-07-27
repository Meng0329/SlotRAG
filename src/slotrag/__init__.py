"""SlotRAG research prototype."""

__version__ = "0.1.0"

from .models import (
    BindingRow,
    EvidenceRecord,
    ExecutionResult,
    Passage,
    QuestionRecord,
    RelationalOperator,
    Slot,
    SlotPlan,
)
from .qo import LogicalPlan, PhysicalPlan
from .action_policy import ActionDecision, ActionPolicyContext, PhysicalActionPolicy
from .binding import AdaptiveBindingBeam, BindingBeamDecision

__all__ = [
    "BindingRow",
    "EvidenceRecord",
    "ExecutionResult",
    "Passage",
    "QuestionRecord",
    "RelationalOperator",
    "Slot",
    "SlotPlan",
    "LogicalPlan",
    "PhysicalPlan",
    "ActionDecision",
    "ActionPolicyContext",
    "PhysicalActionPolicy",
    "AdaptiveBindingBeam",
    "BindingBeamDecision",
]
