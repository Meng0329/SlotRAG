#!/usr/bin/env python3
"""G5 single-chain high-budget τ rescan — verify 2wiki 4-slot chain S4=6 truncation.

裁决12g: 2wiki 4-slot chain (298f23b8, "Which film has the director who was
born later...") showed τ={S1:1, S2:3, S3:5, S4:6}. If τ=2·depth−1 holds, S4
should be 7 — but the sweep ceiling was {1..6}, so 6 may be a truncation
artifact (true τ≥7 capped at 6), or a genuine saturation (retrieval recall
ceiling at depth 4).

This probe rescans that single chain with budget {1..10} to disambiguate:
  - S4=7 (or higher)  → truncation artifact; τ≈2d−1 holds to depth 4.
  - S4=6 (again)      → genuine saturation at depth 4; τ=2d−1 breaks on deep
                        chains (the 'S4' budget ceiling is a recall limit,
                        not a monotone linear growth).
Either outcome is written honestly to the ledger.
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
    ap.add_argument("--budgets", type=str, default="1,2,3,4,5,6,7,8,9,10")
    ap.add_argument("--first-window", type=int, default=3)
    ap.add_argument("--out", type=str, default="/tmp/g5_s4_rescan.json")
    args = ap.parse_args(argv[1:])
    _load_env()

    from slotrag.planner import SlotCompiler, AdaptiveExecutor, SlotMaterializer
    from slotrag.action_policy import PhysicalActionPolicy
    from slotrag.models import Passage
    from slotrag.retrieval import HybridRetriever

    _cfg, (client, embedding, reranker) = _providers()
    cal = _calibrator()
    budgets = [int(b) for b in args.budgets.split(",") if b.strip()]

    # find the chain in 2wiki dev
    data_path = ROOT / "benchmark" / "2wikimultihop" / "2wikimultihop_dev.jsonl"
    target = None
    with open(data_path) as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("id") == args.qid:
                target = rec
                break
    if target is None:
        print("HONEST: qid %s not found in 2wiki dev" % args.qid)
        return 1

    q = target["question"]
    passages = target.get("passages") or []
    compiler = SlotCompiler(client)
    plan, _cm = compiler.compile(q, answer_kind="short")
    print("q=%s slots=%d" % (args.qid[:8], len(plan.slots)))
    print("  q: %.80s" % q)

    ps = [Passage(id=str(p["id"]), text=p["text"], doc_id=p["doc_id"]) for p in passages]
    retriever = HybridRetriever(
        passages=ps, embedding_client=embedding, reranker_client=reranker,
        bm25_k=20, dense_k=20, final_k=20, rrf_k=60,
        rerank_enabled=False, sparse_index_mode="body")

    recovered = {b: {} for b in budgets}
    for budget in budgets:
        mat = SlotMaterializer(client, retriever, max_passages=args.first_window)
        ex = AdaptiveExecutor(
            mat, max_retrieval_calls=budget, max_binding_contexts=2, random_seed=2027,
            sufficiency_calibrator=cal,
            action_policy=PhysicalActionPolicy(topk_expansion_mode="utility"))
        r = ex.execute(plan, strategy="adaptive", physical_plan=None)
        slot_ok = {}
        for t in r.slot_traces:
            ok = any(mm.extracted_rows and len(mm.extracted_rows) > 0
                     for mm in t.materializations)
            slot_ok[t.slot_id] = ok
        for sid in slot_ok:
            recovered[budget].setdefault(sid, slot_ok[sid])
        print("  b=%d slot_ok=%s" % (budget, slot_ok))

    thresholds = {}
    for sid in set().union(*[set(v.keys()) for v in recovered.values()]):
        thr = next((b for b in budgets if recovered[b].get(sid, False)), None)
        thresholds[sid] = thr

    print("\n=== S4 rescan (budget {1..10}) ===")
    for sid in sorted(thresholds):
        pos = int(sid[1:]) if sid[1:].isdigit() else None
        expect = 2 * pos - 1 if pos else None
        note = ""
        if expect and thresholds[sid] is not None and thresholds[sid] > expect:
            note = "  > expected 2d-1=%d (deviation)" % expect
        elif expect and thresholds[sid] is not None and thresholds[sid] < expect:
            note = "  < expected 2d-1=%d (deviation)" % expect
        print("  %s τ=%s (2d-1=%s)%s" % (sid, thresholds[sid], expect, note))
    s4 = thresholds.get("S4")
    if s4 is None:
        verdict = "S4 unrecoverable in {1..10} (τ=∞)"
    elif s4 >= 7:
        verdict = "S4=τ≥7 → sweep-truncation confirmed, τ=2d−1 holds to depth 4"
    else:
        verdict = "S4=τ=6 → genuine saturation at depth 4, τ=2d−1 breaks on deep chains"
    print("\nVERDICT: %s" % verdict)

    Path(args.out).write_text(json.dumps({
        "qid": args.qid, "budgets": budgets,
        "recovered_per_budget": recovered, "thresholds": thresholds,
        "verdict": verdict,
    }, ensure_ascii=False, indent=2))
    print("Wrote %s" % args.out)


if __name__ == "__main__":
    main()