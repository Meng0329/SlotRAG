import hashlib
import json

from slotrag.benchmarking.publication_gate import audit_publication_readiness


def _write_run(root, *, exact_upstream: bool, stage: str = "test", adapted: bool = False):
    trace_path = root / "traces" / stage / "hotpotqa" / "hybrid" / "q1" / "attempt-0001.jsonl"
    trace_path.parent.mkdir(parents=True)
    trace_path.write_text('{"schema_version":1}\n', encoding="utf-8")
    record = {
        "schema_version": 28,
        "dataset": "hotpotqa",
        "method": "hybrid",
        "method_label": "hybrid",
        "question_id": "q1",
        "attempt_index": 1,
        "result": {"status": "ok"},
        "provider_trace": {
            "enabled": True,
            "event_count": 1,
            "path": str(trace_path.relative_to(root)),
            "sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        },
    }
    item_path = root / "items" / stage / "hotpotqa" / "hybrid" / "q1.json"
    item_path.parent.mkdir(parents=True)
    item_path.write_text(json.dumps(record), encoding="utf-8")
    attempt_path = root / "attempts" / stage / "hotpotqa" / "hybrid" / "q1" / "attempt-0001.json"
    attempt_path.parent.mkdir(parents=True)
    attempt_path.write_text(json.dumps(record), encoding="utf-8")
    (root / "samples" / stage).mkdir(parents=True)
    (root / "samples" / stage / "hotpotqa.jsonl").write_text('{"id":"q1"}\n', encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({
        "suite": {
            "random_seeds": [1],
            "stages": {stage: {"sample_size": 1, "methods": ["hybrid"]}},
        },
        "run_requests": [{"stage": stage, "datasets": ["hotpotqa"], "methods": ["hybrid"]}],
        "comparison_validity": {"exact_upstream_execution_verified": exact_upstream},
    }), encoding="utf-8")
    (root / "matrix-manifest.json").write_text(json.dumps({
        "stage": stage, "jobs": [{"dataset": "hotpotqa", "method": "hybrid"}],
    }), encoding="utf-8")
    (root / "baseline-audit.json").write_text("{}", encoding="utf-8")
    if not adapted:
        (root / "adapter-audit.json").write_text("{}", encoding="utf-8")
    if adapted:
        (root / "adapter-audit.json").write_text(json.dumps({
            "schema_version": 1,
            "protocol": "shared_provider_adapted",
            "publication_scope": "adapted_protocol_only",
            "exact_upstream_execution_verified": False,
            "checks": {
                "same_question_sample": True,
                "same_provider_model": True,
                "same_retrieval_corpus": True,
                "same_answer_extraction": True,
                "raw_outputs_preserved": True,
                "attempts_and_failures_preserved": True,
            },
            "methods": {
                "hybrid": {
                    "execution_kind": "controlled_adapter",
                    "source": "repository-local",
                    "source_revision": "local",
                    "adaptation_notes": "controlled shared-provider adapter",
                },
            },
        }), encoding="utf-8")
    (root / "command.txt").write_text("test\n", encoding="utf-8")


def test_gate_keeps_complete_diagnostic_run_out_of_publication_claims(tmp_path):
    _write_run(tmp_path, exact_upstream=False)
    report = audit_publication_readiness(tmp_path, "test", require_trace=True, allow_diagnostic_adapters=True)
    assert report["analysis_ready"] is True
    assert report["publication_ready"] is False
    assert report["status"] == "diagnostic_complete"
    assert "upstream_baseline_execution_not_verified" in report["blocking_reasons"]


def test_gate_allows_exact_upstream_run(tmp_path):
    _write_run(tmp_path, exact_upstream=True)
    report = audit_publication_readiness(tmp_path, "test", require_trace=True)
    assert report["analysis_ready"] is True
    assert report["publication_ready"] is True
    assert report["status"] == "publication_ready"


def test_gate_labels_smoke_as_diagnostic_even_without_baselines(tmp_path):
    _write_run(tmp_path, exact_upstream=False, stage="main_comparison_smoke")
    report = audit_publication_readiness(tmp_path, "main_comparison_smoke", require_trace=True, allow_diagnostic_adapters=True)
    assert report["analysis_ready"] is True
    assert report["publication_ready"] is False
    assert report["status"] == "diagnostic_complete"


def test_gate_allows_explicit_adapted_protocol_only_with_opt_in(tmp_path):
    _write_run(tmp_path, exact_upstream=False, adapted=True)

    report = audit_publication_readiness(
        tmp_path,
        "test",
        require_trace=True,
        allow_adapted_protocol=True,
    )

    assert report["analysis_ready"] is True
    assert report["publication_ready"] is True
    assert report["publication_scope"] == "adapted_protocol_only"
    assert report["status"] == "publication_ready_adapted_protocol"


def test_gate_rejects_adapted_protocol_without_audit_file(tmp_path):
    _write_run(tmp_path, exact_upstream=False)

    report = audit_publication_readiness(
        tmp_path,
        "test",
        require_trace=True,
        allow_adapted_protocol=True,
    )

    assert report["publication_ready"] is False
    assert any(reason.startswith("adapted_protocol_invalid:") for reason in report["blocking_reasons"])
