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
]
