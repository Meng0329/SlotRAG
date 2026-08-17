#!/usr/bin/env python3
"""G3 order+allocation benefit probe — star (3-slot) with order freedom.

Structure: S1 and S2 are INDEPENDENT siblings that both bind ?country (from
different angles), S3 joins both on ?country and produces the answer. The join
graph is connected (star: S1--S3, S2--S3), but S1/S2 have no edge between them,
so BOTH execution orders [S1,S2,S3] and [S2,S1,S3] are dependency-respecting.

Importance: S1 = person->birth country (low, 1.0), S2 = country->population
(high, 5.0). Under a tight budget, static (cost-proxy, uniform allocation) may
run S1 first and expand it; G3 (importance-weighted) should prioritize S2.

Self-check: prints the first-window passage ids per slot to confirm S2's truth
is outside the first window, so EXPAND_TOPK can make a difference.
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


CORPUS = [
    # S1 truth (strong BM25): doc1
    ("doc1", "Marie Curie was born in Warsaw, a city in Poland, in 1867."),
    # S2 truth (weak lexical match, ranked below distractors): doc8
    ("doc2", "Warsaw is the capital city of Poland, famous for its Old Town and Vistula river."),
    ("doc3", "The population of Paris is approximately 2.1 million people."),
    ("doc4", "Tokyo has a population of roughly 14 million people."),
    ("doc5", "London is the capital of England with about 9 million people."),
    ("doc6", "Berlin has a population of approximately 3.7 million people."),
    ("doc7", "Madrid, capital of Spain, has roughly 3.3 million inhabitants."),
    ("doc8", "Poland had approximately 38 million people according to a 2021 demographic estimate."),
    ("doc9", "Rome is the capital of Italy with a population around 2.8 million."),
    ("doc10", "Moscow, the capital of Russia, has about 12 million residents."),
]


def _slot_plan():
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
            Slot(id="S3", predicate="Combine Country Facts",
                 arguments=["?country"],
                 variable_types={"country": "string"},
                 estimated_cardinality=3, estimated_cost=0.5, importance=1.0),
        ],
        joins=[
            JoinSpec(left_slot="S1", left_field="country", right_slot="S3", right_field="country"),
            JoinSpec(left_slot="S2", left_field="country", right_slot="S3", right_field="country"),
        ],
        outputs=["?country", "?pop"],
    )


def _providers():
    from slotrag.cli import load_config
    from slotrag.providers import provider_clients
    cfg = load_config(ROOT / "configs" / "default.yaml")
    return cfg, provider_clients(cfg)


def _build_retriever(embedding, reranker):
    from slotrag.models import Passage
    from slotrag.retrieval import HybridRetriever
    passages = [Passage(id=docid, text=text, doc_id=docid) for docid, text in CORPUS]
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
    ap.add_argument("--budget", type=int, default=3)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--out", type=str, default="/tmp/g3_star_probe.json")
    ap.add_argument("--first-window", type=int, default=2)
    args = ap.parse_args(argv[1:])
    _load_env()

    from slotrag.qo import compile_physical_plan, logical_plan_from_slot_plan
    from slotrag.optimizer import PlanObjectiveParams, search_physical_plans
    from slotrag.planner import AdaptiveExecutor, SlotMaterializer, derive_evidence_state
    from slotrag.action_policy import PhysicalActionPolicy

    _cfg, (client, embedding, reranker) = _providers()
    retriever = _build_retriever(embedding, reranker)
    plan = _slot_plan()
    logical = logical_plan_from_slot_plan(plan)
    cal = _calibrator()

    static = compile_physical_plan(logical, retrieval_strategy="hybrid")
    searched, tele = search_physical_plans(
        logical,
        params=PlanObjectiveParams(
            retrieval_budget=args.budget,
            requirement_importance={"S1": 1.0, "S2": 5.0, "S3": 1.0}),
    )

    def run_with(physical):
        mat = SlotMaterializer(client, retriever, max_passages=args.first_window)
        executor = AdaptiveExecutor(
            mat,
            max_retrieval_calls=args.budget,
            max_binding_contexts=2,
            random_seed=2027,
            sufficiency_calibrator=cal,
            action_policy=PhysicalActionPolicy(topk_expansion_mode="utility"),
        )
        result = executor.execute(plan, strategy="adaptive", physical_plan=physical)
        state = derive_evidence_state(plan, result)
        return result, state

    # --- first-window self-check: S2 truth outside window? ---
    print("=== FIRST-WINDOW SELF-CHECK (max_passages=%d) ===" % args.first_window)
    s2_query = "Country Population ?country ?pop"
    results = retriever.search(s2_query)
    top_ids = [r.passage.id for r in results[:args.first_window]]
    all_ids = [r.passage.id for r in results]
    truth_in_window = "doc8" in top_ids
    print("S2 query:", repr(s2_query))
    print("First %d ids: %s" % (args.first_window, top_ids))
    print("All ids: %s" % all_ids)
    print("Truth doc8 in first window? %s" % truth_in_window)
    if not truth_in_window:
        print("PASS: premise holds (truth outside first window)")
    else:
        print("WARNING: truth in first window — premise may be weak")
    print()

    out_rows = []
    for run_i in range(args.n):
        res_s, st_s = run_with(static)
        res_g, st_g = run_with(searched)
        row = {
            "run": run_i,
            "static": {
                "allocated": {sid: ba.retrieval_calls for sid, ba in static.budget_allocation.items()},
                "order": res_s.order,
                "retrieval_calls": res_s.metrics.retrieval_calls,
                "llm_calls": res_s.metrics.llm_calls,
                "satisfied": st_s.satisfied_count(),
                "answer": res_s.answer,
                "evidence": len(res_s.evidence),
                "status": res_s.status,
                "error": res_s.error,
            },
            "search": {
                "allocated": {sid: ba.retrieval_calls for sid, ba in searched.budget_allocation.items()},
                "order": res_g.order,
                "retrieval_calls": res_g.metrics.retrieval_calls,
                "llm_calls": res_g.metrics.llm_calls,
                "satisfied": st_g.satisfied_count(),
                "answer": res_g.answer,
                "evidence": len(res_g.evidence),
                "status": res_g.status,
                "error": res_g.error,
            },
        }
        out_rows.append(row)
        print("run %d: static order=%s calls=%d sat=%d ans=%r | search order=%s calls=%d sat=%d ans=%r"
              % (run_i, res_s.order, res_s.metrics.retrieval_calls, st_s.satisfied_count(), res_s.answer,
                 res_g.order, res_g.metrics.retrieval_calls, st_g.satisfied_count(), res_g.answer))

    Path(args.out).write_text(json.dumps({
        "corpus": [{"id": d, "text": t} for d, t in CORPUS],
        "first_window": args.first_window,
        "budget": args.budget,
        "importance": {"S1": 1.0, "S2": 5.0, "S3": 1.0},
        "static_allocated": {sid: ba.retrieval_calls for sid, ba in static.budget_allocation.items()},
        "search_allocated": {sid: ba.retrieval_calls for sid, ba in searched.budget_allocation.items()},
        "search_telemetry": tele.model_dump(),
        "truth_outside_window": not truth_in_window,
        "s2_top_ids": all_ids,
        "runs": out_rows,
    }, ensure_ascii=False, indent=2))
    print("\nWrote %s" % args.out)


if __name__ == "__main__":
    main()
