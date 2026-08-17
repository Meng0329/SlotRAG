#!/usr/bin/env python3
"""G5 paired statistics for G3(chain-rule) vs static/flat.

裁决 12o: benefit domain = ≥3-slot chains, RARE; 2-slot = 0 savings (pinned).
This script computes, per-chain, the paired difference in retrieval_calls between
chain-rule and each reference (static, flat), then reports:
  - wins/ties/losses (paired, per-question_id, following statistics.py convention)
  - Cliff's delta (dominance), mean & median diff
  - paired bootstrap CI (2.5/97.5) and two-sided p (rejected-bootstrap proportion,
    Holm-corrected across the 2 comparisons)
Mirrors src/slotrag/benchmarking/statistics.py:paired_bootstrap grammar so headlined
numbers stay consistent with the repo's established protocol. Sign convention:
difference = reference − chain_rule  →  positive diff = chain-rule saves calls.

This is a LOW-cost (CPU-only) analysis over an already-ran experiment's results JSON.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _holm(cmp_list: list[dict]) -> None:
    """Holm-Bonferroni correction in-place on p_value (mirror statistics.py)."""
    m = len(cmp_list)
    if not m:
        return
    order = sorted(range(m), key=lambda i: cmp_list[i]["p_value"])
    for rank, idx in enumerate(order):
        cmp_list[idx]["p_holm"] = min(1.0, cmp_list[idx]["p_value"] * (m - rank))


def _paired(diffs: np.ndarray, name: str, reference: str, iterations: int, seed: int):
    """differences = reference − chain_rule; lower-is-better ⇒ positive diff is a win."""
    rng = np.random.default_rng(seed)
    wins = int(np.sum(diffs > 0))
    ties = int(np.sum(np.isclose(diffs, 0.0)))
    losses = len(diffs) - wins - ties
    pairw = diffs[:, None] - diffs[None, :]
    cliffs = float((np.sum(pairw > 0) - np.sum(pairw < 0)) / pairw.size)
    if len(diffs) < 2:
        return {"comparison": name, "reference": reference, "count": len(diffs),
                "mean_difference": float(diffs.mean()), "median_difference": float(np.median(diffs)),
                "wins": wins, "ties": ties, "losses": losses, "win_rate": wins / len(diffs),
                "cliffs_delta": cliffs, "ci_low": None, "ci_high": None, "p_value": None}
    indices = rng.integers(0, len(diffs), size=(iterations, len(diffs)))
    boot = diffs[indices].mean(axis=1)
    p_value = min(1.0, 2 * min(float(np.mean(boot <= 0)), float(np.mean(boot >= 0))))
    return {"comparison": name, "reference": reference, "count": len(diffs),
            "mean_difference": float(diffs.mean()), "median_difference": float(np.median(diffs)),
            "wins": wins, "ties": ties, "losses": losses, "win_rate": wins / len(diffs),
            "cliffs_delta": cliffs, "ci_low": float(np.percentile(boot, 2.5)),
            "ci_high": float(np.percentile(boot, 97.5)), "p_value": p_value}


def main(argv=None):
    argv = argv or sys.argv
    ap = argparse.ArgumentParser()
    ap.add_argument("--result-json", default="/tmp/g5_chainrule_result_v1.json")
    ap.add_argument("--iterations", type=int, default=100_000)
    ap.add_argument("--seed", type=int, default=2027)
    ap.add_argument("--out", default="/tmp/g5_chainrule_stats.json")
    args = ap.parse_args(argv[1:])
    d = json.load(open(args.result_json))
    results = d.get("results", [])

    # per (qid, run): collect the three arms' child-metrics (agg over runs -> per qid diff)
    per_qid = {}  # qid -> (static_calls, flat_calls, cr_calls, rows[])
    for rec in results:
        qid = str(rec["qid"])
        agg = {"static": [], "flat": [], "chain_rule": []}
        for row in rec["rows"]:
            agg["static"].append(row["static"]["calls"])
            agg["flat"].append(row["flat"]["calls"])
            agg["chain_rule"].append(row["chain_rule"]["calls"])
        per_qid[qid] = {
            "n_slots": rec["n_slots"], "tau": rec["tau"],
            "static": float(np.mean(agg["static"])),
            "flat": float(np.mean(agg["flat"])),
            "chain_rule": float(np.mean(agg["chain_rule"])),
            "n_runs": len(rec["rows"]),
        }

    qids = sorted(per_qid)
    d_cr_static = np.asarray([per_qid[q]["static"] - per_qid[q]["chain_rule"] for q in qids])
    d_cr_flat = np.asarray([per_qid[q]["flat"] - per_qid[q]["chain_rule"] for q in qids])

    # Determinism: intra-chain spread of the arm-specific raw calls across repeats.
    # Zero spread => savings are structural, not sampling noise.
    spread = []
    for rec in results:
        for arm in ("static", "flat", "chain_rule"):
            vals = [row[arm]["calls"] for row in rec["rows"]]
            spread.append(max(vals) - min(vals))
    max_spread = max(spread) if spread else 0
    n_zero_spread = sum(1 for s in spread if s == 0)

    comparisons = [
        _paired(d_cr_static, "chain_rule", "static", args.iterations, args.seed),
        _paired(d_cr_flat, "chain_rule", "flat", args.iterations, args.seed),
    ]
    _holm(comparisons)

    # ≥3-slot subdomain = the law's predicted benefit domain (12l/12o).
    sub_qids = [q for q in qids if per_qid[q]["n_slots"] >= 3]
    sub_comps = []
    if sub_qids:
        sd_s = np.asarray([per_qid[q]["static"] - per_qid[q]["chain_rule"] for q in sub_qids])
        sd_f = np.asarray([per_qid[q]["flat"] - per_qid[q]["chain_rule"] for q in sub_qids])
        sub_comps = [
            _paired(sd_s, "chain_rule", "static", args.iterations, args.seed),
            _paired(sd_f, "chain_rule", "flat", args.iterations, args.seed),
        ]
        _holm(sub_comps)

    print("=== G3(chain-rule) vs static/flat  (paired, %d qids, budget=%d) ==="
          % (len(qids), d["config"]["budget"]))
    print("lower-is-better calls; positive diff => chain-rule saves (win).\n")
    print("[determinism] across all chains x arms: n_intra_samples=%d, zero_spread=%d/%d, max_spread=%d"
          % (len(spread), n_zero_spread, len(spread), max_spread))
    print("  (zero spread => identical calls every repeat => structural, not noise)\n")
    for c in comparisons:
        ci = "" if c["ci_low"] is None else "  CI[%.3f, %.3f]  p=%.4f (holm=%.4f)" % (
            c["ci_low"], c["ci_high"], c["p_value"], c.get("p_holm", c["p_value"]))
        print("  ALL  %-11s vs %-6s n=%2d  mean=%.3f med=%.3f  W/T/L=%d/%d/%d  d=%.3f%s"
              % (c["comparison"], c["reference"], c["count"],
                 c["mean_difference"], c["median_difference"],
                 c["wins"], c["ties"], c["losses"], c["cliffs_delta"], ci))
    print("  --- ≥3-slot subdomain (predicted benefit domain) ---")
    if sub_comps:
        for c in sub_comps:
            ci = "" if c["ci_low"] is None else "  CI[%.3f, %.3f]  p=%.4f (holm=%.4f)" % (
                c["ci_low"], c["ci_high"], c["p_value"], c.get("p_holm", c["p_value"]))
            print("  >=3  %-11s vs %-6s n=%2d  mean=%.3f med=%.3f  W/T/L=%d/%d/%d  d=%.3f%s"
                  % (c["comparison"], c["reference"], c["count"],
                     c["mean_difference"], c["median_difference"],
                     c["wins"], c["ties"], c["losses"], c["cliffs_delta"], ci))
    else:
        print("  (no ≥3-slot chains in sample)")
    print("\nper-chain:")
    for q in qids:
        p = per_qid[q]
        s, f, c_ = p["static"], p["flat"], p["chain_rule"]
        print("  %s slots=%d n_runs=%d: static=%.0f flat=%.0f cr=%.0f  saves_vs_static=%+.1f"
              % (q[:10], p["n_slots"], p["n_runs"], s, f, c_, s - c_))

    Path(args.out).write_text(json.dumps(
        {"config": dict(d["config"]), "n_qids": len(qids), "comparisons": comparisons,
         "subdomain_ge3": sub_comps, "determinism": {"n_intra_samples": len(spread),
                                                     "zero_spread": n_zero_spread,
                                                     "max_spread": max_spread},
         "per_chain": per_qid}, ensure_ascii=False, indent=2))
    print("\nWrote %s" % args.out)


if __name__ == "__main__":
    main()