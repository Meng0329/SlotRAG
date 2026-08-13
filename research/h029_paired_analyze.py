#!/usr/bin/env python3
"""Paired analysis: guard (control) vs guard-budget (H-029 treatment) on SEALED samples.

Reads per-item JSON for both methods across datasets, pairs by question_id,
and reports:
  * n paired / guard-only / budget-only
  * status mix per method (ok / budget_exceeded / other)
  * acc_full (all items, BE=0.0) and acc_ok (ok items only) per method
  * on paired items that guard=BUDGET_EXCEEDED: how many budget recovered to ok?
  * on paired items both ok: acc_ok diff (quality regression check)
  * retrieval_calls mean (cost transparency)
"""
import argparse, glob, json, collections, statistics

GUARD = "slotrag-grounded-frontier-perpath-guard"
BUDGET = "slotrag-grounded-frontier-perpath-guard-budget"
DATASETS = ["musique", "hotpotqa", "2wikimultihop", "drop"]


def load_items(root, ds, method):
    out = {}
    for f in glob.glob(f"{root}/items/tier3_sealed/{ds}/{method}/*.json"):
        if ".lock" in f:
            continue
        d = json.load(open(f))
        out[d["question_id"]] = d
    return out


def status(item):
    return (item.get("result") or {}).get("status")


def primary(item):
    s = item.get("scores") or {}
    # primary_score is the honest full-sample metric (BE=0.0)
    return s.get("primary_score", 0.0)


def metric(item, key):
    m = (item.get("result") or {}).get("metrics") or {}
    if not isinstance(m, dict):
        return 0
    return m.get(key, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--datasets", nargs="*", default=DATASETS)
    args = ap.parse_args()

    for ds in args.datasets:
        g = load_items(args.root, ds, GUARD)
        b = load_items(args.root, ds, BUDGET)
        common = sorted(set(g) & set(b))
        print(f"\n{'='*78}\n===== {ds}  (paired n={len(common)}, guard-only={len(set(g)-set(b))}, budget-only={len(set(b)-set(g))}) =====")

        # Status mix
        gs = collections.Counter(status(i) for i in g.values())
        bs = collections.Counter(status(i) for i in b.values())
        print(f"  status  guard={dict(gs)}  budget={dict(bs)}")

        # acc_full / acc_ok
        def acc(items):
            ok = [i for i in items.values() if status(i) == "ok"]
            full = sum(primary(i) for i in items.values()) / len(items) if items else 0
            okacc = sum(primary(i) for i in ok) / len(ok) if ok else 0
            return full, okacc, len(ok)
        gf, gok, gokn = acc(g)
        bf, bok, bokn = acc(b)
        print(f"  acc_full: guard={gf:.4f}  budget={bf:.4f}  (Δ={bf-gf:+.4f})")
        print(f"  acc_ok :  guard={gok:.4f} (n={gokn})  budget={bok:.4f} (n={bokn})  (Δ={bok-gok:+.4f})")

        # Recovery: items guard=BE, budget=?
        be_recovered = be_still = be_lost = 0
        be_recovered_scores = []
        for qid in common:
            if status(g[qid]) == "budget_exceeded":
                if status(b[qid]) == "ok":
                    be_recovered += 1
                    be_recovered_scores.append(primary(b[qid]))
                elif status(b[qid]) == "budget_exceeded":
                    be_still += 1
                else:
                    be_lost += 1
        print(f"  recovery from guard-BE: {be_recovered} recovered (mean score {statistics.mean(be_recovered_scores) if be_recovered_scores else 0:.4f}), {be_still} still BE, {be_lost} other")

        # Quality regression on both-ok items
        both_ok = [qid for qid in common if status(g[qid]) == "ok" and status(b[qid]) == "ok"]
        if both_ok:
            g_ok_scores = [primary(g[qid]) for qid in both_ok]
            b_ok_scores = [primary(b[qid]) for qid in both_ok]
            wins = sum(1 for a, z in zip(g_ok_scores, b_ok_scores) if z > a)
            losses = sum(1 for a, z in zip(g_ok_scores, b_ok_scores) if z < a)
            print(f"  both-ok n={len(both_ok)}: guard_acc={statistics.mean(g_ok_scores):.4f} budget_acc={statistics.mean(b_ok_scores):.4f} (Δ={statistics.mean(b_ok_scores)-statistics.mean(g_ok_scores):+.4f}, wins={wins} losses={losses} ties={len(both_ok)-wins-losses})")
            # previously-correct regression check
            reg = sum(1 for a, z in zip(g_ok_scores, b_ok_scores) if a >= 1.0 and z < 1.0)
            rec = sum(1 for a, z in zip(g_ok_scores, b_ok_scores) if a < 1.0 and z >= 1.0)
            print(f"   1.0→<1.0 regressions: {reg}   <1.0→1.0 recoveries: {rec}")

        # Cost
        grc = statistics.mean([metric(g[qid], "retrieval_calls") for qid in common]) if common else 0
        brc = statistics.mean([metric(b[qid], "retrieval_calls") for qid in common]) if common else 0
        gllm = statistics.mean([metric(g[qid], "llm_calls") for qid in common]) if common else 0
        bllm = statistics.mean([metric(b[qid], "llm_calls") for qid in common]) if common else 0
        print(f"  cost: retrieval_calls guard={grc:.2f} budget={brc:.2f}  |  llm_calls guard={gllm:.2f} budget={bllm:.2f}")


if __name__ == "__main__":
    main()
