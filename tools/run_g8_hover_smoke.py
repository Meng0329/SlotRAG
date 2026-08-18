#!/usr/bin/env python3
"""G8 cross-task smoke — HoVer claim verification through the SlotRAG architecture.

证明: HoVer 等非 QA 任务无需重写核心 architecture 即可端到端执行。

Architecture path (zero core changes):
  claim → adapt_record → HybridRetriever(Wikipedia local corpus) →
  compile_slotrag_plan(answer_kind="boolean") → deterministic single-slot plan →
  SlotMaterializer → AdaptiveExecutor → generate_answer_response(True/False) →
  gold: SUPPORTED→True, NOT_SUPPORTED→False

Uses frozen-plan replay (same plan across arms) to isolate optimizer effect.
Reads HoVer dev set (hover_dev.json) and hotpotqa validation for shared corpus.
"""

from __future__ import annotations
import argparse, json, os, sys, time
from pathlib import Path
from collections import Counter

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
    ap = argparse.ArgumentParser(description="G8 HoVer claim-verification smoke")
    ap.add_argument("--hover-json", type=str, default="/tmp/hover_dev.json",
                    help="HoVer dev JSON (downloaded in §34)")
    ap.add_argument("--hotpotqa-jsonl", type=str,
                    default=str(ROOT / "benchmark" / "hotpotqa" / "hotpotqa_validation.jsonl"))
    ap.add_argument("--budget", type=int, default=6,
                    help="Matched retrieval budget (same as G7)")
    ap.add_argument("--max-claims", type=int, default=30,
                    help="Max claims to evaluate (subset for smoke)")
    ap.add_argument("--out", type=str, default="/tmp/g8_hover_smoke_result.json")
    args = ap.parse_args(argv[1:])
    _load_env()

    from slotrag.cli import load_config
    from slotrag.providers import provider_clients
    from slotrag.models import Passage, QuestionRecord
    from slotrag.retrieval import HybridRetriever
    from slotrag.benchmarking.methods import METHODS, compile_slotrag_plan, run_method

    cfg = load_config(ROOT / "configs" / "default.yaml")
    agnes, embedding, reranker = provider_clients(cfg)

    # Load HoVer dev and hotpotqa validation
    hover_recs = json.load(open(args.hover_json))
    hpqa_recs = {}
    for i, line in enumerate(open(args.hotpotqa_jsonl)):
        r = json.loads(line)
        hpqa_recs[r["id"]] = (r, i)

    # Filter to overlapping hpqa_ids (realistic frozen corpus)
    hpqa_to_hover = {}
    for hr in hover_recs:
        hpqa_id = hr.get("hpqa_id")
        if hpqa_id and hpqa_id in hpqa_recs:
            hpqa_to_hover.setdefault(hpqa_id, []).append(hr)

    # Balanced stratified sample: both labels, across hop counts (2/3/4).
    # A degenerate always-True system would score 100% on a SUPPORTED-only
    # sample; NOT_SUPPORTED claims prove the discriminator actually discriminates.
    import random
    random.seed(2027)
    all_eligible = [(hpqa_id, hr_list) for hpqa_id, hr_list in hpqa_to_hover.items()]
    by_label_hop: dict[tuple[str, int], list] = {}
    for hpqa_id, hr_list in all_eligible:
        hr = hr_list[0]
        key = (hr["label"], int(hr.get("num_hops", 2) or 2))
        by_label_hop.setdefault(key, []).append((hpqa_id, hr_list))
    eligible: list[tuple] = []
    n_cells = len(by_label_hop)
    per_key = max(1, args.max_claims // max(1, n_cells))
    for key in sorted(by_label_hop):
        pool = by_label_hop[key]
        random.shuffle(pool)
        eligible.extend(pool[:per_key])
    random.shuffle(eligible)
    eligible = eligible[:args.max_claims]
    print("balanced sample: %d claims (SUPPORTED %d / NOT_SUPPORTED %d) across %d label×hop cells" % (
        len(eligible),
        sum(1 for _, hlist in eligible if hlist[0]["label"] == "SUPPORTED"),
        sum(1 for _, hlist in eligible if hlist[0]["label"] == "NOT_SUPPORTED"),
        n_cells,
    ), flush=True)

    # HoVer gold mapping
    HOVER_GOLD = {"SUPPORTED": "True", "NOT_SUPPORTED": "False"}

    ARMS = ["slotrag-hover"]
    assert all(m in METHODS for m in ARMS), "G7 ablation methods not registered"

    results = []
    resumable = Path(args.out).exists()
    done_ids = set()
    if resumable:
        try:
            prior = json.load(open(args.out)).get("results", [])
            done_ids = {r["hover_uid"] for r in prior}
            results = list(prior)
            print("resume: %d claims already done" % len(done_ids), flush=True)
        except Exception:
            pass

    for hpqa_id, hover_list in eligible:
        # Use first hover claim per hpqa_id for this smoke
        hr = hover_list[0]
        hover_uid = hr["uid"]
        if hover_uid in done_ids:
            continue

        hpqa_prob, hpqa_idx = hpqa_recs[hpqa_id]
        gold_bool = HOVER_GOLD.get(hr["label"])
        if gold_bool is None:
            print("  !! skip %s: unknown label %s" % (hover_uid[:8], hr["label"]))
            continue

        # Build local corpus from hotpotqa record's passages
        ps = [Passage(id=str(p["id"]), text=p["text"], doc_id=p["doc_id"])
              for p in hpqa_prob.get("passages") or []]

        # QuestionRecord: claim as question, gold as True/False
        q = QuestionRecord(
            id=hover_uid,
            question=hr["claim"],
            answers=[gold_bool],
            passages=ps,
            metadata={"hover_label": hr["label"], "num_hops": hr.get("num_hops", "?"),
                       "hpqa_id": hpqa_id},
        )

        retriever = HybridRetriever(
            passages=ps, embedding_client=embedding, reranker_client=reranker,
            bm25_k=20, dense_k=20, final_k=20, rrf_k=60,
            rerank_enabled=False, sparse_index_mode="body")

        n_hpqa_passages = len(ps)
        num_hops = hr.get("num_hops", "?")
        print("\n=== %s hops=%s hpqa_passages=%d ===" % (hover_uid[:8], num_hops, n_hpqa_passages))
        print("  claim: %.90s" % hr["claim"])
        print("  gold:  %s (%s)" % (gold_bool, hr["label"]))

        # Compile plan once (frozen replay across arms)
        plan, cm = compile_slotrag_plan(METHODS["slotrag-hover"], "hover", q, agnes)
        n_slots = len(plan.slots)
        print("  plan: %d slots = %s" % (n_slots, [s.id for s in plan.slots]))

        per_arm = {}
        arm_err = None
        for m in ARMS:
            t0 = time.perf_counter()
            try:
                r = run_method(
                    m, dataset="hover", question=q, retriever=retriever,
                    client=agnes, config=cfg, seed=2027,
                    max_steps=4, max_retrieval_calls=args.budget,
                    frozen_plan=plan,
                )
            except Exception as exc:
                per_arm[m] = {"error": "%s: %s" % (type(exc).__name__, str(exc)[:200]),
                              "calls": None, "em": None}
                print("  %-22s ERROR %s" % (m, str(exc)[:80]))
                arm_err = True
                continue
            elapsed_ms = (time.perf_counter() - t0) * 1000
            ans = r.answer
            em = int(str(ans).strip().lower() == gold_bool.lower())
            calls = r.metrics.retrieval_calls if r.metrics else 0
            per_arm[m] = {
                "answer": ans, "em": em, "calls": calls,
                "n_rows": len(r.rows), "status": r.status,
                "elapsed_ms": round(elapsed_ms),
                "satisfied": sum(1 for e in r.evidence) if r.evidence else 0,
            }
            print("  %-22s calls=%d em=%d ans=%-6s rows=%d" % (m, calls, em, ans, len(r.rows)))

        results.append({
            "hover_uid": hover_uid, "hpqa_id": hpqa_id,
            "num_hops": num_hops, "label": hr["label"], "gold_bool": gold_bool,
            "claim": hr["claim"], "n_hpqa_passages": n_hpqa_passages,
            "n_slots": n_slots, "arms": per_arm,
        })

        # Checkpoint
        Path(args.out).write_text(json.dumps({
            "config": {"budget": args.budget, "arms": ARMS, "max_claims": args.max_claims},
            "n_claims": len(results), "incomplete": arm_err is not None,
            "results": results,
        }, ensure_ascii=False, indent=2, default=str))

    # Aggregate
    by_hops = {}
    for rec in results:
        h = rec.get("num_hops", "?")
        by_hops.setdefault(h, []).append(rec)

    print("\n" + "=" * 60)
    print("G8 HoVer claim-verification smoke — %d claims" % len(results))
    print("=" * 60)
    for hop, recs in sorted(by_hops.items()):
        hover_em = [r["arms"].get("slotrag-hover", {}).get("em") for r in recs
                    if r["arms"].get("slotrag-hover", {}).get("em") is not None]
        hover_calls = [r["arms"].get("slotrag-hover", {}).get("calls", 0) for r in recs
                       if r["arms"].get("slotrag-hover", {}).get("calls") is not None]
        print("\nhop=%s  n=%d" % (hop, len(recs)))
        if hover_em:
            print("  hover  EM=%.0f%%  calls=%.2f" % (100*sum(hover_em)/len(hover_em), sum(hover_calls)/len(hover_calls)))

    all_hover_em = [r["arms"].get("slotrag-hover", {}).get("em") for r in results
                    if r["arms"].get("slotrag-hover", {}).get("em") is not None]
    all_hover_calls = [r["arms"].get("slotrag-hover", {}).get("calls", 0) for r in results
                       if r["arms"].get("slotrag-hover", {}).get("calls") is not None]
    print("\nOverall hover EM=%.0f%% (%d/%d)  calls=%.2f" % (
        100*sum(all_hover_em)/max(1,len(all_hover_em)), sum(all_hover_em), len(all_hover_em),
        sum(all_hover_calls)/max(1,len(all_hover_calls))))

    # Write final
    summary = {
        "config": {"budget": args.budget, "arms": ARMS, "max_claims": args.max_claims},
        "n_claims": len(results),
        "overall_hover_em": float(sum(all_hover_em)/max(1,len(all_hover_em))),
        "overall_hover_calls": float(sum(all_hover_calls)/max(1,len(all_hover_calls))),
        "results": results,
    }
    Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    print("\nWrote %s" % args.out)


if __name__ == "__main__":
    main()
