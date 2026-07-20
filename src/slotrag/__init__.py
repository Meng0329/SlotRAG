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

__all__ = [
    "BindingRow",
    "EvidenceRecord",
    "ExecutionResult",
    "Passage",
    "QuestionRecord",
    "RelationalOperator",
    "Slot",
    "SlotPlan",
]
