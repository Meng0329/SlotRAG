#!/usr/bin/env python3
"""Paired analysis for H-030 n120 run (guard vs guard-budget with H-029+H-030).

Pairs each question id across the two methods, reports:
- acc_full / acc_ok (guard-budget vs guard)
- BE recovery: items BE in guard that recover to ok/failed/empty in budget
- both-ok quality: answer-stability / F1 delta on items ok in both
"""
import json, glob
import sys
from pathlib import Path
sys.path.insert(0, "src")
from slotrag.evaluation import token_f1

def load_results(ds_dir, method):
    out = {}
    for f in glob.glob(f"{ds_dir}/{method}/*.json"):
        d = json.load(open(f))
        qid = d["question_id"]
        r = d["result"]
        out[qid] = {
            "status": r.get("status"),
            "answer": r.get("answer"),
            "answers": d.get("answers", []),
            "score": d.get("scores", {}).get("primary_score") or 0.0,
            "acc_full": 1.0 if r.get("status") == "ok" else 0.0,
            "acc_ok": d.get("scores", {}).get("primary_score") or 0.0,
        }
    return out

def main():
    base = "runs/slotrag-phase4-h030-n120/items/tier3_sealed"
    for ds in ("musique", "hotpotqa"):
        ds_dir = f"{base}/{ds}"
        guard = load_results(ds_dir, "slotrag-grounded-frontier-perpath-guard")
        budget = load_results(ds_dir, "slotrag-grounded-frontier-perpath-guard-budget")
        common = set(guard) & set(budget)
        print(f"=== {ds} (paired n={len(common)}) ===")
        if not common:
            print("  (no paired results yet)")
            continue
        # acc_full
        gf = [guard[q]["acc_full"] for q in common]
        bf = [budget[q]["acc_full"] for q in common]
        # acc_ok: mean primary_score over ok items
        gok = [guard[q]["acc_ok"] for q in common if guard[q]["status"]=="ok"]
        bok = [budget[q]["acc_ok"] for q in common if budget[q]["status"]=="ok"]
        g_ok_mean = sum(gok)/len(gok) if gok else 0
        b_ok_mean = sum(bok)/len(bok) if bok else 0
        print(f"  acc_full: guard {sum(gf)/len(gf):.3f} -> budget {sum(bf)/len(bf):.3f} (Δ {sum(bf)/len(bf)-sum(gf)/len(gf):+.3f})")
        print(f"  acc_ok mean: guard {g_ok_mean:.3f} -> budget {b_ok_mean:.3f} (Δ {b_ok_mean-g_ok_mean:+.3f})")
        # BE recovery
        g_be = [q for q in common if guard[q]["status"]=="budget_exceeded"]
        recov = [q for q in g_be if budget[q]["status"]=="ok"]
        recov_ok = sum(1 for q in recov if budget[q]["acc_ok"]>0)
        print(f"  BE in guard: {len(g_be)}, recovered to ok: {len(recov)} (of which score>0: {recov_ok})")
        # both-ok
        both = [q for q in common if guard[q]["status"]=="ok" and budget[q]["status"]=="ok"]
        changed = [q for q in both if token_f1(guard[q]["answer"] or "", [guard[q]["answers"][0] if guard[q]["answers"] else ""]) != token_f1(budget[q]["answer"] or "", [budget[q]["answers"][0] if budget[q]["answers"] else ""])]
        d_f1 = []
        for q in both:
            gold = guard[q]["answers"]
            gf1 = token_f1(guard[q]["answer"] or "", gold)
            bf1 = token_f1(budget[q]["answer"] or "", gold)
            d_f1.append(bf1-gf1)
        print(f"  both-ok: {len(both)}, answer-F1 changed: {len(changed)}, mean ΔF1: {sum(d_f1)/len(d_f1) if d_f1 else 0:+.4f}")

if __name__ == "__main__":
    main()
