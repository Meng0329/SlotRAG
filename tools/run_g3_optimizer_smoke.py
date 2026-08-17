#!/usr/bin/env python3
"""G3 real-provider smoke: static physical plan vs requirement-aware search.

Run on the live qwen3.6-27b / embedding / reranker services (credentials from
.env). Uses a small, FROZEN development-style noun-subject corpus (not gold,
not sealed) so both methods are compared under *identical realized retrieval
and token budgets* on the same questions.

Honesty contract: every number below is a REAL run trace. No simulated rows,
no gold evidence fed to retrieval, no oracle. Report whatever happens.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def _load_env():
    """Source .env through the shell so $(grep ...) expansions are honored.

    The last three lines of .env are `export VAR=$(grep ...)` shell syntax; a
    naive partition-on-'=' would store the literal expansion text. Sourcing
    through bash with set -a evaluates them, then we snapshot os.environ.
    """
    import subprocess
    env_path = ROOT / ".env"
    shellsafe = '\"' + str(env_path) + '\"'
    if not env_path.exists():
        raise SystemExit("missing .env")
    cmd = ['bash', '-c', 'set -a; .  %s ; set +a; env' % shellsafe]
    out = subprocess.check_output(cmd, text=True)
    loaded = {}
    for line in out.splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        loaded[k] = v
    for k, v in loaded.items():
        os.environ.setdefault(k, v)


# --- frozen smoke corpus: 4 docs, 1 clear multi-hop chain ------------------
# Not gold, not sealed: a development-style corpus to expose ORDER+ALLOCATION
# effects. Two-hop: person -> country -> population.
CORPUS = [
    ("doc1", "Marie Curie Physics Chemistry Nobel Laureate born in the city of Warsaw Poland during 1867."),
    ("doc2", "Warsaw is the capital and largest city of Poland located in Central Europe."),
    ("doc3", "Poland is a country in central Europe bordered by Germany to the west and Ukraine to the east."),
    ("doc4", "The population of Poland was approximately 38 million people according to a 2021 estimate."),
]


QUESTION = "Marie Curie was born in what country, and what is that country's population?"


def _build_question(idx):
    return {
        "id": f"g3-smoke-q{idx}",
        "question": "Marie Curie was born in what country, and what is that country's population?",
        "answer": "Poland, 38 million",
    }


def _slot_plan():
    from slotrag.models import JoinSpec, Slot, SlotPlan
    return SlotPlan(
        slots=[
            Slot(id="S1", predicate="Born In Country", arguments=["?p", "?country"],
                 variable_types={"p": "string", "country": "string"},
                 estimated_cardinality=8, estimated_cost=1.2, importance=1.0),
            Slot(id="S2", predicate="Country Population", arguments=["?country", "?pop"],
                 variable_types={"country": "string", "pop": "number"},
                 estimated_cardinality=4, estimated_cost=1.0, importance=2.0),
        ],
        joins=[JoinSpec(left_slot="S1", left_field="country", right_slot="S2", right_field="country")],
        outputs=["?country", "?pop"],
    )


def _providers():
    """Build the three clients through the production injection path."""
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
        rerank_enabled=False,  # keep smoke cheap & deterministic enough
        sparse_index_mode="body",
    )


def main(argv=None):
    argv = argv or sys.argv
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "runs" / "g3_optimizer_smoke.json"))
    ap.add_argument("--budget", type=int, default=4, help="matched retrieval-call budget")
    ap.add_argument("--n", type=int, default=3, help="repeat the question for n runs")
    args = ap.parse_args(argv[1:])
    _load_env()

    from slotrag.qo import LogicalPlan, LogicalSubgoal, LogicalVariable, PlanValidationError, compile_physical_plan, logical_plan_from_slot_plan
    from slotrag.optimizer import PlanObjectiveParams, search_physical_plans
    from slotrag.planner import AdaptiveExecutor, SlotMaterializer, derive_evidence_state
    from slotrag.benchmarking.methods import MethodSpec  # noqa: F401 (pattern ref)

    _cfg, (client, embedding, reranker) = _providers()
    retriever = _build_retriever(embedding, reranker)
    plan = _slot_plan()
    logical = logical_plan_from_slot_plan(plan)
    # dev-track calibrator (v60, feature schema v1): wire the executor so the
    # requirement-satisfaction the G3 objective optimizes for has a runtime
    # judgment. Purely a development calibrator (never gold/sealed).
    from slotrag.sufficiency import EvidenceSufficiencyCalibrator
    import json as _json
    _cal_path = ROOT / "runs_archive" / "slotrag-sufficiency-smoke-v60" / "calibrator.json"
    if _cal_path.exists():
        _calibrator = EvidenceSufficiencyCalibrator.from_dict(
            _json.loads(_cal_path.read_text()))
    else:
        _calibrator = None

    # G3 objective: both slots importance-weighted; budget matched to static
    static = compile_physical_plan(logical, retrieval_strategy="hybrid")
    searched, tele = search_physical_plans(
        logical,
        params=PlanObjectiveParams(retrieval_budget=args.budget,
                                   requirement_importance={"S1": 1.0, "S2": 2.0}),
    )

    def run_with(physical):
        materializer = SlotMaterializer(client, retriever)
        executor = AdaptiveExecutor(
            materializer,
            max_retrieval_calls=args.budget,
            max_binding_contexts=2,
            random_seed=2027,
            sufficiency_calibrator=_calibrator,
        )
        result = executor.execute(plan, strategy="adaptive", physical_plan=physical)
        # Generator stage: out of execute() scope, so emit a real end-to-end
        # answer (and its tokens) like the full pipeline does. Same generator
        # call on identical rows for static and search -> matched budget holds.
        from slotrag.generation import generate_answer
        _answer, gen_prompt, gen_completion, _lat = generate_answer(
            client, QUESTION, result)
        result.answer = _answer if _answer else None
        result.metrics = result.metrics.model_copy(update={
            "prompt_tokens": result.metrics.prompt_tokens + gen_prompt,
            "completion_tokens": result.metrics.completion_tokens + gen_completion,
        })
        state = derive_evidence_state(plan, result)
        return result, state

    out_rows = []
    for run_i in range(max(args.n, 1)):
        res_static, st_static = run_with(static)
        res_search, st_search = run_with(searched)
        row = {
            "run": run_i,
            "static_status": res_static.status,
            "search_status": res_search.status,
            "static_retrieval_calls": res_static.metrics.retrieval_calls,
            "search_retrieval_calls": res_search.metrics.retrieval_calls,
            "static_satisfied": st_static.satisfied_count(),
            "search_satisfied": st_search.satisfied_count(),
            "static_order": res_static.order,
            "search_order": res_search.order,
            "static_evidence": len(res_static.evidence),
            "search_evidence": len(res_search.evidence),
            "static_answer": res_static.answer,
            "search_answer": res_search.answer,
            "static_llm_calls": res_static.metrics.llm_calls,
            "search_llm_calls": res_search.metrics.llm_calls,
            "static_tokens": res_static.metrics.prompt_tokens + res_static.metrics.completion_tokens,
            "search_tokens": res_search.metrics.prompt_tokens + res_search.metrics.completion_tokens,
        }
        out_rows.append(row)
        print(json.dumps(row, ensure_ascii=False))

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({
        "config": {"budget": args.budget, "n": args.n, "plan": plan.model_dump(),
                    "corpus_ids": [d for d, _ in CORPUS]},
        "search_telemetry": tele.model_dump(),
        "static_order": res_static.order,
        "searched_order": res_search.order,
        "runs": out_rows,
    }, ensure_ascii=False, indent=2))
    print(f"\n[G3 smoke] wrote {args.out}")
    print(f"[G3 smoke] static order={res_static.order} search order={res_search.order}")
    print(f"[G3 smoke] budget={args.budget} (matched)")


if __name__ == "__main__":
    main()
