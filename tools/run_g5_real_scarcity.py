#!/usr/bin/env python3
"""G5 real-data budget-sensitivity check — are there scarce (budget-sensitive) slots on real 2-hop loads?

裁决12d boundary: pseudo-label differencing is stable on 4 synthetic chains
where S2 is scarce BY CONSTRUCTION. But on REAL hotpotqa-编译 plans, the
per-slot scarcity is unknown — real corpora are larger and truth distribution
is natural. This probe asks: on real 2+slot chains, does a budget sweep expose
any slot whose target truth is lost at low budget (budget-sensitive, ~=scarce)?

If yes: real pseudo-labels exist -> G5 estimator has real training signal.
If no: real plans have no budget-sensitive slots -> the synthetic differential
does not transfer; the scarcity regularity may be an artifact of the synthetic
fixture. Either result is reported honestly.

For each real problem that compiles to a >=2-slot plan, sweep the total budget
and record each slot's target-truth recovery threshold via extracted_rows (the
裁决12c signal). A slot is 'budget-sensitive/scarce' if its recovery threshold
exceeds its base (1) call.
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
    ap.add_argument("--dataset", type=str, default="hotpotqa")
    ap.add_argument("--split", type=str, default="validation")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--budgets", type=str, default="1,2,3,4,5,6")
    ap.add_argument("--first-window", type=int, default=3)
    ap.add_argument("--out", type=str, default="/tmp/g5_real_scarcity.json")
    args = ap.parse_args(argv[1:])
    _load_env()

    from slotrag.planner import SlotCompiler, AdaptiveExecutor, SlotMaterializer
    from slotrag.qo import compile_physical_plan, logical_plan_from_slot_plan
    from slotrag.action_policy import PhysicalActionPolicy
    from slotrag.models import Passage
    from slotrag.retrieval import HybridRetriever

    _cfg, (client, embedding, reranker) = _providers()
    cal = _calibrator()
    budgets = [int(b) for b in args.budgets.split(",") if b.strip()]

    data_path = ROOT / "benchmark" / args.dataset / ("%s_%s.jsonl" % (args.dataset, args.split))
    if not data_path.exists():
        print("missing %s" % data_path)
        return 1
    problems = []
    with open(data_path) as f:
        for line in f:
            problems.append(json.loads(line))
            if len(problems) >= args.n:
                break

    compiler = SlotCompiler(client)
    scarce_questions = []
    inspected = []  # >=2-slot plans that ran the sweep
    n_compile_fail = n_too_few = 0
    for prob in problems:
        q = prob["question"]
        passages = prob.get("passages") or []
        if not passages:
            continue
        try:
            plan, _cm = compiler.compile(q, answer_kind="short")
        except Exception:
            n_compile_fail += 1
            continue
        if len(plan.slots) < 2:
            n_too_few += 1
            continue
        # gold per slot? We don't have gold per slot cheaply; instead we treat a
        # slot as 'recovered' if ANY extraction materialized non-empty bindings at
        # that budget (target value found). Scarcity = needs >base calls.
        ps = [Passage(id=str(p["id"]), text=p["text"], doc_id=p["doc_id"]) for p in passages]
        retriever = HybridRetriever(
            passages=ps, embedding_client=embedding, reranker_client=reranker,
            bm25_k=20, dense_k=20, final_k=20, rrf_k=60,
            rerank_enabled=False, sparse_index_mode="body")

        # per budget, per slot: did any materialization produce bindings?
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
                ok = any(
                    mm.extracted_rows and len(mm.extracted_rows) > 0
                    for mm in t.materializations)
                slot_ok[t.slot_id] = ok
            for sid in slot_ok:
                recovered[budget].setdefault(sid, slot_ok[sid])

        # recovery threshold per slot = lowest budget where recovered
        thresholds = {}
        for sid in set().union(*[set(v.keys()) for v in recovered.values()]):
            thr = next((b for b in budgets if recovered[b].get(sid, False)), None)
            thresholds[sid] = thr
        scarce = {sid: thr for sid, thr in thresholds.items() if thr is not None and thr > 1}
        inspected.append({
            "qid": prob.get("id"), "question": q[:60], "n_slots": len(plan.slots),
            "thresholds": thresholds, "scarce_slots": scarce,
        })
        print("q=%s slots=%d thresholds=%s scarce=%s"
              % (prob.get("id")[:8], len(plan.slots), thresholds, list(scarce.keys())))
        if scarce:
            scarce_questions.append(prob.get("id"))

    n_real_plans = len(inspected)
    n_with_scarce = len(scarce_questions)
    print("\n=== real-data budget-sensitivity (%d problems, %s) ===" % (args.n, args.dataset))
    print("compile_fail=%d, <2-slot=%d, real 2+slot chains run=%d" % (n_compile_fail, n_too_few, n_real_plans))
    print("plans WITH budget-sensitive(scarce) slots: %d / %d" % (n_with_scarce, n_real_plans))
    if n_real_plans and n_with_scarce > 0:
        print("=> real pseudo-labels EXIST: G5 estimator has real training signal.")
    else:
        print("=> no budget-sensitive slots on real plans (or none ran): synthetic")
        print("   differential may not transfer; real scarcity is an open question.")

    Path(args.out).write_text(json.dumps({
        "config": {"dataset": args.dataset, "split": args.split, "n": args.n,
                   "budgets": budgets, "first_window": args.first_window},
        "counts": {"problems": args.n, "compile_fail": n_compile_fail, "too_few_slots": n_too_few,
                   "real_2plus_chains": n_real_plans, "with_scarce_slots": n_with_scarce},
        "inspected": inspected,
    }, ensure_ascii=False, indent=2))
    print("Wrote %s" % args.out)


if __name__ == "__main__":
    main()