from pathlib import Path

from slotrag.benchmarking.baselines import BASELINE_SPECS, audit_baselines


def test_baseline_registry_marks_local_descriptions_as_non_upstream():
    report = audit_baselines(Path.cwd(), ["hotpotqa", "drop"])
    by_key = {item["key"]: item for item in report["reports"]}
    assert report["exact_upstream_execution_verified"] is False
    assert by_key["hybrid"]["status"] == "local_adapter_only"
    assert by_key["react"]["status"] == "local_adapter_only"
    assert by_key["srag"]["status"] == "local_adapter_only"
    assert by_key["planrag"]["status"] == "dataset_mismatch"
    assert by_key["ircot"]["status"] in {"missing_runtime_artifacts", "available_but_not_executed"}


def test_baseline_specs_have_provenance_fields():
    assert {spec.key for spec in BASELINE_SPECS} == {
        "ircot",
        "planrag",
        "graphrag",
        "hybrid",
        "react",
        "srag",
    }
    for spec in BASELINE_SPECS:
        assert spec.path
        assert spec.source
        assert spec.execution_kind
        assert spec.comparability_note

