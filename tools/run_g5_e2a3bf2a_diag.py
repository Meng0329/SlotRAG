#!/usr/bin/env python3
"""G5 e2a3bf2a S2 binding diagnosis — why does S2 not bind the answer '12 June 1516'?

裁决12h cited e2a3bf2a ('When did John V, Prince Of Anhalt-Zerbst's father die?',
answer '12 June 1516') as the POSITIVE example of a well-defined chain where the
last slot (S2) binds the answer value. The well-defined collector (12h+1)
measured ans_bearing=[] for S2 — a contradiction. Either 12h's claim was
inference-not-measured, or the token-match is too strict.

This probe runs the chain once at budget≥3 (S2 τ=3) and dumps S2's actual
extracted_rows binding values so we can see what S2 binds and whether the answer
is truly absent or just in a non-matching surface form.
"""

from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def _load_env():
    import subprocess
    env_path = ROOT / ".env"
    if not env_path.exists():
        raise SystemExit("missing .env")
    shellsafe = '"' + str(env_path) + '"'
    out = subprocess.check_output(
        ["bash", "-c", "set -a; .  %s ; set +a; env" % shellsafe], text=True)
    loaded = {}
    for line in out.splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        loaded[k] = v
    for k, v in loaded.items():
        os.environ.setdefault(k, v)


def _providers():
    from slotrag.cli import load_config
    from slotrag.providers import provider_clients
    cfg = load_config(ROOT / "configs" / "default.yaml")
    return cfg, provider_clients(cfg)


def _calibrator():
    from slotrag.sufficiency import EvidenceSufficiencyCalibrator
    import json as _json
    cal_path = ROOT / "runs_archive" / "slotrag-sufficiency-smoke-v60" / "calibrator.json"
    if cal_path.exists():
        return EvidenceSufficiencyCalibrator.from_dict(_json.loads(cal_path.read_text()))
    return None


def main(argv=None):
    argv = argv or sys.argv
    ap = argparse.ArgumentParser()
    ap.add_argument("--qid", type=str, default="e2a3bf2a0bdd11eba7f7acde48001122")
    ap.add_argument("--budget", type=int, default=3)
    ap.add_argument("--first-window", type=int, default=3)
    ap.add_argument("--out", type=str, default="/tmp/g5_e2a3bf2a_diag.json")
    args = ap.parse_args(argv[1:])
    _load_env()

    from slotrag.planner import SlotCompiler, AdaptiveExecutor, SlotMaterializer
    from slotrag.action_policy import PhysicalActionPolicy
    from slotrag.models import Passage
    from slotrag.retrieval import HybridRetriever

    _cfg, (client, embedding, reranker) = _providers()
    cal = _calibrator()

    data_path = ROOT / "benchmark" / "2wikimultihop" / "2wikimultihop_dev.jsonl"
    target = None
    with open(data_path) as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("id") == args.qid:
                target = rec
                break
    q = target["question"]
    ans = target.get("answers") or target.get("answer")
    passages = target.get("passages") or []
    compiler = SlotCompiler(client)
    plan, _cm = compiler.compile(q, answer_kind="short")
    print("q=%s answer='%s'" % (args.qid[:8], ans))
    print("slots=%d predicates: %s" % (len(plan.slots), [s.predicate for s in plan.slots]))

    ps = [Passage(id=str(p["id"]), text=p["text"], doc_id=p["doc_id"]) for p in passages]
    retriever = HybridRetriever(
        passages=ps, embedding_client=embedding, reranker_client=reranker,
        bm25_k=20, dense_k=20, final_k=20, rrf_k=60,
        rerank_enabled=False, sparse_index_mode="body")
    mat = SlotMaterializer(client, retriever, max_passages=args.first_window)
    ex = AdaptiveExecutor(
        mat, max_retrieval_calls=args.budget, max_binding_contexts=2, random_seed=2027,
        sufficiency_calibrator=cal,
        action_policy=PhysicalActionPolicy(topk_expansion_mode="utility"))
    r = ex.execute(plan, strategy="adaptive", physical_plan=None)

    print("\n=== slot traces (budget=%d) ===" % args.budget)
    detail = {}
    for t in r.slot_traces:
        bvals = []
        srcs = []
        for mm in t.materializations:
            for er in mm.extracted_rows:
                bvals.append(er.bindings)
                srcs.append(str(er.source_id))
        detail[t.slot_id] = {"bindings": bvals, "sources": srcs}
        print("  %s:" % t.slot_id)
        for b, s in zip(bvals, srcs):
            print("     bind=%s src=%s" % (json.dumps(b, ensure_ascii=False)[:160], s[:60]))

    Path(args.out).write_text(json.dumps(detail, ensure_ascii=False, indent=2, default=str))
    print("Wrote %s" % args.out)


if __name__ == "__main__":
    main()