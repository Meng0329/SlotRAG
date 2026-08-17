#!/usr/bin/env python3
"""G5 H-G5-2 learnability probe — can per-slot execution state predict recovery?

Tests whether the estimator's input features (SufficiencyFeatures, 30-dim,
from slot_trace.sufficiency_features) carry predictive signal for "will this
slot's target truth be recovered at this budget". If yes, a learned importance
estimator is feasible (H-G5-2 learnability half).

Method:
  - Collect per-(question, budget, slot) samples by running the real
    compile->execute path over a budget sweep.
  - Features: slot_trace.sufficiency_features dict (30-dim, V2 schema).
  - Label: slot recovered? (extracted_rows signal, 裁决12c).
  - Fit LogisticRegression, 5-fold CV, report held-out AUC.
  - ALSO fit on budget-stripped features (drop budget_remaining,
    budget_fraction, retrieval_count) to show non-budget features carry signal.

Honest: reports AUC with/without budget features. If budget-stripped AUC ~ 0.5,
recovery is predicted mostly by budget state, not content state — still
learnable, but a weaker story.
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


def _synthetic_questions():
    """§10's 4 questions: independent 2-slot chains, S1 abundant / S2 scarce."""
    return [
        {"id": "q1", "person": "Marie Curie", "country": "Poland", "pop": "38 million"},
        {"id": "q2", "person": "Nikola Tesla", "country": "Croatia", "pop": "3.9 million"},
        {"id": "q3", "person": "Isaac Newton", "country": "England", "pop": "56 million"},
        {"id": "q4", "person": "Galileo Galilei", "country": "Italy", "pop": "59 million"},
    ]


def _synthetic_corpus(person, country, pop):
    return [
        ("doc1", "%s was born in %s, a city in %s, in 1867." % (person, country, country)),
        ("doc2", "%s is the capital city of %s, known for its history and culture." % (country, country)),
        ("doc3", "The population of Paris is approximately 2.1 million people."),
        ("doc4", "Tokyo has a population of roughly 14 million people."),
        ("doc5", "London has a population of about 9 million people."),
        ("doc6", "Berlin has a population of about 3.7 million people."),
        ("doc7", "Madrid has a population of roughly 3.3 million people."),
        ("doc8", "Rome has a population of approximately 2.8 million people."),
        ("doc9", "Moscow has a population of about 12 million people."),
        ("doc10", "The nation of %s had approximately %s people according to a recent estimate." % (country, pop)),
    ]


def _synthetic_plan(person, country):
    from slotrag.models import JoinSpec, Slot, SlotPlan
    return SlotPlan(
        slots=[
            Slot(id="S1", predicate="Person Birth Country",
                 arguments=["?person", "?country"],
                 variable_types={"person": "string", "country": "string"},
                 estimated_cardinality=5, estimated_cost=1.0, importance=1.0),
            Slot(id="S2", predicate="Country Population",
                 arguments=["?country", "?pop"],
                 variable_types={"country": "string", "pop": "number"},
                 estimated_cardinality=8, estimated_cost=1.5, importance=1.0),
        ],
        joins=[JoinSpec(left_slot="S1", left_field="country", right_slot="S2", right_field="country")],
        outputs=["?country", "?pop"],
    )


BUDGET_FEATURES = {"budget_remaining", "budget_fraction", "retrieval_count"}


