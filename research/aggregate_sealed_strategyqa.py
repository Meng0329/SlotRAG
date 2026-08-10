#!/usr/bin/env python3
"""Aggregate strategyqa SEALED results across multiple runs (mean ± run-to-run range).

用法: python3 research/aggregate_sealed_strategyqa.py \
  --runs runs/slotrag-phase4-trace,runs/slotrag-phase4-trace-r2,runs/slotrag-phase4-trace-r3

对每个方法，输出:
  - 每次运行的 accuracy
  - 跨运行 mean / min / max / range
  - 每次运行的 per-question 答案 + 跨运行 flip 统计
  - guard vs 最强 baseline 的稳健判定（基于 mean）
"""
import argparse, json, glob, collections
from pathlib import Path


def load_run(run_dir: str) -> dict[str, dict[str, dict]]:
    """{method: {qid: {answer, accuracy, status}}}"""
    base = Path(run_dir) / "items" / "tier3_sealed" / "strategyqa"
    if not base.exists():
        return {}
    out: dict[str, dict[str, dict]] = collections.defaultdict(dict)
    for p in sorted(base.rglob("*.json")):
        d = json.loads(p.read_text())
        method = d.get("method_label") or d.get("method")
        result = d.get("result") or {}
        status = result.get("status")
        out[method][d["question_id"]] = {
            "answer": result.get("answer"),
            "accuracy": (d.get("scores") or {}).get("primary_score"),
            "status": status,
        }
    return dict(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True, help="comma-separated run dirs")
    args = ap.parse_args()
    run_dirs = [Path(r) for r in args.runs.split(",")]

    # Load all runs
    all_runs: dict[str, list[dict[str, dict]]] = collections.defaultdict(list)
    run_labels = [str(r).split("/")[-1] for r in run_dirs]
    for rd in run_dirs:
        data = load_run(str(rd))
        for method, per_q in data.items():
            all_runs[method].append(per_q)

    methods = sorted(all_runs.keys())
    print(f"runs: {run_labels}")
    print(f"methods: {methods}")
    print()

    summary: dict[str, dict] = {}
    flip_stats: dict[str, dict] = collections.defaultdict(dict)
    for method in methods:
        run_list = all_runs[method]
        accs = []
        per_question_votes: dict[str, list] = collections.defaultdict(list)
        for per_q in run_list:
            accs.append(sum(v["accuracy"] or 0 for v in per_q.values()) / len(per_q))
            for qid, v in per_q.items():
                per_question_votes[qid].append(v["answer"])
        n = len(accs)
        mean = sum(accs) / n
        lo, hi = min(accs), max(accs)
        # Per-question stability: how many flip across runs
        flips = 0
        for qid, votes in per_question_votes.items():
            distinct = {a for a in votes if a}
            if len(distinct) > 1:
                flips += 1
        print(f"--- {method} ---")
        for i, (rl, acc) in enumerate(zip(run_labels, accs)):
            print(f"  run_{i} ({rl}): accuracy={acc:.4f}")
        print(f"  mean={mean:.4f}  range=[{lo:.4f}, {hi:.4f}]  Δ={hi-lo:.4f}  flips/180={flips}")
        summary[method] = {
            "accuracies": accs,
            "mean": mean,
            "min": lo,
            "max": hi,
            "range": hi - lo,
            "flips": flips,
        }
        print()

    # Guard vs strongest baseline
    if "slotrag-grounded-frontier-perpath-guard" in summary:
        guard = summary["slotrag-grounded-frontier-perpath-guard"]
        print("=== guard(vs baselines) 稳健判定 ===")
        for bl in ["ircot", "graphrag", "react"]:
            if bl in summary:
                b = summary[bl]
                dmean = guard["mean"] - b["mean"]
                # 用 run-level mean 差 + range 判断
                print(f"  guard({guard['mean']:.4f}) vs {bl}({b['mean']:.4f}): Δmean={dmean:+.4f}")
    print()
    print(json.dumps({m: {k: (v if k != 'accuracies' else [round(x,4) for x in v]) for k,v in s.items()} for m,s in summary.items()}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())