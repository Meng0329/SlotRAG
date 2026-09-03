#!/usr/bin/env python3
"""Debug the frozen import hash mismatch."""
import json
import sys
import hashlib
import tempfile
import yaml
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, ".")

from slotrag.config import AppConfig
from slotrag.benchmarking.config import BenchmarkSuite
from slotrag.benchmarking.datasets import DATASETS, iter_jsonl, adapt_record
from slotrag.benchmarking.methods import METHODS, slotrag_compile_options

REPO = Path(".").resolve()
FROZEN = REPO / "research" / "hstruct_frozen_validation" / "2wikimultihop"


def canon(obj):
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


qid = "0163c021087511ebbd67ac1f6bf848b6"
spec = DATASETS["2wikimultihop"]
q = None
for idx, rec in iter_jsonl(REPO / "benchmark" / spec.evaluation_file):
    qq = adapt_record(spec, rec, idx, split="evaluation")
    if qq.id == qid:
        q = qq
        break
print("loaded q:", q.id, repr(q.question[:60]))

snap_file = sorted(FROZEN.glob("*-c86fd68ed3c2.json"))[0]
snap = json.loads(snap_file.read_text())
print("snapshot stage:", snap["stage"])
print("snapshot source_method:", snap["source_method"])
print("snapshot input_sha256:", snap["input_sha256"])

# What the runner computes for the import (source_stage = snap stage)
stage = snap["stage"]
sm = "slotrag-g7-static"
source_input = {
    "stage": stage,
    "dataset": "2wikimultihop",
    "question_id": qid,
    "question": q.question,
    "source_method": sm,
    "compiler_options": slotrag_compile_options(METHODS[sm], "2wikimultihop", q),
}
exp = canon(source_input)
print("runner-expected input_sha256:", exp)
print("MATCH:", exp == snap["input_sha256"])

if exp != snap["input_sha256"]:
    # What my fixup script computed — same stage value?
    print("snapshot stage in file:", snap.get("stage"))
    print("snapshot compiler_options match source_input?",
          snap.get("compiler_options") == source_input["compiler_options"])
