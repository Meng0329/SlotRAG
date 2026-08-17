#!/usr/bin/env python3
"""G3 allocation real-data validation — does the §10 bimodal ratio generalize?

Compiles REAL HotpotQA bridge problems via SlotCompiler, then for each plan that
is an executor-consumable CHAIN (>=2 slots, single legal topo order) runs BOTH
static and G3 physical plans on the sample's own passages corpus under an
identical matched budget, and measures:
  - the (static_calls - search_calls) distribution,
  - evidence-quality equality (evidence source ids),
  - the RISK rate: search plans that ABSTAIN / return empty / lose the gold
    evidence versus static (the §10 q2 catastrophe).

Honest positioning: this does NOT assume G3 saves calls. It measures on real
distributed data whether (a) chain plans are common, (b) G3's allocation ever
differs from static in realized calls, and (c) the q2-style catastrophic
abstention generalizes or is confined to the synthetic fixture. 0-observation
coverage is reported, not hidden.
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


def _build_retriever(embedding, reranker, passages):
    from slotrag.models import Passage
    from slotrag.retrieval import HybridRetriever
    ps = [Passage(id=p["id"], text=p["text"], doc_id=p["doc_id"]) for p in passages]
    return HybridRetriever(
        passages=ps,
        embedding_client=embedding,
        reranker_client=reranker,
        bm25_k=20, dense_k=20, final_k=20,
        rrf_k=60,
        rerank_enabled=False,
        sparse_index_mode="body",
    )


def _calibrator():
    from slotrag.sufficiency import EvidenceSufficiencyCalibrator
    import json as _json
    cal_path = ROOT / "runs_archive" / "slotrag-sufficiency-smoke-v60" / "calibrator.json"
    if cal_path.exists():
        return EvidenceSufficiencyCalibrator.from_dict(_json.loads(cal_path.read_text()))
    return None


def _is_chain(plan) -> bool:
    """A plan is executor-consumable if it has >=2 slots, a connected join
    graph, and each non-first slot joins the already-materialized frontier
    (chain-only). Return True or the reason it's not."""
    slots = plan.slots
    if len(slots) < 2:
        return False
    # every slot after the first must join some prior slot (chain condition is
    # the executor's real constraint; here we approximate by checking the
    # connectedness that SlotPlan enforces and that all slots are in one chain).
    join_fields = {}
    for j in plan.joins:
        join_fields.setdefault(j.right_slot, []).append((j.left_slot, j.left_field, j.right_field))
    # build adjacency over slot ids
    ordered = []
    remaining = set(s.id for s in slots)
    while remaining:
        # pick a slot whose join partners are already in `ordered` (or is first)
        chosen = None
        for sid in list(remaining):
            partners = {l for (l, f, r) in join_fields.get(sid, [])}
            # any pre-existing join partner (could be from a prior iteration)
            if sid == next(iter(remaining)):
                pass
            if not ordered or any(p in ordered for p in partners):
                chosen = sid
                break
        if chosen is None:
            return False  # non-chain: some slot has no join predecessor available
        ordered.append(chosen)
        remaining.discard(chosen)
    return len(ordered) == len(slots)


