import json
from pathlib import Path

from slotrag.benchmarking.adapted_protocol import (
    build_adapter_audit,
    validate_adapter_audit,
)


def test_adapter_audit_is_explicit_about_shared_protocol_and_upstream_limits():
    report = build_adapter_audit(Path.cwd(), ["hotpotqa", "drop"], ["slotrag", "hybrid", "ircot"])

    assert report["protocol"] == "shared_provider_adapted"
    assert report["publication_scope"] == "adapted_protocol_only"
    assert report["exact_upstream_execution_verified"] is False
    assert report["checks"]["same_question_sample"] is True
    assert report["methods"]["ircot"]["execution_kind"] == "controlled_adapter"
    assert not validate_adapter_audit(report, ["hybrid", "ircot"])


def test_adapter_audit_rejects_missing_method_provenance():
    report = build_adapter_audit(Path.cwd(), ["hotpotqa"], ["slotrag", "hybrid"])
    del report["methods"]["hybrid"]["adaptation_notes"]

    errors = validate_adapter_audit(report, ["hybrid"])

    assert "method_missing_adaptation_notes:hybrid" in errors
