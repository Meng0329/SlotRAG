#!/usr/bin/env python3
"""
fix_hstruct_frozen_snapshots.py — V1.2: Repair frozen-plan snapshot integrity

The V1.2 validation extraction (extract_validation_plans.py) saved snapshots with:
  - input_sha256 over a 5-field compile_input (MISSING the "question" field)
  - source_method = "slotrag"
  - filename = {question_id}.json

BenchmarkRunner._load_or_create_frozen_plan_locked() (runner.py:466-489) validates imports:
  1. imported.source_method must equal stage.frozen_plan_source
     (slotrag-g7-static for the confirmatory stage — see tkde-g7-frontier.yaml pattern)
  2. imported.input_sha256 must equal _canonical_sha256(_frozen_plan_input(...))
     which is a SIX-field dict: {stage, dataset, question_id, question, source_method, compiler_options}
  3. file must be named {_safe_id(question_id)}.json at import_dir/dataset/

This script repairs all snapshots in place:
  a. recompute input_sha256 with the full 6-field compile_input (incl. "question")
  b. set source_method to slotrag-g7-static (the confirmatory stage's frozen_plan_source)
  c. rename to _safe_id(question_id).json

The plan payload is untouched (plan_sha256 stays valid) because compiler_options
are identical across slotrag / slotrag-g7-static / slotrag-g7-chain (identity audit).

Usage:
    python tools/fix_hstruct_frozen_snapshots.py
"""

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from slotrag.data import load_questions
from slotrag.benchmarking.datasets import DATASETS as DATASET_SPECS
from slotrag.benchmarking.methods import METHODS, slotrag_compile_options
from slotrag.benchmarking.runner import _safe_id, _canonical_sha256

FROZEN_DIR = REPO / "research" / "hstruct_frozen_validation"
TARGET_SOURCE_METHOD = "slotrag-g7-static"  # frozen_plan_source of confirmatory stage
TARGET_DATASETS = ["hotpotqa", "2wikimultihop", "musique"]


def load_question_record(dataset: str, question_id: str):
    """Load full QuestionRecord from the evaluation (validation) benchmark file."""
    spec = DATASET_SPECS[dataset]
    path = REPO / "benchmark" / spec.evaluation_file
    if not path.exists():
        return None
    for q in load_questions(path):
        if q.id == question_id:
            return q
    return None


def main():
    print("=== Fix H-STRUCT Frozen Snapshots (V1.2) ===")
    print(f"Target source_method: {TARGET_SOURCE_METHOD}")
    print(f"Frozen dir: {FROZEN_DIR}")
    print()

    # Load all question records per dataset for the "question" field
    q_by_ds = {}
    for ds in TARGET_DATASETS:
        spec = DATASET_SPECS[ds]
        path = REPO / "benchmark" / spec.evaluation_file
        if not path.exists():
            print(f"  WARNING: {path} not found")
            continue
        q_by_ds[ds] = {q.id: q for q in load_questions(path)}
        print(f"  {ds}: {len(q_by_ds[ds])} validation records loaded")

    print()

    fixed = 0
    missing_q = 0
    errors = 0

    for ds in TARGET_DATASETS:
        snap_dir = FROZEN_DIR / ds
        if not snap_dir.exists():
            continue
        for old_path in sorted(snap_dir.glob("*.json")):
            try:
                snap = json.loads(old_path.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"  ERROR reading {old_path}: {e}")
                errors += 1
                continue

            qid = snap.get("question_id")
            if not qid:
                print(f"  ERROR missing question_id in {old_path}")
                errors += 1
                continue

            question = q_by_ds.get(ds, {}).get(qid)
            if question is None:
                print(f"  WARN: question {ds}/{qid} not found — leaving file (cannot recompute)")
                missing_q += 1
                continue

            # (a) recompute input_sha256 with full 6-field compile_input
            compile_input = {
                "stage": snap.get("stage", "hstruct-v12-census"),
                "dataset": ds,
                "question_id": qid,
                "question": question.question,
                "source_method": TARGET_SOURCE_METHOD,
                "compiler_options": slotrag_compile_options(METHODS[TARGET_SOURCE_METHOD], ds, question),
            }
            snap["input_sha256"] = _canonical_sha256(compile_input)

            # (b) relabel source_method
            snap["source_method"] = TARGET_SOURCE_METHOD
            snap["compiler_options"] = compile_input["compiler_options"]
            snap["preparation_mode"] = "v12_census_fixed"

            # (b2) recompute plan_sha256 with runner-identical canonical (ensure_ascii=False).
            #      The extraction used ensure_ascii=True; for plans containing non-ASCII
            #      text the two hashes diverge and the import plan-hash check would fail.
            snap["plan_sha256"] = _canonical_sha256(snap["plan"])

            # (c) rename to _safe_id(question_id).json
            new_path = snap_dir / f"{_safe_id(qid)}.json"
            if new_path != old_path:
                shutil.move(str(old_path), str(new_path))

            new_path.write_text(
                json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            fixed += 1

    print(f"\nDone: {fixed} snapshots fixed, {missing_q} missing question (skipped), {errors} errors")
    print("Next: verify with tests/test_hstruct_readiness.py::TestFrozenImportRoundtrip")


if __name__ == "__main__":
    main()
