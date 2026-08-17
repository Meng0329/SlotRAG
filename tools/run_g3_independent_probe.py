#!/usr/bin/env python3
"""G3 allocation benefit probe — two INDEPENDENT slots, tight budget, evidence-scarce corpus.

Structural test: with budget=3 and max_passages=2 first window, each slot needs
1 base + 1 expand = 2 calls, but the global budget is only 3. One slot must go
unexpanded. Static allocates uniformly (both slots get 4 in the plan), so its
execution order (cost-proxy) expands the LOW-importance slot first, wasting the
budget. G3 allocates importance-weighted (high-importance slot gets more), so it
expands the HIGH-importance slot first. If the high-importance slot's truth is
OUTSIDE the first window but INSIDE the expanded window, G3 benefits.

Self-check: prints the first-window passage ids per slot so we can verify the
"truth outside window" premise holds.
"""

from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def _load_env():
    """Source .env through the shell so $(grep ...) expansions are honored."""
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


# --- corpus: two independent questions, evidence-scarce for high-importance slot ---
# S1: person birth city — truth in doc1 (strong BM25 hit), always top-2.
# S2: Warsaw population — truth in doc8 ("Poland 38 million", no "Warsaw"), ranks
#     behind 5-6 distractor docs about OTHER cities' populations in BM25, so it
#     falls outside max_passages=2.

S1_CORPUS = [
    ("doc1", "Marie Curie was born in Warsaw, a city in Poland, in 1867."),
    ("doc2", "Warsaw is the capital city of Poland, known for its rich history and culture."),
    ("doc3", "The population of Paris is approximately 2.1 million people according to recent data."),
    ("doc4", "Tokyo has a population of roughly 14 million, making it the world's largest metro area."),
]

S2_CORPUS = [
    ("doc5", "Paris is the capital of France with approximately 2.1 million residents."),
    ("doc6", "Tokyo is the most populous city on earth with around 14 million people."),
    ("doc7", "London has a population of approximately 9 million people."),
    ("doc8", "Poland had approximately 38 million people according to a 2021 demographic estimate."),
    ("doc9", "Berlin is the capital of Germany with a population of about 3.7 million."),
    ("doc10", "Madrid, the capital of Spain, has roughly 3.3 million inhabitants."),
]

# Combined corpus for the shared retriever
FULL_CORPUS = S1_CORPUS + S2_CORPUS


def _slot_plan():
    from slotrag.models import Slot, SlotPlan
    return SlotPlan(
        slots=[
            Slot(id="S1", predicate="Person Birth City",
                 arguments=["?person", "?city"],
                 variable_types={"person": "string", "city": "string"},
                 estimated_cardinality=5, estimated_cost=1.0, importance=1.0),
            Slot(id="S2", predicate="City Population",
                 arguments=["?city", "?pop"],
                 variable_types={"city": "string", "pop": "number"},
                 estimated_cardinality=5, estimated_cost=1.5, importance=5.0),
        ],
        # NO joins — independent slots, order not locked
        outputs=["?person", "?city", "?pop"],
    )


def _providers():
    from slotrag.cli import load_config
    from slotrag.providers import provider_clients
    cfg = load_config(ROOT / "configs" / "default.yaml")
    return cfg, provider_clients(cfg)


def _build_retriever(embedding, reranker):
    from slotrag.models import Passage
    from slotrag.retrieval import HybridRetriever
    passages = [Passage(id=docid, text=text, doc_id=docid) for docid, text in FULL_CORPUS]
    return HybridRetriever(
        passages=passages,
        embedding_client=embedding,
        reranker_client=reranker,
        bm25_k=8, dense_k=8, final_k=8,
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
    ap.add_argument("--budget", type=int, default=3, help="global matched retrieval-call budget")
    ap.add_argument("--n", type=int, default=3, help="repeat runs for stability")
    ap.add_argument("--out", type=str, default="/tmp/g3_independent_probe.json")
    ap.add_argument("--first-window", type=int, default=2, help="initial max_passages (small)")
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
            requirement_importance={"S1": 1.0, "S2": 5.0}),
    )

    def run_with(physical, label):
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
        return result, state, mat

    # --- first-window self-check: verify truth outside window for S2 ---
    print("=== FIRST-WINDOW SELF-CHECK (max_passages=%d) ===" % args.first_window)
    from slotrag.models import Slot
    s2_query = "City Population ?city ?pop"
    mat_check = SlotMaterializer(client, retriever, max_passages=args.first_window)
    from slotrag.models import JoinSpec
    s2_only = _slot_plan().slots[1]  # S2 = City Population
    # direct retrieval check
    results = retriever.search(s2_query)
    top_ids = [r.passage.id for r in results[:args.first_window]]
    all_ids = [r.passage.id for r in results]
    s2_truth_id = "doc8"  # "Poland 38 million"
    truth_in_window = s2_truth_id in top_ids
    print("S2 query:", repr(s2_query))
    print("First %d passage ids: %s" % (args.first_window, top_ids))
    print("All passage ids: %s" % all_ids)
    print("Truth doc (%s) in first window? %s" % (s2_truth_id, truth_in_window))
    if not truth_in_window:
        print("PASS: premise holds — truth outside first window")
    else:
        print("WARNING: truth IS in first window — probe premise may be weak")
    print()

    out_rows = []
    for run_i in range(args.n):
        res_static, st_static, mat_static = run_with(static, "static")
        res_search, st_search, mat_search = run_with(searched, "search")
        # build per-slot expansion info
        row = {
            "run": run_i,
            "budget": args.budget,
            "first_window": args.first_window,
            "static": {
                "allocated": static.budget_allocation,
                "order": res_static.order,
                "retrieval_calls": res_static.metrics.retrieval_calls,
                "satisfied": st_static.satisfied_count(),
                "answer": res_static.answer,
                "evidence": len(res_static.evidence),
            },
            "search": {
                "allocated": {sid: ba.retrieval_calls
                              for sid, ba in searched.budget_allocation.items()},
                "order": res_search.order,
                "retrieval_calls": res_search.metrics.retrieval_calls,
                "satisfied": st_search.satisfied_count(),
                "answer": res_search.answer,
                "evidence": len(res_search.evidence),
            },
            "search_telemetry": tele.model_dump(),
        }
        out_rows.append(row)
        # per-run summary
        s_order = res_static.order
        g_order = res_search.order
        print("run %d: static_order=%s calls=%d satisfied=%d | search_order=%s calls=%d satisfied=%d"
              % (run_i, s_order, res_static.metrics.retrieval_calls, st_static.satisfied_count(),
                 g_order, res_search.metrics.retrieval_calls, st_search.satisfied_count()))

    Path(args.out).write_text(json.dumps({
        "corpus": [{"id": d, "text": t} for d, t in FULL_CORPUS],
        "first_window": args.first_window,
        "budget": args.budget,
        "importance": {"S1": 1.0, "S2": 5.0},
        "static_allocated": {sid: ba.retrieval_calls for sid, ba in static.budget_allocation.items()},
        "search_allocated": {sid: ba.retrieval_calls for sid, ba in searched.budget_allocation.items()},
        "search_telemetry": tele.model_dump(),
        "truth_outside_window": not truth_in_window,
        "runs": out_rows,
    }, ensure_ascii=False, indent=2))
    print("\nWrote %s" % args.out)


if __name__ == "__main__":
    main()
