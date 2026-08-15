#!/usr/bin/env python3
"""Phase 4 main-table recompute after full guard-budget rerun.

Reuses b1 guard (runs/slotrag-phase4-trace-b1) as the pre-fix baseline and the
new guard-budget (runs/slotrag-phase4-budget-full) as the post-fix method.
Both share identical qid samples (symlinked), so the comparison is paired.

Reports per dataset: acc_full guard->budget, acc_ok, BE counts, Δ vs strongest
baseline, and the WIN/TIE/LOSS judgment vs SEALED-matched baselines.
Coverage = fraction of cells where guard-budget beats the strongest baseline.
"""
import json, glob, sys
from dataclasses import dataclass

# SEALED-matched strongest baselines (from audit §6.1, verified against b1 items)
BASELINES = {
    "musique":       ("ircot",      0.5263),
    "hotpotqa":      ("graphrag",   0.8124),
    "2wikimultihop": ("ircot",      0.7449),
    "drop":          ("graphrag",   0.7246),
}
GUARD_DIR = "runs/slotrag-phase4-trace-b1"
BUDGET_DIR = "runs/slotrag-phase4-budget-full"

def load(ds, method, base):
    out = {}
    for f in glob.glob(f"{base}/items/tier3_sealed/{ds}/{method}/*.json"):
        d = json.load(open(f)); r = d["result"]
        out[d["question_id"]] = {
            "status": r.get("status"),
            "answer": r.get("answer"),
            "score": d["scores"].get("primary_score") or 0.0,
        }
    return out

def main():
    datasets = ["musique", "hotpotqa", "2wikimultihop", "drop"]
    print(f"{'ds':<12} {'acc_full g→b':<18} {'acc_ok g→b':<18} {'BE g→b':<12} {'baseline':<16} {'Δ_budget':<10} verdict")
    print("-" * 100)
    wins = 0; cells = 0
    for ds in datasets:
        guard = load(ds, "slotrag-grounded-frontier-perpath-guard", GUARD_DIR)
        budget = load(ds, "slotrag-grounded-frontier-perpath-guard-budget", BUDGET_DIR)
        common = set(guard) & set(budget)
        if not common:
            print(f"{ds}: (budget run incomplete, n={0})")
            continue
        cells += 1
        n = len(common)
        # acc_full = mean over all common items (BE=0)
        g_full = sum(guard[q]["score"] for q in common)/n
        b_full = sum(budget[q]["score"] for q in common)/n
        # acc_ok = mean over ok
        g_ok = [guard[q]["score"] for q in common if guard[q]["status"]=="ok"]
        b_ok = [budget[q]["score"] for q in common if budget[q]["status"]=="ok"]
        g_ok_mean = sum(g_ok)/len(g_ok) if g_ok else 0
        b_ok_mean = sum(b_ok)/len(b_ok) if b_ok else 0
        g_be = sum(1 for q in common if guard[q]["status"]=="budget_exceeded")
        b_be = sum(1 for q in common if budget[q]["status"]=="budget_exceeded")
        # baseline
        bmap, bacc = BASELINES[ds]
        delta = b_full - bacc
        verdict = "WIN" if delta > 0.03 else ("LOSS" if delta < -0.03 else "TIE")
        if delta > 0.03: wins += 1
        print(f"{ds:<12} {g_full:.4f}->{b_full:.4f} ({delta:+.3f} vs base) {g_ok_mean:.4f}->{b_ok_mean:.4f} {g_be}->{b_be} {bmap}({bacc:.4f}) {delta:+.4f} {verdict}")
    print("-" * 100)
    print(f"Coverage (budget vs strongest baseline, Δ>0.03 point): {wins}/{cells} = {wins/cells*100:.1f}%")

if __name__ == "__main__":
    main()