#!/usr/bin/env python3
"""G5 S4 proxy-ground-truth diagnosis — does 'non-empty extract' proxy misfire on deep chains?

The real_scarcity probe labels a slot 'recovered' at budget b iff ANY materialization
has non-empty extracted_rows ('non-empty bindings' proxy). For the 2wiki 4-slot chain
(qid 298f23b8, answer 'El Extraño Viaje'), S4 τ came out 6 (vs 2d−1 expectation 7).

The proxy may MISFIRE two ways:
  (a) UNDERCOUNT τ: bindings are non-empty but do NOT contain the slot's target truth
      (answer tail value) → counts 'recovered' when truth not yet materialized.
  (b) Truly scarce: at b<6 S4 yields NO extracted rows at all → genuine scarcity.

This probe prints each budget's S4 (and neighbor) extracted_rows binding VALUES so we
can distinguish (a) from (b): if b=5 has non-empty bindings WITHOUT the answer value,
the τ=6 is a proxy artifact (true τ higher); if b=5 has empty bindings, τ=6 is real.
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
    ap.add_argument("--qid", type=str, default="298f23b8088a11ebbd6eac1f6bf848b6")
    ap.add_argument("--budgets", type=str, default="4,5,6,7")
    ap.add_argument("--first-window", type=int, default=3)
    ap.add_argument("--answer", type=str, default="El Extraño Viaje")
    ap.add_argument("--out", type=str, default="/tmp/g5_s4_proxy_diag.json")
    args = ap.parse_args(argv[1:])
    _load_env()

    from slotrag.planner import SlotCompiler, AdaptiveExecutor, SlotMaterializer
    from slotrag.action_policy import PhysicalActionPolicy
    from slotrag.models import Passage
    from slotrag.retrieval import HybridRetriever

    _cfg, (client, embedding, reranker) = _providers()
    cal = _calibrator()
    budgets = [int(b) for b in args.budgets.split(",") if b.strip()]

    data_path = ROOT / "benchmark" / "2wikimultihop" / "2wikimultihop_dev.jsonl"
    target = None
    with open(data_path) as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("id") == args.qid:
                target = rec
                break
    q = target["question"]
    passages = target.get("passages") or []
    ans = args.answer.strip().lower()
    compiler = SlotCompiler(client)
    plan, _cm = compiler.compile(q, answer_kind="short")

    ps = [Passage(id=str(p["id"]), text=p["text"], doc_id=p["doc_id"]) for p in passages]
    retriever = HybridRetriever(
        passages=ps, embedding_client=embedding, reranker_client=reranker,
        bm25_k=20, dense_k=20, final_k=20, rrf_k=60,
        rerank_enabled=False, sparse_index_mode="body")

    detail = {}
    for budget in budgets:
        mat = SlotMaterializer(client, retriever, max_passages=args.first_window)
        ex = AdaptiveExecutor(
            mat, max_retrieval_calls=budget, max_binding_contexts=2, random_seed=2027,
            sufficiency_calibrator=cal,
            action_policy=PhysicalActionPolicy(topk_expansion_mode="utility"))
        r = ex.execute(plan, strategy="adaptive", physical_plan=None)
        slot_info = {}
        for t in r.slot_traces:
            n_rows = 0
            bvals = []
            has_ans = False
            for mm in t.materializations:
                for er in mm.extracted_rows:
                    n_rows += 1
                    b = er.bindings
                    bvals.append(str(b))
                    for _, v in b.items():
                        if ans in str(v).strip().lower():
                            has_ans = True
            slot_info[t.slot_id] = {
                "n_extracted_rows": n_rows,
                "bindings": bvals,
                "contains_answer": has_ans,
            }
        detail[budget] = slot_info
        print("b=%d" % budget)
        for sid, si in slot_info.items():
            print("  %s rows=%d contains_answer=%s bindings=%s"
                  % (sid, si["n_extracted_rows"], si["contains_answer"],
                     json.dumps(si["bindings"], ensure_ascii=False)[:200]))

    Path(args.out).write_text(json.dumps(detail, ensure_ascii=False, indent=2,
                                         default=str))
    print("Wrote %s" % args.out)


if __name__ == "__main__":
    main()