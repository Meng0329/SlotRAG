#!/usr/bin/env python3
"""TKDE main-table reproduction from frozen per-question items.

Rebuilds the end-to-end matched-budget table (EM / F1 / calls per arm, with
paired bootstrap CIs on call deltas) independently from raw per-question
attempt records. This is the Phase 13/17 "independent script from raw records"
requirement: no number in the paper's main table is trusted unless this script
reproduces it from runs/ items.

Usage:
    python tools/summarize_tkde_main_table.py \
        --run-dir runs/tkde-g6 \
        --stage g6-effective --dataset hotpotqa \
        --arms slotrag-g7-static slotrag-g7-flat slotrag-g7-chain
    python tools/summarize_tkde_main_table.py \
        --run-dir runs/tkde-r11-baselines --stage tkde-r11-baselines \
        --dataset hotpotqa \
        --arms hybrid ircot react slotrag-g7-static slotrag-g7-chain
"""
from __future__ import annotations
import argparse, json, glob, sys, math
from pathlib import Path
from collections import defaultdict

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

# ---- exact-match normalization (mirrors metrics.py) ----
def _normalize_answer(s: str) -> str:
    import re
    s = (s or "").lower().strip()
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    s = re.sub(r"[^\w\s]", "", s)
    return " ".join(s.split())


def _em(pred: str, gold: str) -> bool:
    return _normalize_answer(pred) == _normalize_answer(gold)


def _f1(pred: str, gold: str) -> float:
    import re
    def _tok(s):
        s = (s or "").lower().strip()
        return re.sub(r"[^\w\s]", "", s).split()
    p, g = set(_tok(pred)), set(_tok(gold))
    if not p and not g:
        return 1.0
    if not p or not g:
        return 0.0
    inter = len(p & g)
    if inter == 0:
        return 0.0
    prec, rec = inter / len(p), inter / len(g)
    return 2 * prec * rec / (prec + rec)


def _load_items(run_dir: Path, stage: str, dataset: str, arm: str) -> dict[str, dict]:
    """Load ok items for one arm, keyed by question hash."""
    items: dict[str, dict] = {}
    pat = run_dir / "items" / stage / dataset / arm / "*.json"
    for f in sorted(glob.glob(str(pat))):
        try:
            d = json.loads(Path(f).read_text())
        except Exception:
            continue
        if d.get("failure_category", "ok") != "ok":
            continue
        items[Path(f).stem] = d
    return items


def _pair(
    chain_items: dict[str, dict], base_items: dict[str, dict]
) -> tuple[np.ndarray, np.ndarray]:
    """Matched valid pairs between chain arm and a base arm (intersection of ok)."""
    common = sorted(set(chain_items) & set(base_items))
    d = np.array([
        chain_items[q]["result"]["metrics"]["retrieval_calls"]
        - base_items[q]["result"]["metrics"]["retrieval_calls"]
        for q in common
    ])
    em_delta = np.array([
        float(chain_items[q].get("scores", {}).get("em", 0.0))
        - float(base_items[q].get("scores", {}).get("em", 0.0))
        for q in common
    ])
    return d, em_delta


def _boot_p(d: np.ndarray, seed: int = 2027, iters: int = 100_000) -> tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    b = rng.choice(d, size=(iters, len(d)), replace=True).mean(axis=1)
    p = min(1.0, 2 * min(float(np.mean(b <= 0)), float(np.mean(b >= 0))))
    return p, float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))


def _mcnemar(
    chain_items: dict[str, dict], base_items: dict[str, dict]
) -> tuple[int, int, float]:
    """Exact two-sided McNemar on matched valid pairs.

    b = # pairs where chain is correct and base is wrong
    c = # pairs where chain is wrong and base is correct
    p = exact two-sided binomial tail under the null b ~ Binomial(b+c, 0.5).
    """
    from math import comb
    common = sorted(set(chain_items) & set(base_items))
    b = c = 0
    for q in common:
        ec = int(chain_items[q].get("scores", {}).get("em", 0.0))
        eb = int(base_items[q].get("scores", {}).get("em", 0.0))
        if ec > eb:
            b += 1
        elif eb > ec:
            c += 1
    n = b + c
    if n == 0:
        return b, c, 1.0
    # exact two-sided: 2 * P(X <= min(b,c)) with the degenerate mid-mass convention
    k = min(b, c)
    p = 2.0 * sum(comb(n, i) * 0.5**n for i in range(k + 1))
    return b, c, min(1.0, p)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--arms", nargs="+", required=True)
    ap.add_argument("--chain-arm", default="slotrag-g7-chain",
                    help="arm treated as the method; others are compared to it")
    ap.add_argument("--seed", type=int, default=2027)
    args = ap.parse_args()

    items = {a: _load_items(args.run_dir, args.stage, args.dataset, a) for a in args.arms}
    chain = items[args.chain_arm]

    print(f"# Main table reproduction — {args.dataset} @ {args.stage} (from {args.run_dir})")
    print(f"# chain arm = {args.chain_arm}; seed={args.seed}")
    print("# EM/F1 read from per-question items[].scores (repository metrics.py calculation);")
    print("# calls from items[].result.metrics.retrieval_calls.")
    print()
    header = f"{'arm':22s} {'n':>3} {'EM%':>6} {'F1':>6} {'calls':>6} {'Δcalls vs chain':>10} {'p_boot':>7} {'CI95':>12}"
    print(header)
    print("-" * len(header))
    for arm in args.arms:
        recs = items[arm]
        n = len(recs)
        if n == 0:
            print(f"{arm:22s}  0   --   --   --   (no ok items)")
            continue
        em = sum(1 for r in recs.values() if r.get("scores", {}).get("em")) / n
        f1s = [r.get("scores", {}).get("f1", 0.0) for r in recs.values()]
        calls = np.mean([r["result"]["metrics"]["retrieval_calls"] for r in recs.values()])
        if arm == args.chain_arm:
            print(f"{arm:22s} {n:>3} {100*em:>5.1f} {np.mean(f1s):>6.2f} {calls:>6.2f}")
        else:
            d, _ = _pair(chain, recs)
            if len(d) > 0:
                p, lo, hi = _boot_p(d, args.seed)
                print(f"{arm:22s} {n:>3} {100*em:>5.1f} {np.mean(f1s):>6.2f} {calls:>6.2f} "
                      f"{d.mean():>+10.2f} {p:>7.3f} [{lo:>5.2f},{hi:>5.2f}]")
            else:
                print(f"{arm:22s} {n:>3} {100*em:>5.1f} {np.mean(f1s):>6.2f} {calls:>6.2f}")
    print()
    print("# Δcalls = chain − base (negative = chain spends fewer retrieval calls).")
    print("# p_boot = paired bootstrap on matched valid pairs, seed=2027, 100k iters.")

    # ---- McNemar on matched pairs (Phase 13 statistical audit) ----
    print()
    print("# McNemar (exact two-sided) — chain vs each non-chain arm, matched valid pairs")
    print(f"{'arm':22s} {'b(chainW,baseL)':>17} {'c(chainL,baseW)':>17} {'n_disc':>7} {'p_exact':>8}")
    print("-" * 65)
    for arm in args.arms:
        if arm == args.chain_arm:
            continue
        b, c, p = _mcnemar(chain, items[arm])
        print(f"{arm:22s} {b:>17d} {c:>17d} {b+c:>7d} {p:>8.3f}")


if __name__ == "__main__":
    main()
