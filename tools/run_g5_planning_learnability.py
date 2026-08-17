#!/usr/bin/env python3
"""G5 planning-time learnability — can PRE-EXECUTION plan metadata predict slot scarcity?

The v1 probe used runtime features (sufficiency_features incl. row_count) and
got AUC 1.0 dominated by row_count — an AFTER-THE-FACT observation, trivial.
The scientifically meaningful question is PLANNING-TIME prediction: before any
budget is allocated, can per-slot scarcity (tau>1, from the §12e/12e-data
recovery thresholds) be predicted from plan metadata alone?

Features (available at planning time, before execution):
  chain_depth, slot position, is_downstream (joins a prior slot's binding),
  estimated_cardinality, estimated_cost, importance (constant), predicate-token
  hashes (1-of-K over distinct predicates seen).

Label: slot scarcity = tau > 1 (from the real-data budget sweep, reused via
--scarcity-json; fallback: run the sweep here).

If planning-time AUC > 0.6 (esp. no row_count/budget leak), a learned PLANNING
estimator is viable — the independent-value claim of G5. If ~0.5, G5 must
consume runtime observations (gap signal path) — honest fork resolution.
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
    loaded = {}
    for line in out.splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        loaded[k] = v
    for k, v in loaded.items():
        os.environ.setdefault(k, v)


def _providers():
    from slotrag.cli import load_config
    from slotrag.providers import provider_clients
    cfg = load_config(ROOT / "configs" / "default.yaml")
    return cfg, provider_clients(cfg)


def main(argv=None):
    argv = argv or sys.argv
    ap = argparse.ArgumentParser()
    ap.add_argument("--scarcity-json", type=str, default="/tmp/g5_real_scarcity20.json")
    ap.add_argument("--out", type=str, default="/tmp/g5_planning_learnability.json")
    args = ap.parse_args(argv[1:])
    _load_env()

    # load the §12e scarcity sweep (thresholds per slot per question)
    sc = json.load(open(args.scarcity_json))
    inspected = sc.get("inspected", [])
    print("loading %d inspected plans from %s" % (len(inspected), args.scarcity_json))

    # We need plan metadata per slot. We did NOT persist slot predicates in the
    # scarcity sweep's JSON (only thresholds). Re-derive: fall back to the
    # per-slot threshold + chain_depth (available), and a position proxy
    # (slot lexeme order). For predicate features we'd need a re-run — honest
    # note: this first pass uses structural features only (depth, position).
    # That is a legitimate planning-time set and enough to test structure-driven
    # scarcity prediction.

    samples = []
    for insp in inspected:
        qid = insp.get("qid")
        depth = insp.get("n_slots")
        thresholds = insp.get("thresholds", {})
        scarce = insp.get("scarce_slots", {})
        for sid, tau in thresholds.items():
            if tau is None:
                continue
            # position within the plan (S1, S2, ...); downstream if not first
            order = int(sid[1:]) if sid[1:].isdigit() else len(thresholds)
            is_downstream = order > 1
            label = 1 if tau > 1 else 0  # scarcity = needs more than 1 base call
            samples.append({
                "qid": qid, "slot": sid, "chain_depth": depth,
                "position": order, "is_downstream": int(is_downstream),
                "tau": tau, "scarce": label,
            })
    n = len(samples)
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score, StratifiedKFold
    y = np.array([s["scarce"] for s in samples])
    # features: is_downstream, chain_depth, position
    X = np.array([[s["is_downstream"], s["chain_depth"], s["position"]] for s in samples], dtype=float)
    base = y.mean()
    n_pos, n_neg = int(y.sum()), int(len(y) - y.sum())
    print("\n=== planning-time learnability (%d slot observations) ===" % n)
    print("scarce(+)=%d not(+)=%d base=%.3f" % (n_pos, n_neg, base))
    # trivial baseline: 'downstream is scarce'
    trivial_acc = np.mean((X[:, 0] == 1) == (y == 1)) if n else 0
    print("trivial baseline acc (is_downstream == scarce): %.3f" % trivial_acc)
    if n_pos and n_neg and n >= 12:
        cv = StratifiedKFold(n_splits=4, shuffle=True, random_state=2027)
        auc = cross_val_score(LogisticRegression(max_iter=2000), X, y, cv=cv, scoring="roc_auc")
        print("planning AUC (downstream, depth, position): %.3f +- %.3f" % (auc.mean(), auc.std()))
        # remove the strong positional features: just chain_depth alone
        Xd = np.array([[s["chain_depth"]] for s in samples], dtype=float)
        auc_depth = cross_val_score(LogisticRegression(max_iter=2000), Xd, y, cv=cv, scoring="roc_auc")
        print("AUC (chain_depth only): %.3f +- %.3f" % (auc_depth.mean(), auc_depth.std()))
    else:
        print("HONEST: insufficient balanced sample for AUC.")

    # per-position breakdown
    print("\nper slot-position scarcity rate:")
    for pos in sorted({s["position"] for s in samples}):
        sub = [s for s in samples if s["position"] == pos]
        rate = sum(s["scarce"] for s in sub) / len(sub)
        print("  position %d: n=%d scarce-rate=%.2f" % (pos, len(sub), rate))

    Path(args.out).write_text(json.dumps({
        "n_samples": n, "n_scarce": n_pos, "base_rate": base,
        "label_note": "planning-time structural features only (downstream, depth, position); "
                      "predicate/cardinality features need a re-run for full feature set",
        "samples": samples,
    }, ensure_ascii=False, indent=2))
    print("Wrote %s" % args.out)


if __name__ == "__main__":
    main()