"""H-015: generation evidence curation (dedupe + cap)."""

from slotrag.benchmarking.methods import _curate_evidence
from slotrag.models import EvidenceRecord, ExecutionResult


def _result_with_evidence(count: int, *, dupes: int = 0) -> ExecutionResult:
    evidence = []
    for i in range(count):
        evidence.append(EvidenceRecord(
            source_id=f"p{i}",
            source_span=f"span {i}",
            slot_id="S1",
            bindings={},
        ))
    for i in range(dupes):
        evidence.append(EvidenceRecord(
            source_id="p0",  # duplicate of the first
            source_span="duplicate span",
            slot_id="S1",
            bindings={},
        ))
    return ExecutionResult(evidence=evidence)


def test_curate_dedupes_repeated_sources():
    result = _result_with_evidence(3, dupes=2)
    curated = _curate_evidence(result)
    assert len(curated.evidence) == 3  # 3 unique sources, 2 dupes dropped
    source_ids = [e.source_id for e in curated.evidence]
    assert len(set(source_ids)) == len(source_ids)


def test_curate_caps_to_max_items():
    result = _result_with_evidence(12)
    curated = _curate_evidence(result)
    assert len(curated.evidence) == 8  # capped at default max_items


def test_curate_is_noop_within_limit_and_no_dupes():
    result = _result_with_evidence(5)
    curated = _curate_evidence(result)
    # No change → returns the same object (model_copy returns self when unchanged)
    assert len(curated.evidence) == 5


def test_curate_keeps_original_source_order():
    result = _result_with_evidence(10, dupes=3)
    curated = _curate_evidence(result)
    first_ids = [e.source_id for e in curated.evidence]
    assert first_ids == ["p0", "p1", "p2", "p3", "p4", "p5", "p6", "p7"]
