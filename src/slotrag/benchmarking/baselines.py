"""Machine-readable provenance and comparability audit for benchmark baselines.

The benchmark runner deliberately keeps local adapters separate from upstream
repositories.  This module makes that distinction explicit in manifests and
reports so a diagnostic adapter run cannot be presented as an exact paper
reproduction.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class BaselineSpec:
    key: str
    label: str
    path: str
    source: str
    execution_kind: str
    supported_datasets: tuple[str, ...]
    entrypoints: tuple[str, ...]
    required_paths: tuple[str, ...]
    comparability_note: str


BASELINE_SPECS: tuple[BaselineSpec, ...] = (
    BaselineSpec(
        key="ircot",
        label="IRCoT",
        path="baseline/ircot",
        source="StonyBrookNLP/ircot",
        execution_kind="upstream_repository",
        supported_datasets=("hotpotqa", "2wikimultihop", "musique", "iirc"),
        entrypoints=("reproduce.sh", "runner.py", "predict.py"),
        required_paths=("processed_data", "retriever_server", "requirements.txt"),
        comparability_note=(
            "The upstream code uses its processed_data format, Elasticsearch retriever, "
            "and the published IRCoT configs; the current benchmark does not provide an "
            "exact adapter for those artifacts."
        ),
    ),
    BaselineSpec(
        key="planrag",
        label="PlanRAG",
        path="baseline/PlanRAG",
        source="myeon9h/PlanRAG",
        execution_kind="upstream_repository",
        supported_datasets=("dqa_locating", "dqa_building"),
        entrypoints=("src/main.py", "config.json", "requirements.txt"),
        required_paths=("data/locating/questions/simulated_question.json", "data/building/questions/simulated_questions.json"),
        comparability_note=(
            "The released implementation evaluates DQA relational/graph scenarios, not "
            "HotpotQA, 2WikiMultiHopQA, MuSiQue, StrategyQA, or DROP."
        ),
    ),
    BaselineSpec(
        key="graphrag",
        label="Microsoft GraphRAG",
        path="baseline/graph_rag",
        source="microsoft/graphrag",
        execution_kind="upstream_repository",
        supported_datasets=(),
        entrypoints=("README.md", "pyproject.toml"),
        required_paths=("packages/graphrag",),
        comparability_note=(
            "GraphRAG is a corpus indexing/query pipeline. No upstream QA benchmark "
            "runner or official mapping for the current question records is present."
        ),
    ),
    BaselineSpec(
        key="hybrid",
        label="Hybrid RAG",
        path="baseline/hybrid_rag",
        source="repository-local",
        execution_kind="local_description_only",
        supported_datasets=(),
        entrypoints=("README.md",),
        required_paths=(),
        comparability_note="The directory contains a method description only; the executable used in the diagnostic run is src/slotrag/benchmarking/methods.py.",
    ),
    BaselineSpec(
        key="react",
        label="ReAct RAG",
        path="baseline/react_rag",
        source="repository-local",
        execution_kind="local_description_only",
        supported_datasets=(),
        entrypoints=("README.md",),
        required_paths=(),
        comparability_note="The directory contains a method description only; the executable used in the diagnostic run is src/slotrag/benchmarking/methods.py.",
    ),
    BaselineSpec(
        key="srag",
        label="SRAG",
        path="baseline/srag",
        source="repository-local",
        execution_kind="local_description_only",
        supported_datasets=(),
        entrypoints=("README.md",),
        required_paths=(),
        comparability_note="The directory contains a method description only; the executable used in the diagnostic run is src/slotrag/benchmarking/methods.py.",
    ),
)


def _git_revision(path: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_baselines(
    root: Path,
    benchmark_datasets: Iterable[str],
    *,
    specs: Iterable[BaselineSpec] = BASELINE_SPECS,
) -> dict[str, Any]:
    """Audit local baseline repositories without executing provider calls."""
    requested = sorted(set(benchmark_datasets))
    reports: list[dict[str, Any]] = []
    for spec in specs:
        path = root / spec.path
        missing_entrypoints = [item for item in spec.entrypoints if not (path / item).exists()]
        missing_required = [item for item in spec.required_paths if not (path / item).exists()]
        supported = sorted(set(requested) & set(spec.supported_datasets))
        unsupported = sorted(set(requested) - set(spec.supported_datasets))
        if spec.execution_kind == "local_description_only":
            status = "local_adapter_only"
        elif not path.exists():
            status = "missing_repository"
        elif missing_entrypoints or missing_required:
            status = "missing_runtime_artifacts"
        elif not supported:
            status = "dataset_mismatch"
        else:
            status = "available_but_not_executed"
        reports.append(
            {
                "key": spec.key,
                "label": spec.label,
                "path": str(path),
                "source": spec.source,
                "execution_kind": spec.execution_kind,
                "git_revision": _git_revision(path) if path.exists() else None,
                "path_exists": path.exists(),
                "entrypoints": list(spec.entrypoints),
                "missing_entrypoints": missing_entrypoints,
                "required_paths": list(spec.required_paths),
                "missing_required_paths": missing_required,
                "supported_requested_datasets": supported,
                "unsupported_requested_datasets": unsupported,
                "status": status,
                "exact_upstream_execution": False,
                "comparability_note": spec.comparability_note,
                "entrypoint_sha256": {
                    item: _sha256(path / item) for item in spec.entrypoints if (path / item).is_file()
                },
            }
        )
    return {
        "schema_version": 1,
        "benchmark_datasets": requested,
        "exact_upstream_execution_verified": False,
        "reports": reports,
    }

