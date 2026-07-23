"""Provenance checks for a shared-provider baseline adaptation protocol.

The repositories in ``baseline/`` do not all expose a runner for the five
question-answering datasets used by SlotRAG.  A controlled adapter can still
be useful for an explicitly labelled comparison, but it must carry enough
provenance to prevent it being reported as an exact upstream reproduction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .baselines import BASELINE_SPECS, audit_baselines


_REQUIRED_CHECKS = (
    "same_question_sample",
    "same_provider_model",
    "same_retrieval_corpus",
    "same_answer_extraction",
    "raw_outputs_preserved",
    "attempts_and_failures_preserved",
)

_ADAPTATION_NOTES = {
    "hybrid": (
        "Controlled shared-provider adapter: whole-question lexical+dense retrieval "
        "followed by the common answer generator; the local repository has no executable runner."
    ),
    "ircot": (
        "Controlled shared-provider adapter: bounded interleaved search/reasoning loop; "
        "the upstream Completion API, Elasticsearch index, and raw corpus are not invoked."
    ),
    "planrag": (
        "Controlled shared-provider adapter: one static multi-query plan followed by retrieval; "
        "the released PlanRAG code targets DQA scenarios and has no mapping for these QA records."
    ),
    "react": (
        "Controlled shared-provider adapter: bounded action/observation search loop; "
        "the repository-local directory contains a description rather than an executable runner."
    ),
    "srag": (
        "Controlled shared-provider adapter: structured late-join retrieval with bindings and "
        "replanning disabled; the repository-local directory contains a description only."
    ),
    "graphrag": (
        "Controlled shared-provider adapter: per-question lexical entity graph and PageRank "
        "over the supplied passages; the upstream GraphRAG package has no QA benchmark runner."
    ),
}


def build_adapter_audit(
    root: Path,
    benchmark_datasets: Iterable[str],
    methods: Iterable[str],
) -> dict[str, Any]:
    """Build a deterministic audit for an adapted comparison matrix."""
    requested_methods = list(dict.fromkeys(str(method) for method in methods))
    baseline_audit = audit_baselines(root, benchmark_datasets)
    reports = {str(item["key"]): item for item in baseline_audit["reports"]}
    method_reports: dict[str, dict[str, Any]] = {}
    for method in requested_methods:
        if method == "slotrag":
            method_reports[method] = {
                "execution_kind": "proposed_method",
                "source": "repository-local",
                "source_revision": baseline_audit.get("code_revision"),
                "adaptation_notes": "Proposed SlotRAG implementation under evaluation.",
            }
            continue
        report = reports.get(method)
        if report is None:
            method_reports[method] = {
                "execution_kind": "slotrag_ablation_or_unknown",
                "source": "repository-local",
                "source_revision": None,
                "adaptation_notes": "Method is not a registered external baseline.",
            }
            continue
        method_reports[method] = {
            "execution_kind": "controlled_adapter",
            "source": report.get("source"),
            "source_path": report.get("path"),
            "source_revision": report.get("git_revision"),
            "source_entrypoint_sha256": report.get("entrypoint_sha256", {}),
            "upstream_execution_kind": report.get("execution_kind"),
            "upstream_status": report.get("status"),
            "adaptation_notes": _ADAPTATION_NOTES.get(
                method,
                "Controlled shared-provider adapter; see source status and entrypoint hashes.",
            ),
        }
    return {
        "schema_version": 1,
        "protocol": "shared_provider_adapted",
        "publication_scope": "adapted_protocol_only",
        "exact_upstream_execution_verified": False,
        "benchmark_datasets": sorted(set(str(dataset) for dataset in benchmark_datasets)),
        "methods": method_reports,
        "checks": {name: True for name in _REQUIRED_CHECKS},
        "answer_extraction": "final_tag_or_think_suffix_v2",
        "retry_accounting": "immutable_attempts_and_final_records",
        "notes": (
            "This audit authorizes an adapted comparison table only. It does not authorize "
            "claims that the external repositories were executed exactly."
        ),
    }


def validate_adapter_audit(
    audit: dict[str, Any] | None,
    baseline_methods: Iterable[str],
) -> list[str]:
    """Return blocking reasons for an adapted protocol audit."""
    errors: list[str] = []
    if not isinstance(audit, dict):
        return ["audit_missing_or_invalid"]
    if audit.get("schema_version") != 1:
        errors.append("schema_version_invalid")
    if audit.get("protocol") != "shared_provider_adapted":
        errors.append("protocol_invalid")
    if audit.get("publication_scope") != "adapted_protocol_only":
        errors.append("publication_scope_invalid")
    if audit.get("exact_upstream_execution_verified") is not False:
        errors.append("exact_upstream_flag_must_be_false")
    checks = audit.get("checks")
    if not isinstance(checks, dict):
        errors.append("checks_missing_or_invalid")
    else:
        for name in _REQUIRED_CHECKS:
            if checks.get(name) is not True:
                errors.append(f"check_failed:{name}")
    methods = audit.get("methods")
    if not isinstance(methods, dict):
        errors.append("methods_missing_or_invalid")
        methods = {}
    for method in sorted(set(str(value) for value in baseline_methods)):
        entry = methods.get(method)
        if not isinstance(entry, dict):
            errors.append(f"method_missing:{method}")
            continue
        if entry.get("execution_kind") != "controlled_adapter":
            errors.append(f"method_kind_invalid:{method}")
        if not entry.get("source"):
            errors.append(f"method_missing_source:{method}")
        if not entry.get("source_revision"):
            errors.append(f"method_missing_source_revision:{method}")
        if not entry.get("adaptation_notes"):
            errors.append(f"method_missing_adaptation_notes:{method}")
    return sorted(set(errors))


__all__ = ["build_adapter_audit", "validate_adapter_audit"]
