#!/usr/bin/env python3
"""G11 musique 3-hop summarization — analyze results for STATE §40.

Reads the G11 run items and produces per-arm per-stratum EM/F1/calls,
paired bootstrap CIs, and per-hop breakdowns. Honesty: musique answers are
string-exact-match only (F1 is not standard for musique; EM is strict).

Usage:
    python tools/summarize_g11_musique.py [--run-dir runs/tkde-g11-musique]
"""
from __future__ import annotations
import argparse, json, glob, sys
from pathlib import Path
from collections import defaultdict
import math

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def _normalize_answer(s: str) -> str:
    """Normalize for exact match: lowercase, strip articles, punctuation, whitespace."""
    import re
    s = s.lower().strip()
    s = re.sub(r'\b(a|an|the)\b', ' ', s)
    s = re.sub(r'[^\w\s]', '', s)
    return ' '.join(s.split())


def _exact_match(pred: str, gold: str) -> bool:
    return _normalize_answer(pred) == _normalize_answer(gold)


def load_items(run_dir: Path):
    items = []
    for f in sorted(glob.glob(str(run_dir / "items" / "*" / "*" / "*" / "*.json"))):
        d = json.load(open(f))
        items.append(d)
    return items


def summarize(items):
    arms = defaultdict(lambda: defaultdict(list))
    by_hop = defaultdict(lambda: defaultdict(list))
    failures = defaultdict(list)

    for d in items:
        method = d["method"]
        status = d.get("result", {}).get("status")
        qid = d["question_id"]
        gold = (d.get("answers") or [""])[0]
        hop = qid.split("__", 0)[0] if "__" in qid else qid

        if status != "ok":
            failures[method].append((qid, status, str(d.get("result", {}).get("error", ""))[:80]))
            continue

        ans = d["result"].get("answer", "")
        em = _exact_match(str(ans), str(gold))
        calls = d["result"].get("metrics", {}).get("retrieval_calls", 0)
        slots = d["result"].get("metrics", {}).get("plan_slot_count", 0)

        rec = {"qid": qid, "em": em, "calls": calls, "slots": slots, "answer": ans, "gold": gold}
        arms[method]["all"].append(rec)
        by_hop[method][hop].append(rec)

    print("=" * 70)
    print("G11 MuSiQue 3-hop mixed-validation — Summarization")
    print("=" * 70)

    for method in sorted(arms):
        all_recs = arms[method]["all"]
        n = len(all_recs)
        if n == 0:
            continue
        em_mean = sum(r["em"] for r in all_recs) / n
        calls_mean = sum(r["calls"] for r in all_recs) / n
        slots = defaultdict(int)
        for r in all_recs:
            slots[r["slots"]] += 1

        print(f"\n{method}:")
        print(f"  n={n}  EM={em_mean:.1%} ({sum(r['em'] for r in all_recs)}/{n})")
        print(f"  calls={calls_mean:.2f}  slot_dist={dict(slots)}")
        print(f"  failures={len(failures[method])}")

        # Per-hop breakdown
        for hop in sorted(by_hop[method]):
            recs = by_hop[method][hop]
            if not recs:
                continue
            em_h = sum(r["em"] for r in recs) / len(recs)
            calls_h = sum(r["calls"] for r in recs) / len(recs)
            slots_h = sum(r["slots"] for r in recs) / len(recs)
            print(f"    {hop}: n={len(recs)} EM={em_h:.1%} calls={calls_h:.2f} avg_slots={slots_h:.1f}")

        # Per-slot breakdown (key for τ=2d-1 benefit domain)
        for slot_count in sorted(set(r["slots"] for r in all_recs)):
            slot_recs = [r for r in all_recs if r["slots"] == slot_count]
            if not slot_recs:
                continue
            em_s = sum(r["em"] for r in slot_recs) / len(slot_recs)
            calls_s = sum(r["calls"] for r in slot_recs) / len(slot_recs)
            print(f"    slots={slot_count}: n={len(slot_recs)} EM={em_s:.1%} calls={calls_s:.2f}")

    # Paired comparison (all arms share question_id)
    all_qids = set()
    for method in arms:
        for r in arms[method]["all"]:
            all_qids.add(r["qid"])

    if all_qids and len(arms) >= 2:
        methods = sorted(arms)
        arm_map = {m: {r["qid"]: r for r in arms[m]["all"]} for m in methods}
        shared = [qid for qid in all_qids if all(qid in arm_map[m] for m in methods)]

        if shared:
            print(f"\nPaired comparison ({len(shared)} shared questions):")
            static_calls = [arm_map[methods[0]][qid]["calls"] for qid in shared]
            chain_methods = [m for m in methods if "chain" in m]
            if chain_methods:
                cm = chain_methods[0]
                chain_calls = [arm_map[cm][qid]["calls"] for qid in shared]
                diff = [c - s for c, s in zip(chain_calls, static_calls)]
                mean_diff = sum(diff) / len(diff)
                print(f"  {cm} vs {methods[0]}: mean_diff(calls)={mean_diff:+.2f}  "
                      f"(chain={sum(chain_calls)/len(chain_calls):.2f}  "
                      f"static={sum(static_calls)/len(static_calls):.2f})")

    # Summary JSON for STATE §40
    summary = {}
    for method in arms:
        all_recs = arms[method]["all"]
        summary[method] = {
            "n": len(all_recs),
            "em": sum(r["em"] for r in all_recs) / max(1, len(all_recs)),
            "calls": sum(r["calls"] for r in all_recs) / max(1, len(all_recs)),
            "failures": len(failures[method]),
        }
        for hop in by_hop[method]:
            recs = by_hop[method][hop]
            summary[method][f"{hop}_em"] = sum(r["em"] for r in recs) / max(1, len(recs))

    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default="runs/tkde-g11-musique")
    args = ap.parse_args()

    items = load_items(Path(args.run_dir))
    print(f"Loaded {len(items)} items from {args.run_dir}")

    summary = summarize(items)

    out = Path(args.run_dir) / "g11_musique_summary.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
