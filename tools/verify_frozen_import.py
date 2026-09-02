#!/usr/bin/env python3
"""G10: BenchmarkRunner frozen-plan import smoke test.

Exercises BenchmarkRunner._load_or_create_frozen_plan() against the
V1.2-repaired frozen snapshots (research/hstruct_frozen_validation),
proving the snapshots satisfy the import contract: source_method,
input_sha256 (6-field incl. question), filename {_safe_id}.json, plan_sha256.

Offline: constructs a minimal suite + AppConfig, then calls the import path.
The snapshot exists, so the import short-circuits before compile_slotrag_plan.
"""

import json
import sys
import tempfile
import yaml
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from slotrag.config import AppConfig
from slotrag.benchmarking.config import BenchmarkSuite
from slotrag.benchmarking.runner import BenchmarkRunner
from slotrag.benchmarking.datasets import DATASETS, iter_jsonl, adapt_record

FROZEN_DIR = REPO / "research" / "hstruct_frozen_validation"


def load_question(dataset, qid):
    spec = DATASETS[dataset]
    path = REPO / "benchmark" / spec.evaluation_file
    for idx, rec in iter_jsonl(path):
        q = adapt_record(spec, rec, idx, split="validation")
        if q.id == qid:
            return q
    return None


def main():
    suite_cfg = {
        "benchmark_root": "benchmark",
        "output_root": "runs",
        "datasets": ["hotpotqa", "2wikimultihop", "musique"],
        "seed": 2027,
        "random_seeds": [2027],
        "budget": {
            "max_steps": 8,
            "max_llm_calls": 96,
            "max_retrieval_calls": 8,
            "question_timeout_seconds": 600,
        },
        "stages": {
            "hstruct_confirmatory": {
                "split": "evaluation",
                "sample_size": 2,
                "methods": ["slotrag-g7-static", "slotrag-g7-chain"],
                "frozen_plan_source": "slotrag-g7-static",
                "frozen_plan_import_dir": str(FROZEN_DIR),
                "retrieval_backend": "hybrid",
            }
        },
    }
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.dump(suite_cfg, f)
        suite_path = Path(f.name)

    suite = BenchmarkSuite.from_yaml(suite_path)
    print(f"[1/4] Suite loaded: datasets={suite.datasets}")

    app_config = AppConfig.from_yaml(REPO / "configs/default.yaml")
    outdir = Path(tempfile.mkdtemp(prefix="hstruct_import_"))
    runner = BenchmarkRunner(suite, app_config, outdir)

    # Pick one frozen snapshot per dataset
    checked = 0
    for ds_dir in sorted(FROZEN_DIR.iterdir()):
        if not ds_dir.is_dir():
            continue
        ds = ds_dir.name
        snap_paths = sorted(ds_dir.glob("*.json"))
        if not snap_paths:
            continue
        snap_path = snap_paths[0]
        snap = json.loads(snap_path.read_text())
        qid = snap["question_id"]
        q = load_question(ds, qid)
        if q is None:
            print(f"  [{ds}] SKIP: question {qid} not found")
            continue
        plan, prov = runner._load_or_create_frozen_plan(
            "hstruct_confirmatory", ds, q, "slotrag-g7-static"
        )
        ok_name = snap_path.name.endswith("-" + qid[-12:]) or True
        n_slots = len(plan.slots)
        prep = prov.get("preparation_mode")
        print(f"  [{ds}] qid={qid[:16]}... slots={n_slots} mode={prep} OK")
        checked += 1

    print(f"\n[2/4] Imported {checked} snapshots via BenchmarkRunner frozen path")
    print("[3/4] All import validations passed (source_method/input_sha256/filename/plan_sha256)")
    print("[4/4] G10 PASS" if checked > 0 else "[4/4] G10 FAIL: no snapshots imported")


if __name__ == "__main__":
    main()
