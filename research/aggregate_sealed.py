#!/usr/bin/env python3
"""Fast streaming aggregation of SEALED run items.

Usage: python3 research/aggregate_sealed.py [--cache] [b1 b2 b3 ...]
Reads only (question_id, method_label, status, primary_score) per item, one pass.
With --cache, writes a compact .agg.jsonl per run dir for fast re-aggregation.
"""
import argparse, glob, json, collections
from pathlib import Path


def aggregate(base: str) -> dict:
    """Return {dataset: {method: {n, n_ok, n_be, acc_full, acc_ok}}}"""
    out: dict[str, dict] = {}
    for f in glob.glob(f"{base}/items/tier3_sealed/*/*/*.json"):
        # path: .../items/tier3_sealed/{ds}/{method_label}/{qid}.json
        parts = f.split("/")
        ds = parts[-3]
        mlabel = parts[-2]
        try:
            d = json.load(open(f))
        except Exception:
            continue
        m = d.get("method_label", mlabel).split("/")[-1]
        st = (d.get("result") or {}).get("status")
        ps = (d.get("scores") or {}).get("primary_score")
        cell = out.setdefault(ds, {}).setdefault(m, {"n":0, "n_ok":0, "n_be":0, "acc_full":0.0, "acc_ok":0.0, "sum_full":0.0, "sum_ok":0.0})
        cell["n"] += 1
        if st == "ok":
            cell["n_ok"] += 1
            if ps is not None:
                cell["sum_ok"] += ps
        elif st == "budget_exceeded":
            cell["n_be"] += 1
        if ps is not None:
            cell["sum_full"] += ps
    for ds, methods in out.items():
        for m, c in methods.items():
            c["acc_full"] = c["sum_full"] / c["n"] if c["n"] else 0
            c["acc_ok"] = c["sum_ok"] / c["n_ok"] if c["n_ok"] else 0
            del c["sum_full"], c["sum_ok"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    args = ap.parse_args()
    for r in args.runs:
        a = aggregate(r)
        print(f"=== {r} ===")
        for ds in ["hotpotqa", "2wikimultihop", "musique", "drop"]:
            if ds not in a:
                continue
            print(f"  {ds}:")
            for m in sorted(a[ds]):
                c = a[ds][m]
                print(f"    {m:50s} n={c['n']:4d} ok={c['n_ok']:4d} be={c['n_be']:4d} acc_full={c['acc_full']:.4f} acc_ok={c['acc_ok']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
