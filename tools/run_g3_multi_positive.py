#!/usr/bin/env python3
"""G3 allocation multi-question positive set — quantify the -calls distribution.

Each question is an independent 2-slot chain over its OWN 10-doc corpus:
  - S1 (low importance): truth ranks #1 (strong BM25), always in the first window.
  - S2 (high importance): truth intentionally uses NO keyword of the slot query,
    so it ranks ~#5 (outside max_passages=2), recovered only by EXPAND 2->10.
  - 8 distractor docs before/around S2 truth.

Measures across questions: the distribution of (static_calls - search_calls),
plus confirmation that evidence quality (rows + source ids) is equal between
the two plans.

Empirically BIMODAL (2026-08-17, /tmp/g3_multi_positive.json, budget=6/n=3):
  - gain side (3/4 questions q1 q3 q4): G3 = static evidence (doc1+doc10),
    -1 call (4->3). Same as the single-question §9 decisive probe.
  - risk side (1/4 question q2): G3 allocates S1=1 call, S1 first retrieval
    lands on distractors -> has_rows=False -> ABSTAIN (status=empty, rows=[],
    evidence=distractors). static's uniform 4 calls would have recovered doc10.
    So the aggressive allocation has a robustness cost: it depends on the
    calibrator judging "this slot still needs more" correctly AND the first
    window containing a bindable row.

Honest: reports every question's raw numbers; any question where G3 does NOT
save calls (or regresses) is reported as-is, not hidden.
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


def _corpus_for(qid: str, person: str, country: str, pop: str, distractors: list[str]):
    """Build the 10-doc corpus for one question.
    doc1 = S1 truth (strong), doc2 = country fact, docs 3-9 = population distractors,
    doc10 = S2 truth (weak keyword, ranks ~#5).
    """
    return [
        ("doc1", "%s was born in %s, a city in %s, in 1867." % (person, country, country)),
        ("doc2", "%s is the capital city of %s, known for its history and culture." % (country, country)),
        ("doc3", "The population of Paris is approximately 2.1 million people."),
        ("doc4", "Tokyo has a population of roughly 14 million people."),
        ("doc5", "London has a population of about 9 million people."),
        ("doc6", "Berlin has a population of approximately 3.7 million people."),
        ("doc7", "Madrid has a population of roughly 3.3 million people."),
        ("doc8", "Rome has a population of approximately 2.8 million people."),
        ("doc9", "Moscow has a population of about 12 million people."),
        # S2 truth: country's population, NO "population" keyword -> ranks below
        # the explicit-population distractors 3-9, i.e. ~#10 in BM25/dense.
        ("doc10", "The nation of %s had approximately %s people according to a recent estimate." % (country, pop)),
    ]


# Corpus builder needs country names per question; use 4 distinct country/person pairs.
QUESTIONS = [
    {"id": "q1", "person": "Marie Curie", "country": "Poland", "pop": "38 million"},
    {"id": "q2", "person": "Nikola Tesla", "country": "Croatia", "pop": "3.9 million"},
    {"id": "q3", "person": "Isaac Newton", "country": "England", "pop": "56 million"},
    {"id": "q4", "person": "Galileo Galilei", "country": "Italy", "pop": "59 million"},
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
                 estimated_cardinality=8, estimated_cost=1.5, importance=5.0),
        ],
        joins=[JoinSpec(left_slot="S1", left_field="country", right_slot="S2", right_field="country")],
        outputs=["?country", "?pop"],
    )


def _providers():
    from slotrag.cli import load_config
    from slotrag.providers import provider_clients
    cfg = load_config(ROOT / "configs" / "default.yaml")
    return cfg, provider_clients(cfg)


def _build_retriever(embedding, reranker, corpus):
    from slotrag.models import Passage
    from slotrag.retrieval import HybridRetriever
    passages = [Passage(id=docid, text=text, doc_id=docid) for docid, text in corpus]
    return HybridRetriever(
        passages=passages,
        embedding_client=embedding,
        reranker_client=reranker,
        bm25_k=10, dense_k=10, final_k=10,
        rrf_k=60,
        rerank_enabled=False,
        sparse_index_mode="body",
    )


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
    ap.add_argument("--budget", type=int, default=6)
    ap.add_argument("--n", type=int, default=3, help="repeats per question")
    ap.add_argument("--out", type=str, default="/tmp/g3_multi_positive.json")
    ap.add_argument("--first-window", type=int, default=2)
    args = ap.parse_args(argv[1:])
    _load_env()

    from slotrag.qo import compile_physical_plan, logical_plan_from_slot_plan
    from slotrag.optimizer import PlanObjectiveParams, search_physical_plans
    from slotrag.planner import AdaptiveExecutor, SlotMaterializer, derive_evidence_state
    from slotrag.action_policy import PhysicalActionPolicy

    _cfg, (client, embedding, reranker) = _providers()
    cal = _calibrator()

    all_rows = []
    summary = []
    for qi, q in enumerate(QUESTIONS):
        corpus = _corpus_for(q["id"], q["person"], q["country"], q["pop"], [])
        retriever = _build_retriever(embedding, reranker, corpus)
        plan = _slot_plan(q["person"], q["country"])
        logical = logical_plan_from_slot_plan(plan)
        truth_id = "doc10"

        static = compile_physical_plan(logical, retrieval_strategy="hybrid")
        searched, tele = search_physical_plans(
            logical,
            params=PlanObjectiveParams(
                retrieval_budget=args.budget,
                requirement_importance={"S1": 1.0, "S2": 5.0}),
        )

        # self-check: is S2 truth outside window?
        s2_query = "Country Population ?country ?pop"
        results = retriever.search(s2_query)
        all_ids = [r.passage.id for r in results]
        truth_rank = all_ids.index(truth_id) if truth_id in all_ids else -1
        truth_outside = not (truth_id in all_ids[:args.first_window])

        def run_with(phys):
            mat = SlotMaterializer(client, retriever, max_passages=args.first_window)
            ex = AdaptiveExecutor(
                mat, max_retrieval_calls=args.budget, max_binding_contexts=2,
                random_seed=2027, sufficiency_calibrator=cal,
                action_policy=PhysicalActionPolicy(topk_expansion_mode="utility"))
            r = ex.execute(plan, strategy="adaptive", physical_plan=phys)
            st = derive_evidence_state(plan, r)
            return r, st

        def _evidence_ids(res):
            return sorted(e.source_id for e in res.evidence)

        q_rows = []
        for run_i in range(args.n):
            res_s, st_s = run_with(static)
            res_g, st_g = run_with(searched)
            row = {
                "question": q["id"],
                "run": run_i,
                "truth_outside_window": truth_outside,
                "truth_rank": truth_rank,
                "static": {
                    "calls": res_s.metrics.retrieval_calls,
                    "extra_calls": res_s.metrics.physical_action_extra_retrieval_calls,
                    "actions": res_s.metrics.physical_action_executed,
                    "satisfied": st_s.satisfied_count(),
                    "answer": res_s.answer,
                    "evidence": len(res_s.evidence),
                    "evidence_ids": _evidence_ids(res_s),
                    "status": res_s.status,
                    "rows": res_s.rows,
                },
                "search": {
                    "calls": res_g.metrics.retrieval_calls,
                    "extra_calls": res_g.metrics.physical_action_extra_retrieval_calls,
                    "actions": res_g.metrics.physical_action_executed,
                    "satisfied": st_g.satisfied_count(),
                    "answer": res_g.answer,
                    "evidence": len(res_g.evidence),
                    "evidence_ids": _evidence_ids(res_g),
                    "status": res_g.status,
                    "rows": res_g.rows,
                },
                "calls_delta_static_minus_search": res_s.metrics.retrieval_calls - res_g.metrics.retrieval_calls,
            }
            q_rows.append(row)
            all_rows.append(row)

        # per-question aggregate over runs
        d = [r["calls_delta_static_minus_search"] for r in q_rows]
        shim = {
            "question": q["id"],
            "country": q["country"],
            "truth_outside_window": truth_outside,
            "truth_rank": truth_rank,
            "calls_delta_mean": sum(d) / len(d) if d else 0,
            "calls_delta_min": min(d) if d else 0,
            "calls_delta_max": max(d) if d else 0,
            "static_calls": q_rows[0]["static"]["calls"],
            "search_calls": q_rows[0]["search"]["calls"],
            "equal_rows": q_rows[0]["static"]["rows"] == q_rows[0]["search"]["rows"],
            "equal_evidence_ids": q_rows[0]["static"]["evidence_ids"] == q_rows[0]["search"]["evidence_ids"],
            "search_lost_evidence": len(q_rows[0]["search"]["evidence_ids"]) < len(q_rows[0]["static"]["evidence_ids"]),
            "static_evidence_ids": q_rows[0]["static"]["evidence_ids"],
            "search_evidence_ids": q_rows[0]["search"]["evidence_ids"],
            "both_status_ok": q_rows[0]["static"]["status"] == q_rows[0]["search"]["status"] == "ok",
        }
        summary.append(shim)
        print("q=%s country=%s truth_outside=%s rank=%d | static_calls=%d search_calls=%d delta(mean)=%.1f equal_rows=%s"
              % (q["id"], q["country"], truth_outside, truth_rank,
                 shim["static_calls"], shim["search_calls"], shim["calls_delta_mean"], shim["equal_rows"]))

    # aggregate across questions
    all_delta = [r["calls_delta_static_minus_search"] for r in all_rows]
    n_save = sum(1 for d in all_delta if d > 0)
    n_eq = sum(1 for d in all_delta if d == 0)
    n_worse = sum(1 for d in all_delta if d < 0)
    print("\n=== across %d questions x %d runs = %d observations ===" % (len(QUESTIONS), args.n, len(all_delta)))
    print("G3 saves calls: %d (%d.1%%)" % (n_save, 100.0 * n_save / len(all_delta)))
    print("G3 equal: %d; G3 worse: %d" % (n_eq, n_worse))
    print("mean delta (static-search): %.3f calls" % (sum(all_delta) / len(all_delta)))
    print("mean static calls: %.2f, mean search calls: %.2f"
          % (sum(r["static"]["calls"] for r in all_rows) / len(all_rows),
             sum(r["search"]["calls"] for r in all_rows) / len(all_rows)))

    Path(args.out).write_text(json.dumps({
        "config": {"budget": args.budget, "n": args.n, "first_window": args.first_window},
        "importance": {"S1": 1.0, "S2": 5.0},
        "questions": QUESTIONS,
        "summary": summary,
        "runs": all_rows,
    }, ensure_ascii=False, indent=2))
    print("Wrote %s" % args.out)


if __name__ == "__main__":
    main()