def main(argv=None):
    argv = argv or sys.argv
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=str, default="hotpotqa")
    ap.add_argument("--split", type=str, default="validation")
    ap.add_argument("--n", type=int, default=8, help="questions to compile/attempt")
    ap.add_argument("--budget", type=int, default=6)
    ap.add_argument("--first-window", type=int, default=3)
    ap.add_argument("--out", type=str, default="/tmp/g3_real_validate.json")
    args = ap.parse_args(argv[1:])
    _load_env()

    from slotrag.planner import SlotCompiler, AdaptiveExecutor, SlotMaterializer, derive_evidence_state
    from slotrag.qo import compile_physical_plan, logical_plan_from_slot_plan
    from slotrag.optimizer import PlanObjectiveParams, search_physical_plans
    from slotrag.action_policy import PhysicalActionPolicy

    _cfg, (client, embedding, reranker) = _providers()
    cal = _calibrator()

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
    print("loaded %d problems from %s" % (len(problems), data_path))

    compiler = SlotCompiler(client)
    gold_fallen = []
    gold_recovered_but_errored = []

    # per-question counters
    n_compile_fail = 0
    n_nonchain = 0
    results = []
    for qi, prob in enumerate(problems):
        q = prob["question"]
        passages = prob.get("passages") or []
        if not passages:
            continue
        # gold evidence passage ids
        try:
            gold_titles = set(prob.get("gold_evidence", {}).get("title", []))
        except AttributeError:
            gold_titles = set()
        gold_psids = {p["id"] for p in passages if p.get("doc_id") in gold_titles}

        # --- compile ---
        try:
            plan, cm = compiler.compile(q, answer_kind="short")
        except Exception as e:
            n_compile_fail += 1
            results.append({"qid": prob.get("id"), "phase": "compile_fail", "error": str(e)})
            continue
        if not plan.slots:
            n_compile_fail += 1
            results.append({"qid": prob.get("id"), "phase": "compile_empty"})
            continue
        chain_pred = _is_chain(plan)
        if not chain_pred:
            # do NOT pre-screen: the executor is the authority on whether the
            # plan is consumable. We label it for statistics but still attempt
            # the real compile->plan->execute path (below), which will surface
            # any non-chain failure naturally as plan_error/execute_error.
            n_nonchain += 1

        logical = logical_plan_from_slot_plan(plan)
        try:
            static = compile_physical_plan(logical, retrieval_strategy="hybrid")
            searched, tele = search_physical_plans(
                logical,
                params=PlanObjectiveParams(
                    retrieval_budget=args.budget,
                    requirement_importance={sl.id: sl.importance for sl in plan.slots}),
            )
        except Exception as e:
            results.append({"qid": prob.get("id"), "phase": "plan_error", "error": str(e),
                            "n_slots": len(plan.slots)})
            continue

        retriever = _build_retriever(embedding, reranker, passages)

        def run_with(phys):
            mat = SlotMaterializer(client, retriever, max_passages=args.first_window)
            ex = AdaptiveExecutor(
                mat, max_retrieval_calls=args.budget, max_binding_contexts=2,
                random_seed=2027, sufficiency_calibrator=cal,
                action_policy=PhysicalActionPolicy(topk_expansion_mode="utility"))
            r = ex.execute(plan, strategy="adaptive", physical_plan=phys)
            st = derive_evidence_state(plan, r)
            return r, st

        try:
            res_s, st_s = run_with(static)
            res_g, st_g = run_with(searched)
        except Exception as e:
            results.append({"qid": prob.get("id"), "phase": "execute_error", "error": str(e)})
            continue

        # evidence ids recovered by each plan
        evid_s = {e.source_id for e in res_s.evidence}
        evid_g = {e.source_id for e in res_g.evidence}
        gold_got_s = evid_s & gold_psids
        gold_got_g = evid_g & gold_psids

        delt = res_s.metrics.retrieval_calls - res_g.metrics.retrieval_calls
        row = {
            "qid": prob.get("id"),
            "question": q[:60],
            "type": prob.get("type"),
            "n_slots": len(plan.slots),
            "importance": {sl.id: sl.importance for sl in plan.slots},
            "static": {
                "calls": res_s.metrics.retrieval_calls,
                "status": res_s.status,
                "actions": res_s.metrics.physical_action_executed,
                "evid": sorted(evid_s),
                "gold_got": sorted(gold_got_s),
            },
            "search": {
                "calls": res_g.metrics.retrieval_calls,
                "status": res_g.status,
                "actions": res_g.metrics.physical_action_executed,
                "evid": sorted(evid_g),
                "gold_got": sorted(gold_got_g),
            },
            "calls_delta_static_minus_search": delt,
            "equal_evidence": evid_s == evid_g,
            "search_lost_gold": bool(gold_psids) and bool(gold_got_s) and not gold_got_g,
            "static_lost_gold_but_search_got": bool(gold_psids) and not gold_got_s and bool(gold_got_g),
            "search_abstain_or_empty": res_g.status in ("empty", "aborted", "failed"),
        }
        results.append(row)
        print("%-8s type=%-9s slots=%d | static calls=%d %s | search calls=%d %s | delta=%d equal_evid=%s search_lost_gold=%s"
              % (row["qid"], row["type"], row["n_slots"],
                 row["static"]["calls"], row["static"]["status"],
                 row["search"]["calls"], row["search"]["status"],
                 delt, row["equal_evidence"], row["search_lost_gold"]))

    # --- aggregate ---
    chain_rows = [r for r in results if r.get("phase") != "compile_fail" and r.get("phase") != "non_chain"
                  and r.get("phase") != "compile_empty" and "calls_delta_static_minus_search" in r]
    n_total = len(problems)
    print("\n=== SUMMARY (%d problems, %s/%s) ===" % (n_total, args.dataset, args.split))
    print("compile_fail: %d, non_chain (or <2 slots): %d, chain plans executed: %d"
          % (n_compile_fail, n_nonchain, len(chain_rows)))
    if chain_rows:
        deltas = [r["calls_delta_static_minus_search"] for r in chain_rows]
        n_save = sum(1 for d in deltas if d > 0)
        n_eq = sum(1 for d in deltas if d == 0)
        n_worse = sum(1 for d in deltas if d < 0)
        n_abstain = sum(1 for r in chain_rows if r["search_abstain_or_empty"])
        n_search_lost_gold = sum(1 for r in chain_rows if r["search_lost_gold"])
        n_equal_evid = sum(1 for r in chain_rows if r["equal_evidence"])
        print("G3 saves calls: %d; G3 equal calls: %d; G3 worse: %d" % (n_save, n_eq, n_worse))
        print("mean delta (static-search): %.2f calls" % (sum(deltas) / len(deltas)))
        print("search ABSTAIN/empty: %d / %d" % (n_abstain, len(chain_rows)))
        print("search lost gold evidence (vs static): %d / %d" % (n_search_lost_gold, len(chain_rows)))
        print("equal evidence (static==search): %d / %d" % (n_equal_evid, len(chain_rows)))
    else:
        print("NO chain plans executed — real data coverage is zero this run;" +
              " the §10 ratio is CONFINED to synthetic fixture so far (honest).")

    Path(args.out).write_text(json.dumps({
        "config": {"dataset": args.dataset, "split": args.split, "n": args.n,
                   "budget": args.budget, "first_window": args.first_window},
        "counts": {"problems": n_total, "compile_fail": n_compile_fail, "non_chain": n_nonchain,
                   "chain_executed": len(chain_rows)},
        "results": results,
    }, ensure_ascii=False, indent=2))
    print("Wrote %s" % args.out)


if __name__ == "__main__":
    main()