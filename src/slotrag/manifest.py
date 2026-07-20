from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def code_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "uncommitted"


def build_manifest(config: Any, *, dataset: Path, strategy: str, mode: str, question_count: int) -> dict[str, Any]:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "code_revision": code_revision(),
        "dataset": str(dataset),
        "dataset_sha256": _sha256(dataset),
        "question_count": question_count,
        "strategy": strategy,
        "mode": mode,
        "config": config.public_dict(),
    }


def _sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return "unavailable"
    return digest.hexdigest()
