"""Dataset, method, and reporting infrastructure for reproducible benchmarks."""

from .datasets import DATASETS, DatasetSpec, audit_suite, load_sample
from .baselines import BASELINE_SPECS, BaselineSpec, audit_baselines
from .metrics import extract_answer_span, score_record
from .record_audit import audit_run_records
from .publication_gate import audit_publication_readiness

__all__ = [
    "DATASETS",
    "DatasetSpec",
    "audit_suite",
    "load_sample",
    "BASELINE_SPECS",
    "BaselineSpec",
    "audit_baselines",
    "extract_answer_span",
    "audit_run_records",
    "audit_publication_readiness",
    "score_record",
]
