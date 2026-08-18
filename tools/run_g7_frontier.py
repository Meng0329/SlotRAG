#!/usr/bin/env python3
"""G7 matched-budget frontier — honest run on the well-defined chains (benchmark method layer).

裁决12t/§24 established chain-law τ=2·depth−1 benefit on well-defined chains via the
*mechanism* harness (run_g5_chainrule_g3.py, direct optimizer/executor calls). This
script closes the G7 gap: it drives the SAME comparison through the *benchmark
method* layer (methods.run_method on the registered slotrag-g7-* family), proving
the optimizer is a real, end-to-end benchmark method — not just a harness extract.

Design (matches §24 + frozen protocol, honest):
  - Target: the 6 well-defined hotpotqa validation chains (末槽绑答案值, collector
    /tmp/g5_welldefined_tau_hotpotqa.json). These are the subdomain the chain-law is
    calibrated on; the deterministic benchmark sampler cannot reach them (they are
    excluded by its stratification at any size ≤50).
  - Frozen plan: compiled once per question via compile_slotrag_plan, then replayed
    (frozen_plan=...) identically across all arms — the ONLY variable is the
    physical-plan selection path (static compiler vs explicit optimizer).
  - Arms (matched budget, hybrid backend):
      static    = slotrag-g7-static      → compile_physical_plan
      cost-only = slotrag-g7-flat        → search_physical_plans, flat importance
      chain-rule= slotrag-g7-chain       → search_physical_plans, τ=2·depth−1
      chain-bm25= slotrag-g7-chain-bm25  → chain-rule + hybrid/bm25 per-slot variants
  - budget=max_retrieval_calls threads into the optimizer's retrieval_budget.
  - Metrics: realized retrieval_calls (cost) + answer EM + answer-bearing evidence
    coverage (quality). A Pareto WIN = strictly fewer calls at equal-or-better
    correctness/coverage.

Output: per-chain table + aggregate, JSON to --out. Uses real providers.
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
    for line in out.splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k, v)


def main(argv=None):
    argv = argv or sys.argv
    ap = argparse.ArgumentParser()
    ap.add_argument("--well-defined-json", type=str,
                    default="/tmp/g5_welldefined_tau_hotpotqa.json")
    ap.add_argument("--budget", type=int, default=6)
    ap.add_argument("--out", type=str, default="/tmp/g7_frontier_result.json")
    args = ap.parse_args(argv[1:])
    _load_env()

    from slotrag.cli import load_config
    from slotrag.providers import provider_clients
    from slotrag.models import Passage
    from slotrag.retrieval import HybridRetriever
    from slotrag.benchmarking.methods import METHODS, compile_slotrag_plan, run_method
    from slotrag.benchmarking.datasets import adapt_record, DATASETS
    from slotrag.planner import derive_evidence_state

    cfg = load_config(ROOT / "configs" / "default.yaml")
    agnes, embedding, reranker = provider_clients(cfg)

    wd = json.load(open(args.well_defined_json))
    by_qid = {str(r["qid"]): r for r in wd.get("well_defined", [])}

    ARMS = ["slotrag-g7-static", "slotrag-g7-flat",
            "slotrag-g7-chain", "slotrag-g7-chain-bm25"]
    assert all(m in METHODS for m in ARMS), "G7 ablation methods not registered"

    # load full validation split so we can pull each question's local passages
    data_path = ROOT / "benchmark" / "hotpotqa" / "hotpotqa_validation.jsonl"
    recs = {json.loads(line)["id"]: json.loads(line) for line in open(data_path)}
    idx = {json.loads(line)["id"]: i for i, line in enumerate(open(data_path))}

    results = []
    resumable = Path(args.out).exists()
    if resumable:
        try:
            prior = json.load(open(args.out)).get("results", [])
            done_qids = {r["qid"] for r in prior}
            results = [r for r in prior]
            print("resume: %d chains already done" % len(done_qids), flush=True)
        except Exception:
            done_qids, results = set(), []
    else:
        done_qids = set()
    for qid, meta in by_qid.items():
        if qid in done_qids:
            print("  (skip %s: in checkpoint)" % qid[:8], flush=True)
            continue
        prob = recs.get(qid)
        if prob is None:
            print("  !! missing %s in validation" % qid); continue
        # build a correct QuestionRecord via the dataset adapter (same as runner)
        q = adapt_record(DATASETS["hotpotqa"], prob, idx[qid], split="evaluation")
        ps = [Passage(id=str(p["id"]), text=p["text"], doc_id=p["doc_id"])
              for p in prob.get("passages") or []]
        retriever = HybridRetriever(
            passages=ps, embedding_client=embedding, reranker_client=reranker,
            bm25_k=20, dense_k=20, final_k=20, rrf_k=60,
            rerank_enabled=False, sparse_index_mode="body")
        # single deterministic compile (same for all arms)
        plan, _cm = compile_slotrag_plan(METHODS["slotrag-g7-static"], "hotpotqa",
                                          q, agnes)
        n_slots = len(plan.slots)
        imp = {("S%d" % i): 2 * i - 1 for i in range(1, n_slots + 1)}
        print("\n=== %s slots=%d importance=%s ===" % (qid[:8], n_slots, imp), flush=True)
        print("  q: %.70s" % prob["question"], flush=True)

        per_arm = {}
        arm_err = None
        for m in ARMS:
            try:
                r = run_method(
                    m, dataset="hotpotqa", question=q, retriever=retriever,
                    client=agnes, config=cfg, seed=2027,
                    max_steps=4, max_retrieval_calls=args.budget,
                    frozen_plan=plan,
                )
            except Exception as exc:  # service wedge — record and continue to next arm
                per_arm[m] = {"error": "%s: %s" % (type(exc).__name__, str(exc)[:200]),
                              "calls": None, "em": None}
                print("  %-22s ERROR %s: %s" % (m, type(exc).__name__, str(exc)[:120]), flush=True)
                arm_err = True
                continue
            st = r.status
            ans = r.answer
            gold = q.answers  # normalized answer list on the QuestionRecord
            em = int(ans is not None and any(
                str(g).strip().lower() == str(ans).strip().lower()
                for g in ([gold] if isinstance(gold, str) else (gold or []))))
            calls = r.metrics.retrieval_calls if r.metrics else 0
            ev = sorted(e.source_id for e in r.evidence)
            est = derive_evidence_state(plan, r)
            per_arm[m] = {
                "answer": ans, "em": em, "calls": calls,
                "evidence_ids": ev, "n_rows": len(r.rows),
                "status": st,
                "satisfied": est.satisfied_count() if est else 0,
            }
            print("  %-22s calls=%d em=%d ans=%s rows=%d" % (m, calls, em, ans, len(r.rows)), flush=True)
        results.append({"qid": qid, "n_slots": n_slots, "importance": imp,
                        "gold_answer": q.answers,
                        "arms": per_arm})
        # incremental checkpoint so a later wedge doesn't lose completed chains
        Path(args.out).write_text(json.dumps({
            "config": {"budget": args.budget, "arms": ARMS},
            "n_chains": len(results),
            "incomplete": arm_err is not None,
            "results": results,
        }, ensure_ascii=False, indent=2, default=str))

    # aggregate: paired diff chain-vs-static, chain-vs-flat on real->cited? use em + calls
    import numpy as np
    d_cr_static, d_cr_flat = [], []
    em_static, em_chain, em_flat = [], [], []
    cov_static, cov_chain = [], []
    for rec in results:
        a = rec["arms"]
        req = ["slotrag-g7-static", "slotrag-g7-flat", "slotrag-g7-chain"]
        if any(m not in a or a[m].get("em") is None for m in req):
            print("  (skip aggregate for %s: incomplete arm)" % rec["qid"][:8])
            continue
        s, f, c = a["slotrag-g7-static"], a["slotrag-g7-flat"], a["slotrag-g7-chain"]
        d_cr_static.append(c["calls"] - s["calls"])
        d_cr_flat.append(c["calls"] - f["calls"])
        em_static.append(s["em"]); em_flat.append(f["em"]); em_chain.append(c["em"])
    print("\n=== G7 frontier (%d chains, budget=%d) ===" % (len(results), args.budget))
    print("chain-vs-static calls delta: mean=%.2f positive(saves)=%d" %
          (float(np.mean(d_cr_static)), sum(1 for d in d_cr_static if d < 0)))
    print("chain-vs-flat   calls delta: mean=%.2f positive(saves)=%d" %
          (float(np.mean(d_cr_flat)), sum(1 for d in d_cr_flat if d < 0)))
    print("EM static=%.0f%% flat=%.0f%% chain=%.0f%%" %
          (100 * np.mean(em_static), 100 * np.mean(em_flat), 100 * np.mean(em_chain)))

    Path(args.out).write_text(json.dumps({
        "config": {"budget": args.budget, "arms": ARMS},
        "n_chains": len(results),
        "delta_calls_chain_minus_static_mean": float(np.mean(d_cr_static)),
        "delta_calls_chain_minus_flat_mean": float(np.mean(d_cr_flat)),
        "em_static": float(np.mean(em_static)), "em_flat": float(np.mean(em_flat)),
        "em_chain": float(np.mean(em_chain)),
        "results": results,
    }, ensure_ascii=False, indent=2, default=str))
    print("Wrote %s" % args.out)


if __name__ == "__main__":
    main()