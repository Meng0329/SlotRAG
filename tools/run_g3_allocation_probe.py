#!/usr/bin/env python3
"""G3 allocation probe (development, non-sealed).

Empirically tests whether G3's requirement-aware per-slot retrieval budget
allocation produces any measurable difference vs the legacy static equal
allocation, on an evidence-scarce corpus where at least one slot stays
PARTIAL after its first retrieval pass (so it could in principle use
EXPAND_TOPK / complementary retrieval to recover).

Honesty contract:
  * No gold evidence is fed to retrieval. No simulation. Every number is a
    REAL service run trace.
  * Both plans run under the SAME total retrieval-call budget
    (identical retrieval + call budgets in the PVLDB protocol sense).
  * Whatever difference (or lack thereof) is reported, including if G3
    shows no benefit.

What is enabled that the smoke deliberately leaves off (so allocation can
bite -- verified by reading planner.py ~3375-3430):

  1. `SlotMaterializer(...)` keeps the default `max_passages` (small first
     window) so that EXPAND_TOPK has a *smaller* current_top_k to expand FROM
     (planned_top_k from the PhysicalPlan is the EXPAND target).
  2. `AdaptiveExecutor(...)` receives a `PhysicalActionPolicy`
     (topk_expansion_mode="utility") so `_evaluate_sufficiency_and_action`
     actually emits EXPAND_TOPK / complementary candidates instead of a
     None action decision (the smoke passes no action_policy -> always stops
     after the first materialization).
  3. `complementary_retrieval=True` so the question-aware slot+lexical variant
     action is also available (the task names "expansion/complementary").
  4. `sufficiency_calibrator` wired from the dev calibrator so
     `satisfied_count()` reflects a real judgment (without it, predictions
     are None and no action is ever chosen).

Corpus (4 docs, two-hop person -> country -> population):
  The HIGH-importance slot S2 (Country Population) is intentionally written
  so its truth-bearing passage ("Poland population 38 million") is a weak
  lexical match to the S2 query and can fall OUTSIDE a small first top-k
  window, leaving S2 PARTIAL; expanding top_k to the PhysicalPlan's planned
  top_k (default 10) recovers it. The LOW slot S1 (Born In Country) is strong
  and reaches SUFFICIENT on the first pass.

Allocation math (read from optimizer.py _allocate_budget_between):
  static (qo.compile_physical_plan): retrieval_calls = 2 * beam_width = 4 PER
    slot, regardless of the global budget. So each slot's slot_call_budget = 4.
  G3 search_physical_plans: splits `retrieval_budget` across slots proportional
    to requirement_importance (default 1 each, here {S1:1.0, S2:4.0}, each
    slot >= 1 base call). So at total budget B, G3 gives S2 =
    1 + floor-weighted-extra favoring S2.

The honest test runs BOTH plans at the SAME total `retrieval_budget` and
reports the *realized* retrieval calls, expansion/complementary actions,
per-slot sufficiency, and answer -- not the allocated budget (which is just
context for why something did or did not happen.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def _load_env():
    env_path = ROOT / ".env"
    shellsafe = '"' + str(env_path) + '"'
    if not env_path.exists():
        raise SystemExit("missing .env")
    cmd = ["bash", "-c", "set -a; .  %s ; set +a; env" % shellsafe]
    out = subprocess.check_output(cmd, text=True)
    for line in out.splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k, v)
    # NEVER log/print .env contents.


# --- evidence-scarce development corpus (4 docs, two-hop) -------------------
# S1 (LOW importance, 1.0): Born In Country  -- strong, reaches SUFFICIENT fast.
# S2 (HIGH importance, 4.0): Country Population -- truth doc is a weak lexical
#   match so a small first top-k window can miss it (PARTIAL), requiring a
#   top-k EXPAND to recover the (country, population) binding.
CORPUS = [
    # doc1: S1 strong. "born", "Warsaw", "Poland" -- high BM25 score for S1 query.
    ("doc1", "Marie Curie was born in Warsaw, the capital of Poland, in 1867."),
    # doc2: S2 truth. Weak lexical match to the S2 query "Country Population <v>".
    #   "population ... Poland ..." carries the answer but ranks low for a naive
    #   slot query; with a small first top_k it may fall outside the window.
    ("doc2", "A 2021 estimate placed the population of Poland at roughly 38 million people."),
    # doc3: S1 decoy / S2 distractor. Different country, strong "population" hit.
    ("doc3", "The population of Germany is about 84 million according to recent statistics."),
    # doc4: join bridge filler. Mentions Warsaw and Poland but not population,
    #   not the birth fact -- keeps the 4-doc set tight and ranked non-trivially.
    ("doc4", "Warsaw is a city in Poland on the Vistula river."),
]

# S1 query is strong -> doc1/doc4 rank top. S2 query "Country Population" ->
# doc2 (truth) and doc3 (distractor) carry "population" + a country; doc1/doc4
# carry neither "population" nor a number -> doc1/doc4 rank LOW for S2.
QUESTION = "Marie Curie was born in what country, and what is that country's population?"


def _slot_plan():
    from slotrag.models import JoinSpec, Slot, SlotPlan
    return SlotPlan(
        slots=[
            Slot(id="S1", predicate="Born In Country", arguments=["?p", "?country"],
                 variable_types={"p": "string", "country": "string"},
                 estimated_cardinality=8, estimated_cost=1.2, importance=1.0),
            Slot(id="S2", predicate="Country Population", arguments=["?country", "?pop"],
                 variable_types={"country": "string", "pop": "number"},
                 estimated_cardinality=4, estimated_cost=1.0, importance=4.0),
        ],
        joins=[JoinSpec(left_slot="S1", left_field="country",
                        right_slot="S2", right_field="country")],
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
        bm25_k=4, dense_k=4, final_k=3,
        rrf_k=60,
        rerank_enabled=False,
        sparse_index_mode="body",
    )


def _calibrator():
    from slotrag.sufficiency import EvidenceSufficiencyCalibrator
    import json as _json
    cal = ROOT / "runs_archive" / "slotrag-sufficiency-smoke-v60" / "calibrator.json"
    if cal.exists():
        return EvidenceSufficiencyCalibrator.from_dict(_json.loads(cal.read_text()))
    return None


def _materializer(client, retriever, max_passages):
    from slotrag.planner import SlotMaterializer
    return SlotMaterializer(
        client, retriever,
        max_passages=max_passages,
        primary_query_variant="slot",  # enables question-aware complementary variant
    )


_EXECUTOR_KW = dict(
    max_retrieval_calls=8,
    max_binding_contexts=2,
    random_seed=2027,
    complementary_retrieval=True,
)


def run_plan(plan, physical, client, embedding, reranker, budget,
             max_passages=3, calibrator=None):
    from slotrag.planner import AdaptiveExecutor
    from slotrag.action_policy import PhysicalActionPolicy
    from slotrag.generation import generate_answer
    from slotrag.planner import derive_evidence_state
    retriever = _build_retriever(embedding, reranker)
    materializer = _materializer(client, retriever, max_passages=max_passages)
    policy = PhysicalActionPolicy(topk_expansion_mode="utility")
    executor = AdaptiveExecutor(
        materializer,
        max_retrieval_calls=budget,
        max_binding_contexts=2,
        random_seed=2027,
        sufficiency_calibrator=calibrator,
        complementary_retrieval=True,
        action_policy=policy,
    )
    result, _ = _execute_once(executor, plan, physical, client, max_passages)
    return result


def _execute_once(executor, plan, physical, client, max_passages):
    from slotrag.generation import generate_answer
    from slotrag.planner import derive_evidence_state
    result = executor.execute(plan, strategy="adaptive",
                              physical_plan=physical)
    answer, gp, gc, _lat = generate_answer(client, QUESTION, result)
    result.answer = answer if answer else None
    result.metrics = result.metrics.model_copy(update={
        "prompt_tokens": result.metrics.prompt_tokens + gp,
        "completion_tokens": result.metrics.completion_tokens + gc,
    })
    state = derive_evidence_state(plan, result)
    return result, state


def _slot_metrics(result):
    """Per-slot realized retrieval calls + sufficiency from traces."""
    out = {}
    for trace in result.slot_traces:
        out[trace.slot_id] = dict(
            rows=trace.extracted_row_count,
            sufficiency_status=trace.sufficiency_status,
            sufficiency_probability=trace.sufficiency_probability,
            action_selected=trace.action_selected,
            action_executed=trace.action_executed,
            action_execution_reason=trace.action_execution_reason,
            action_rows_added=trace.action_rows_added,
            action_retrieval_calls=trace.action_retrieval_calls,
            action_top_k_before=trace.action_top_k_before,
            action_top_k_after=trace.action_top_k_after,
        )
    return out


def _plan_budgets(physical):
    return {sid: ba.retrieval_calls for sid, ba in
            physical.budget_allocation.items()}


def main(argv=None):
    argv = argv or sys.argv
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--budgets", type=int, nargs="+", default=[4, 8])
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--max-passages", type=int, default=3)
    args = ap.parse_args(argv[1:])
    _load_env()

    from slotrag.qo import compile_physical_plan, logical_plan_from_slot_plan
    from slotrag.optimizer import PlanObjectiveParams, search_physical_plans

    cfg, (client, embedding, reranker) = _providers()
    plan = _slot_plan()
    logical = logical_plan_from_slot_plan(plan)
    calibrator = _calibrator()

    out_rows = []
    for budget in args.budgets:
        # static (legacy) plan: uniform 4-per-slot allocation baked by qo.
        static_phys = compile_physical_plan(logical, retrieval_strategy="hybrid")
        # G3 search: importance-weighted allocation across slots.
        searched_phys, tele = search_physical_plans(
            logical,
            params=PlanObjectiveParams(
                retrieval_budget=budget,
                requirement_importance={"S1": 1.0, "S2": 4.0},
            ),
        )
        print(json.dumps({
            "event": "allocation",
            "budget": budget,
            "static_allocation": _plan_budgets(static_phys),
            "g3_allocation": _plan_budgets(searched_phys),
            "g3_selected_order": tele.selected_order,
            "g3_selected_calls": tele.selected_retrieval_calls_by_slot,
            "g3_utility": tele.selected_estimated_utility,
        }, ensure_ascii=False))
        for run_i in range(max(args.n, 1)):
            t0 = time.perf_counter()
            res_static = run_plan(plan, static_phys, client, embedding,
                                  reranker, budget, max_passages=args.max_passages,
                                  calibrator=calibrator)
            res_search = run_plan(plan, searched_phys, client, embedding,
                                  reranker, budget, max_passages=args.max_passages,
                                  calibrator=calibrator)
            dt = time.perf_counter() - t0
            from slotrag.planner import derive_evidence_state
            st_static = derive_evidence_state(plan, res_static)
            st_search = derive_evidence_state(plan, res_search)
            row = {
                "budget": budget, "run": run_i,
                "max_passages": args.max_passages,
                "static": dict(
                    allocated_budget=_plan_budgets(static_phys),
                    retrieval_calls=res_static.metrics.retrieval_calls,
                    llm_calls=res_static.metrics.llm_calls,
                    expansion_actions=res_static.metrics.physical_action_executed,
                    expansion_count=res_static.metrics.physical_action_executions,
                    extra_retrieval_calls=res_static.metrics.physical_action_extra_retrieval_calls,
                    rows_added=res_static.metrics.physical_action_rows_added,
                    order=res_static.order,
                    status=res_static.status,
                    answered=bool(res_static.answer),
                    answer=res_static.answer,
                    per_slot=_slot_metrics(res_static),
                    evidence=len(res_static.evidence),
                    satisfied=st_static.satisfied_count(),
                ),
                "g3": dict(
                    allocated_budget=_plan_budgets(searched_phys),
                    retrieval_calls=res_search.metrics.retrieval_calls,
                    llm_calls=res_search.metrics.llm_calls,
                    expansion_actions=res_search.metrics.physical_action_executed,
                    expansion_count=res_search.metrics.physical_action_executions,
                    extra_retrieval_calls=res_search.metrics.physical_action_extra_retrieval_calls,
                    rows_added=res_search.metrics.physical_action_rows_added,
                    order=res_search.order,
                    status=res_search.status,
                    answered=bool(res_search.answer),
                    answer=res_search.answer,
                    per_slot=_slot_metrics(res_search),
                    evidence=len(res_search.evidence),
                    satisfied=st_search.satisfied_count(),
                ),
                "elapsed_s": round(dt, 2),
            }
            out_rows.append(row)
            print(json.dumps(row, ensure_ascii=False))
        print(f"[allocation probe] budget={budget} done")

    out_path = args.out or str(ROOT / "runs" / f"g3_allocation_probe_{int(time.time())}.json")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "corpus": [dict(id=d, text=t) for d, t in CORPUS],
        "question": QUESTION,
        "max_passages_first_window": args.max_passages,
        "static_allocation_note": "qo.compile_physical_plan sets retrieval_calls=2*beam_width=4 per slot, fixed.",
        "runs": out_rows,
    }
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\n[probe] wrote {out_path}")


if __name__ == "__main__":
    main()
