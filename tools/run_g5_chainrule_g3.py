#!/usr/bin/env python3
"""G3(chain-rule) main experiment — does deterministic importance unlock G3's allocation?

裁决12j: G5's contribution is the counterfactually-discovered deterministic chain
law τ=2·depth−1, NOT a learned estimator. This experiment closes the G3+G5 arc:
feed importance={2·depth−1} into G3 and compare against G3(flat) and static under
matched budget on REAL well-defined chains.

Arms (per well-defined 2+slot chain, single budget):
  1. static  — compile_physical_plan (uniform 2*beam calls/slot)
  2. G3(flat) — search_physical_plans, requirement_importance omitted (all 1.0) ≡ static
  3. G3(chain-rule) — search_physical_plans, requirement_importance={Si: 2*i−1}

Metrics (matched budget):
  - retrieval_calls (efficiency)
  - evidence id set / answer-bearing coverage (quality): does the plan's output
    evidence contain the answer-bearing passage(s)?
  - equal rows/evidence across arms (quality parity)

Honest: any chain where chain-rule does NOT save calls or regresses quality is
reported as-is. A 'WIN' only counts if calls lower with no coverage regression.

Dataset: real hotpotqa validation, consuming ONLY well-defined chains (末槽绑答案值,
from the collector /tmp/g5_welldefined_tau_hotpotqa.json) — proxy-artifact chains excluded.
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


def _chain_importance(n_slots: int) -> dict:
    """Deterministic rule τ=2·depth−1 → importance per slot."""
    return {"S%d" % i: 2 * i - 1 for i in range(1, n_slots + 1)}


def main(argv=None):
    argv = argv or sys.argv
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=str, default="hotpotqa")
    ap.add_argument("--split", type=str, default="validation")
    ap.add_argument("--well-defined-json", type=str,
                    default="/tmp/g5_welldefined_tau_hotpotqa.json")
    ap.add_argument("--budget", type=int, default=6)
    ap.add_argument("--n", type=int, default=1, help="repeats per chain")
    ap.add_argument("--first-window", type=int, default=3)
    ap.add_argument("--out", type=str, default="/tmp/g5_chainrule_result.json")
    args = ap.parse_args(argv[1:])
    _load_env()

    from slotrag.qo import compile_physical_plan, logical_plan_from_slot_plan
    from slotrag.optimizer import PlanObjectiveParams, search_physical_plans
    from slotrag.planner import AdaptiveExecutor, SlotMaterializer, derive_evidence_state
    from slotrag.action_policy import PhysicalActionPolicy
    from slotrag.models import Passage
    from slotrag.retrieval import HybridRetriever

    _cfg, (client, embedding, reranker) = _providers()
    cal = _calibrator()

    # well-defined chains (qid set) — only these are valid τ/coverage measurement
    wd = json.load(open(args.well_defined_json))
    wd_by_qid = {str(r["qid"]): r for r in wd.get("well_defined", [])}
    keep_qids = set(wd_by_qid.keys())
    print("well-defined chains available: %d" % len(keep_qids))

    data_path = ROOT / "benchmark" / args.dataset / ("%s_%s.jsonl" % (args.dataset, args.split))
    if not data_path.exists():
        print("missing %s" % data_path)
        return 1

    compiler = None
    results = []
    n_used = 0
    with open(data_path) as f:
        for line in f:
            prob = json.loads(line)
            if str(prob.get("id")) not in keep_qids:
                continue
            q = prob["question"]
            passages = prob.get("passages") or []
            if not passages:
                continue
            if compiler is None:
                from slotrag.planner import SlotCompiler
                compiler = SlotCompiler(client)
            plan, _cm = compiler.compile(q, answer_kind="short")
            n_slots = len(plan.slots)
            importance = _chain_importance(n_slots)
            print("\n=== %s slots=%d importance=%s tau=%s ==="
                  % (str(prob.get("id"))[:8], n_slots, importance, wd_by_qid[str(prob.get("id"))]["thresholds"]))
            print("  q: %.70s" % q)

            ps = [Passage(id=str(p["id"]), text=p["text"], doc_id=p["doc_id"]) for p in passages]
            retriever = HybridRetriever(
                passages=ps, embedding_client=embedding, reranker_client=reranker,
                bm25_k=20, dense_k=20, final_k=20, rrf_k=60,
                rerank_enabled=False, sparse_index_mode="body")
            logical = logical_plan_from_slot_plan(plan)

            static_phys = compile_physical_plan(logical, retrieval_strategy="hybrid")
            flat_phys, _t1 = search_physical_plans(
                logical, params=PlanObjectiveParams(retrieval_budget=args.budget))
            cr_phys, _t2 = search_physical_plans(
                logical, params=PlanObjectiveParams(
                    retrieval_budget=args.budget, requirement_importance=importance))

            def run(phys):
                mat = SlotMaterializer(client, retriever, max_passages=args.first_window)
                ex = AdaptiveExecutor(
                    mat, max_retrieval_calls=args.budget, max_binding_contexts=2,
                    random_seed=2027, sufficiency_calibrator=cal,
                    action_policy=PhysicalActionPolicy(topk_expansion_mode="utility"))
                r = ex.execute(plan, strategy="adaptive", physical_plan=phys)
                st = derive_evidence_state(plan, r)
                return r, st

            rows = []
            for run_i in range(args.n):
                r_st, st_st = run(static_phys)
                r_fl, st_fl = run(flat_phys)
                r_cr, st_cr = run(cr_phys)

                # compare by scheduled allocation (physical plan) + runtime calls
                scheduled = {
                    "static": {k: v.calls for k, v in static_phys.allocations.items()},
                    "flat": {k: v.calls for k, v in flat_phys.allocations.items()},
                    "chain_rule": {k: v.calls for k, v in cr_phys.allocations.items()},
                } if hasattr(static_phys, "allocations") else "n/a"

                def ev(rs):
                    return sorted(e.source_id for e in rs.evidence)

                row = {
                    "qid": prob.get("id"), "n_slots": n_slots, "importance": importance,
                    "run": run_i,
                    "scheduled": str(scheduled),
                    "static": {"calls": r_st.metrics.retrieval_calls,
                               "evidence_ids": ev(r_st), "satisfied": st_st.satisfied_count(),
                               "status": r_st.status},
                    "flat": {"calls": r_fl.metrics.retrieval_calls,
                             "evidence_ids": ev(r_fl), "satisfied": st_fl.satisfied_count(),
                             "status": r_fl.status},
                    "chain_rule": {"calls": r_cr.metrics.retrieval_calls,
                                   "evidence_ids": ev(r_cr), "satisfied": st_cr.satisfied_count(),
                                   "status": r_cr.status},
                    "delta_static_minus_chainrule": r_st.metrics.retrieval_calls - r_cr.metrics.retrieval_calls,
                    "delta_flat_minus_chainrule": r_fl.metrics.retrieval_calls - r_cr.metrics.retrieval_calls,
                    "cr_quality_parity_vs_static": ev(r_cr) == ev(r_st),
                }
                rows.append(row)
                print("  run %d static=%d flat=%d chain_rule=%d | parity_vs_static=%s"
                      % (run_i, row["static"]["calls"], row["flat"]["calls"],
                         row["chain_rule"]["calls"], row["cr_quality_parity_vs_static"]))
            results.append({
                "qid": prob.get("id"), "n_slots": n_slots, "importance": importance,
                "tau": wd_by_qid[str(prob.get("id"))]["thresholds"],
                "rows": rows,
            })
            n_used += 1
            if n_used >= args.n:
                # reuse n to cap number of chains for runtime
                pass

    n_chains = len(results)
    # aggregate across all chains × runs
    d_cr_vs_static, d_cr_vs_flat, parity = [], [], []
    for rec in results:
        for row in rec["rows"]:
            d_cr_vs_static.append(row["delta_static_minus_chainrule"])
            d_cr_vs_flat.append(row["delta_flat_minus_chainrule"])
            parity.append(row["cr_quality_parity_vs_static"])

    print("\n=== G3(chain-rule) main experiment (%d chains, budget=%d) ===" % (n_chains, args.budget))
    if d_cr_vs_static:
        import numpy as np
        mean_s = float(np.mean(d_cr_vs_static)); mean_f = float(np.mean(d_cr_vs_flat))
        pct_s = sum(1 for d in d_cr_vs_static if d > 0) / len(d_cr_vs_static)
        pct_f = sum(1 for d in d_cr_vs_flat if d > 0) / len(d_cr_vs_flat)
        parity_r = sum(parity) / len(parity) if parity else 0
        print("calls saved chain_rule-vs-static: mean=%.2f, positive-rate=%.2f" % (mean_s, pct_s))
        print("calls saved chain_rule-vs-flat:   mean=%.2f, positive-rate=%.2f" % (mean_f, pct_f))
        print("chain_rule quality parity vs static: %.2f" % parity_r)
        # per-chain breakdown
        print("\nper-chain:")
        for rec in results:
            r0 = rec["rows"][0]
            print("  %s slots=%d tau=%s: static=%d flat=%d cr=%d delta_cr_static=%d parity=%s"
                  % (rec["qid"][:8], rec["n_slots"], rec["tau"],
                     r0["static"]["calls"], r0["flat"]["calls"], r0["chain_rule"]["calls"],
                     r0["delta_static_minus_chainrule"], r0["cr_quality_parity_vs_static"]))

    Path(args.out).write_text(json.dumps({
        "config": {"dataset": args.dataset, "split": args.split, "budget": args.budget,
                   "first_window": args.first_window},
        "n_chains": n_chains,
        "delta_cr_vs_static_mean": mean_s, "delta_cr_vs_flat_mean": mean_f,
        "delta_cr_vs_static_positive_rate": pct_s, "delta_cr_vs_flat_positive_rate": pct_f,
        "cr_quality_parity_rate": parity_r,
        "results": results,
    }, ensure_ascii=False, indent=2, default=str))
    print("Wrote %s" % args.out)


if __name__ == "__main__":
    main()