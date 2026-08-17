#!/usr/bin/env python3
"""G5 learnability v1 — real-data (question × budget × slot) recovery prediction.

The v0 probe failed on class imbalance (artificial corpus: 0.958 base rate).
This version collects samples from REAL hotpotqa 2+slot chains: for each
problem × budget × slot, record the slot's sufficiency_features (30-dim,
execution state) + whether the slot's truth was recovered in extracted_rows
(裁决12c signal, "non-empty bindings" proxy for real data — noted honestly).

Class balance is naturally better here: real τ distribution is wider (S1=1
mostly but sometimes 2; S2=3 or None; S3=5), so 'recovered at this budget' is
not near-singular.

Questions it answers:
  - H-G5-2 learnability: held-out AUC of a LogisticRegression predicting
    'recovered' from sufficiency_features.
  - Feature source: AUC with all 30 features vs budget-stripped (27) — is the
    signal content-driven or just budget state?
  - Row counts per (recovered=0/1) to prove the class balance claim.

Honest: proxy label (non-empty bindings) noted; real per-slot gold attribution
is a refinement (pre-reg §3).
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


def _calibrator():
    from slotrag.sufficiency import EvidenceSufficiencyCalibrator
    import json as _json
    cal_path = ROOT / "runs_archive" / "slotrag-sufficiency-smoke-v60" / "calibrator.json"
    if cal_path.exists():
        return EvidenceSufficiencyCalibrator.from_dict(_json.loads(cal_path.read_text()))
    return None


BUDGET_FEATURES = {"budget_remaining", "budget_fraction", "retrieval_count"}


def main(argv=None):
    argv = argv or sys.argv
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=str, default="hotpotqa")
    ap.add_argument("--split", type=str, default="validation")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--budgets", type=str, default="1,2,3,4,5,6")
    ap.add_argument("--first-window", type=int, default=3)
    ap.add_argument("--out", type=str, default="/tmp/g5_learnability_v1.json")
    args = ap.parse_args(argv[1:])
    _load_env()

    from slotrag.models import Passage
    from slotrag.retrieval import HybridRetriever
    from slotrag.planner import SlotCompiler, AdaptiveExecutor, SlotMaterializer
    from slotrag.action_policy import PhysicalActionPolicy
    from slotrag.sufficiency import SUFFICIENCY_FEATURE_NAMES

    _cfg, (client, embedding, reranker) = _providers()
    cal = _calibrator()
    budgets = [int(b) for b in args.budgets.split(",") if b.strip()]
    feature_names = list(SUFFICIENCY_FEATURE_NAMES)
    nonbudget_names = [f for f in feature_names if f not in BUDGET_FEATURES]

    data_path = ROOT / "benchmark" / args.dataset / ("%s_%s.jsonl" % (args.dataset, args.split))
    if not data_path.exists():
        print("missing %s" % data_path)
        return 1
    problems = []
    with open(data_path) as f:
        for line in f:
            problems.append(json.loads(line))
            if len(problems) >= args.n:
                break

    compiler = SlotCompiler(client)
    samples = []
    n_plan2 = 0
    for prob in problems:
        q = prob["question"]
        passages = prob.get("passages") or []
        if not passages:
            continue
        try:
            plan, _cm = compiler.compile(q, answer_kind="short")
        except Exception:
            continue
        if len(plan.slots) < 2:
            continue
        n_plan2 += 1
        ps = [Passage(id=p["id"], text=p["text"], doc_id=p["doc_id"]) for p in passages]
        retriever = HybridRetriever(
            passages=ps, embedding_client=embedding, reranker_client=reranker,
            bm25_k=20, dense_k=20, final_k=20, rrf_k=60,
            rerank_enabled=False, sparse_index_mode="body")
        for budget in budgets:
            mat = SlotMaterializer(client, retriever, max_passages=args.first_window)
            ex = AdaptiveExecutor(
                mat, max_retrieval_calls=budget, max_binding_contexts=2, random_seed=2027,
                sufficiency_calibrator=cal,
                action_policy=PhysicalActionPolicy(topk_expansion_mode="utility"))
            r = ex.execute(plan, strategy="adaptive", physical_plan=None)
            for t in r.slot_traces:
                feats = dict(t.sufficiency_features or {})
                # proxy recovery: slot materialized any non-empty extracted row
                recovered = any(
                    mm.extracted_rows and any(er.bindings for er in mm.extracted_rows)
                    for mm in t.materializations)
                samples.append({
                    "feats": feats, "budget": budget, "recovered": recovered,
                    "slot": t.slot_id, "qid": prob.get("id"), "chain_depth": len(plan.slots),
                })

    n = len(samples)
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score, StratifiedKFold
    from sklearn.preprocessing import StandardScaler

    y = np.array([1 if s["recovered"] else 0 for s in samples], dtype=int)
    X = np.array([[s["feats"].get(f, 0.0) for f in feature_names] for s in samples], dtype=float)
    Xnb = np.array([[s["feats"].get(f, 0.0) for f in nonbudget_names] for s in samples], dtype=float)
    base = y.mean()
    n_pos = int(y.sum()); n_neg = int(len(y) - y.sum())
    print("\n=== learnability v1 (real data, %d 2+slot plans) ===" % n_plan2)
    print("samples=%d  recovered(+) =%d  not-recovered(-) =%d  base rate=%.3f"
          % (n, n_pos, n_neg, base))
    if n_pos == 0 or n_neg == 0 or n < 30:
        print("HONEST: cannot compute meaningful AUC (need both classes & n>=30).")
        auc_full = auc_nb = None
    else:
        scaler = StandardScaler()
        Xs = scaler.fit_transform(X); Xnbs = scaler.fit_transform(Xnb)
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=2027)
        auc_full = cross_val_score(LogisticRegression(max_iter=2000), Xs, y, cv=cv, scoring="roc_auc")
        auc_nb = cross_val_score(LogisticRegression(max_iter=2000), Xnbs, y, cv=cv, scoring="roc_auc")
        print("AUC all-features: %.3f +- %.3f" % (auc_full.mean(), auc_full.std()))
        print("AUC budget-stripped: %.3f +- %.3f" % (auc_nb.mean(), auc_nb.std()))
        print("=> content-state signal beyond budget?",
              "YES" if auc_nb.mean() > 0.6 else ("WEAK" if auc_nb.mean() > 0.55 else "NO"))
        # also by slot position: does depth carry the signal?
        for depth in sorted({s["chain_depth"] for s in samples}):
            sub = [s for s in samples if s["chain_depth"] == depth]
            if len(sub) >= 20:
                yy = np.array([1 if s["recovered"] else 0 for s in sub])
                XX = np.array([[s["feats"].get(f, 0.0) for f in feature_names] for s in sub])
                if 0 < yy.mean() < 1:
                    from sklearn.model_selection import cross_val_score as cvs
                    from sklearn.model_selection import StratifiedKFold as SKF
                    XXs = StandardScaler().fit_transform(XX)
                    a = cvs(LogisticRegression(max_iter=2000), XXs, yy, cv=SKF(3, shuffle=True, random_state=2027), scoring="roc_auc")
                    print("  depth=%d: n=%d base=%.3f AUC=%.3f+-%.3f" % (depth, len(sub), yy.mean(), a.mean(), a.std()))

    Path(args.out).write_text(json.dumps({
        "n_plans": n_plan2, "n_samples": n, "n_pos": n_pos, "n_neg": n_neg,
        "base_rate": base,
        "auc_all_features": ({"mean": float(auc_full.mean()), "std": float(auc_full.std())} if auc_full is not None else None),
        "auc_budget_stripped": ({"mean": float(auc_nb.mean()), "std": float(auc_nb.std())} if auc_nb is not None else None),
        "budget_stripped_features": nonbudget_names,
        "label_note": "proxy: non-empty extracted_rows bindings (real per-slot gold attribution is a pre-reg §3 refinement)",
        "samples": samples,
    }, ensure_ascii=False, indent=2))
    print("Wrote %s" % args.out)


if __name__ == "__main__":
    main()