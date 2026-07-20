"""Dataset, method, and reporting infrastructure for reproducible benchmarks."""

from .datasets import DATASETS, DatasetSpec, audit_suite, load_sample
from .metrics import score_record

__all__ = ["DATASETS", "DatasetSpec", "audit_suite", "load_sample", "score_record"]
