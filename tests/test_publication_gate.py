import hashlib
import json

from slotrag.benchmarking.publication_gate import audit_publication_readiness
from slotrag.models import SlotPlan


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


def test_gate_keeps_training_split_available_for_analysis_but_not_publication(tmp_path):
    _write_run(tmp_path, exact_upstream=True)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["suite"]["stages"]["test"]["split"] = "train"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = audit_publication_readiness(tmp_path, "test", require_trace=True)

    assert report["analysis_ready"] is True
    assert report["publication_ready"] is False
    assert report["publication_claim_allowed"] is False
    assert report["status"] == "analysis_ready_nonpublication"
    assert report["data_split"] == "train"
    assert "training_split_not_for_publication" in report["blocking_reasons"]


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


def test_gate_rejects_ablation_with_invalid_existing_sample_audit(tmp_path):
    stage = "component_ablation"
    _write_run(tmp_path, exact_upstream=True, stage=stage)
    (tmp_path / "sample-audit.json").write_text(json.dumps({
        "schema_version": 1,
        "valid": False,
        "all_overlap_count": 0,
        "all_missing_from_source_count": 1,
    }), encoding="utf-8")

    report = audit_publication_readiness(tmp_path, stage, require_trace=True)

    assert report["publication_ready"] is False
    assert "invalid_sample_audit" in report["blocking_reasons"]


def test_gate_rejects_question_deadline_timeout_as_infrastructure_failure(tmp_path):
    _write_run(tmp_path, exact_upstream=True)
    item_path = tmp_path / "items" / "test" / "hotpotqa" / "hybrid" / "q1.json"
    attempt_path = tmp_path / "attempts" / "test" / "hotpotqa" / "hybrid" / "q1" / "attempt-0001.json"
    record = json.loads(item_path.read_text(encoding="utf-8"))
    record["result"] = {
        "status": "budget_exceeded",
        "error": "question timeout exceeded (300s)",
    }
    item_path.write_text(json.dumps(record), encoding="utf-8")
    attempt_path.write_text(json.dumps(record), encoding="utf-8")

    report = audit_publication_readiness(tmp_path, "test", require_trace=True)

    assert report["analysis_ready"] is False
    assert report["publication_ready"] is False
    assert report["status"] == "blocked"
    assert report["infrastructure_failures"] == {
        "question_timeout_count": 1,
        "question_timeout_cells": [
            {"dataset": "hotpotqa", "method": "hybrid", "count": 1},
        ],
    }
    assert "infrastructure_question_timeouts:1" in report["blocking_reasons"]


def test_gate_rejects_replay_hash_not_backed_by_frozen_snapshot(tmp_path):
    _write_run(tmp_path, exact_upstream=True)
    source_plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "Source", "arguments": ["?answer"]}],
        "outputs": ["?answer"],
    }).model_dump(mode="json")
    raced_plan = SlotPlan.model_validate({
        "slots": [{"id": "S1", "predicate": "Raced", "arguments": ["?answer"]}],
        "outputs": ["?answer"],
    }).model_dump(mode="json")

    def plan_hash(plan):
        payload = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    item_path = tmp_path / "items" / "test" / "hotpotqa" / "hybrid" / "q1.json"
    record = json.loads(item_path.read_text(encoding="utf-8"))
    raced_hash = plan_hash(raced_plan)
    record["result"].update({
        "plan": raced_plan,
        "metrics": {"frozen_plan_replays": 1},
    })
    record["plan_provenance"] = {
        "status": "ok",
        "source_method": "slotrag",
        "plan_sha256": raced_hash,
        "effective_plan_sha256": raced_hash,
    }
    item_path.write_text(json.dumps(record), encoding="utf-8")
    attempt_path = tmp_path / "attempts" / "test" / "hotpotqa" / "hybrid" / "q1" / "attempt-0001.json"
    attempt_path.write_text(json.dumps(record), encoding="utf-8")

    snapshot_path = tmp_path / "plans" / "test" / "hotpotqa" / "q1.json"
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_text(json.dumps({
        "status": "ok",
        "source_method": "slotrag",
        "plan_sha256": plan_hash(source_plan),
        "plan": source_plan,
        "compiler_metrics": {},
    }), encoding="utf-8")

    report = audit_publication_readiness(tmp_path, "test", require_trace=True)

    assert report["publication_ready"] is False
    assert report["status"] == "blocked"
    assert report["frozen_plan_audit"]["unknown_snapshot_hash_count"] == 1
    assert "frozen_plan_unknown_snapshot_hash" in report["blocking_reasons"]