def main(argv=None):
    argv = argv or sys.argv
    ap = argparse.ArgumentParser()
    ap.add_argument("--budgets", type=str, default="1,2,3,4")
    ap.add_argument("--first-window", type=int, default=2)
    ap.add_argument("--out", type=str, default="/tmp/g5_learnability.json")
    args = ap.parse_args(argv[1:])
    _load_env()

    from slotrag.models import Passage
    from slotrag.retrieval import HybridRetriever
    from slotrag.planner import AdaptiveExecutor, SlotMaterializer
    from slotrag.action_policy import PhysicalActionPolicy
    from slotrag.sufficiency import SUFFICIENCY_FEATURE_NAMES

    _cfg, (client, embedding, reranker) = _providers()
    cal = _calibrator()
    budgets = [int(b) for b in args.budgets.split(",") if b.strip()]
    feature_names = list(SUFFICIENCY_FEATURE_NAMES)
    nonbudget_names = [f for f in feature_names if f not in BUDGET_FEATURES]

    samples = []  # {feats, budget, recovered, slot, q}
    for q in _synthetic_questions():
        corpus = _synthetic_corpus(q["person"], q["country"], q["pop"])
        passages = [Passage(id=docid, text=text, doc_id=docid) for docid, text in corpus]
        retriever = HybridRetriever(
            passages=passages, embedding_client=embedding, reranker_client=reranker,
            bm25_k=10, dense_k=10, final_k=10, rrf_k=60,
            rerank_enabled=False, sparse_index_mode="body")
        plan = _synthetic_plan(q["person"], q["country"])

        for budget in budgets:
            mat = SlotMaterializer(client, retriever, max_passages=args.first_window)
            ex = AdaptiveExecutor(
                mat, max_retrieval_calls=budget, max_binding_contexts=2, random_seed=2027,
                sufficiency_calibrator=cal,
                action_policy=PhysicalActionPolicy(topk_expansion_mode="utility"))
            r = ex.execute(plan, strategy="adaptive", physical_plan=None)
            for t in r.slot_traces:
                feats = dict(t.sufficiency_features or {})
                # label: recovered via extracted_rows (裁决12c signal)
                if t.slot_id == "S1":
                    recovered = any(
                        str(er.bindings.get("country", "")).strip().lower() == q["country"].lower()
                        for mm in t.materializations for er in mm.extracted_rows)
                else:  # S2
                    recovered = any(
                        str(er.bindings.get("pop", "")).strip().lower() == q["pop"].lower()
                        for mm in t.materializations for er in mm.extracted_rows)
                samples.append({
                    "feats": feats, "budget": budget, "recovered": recovered,
                    "slot": t.slot_id, "q": q["id"],
                })
                print("q=%s b=%d slot=%s recovered=%s n_feats=%d"
                      % (q["id"], budget, t.slot_id, recovered, len(feats)))

    n = len(samples)
    if n < 20:
        print("\nHONEST: too few samples (%d) for a meaningful AUC — need the sweep to produce many (q,budget,slot) rows." % n)
    else:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import cross_val_score, StratifiedKFold
        from sklearn.preprocessing import StandardScaler

        X = np.array([[s["feats"].get(f, 0.0) for f in feature_names] for s in samples], dtype=float)
        Xnb = np.array([[s["feats"].get(f, 0.0) for f in nonbudget_names] for s in samples], dtype=float)
        y = np.array([1 if s["recovered"] else 0 for s in samples], dtype=int)

        scaler = StandardScaler()
        Xs = scaler.fit_transform(X)
        Xnbs = scaler.fit_transform(Xnb)

        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=2027)
        auc_full = cross_val_score(LogisticRegression(max_iter=1000), Xs, y, cv=cv, scoring="roc_auc")
        auc_nb = cross_val_score(LogisticRegression(max_iter=1000), Xnbs, y, cv=cv, scoring="roc_auc")
        base_rate = y.mean()

        print("\n=== learnability (%d samples, %d budget-stripped features) ===" % (n, len(nonbudget_names)))
        print("label base rate (recovered fraction): %.3f" % base_rate)
        print("AUC all-features:  %.3f +- %.3f" % (auc_full.mean(), auc_full.std()))
        print("AUC budget-stripped: %.3f +- %.3f" % (auc_nb.mean(), auc_nb.std()))
        print("=> signal from content state (non-budget) beyond budget state?",
              "YES" if auc_nb.mean() > 0.6 else ("WEAK" if auc_nb.mean() > 0.55 else "NO"))

        Path(args.out).write_text(json.dumps({
            "n_samples": n, "n_features": len(feature_names),
            "base_rate": base_rate,
            "auc_all_features": {"mean": float(auc_full.mean()), "std": float(auc_full.std())},
            "auc_budget_stripped": {"mean": float(auc_nb.mean()), "std": float(auc_nb.std())},
            "budget_stripped_features": nonbudget_names,
            "samples": samples,
        }, ensure_ascii=False, indent=2))
        print("Wrote %s" % args.out)


if __name__ == "__main__":
    main()