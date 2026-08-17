#!/usr/bin/env python3
"""G5 counterfactual pseudo-label collector — multi-question sweep.

Collects per-slot recovery-threshold pseudo-labels across multiple 2-slot-chain
questions. For each question (its own corpus, S1 abundant / S2 scarce by
construction), sweep the total budget and record, per slot, the smallest budget
at which its target truth is recovered in extracted_rows (the 裁决12c signal).

The per-slot recovery threshold is the pseudo-label target for a G5 importance
estimator: a slot with a high threshold is budget-sensitive (scarce truth ->
high importance); a slot recovered at budget 1 is robust (low importance).

Goal: verify the S2> S1 differential (budget-sensitivity ordering) is STABLE
across questions, or expose where it inverts. Honest: every question's raw
thresholds are reported; any inversion is a boundary finding, not hidden.

Uses the §10 questions/corpora (independent 2-slot chains, own 10-doc corpus).
"""

from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

# §10 questions + corpus builder (independent 2-slot chains). No "population"
# keyword on the scarce truth docs so they rank outside the first window.
QUESTIONS = [
    {"id": "q1", "person": "Marie Curie", "country": "Poland", "pop": "38 million"},
    {"id": "q2", "person": "Nikola Tesla", "country": "Croatia", "pop": "3.9 million"},
    {"id": "q3", "person": "Isaac Newton", "country": "England", "pop": "56 million"},
    {"id": "q4", "person": "Galileo Galilei", "country": "Italy", "pop": "59 million"},
]


def _corpus_for(person: str, country: str, pop: str):
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
        # scarce truth: country's population, NO "population" keyword -> ranks
        # below explicit-population distractors, outside first window.
        ("doc10", "The nation of %s had approximately %s people according to a recent estimate." % (country, pop)),
    ]


def _slot_plan(person: str, country: str):
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


def main(argv=None):
    argv = argv or sys.argv
    ap = argparse.ArgumentParser()
    ap.add_argument("--budgets", type=str, default="1,2,3,4,5,6")
    ap.add_argument("--first-window", type=int, default=2)
    ap.add_argument("--n", type=int, default=2, help="repeats per budget")
    ap.add_argument("--out", type=str, default="/tmp/g5_pseudolabel_collect.json")
    args = ap.parse_args(argv[1:])
    _load_env()

    from slotrag.qo import compile_physical_plan, logical_plan_from_slot_plan
    from slotrag.planner import AdaptiveExecutor, SlotMaterializer
    from slotrag.action_policy import PhysicalActionPolicy

    _cfg, (client, embedding, reranker) = _providers()
    cal = _calibrator()
    budgets = [int(b) for b in args.budgets.split(",") if b.strip()]

    per_q = []
    all_rows = []
    for q in QUESTIONS:
        corpus = _corpus_for(q["person"], q["country"], q["pop"])
        from slotrag.models import Passage
        from slotrag.retrieval import HybridRetriever
        passages = [Passage(id=docid, text=text, doc_id=docid) for docid, text in corpus]
        retriever = HybridRetriever(
            passages=passages, embedding_client=embedding, reranker_client=reranker,
            bm25_k=10, dense_k=10, final_k=10, rrf_k=60,
            rerank_enabled=False, sparse_index_mode="body")
        plan = _slot_plan(q["person"], q["country"])
        logical = logical_plan_from_slot_plan(plan)
        static = compile_physical_plan(logical, retrieval_strategy="hybrid")

        # per-slot recovery at each budget
        rec = {b: {"S1": 0.0, "S2": 0.0} for b in budgets}
        for budget in budgets:
            for run in range(args.n):
                mat = SlotMaterializer(client, retriever, max_passages=args.first_window)
                ex = AdaptiveExecutor(
                    mat, max_retrieval_calls=budget, max_binding_contexts=2, random_seed=2027,
                    sufficiency_calibrator=cal,
                    action_policy=PhysicalActionPolicy(topk_expansion_mode="utility"))
                r = ex.execute(plan, strategy="adaptive", physical_plan=static)
                # per-slot truth recovery from extracted_rows (裁决12c signal)
                slot_ok = {}
                for t in r.slot_traces:
                    ok = False
                    for mm in t.materializations:
                        for er in mm.extracted_rows:
                            b = er.bindings
                            if t.slot_id == "S1" and str(b.get("country", "")).strip().lower() == q["country"].lower():
                                ok = True
                            if t.slot_id == "S2" and str(b.get("pop", "")).strip().lower() == q["pop"].lower():
                                ok = True
                    slot_ok[t.slot_id] = ok
                rec[budget]["S1"] += 1.0 if slot_ok.get("S1") else 0.0
                rec[budget]["S2"] += 1.0 if slot_ok.get("S2") else 0.0
                all_rows.append({
                    "question": q["id"], "budget": budget, "run": run,
                    "status": r.status, "s1_recovered": slot_ok.get("S1", False),
                    "s2_recovered": slot_ok.get("S2", False),
                })
        for b in budgets:
            rec[b]["S1"] /= max(args.n, 1)
            rec[b]["S2"] /= max(args.n, 1)

        # recovery threshold = smallest budget with rate > 0.5
        thr_s1 = next((b for b in budgets if rec[b]["S1"] > 0.5), None)
        thr_s2 = next((b for b in budgets if rec[b]["S2"] > 0.5), None)
        differential = (thr_s1 is not None and thr_s2 is not None and thr_s2 > thr_s1)
        per_q.append({
            "question": q["id"], "country": q["country"],
            "s1_threshold": thr_s1, "s2_threshold": thr_s2,
            "s2_more_budget_sensitive": differential,
            "recovery": rec,
        })
        print("q=%s: S1 threshold=%r S2 threshold=%r  S2> S1? %s"
              % (q["id"], thr_s1, thr_s2, differential))

    n_invert = sum(1 for x in per_q if x["s2_more_budget_sensitive"] is False)
    n_total = len(per_q)
    print("\n=== multi-question pseudo-label collection (%d questions) ===" % n_total)
    print("S2 > S1 (scarce slot more budget-sensitive): %d / %d" % (n_total - n_invert, n_total))
    print("inversions/boundaries: %d" % n_invert)

    Path(args.out).write_text(json.dumps({
        "config": {"budgets": budgets, "first_window": args.first_window, "n": args.n},
        "per_question": per_q,
        "n_s2_more_sensitive": n_total - n_invert,
        "n_invert": n_invert,
        "runs": all_rows,
    }, ensure_ascii=False, indent=2))
    print("Wrote %s" % args.out)


if __name__ == "__main__":
    main()