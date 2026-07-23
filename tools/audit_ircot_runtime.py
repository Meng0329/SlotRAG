#!/usr/bin/env python3
"""Create a non-destructive IRCoT upstream runtime/data preflight report."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_revision(path: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _file_info(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "bytes": path.stat().st_size if path.is_file() else None,
        "sha256": _sha256(path),
    }
    if path.is_file():
        try:
            info["nonempty_lines"] = sum(1 for line in path.open(encoding="utf-8") if line.strip())
        except (OSError, UnicodeError):
            info["nonempty_lines"] = None
    return info


def _imports(python: Path) -> dict[str, Any]:
    code = "import _jsonnet, pandas, requests, openai, elasticsearch"
    try:
        subprocess.check_output([str(python), "-c", code], stderr=subprocess.STDOUT, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        output = getattr(exc, "output", "") or str(exc)
        return {"ok": False, "error": output.strip()[-1000:]}
    return {"ok": True, "error": None}


def _probe(url: str, timeout: float = 3.0) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"url": url, "ok": True, "status": response.status, "error": None}
    except urllib.error.HTTPError as exc:
        return {"url": url, "ok": False, "status": exc.code, "error": str(exc)}
    except (OSError, urllib.error.URLError) as exc:
        return {"url": url, "ok": False, "status": None, "error": f"{exc.__class__.__name__}: {exc}"}


def build_report(root: Path, python: Path) -> dict[str, Any]:
    processed = root / "processed_data"
    official = root / "official_evaluation"
    datasets = ("hotpotqa", "2wikimultihopqa", "musique", "iirc")
    processed_files = [
        _file_info(processed / dataset / name)
        for dataset in datasets
        for name in ("dev.jsonl", "dev_subsampled.jsonl", "test_subsampled.jsonl")
    ]
    config_files = [
        _file_info(root / ".retriever_address.jsonnet"),
        _file_info(root / ".llm_server_address.jsonnet"),
        _file_info(root / "reproduce.sh"),
        _file_info(root / "runner.py"),
        _file_info(root / "predict.py"),
    ]
    official_revisions = {
        dataset: _git_revision(official / dataset) for dataset in ("hotpotqa", "2wikimultihopqa", "musique")
    }
    raw_dir = root / "raw_data"
    raw_files = sorted(path for path in raw_dir.rglob("*") if path.is_file()) if raw_dir.exists() else []
    runtime = {
        "python": str(python),
        "python_version": subprocess.check_output([str(python), "--version"], text=True, stderr=subprocess.STDOUT).strip()
        if python.exists()
        else None,
        "imports": _imports(python) if python.exists() else {"ok": False, "error": "python_not_found"},
    }
    services = {
        "elasticsearch": _probe("http://127.0.0.1:9200/_cluster/health"),
        "retriever": _probe("http://127.0.0.1:8000/"),
        "llm_server": _probe("http://127.0.0.1:8010/"),
    }
    llm_contract = {
        "upstream_expected": "OpenAI Completion API with code-davinci-002",
        "candidate_service": "Qwen3.6-27B Chat Completions",
        "exact_api_compatible": False,
        "reason": "Qwen endpoint exposes /v1/chat/completions; IRCoT upstream calls openai.Completion.create(engine=code-davinci-002).",
    }
    missing_processed = [item["path"] for item in processed_files if not item["exists"] or not item.get("bytes")]
    missing_services = [name for name, status in services.items() if not status["ok"]]
    blockers = []
    if missing_processed:
        blockers.append("processed_data_missing_or_empty")
    if not raw_files or not any(path.stat().st_size > 0 for path in raw_files):
        blockers.append("raw_data_missing")
    if not runtime["imports"]["ok"]:
        blockers.append("runtime_imports_missing")
    if missing_services:
        blockers.append("upstream_services_unavailable:" + ",".join(sorted(missing_services)))
    if not llm_contract["exact_api_compatible"]:
        blockers.append("llm_api_contract_mismatch")
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "baseline": "ircot",
        "repository": str(root),
        "git_revision": _git_revision(root),
        "entrypoints": config_files,
        "processed_data": processed_files,
        "official_evaluation_revisions": official_revisions,
        "raw_data": {"directory": str(raw_dir), "file_count": len(raw_files), "files": [_file_info(path) for path in raw_files[:100]]},
        "runtime": runtime,
        "services": services,
        "llm_contract": llm_contract,
        "execution": {
            "write_config_command": "PATH=<ircot-env>/bin:$PATH <ircot-env>/bin/python runner.py ircot_qa codex hotpotqa write --prompt_set 1",
            "prediction_command": "./reproduce.sh ircot_qa codex hotpotqa",
            "prediction_executed": False,
        },
        "blockers": sorted(blockers),
        "exact_upstream_execution_verified": False,
        "ready_for_exact_execution": not blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("baseline/ircot"))
    parser.add_argument("--python", type=Path, default=Path("baseline/ircot/.venv/bin/python"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.root, args.python)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "blockers": report["blockers"], "ready_for_exact_execution": report["ready_for_exact_execution"]}, ensure_ascii=False))
    return 0 if report["ready_for_exact_execution"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
