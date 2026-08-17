#!/usr/bin/env python3
"""G5 estimator — counterfactual pseudo-labeling feasibility probe.

Motivation (裁决11/12): real SlotCompiler emits flat importance=1.0 for every
slot, so G3 allocation === static uniform and requirement-aware allocation has
no signal to consume. The pending design question is: where does per-slot
"importance" ground-truth come from without human labeling?

This probe tests the counterfactual pseudo-labeling thesis:
  per-slot importance is learnable from execution trajectories by treating the
  retrieval-call budget as an experimental knob — a slot's importance is
  "how much evidence is lost if we cut this slot's allocation", measured by
  running the SAME plan at DIFFERENT per-slot budgets and observing which slot,
  when starved, destroys the answer's evidence support.

Concretely: for a fixed chain plan over a fixed corpus, enumerate per-slot
budgets from a floor (abelow) to a generous ceiling, execute each, and record
whether the gold-evidence truth is retained. The slots whose truth drops out
when their budget shrinks are empirically "high-importance". If this signal is
(a) measurable and (b) NOT constant across slots, then it is a viable
supervision target for a G5 importance estimator.

Honest: if all slots collapse at the same budget (no differential signal), the
counterfactual thesis is falsified in this fixture and we report it as such.
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


# 2-slot chain, same shape as the §9/§10 decisive positive probes.
# S1 truth in doc1 (strong), S2 truth in doc8 (deliberately scarce, no
# "population" keyword -> ranks outside the first window, EXPAND-recoverable).
CORPUS = [
    ("doc1", "Marie Curie was born in Warsaw, a city in Poland, in 1867."),
    ("doc2", "Warsaw is the capital city of Poland, famous for its Old Town."),
    ("doc3", "The population of Paris is approximately 2.1 million people."),
    ("doc4", "Tokyo has a population of roughly 14 million people."),
    ("doc5", "London has a population of about 9 million people."),
    ("doc6", "Berlin has a population of about 3.7 million people."),
    ("doc7", "Madrid has a population of roughly 3.3 million people."),
    ("doc8", "Poland had approximately 38 million people according to a 2021 demographic estimate."),
    ("doc9", "Rome has a population of approximately 2.8 million people."),
    ("doc10", "Moscow has a population of about 12 million people."),
]
# S2 truth = doc8; S1 truth = doc1.
GOLD = {"S1": "doc1", "S2": "doc8"}
S2_SLOT_QUERY = "Country Population ?country ?pop"
FIRST_WINDOW = 2  # truth doc8 rank ~5 -> outside window -> EXPAND needed for S2.
EXPAND_TARGET = 10


def _slot_plan():
    from slotrag.models import JoinSpec, Slot, SlotPlan
    # per-slot budget sweep is applied at the *executor* level (max_retrieval_calls)
    # and through physical plan allocation; we keep static importance flat (1.0)
    # to test ONLY the budget->evidence drop signal, decoupled from G3's own
    # importance weighting (which is the thing we're trying to find a target for).
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
    ap.add_argument("--budgets", type=str, default="3,4,5,6",
                    help="comma-sep TOTAL execution budgets to sweep")
    ap.add_argument("--n", type=int, default=2, help="repeats per budget")
    ap.add_argument("--out", type=str, default="/tmp/g5_pseudolabel_probe.json")
    ap.add_argument("--first-window", type=int, default=FIRST_WINDOW)
    args = ap.parse_args(argv[1:])
    _load_env()

    from slotrag.planner import AdaptiveExecutor, SlotMaterializer, derive_evidence_state
    from slotrag.qo import compile_physical_plan, logical_plan_from_slot_plan
    from slotrag.action_policy import PhysicalActionPolicy

    _cfg, (client, embedding, reranker) = _providers()
    retriever = _build_retriever(embedding, reranker)

    budgets = [int(b) for b in args.budgets.split(",") if b.strip()]
    plan = _slot_plan()
    logical = logical_plan_from_slot_plan(plan)
    # static plan (uniform allocation) is the right test bed for "does starving
    # a slot drop evidence" — G3's allocation is what we want to LEARN, so we
    # must not feed it a fixed hand-set allocation here.
    static = compile_physical_plan(logical, retrieval_strategy="hybrid")
    cal = _calibrator()

    def run_with(budget):
        mat = SlotMaterializer(client, retriever, max_passages=args.first_window)
        ex = AdaptiveExecutor(
            mat, max_retrieval_calls=budget, max_binding_contexts=2,
            random_seed=2027, sufficiency_calibrator=cal,
            action_policy=PhysicalActionPolicy(topk_expansion_mode="utility"))
        r = ex.execute(plan, strategy="adaptive", physical_plan=static)
        evid = {e.source_id for e in r.evidence}
        # per-slot binding truth: does the slot's extracted binding contain the
        # gold value? This is the CALIBRATOR-FREE pseudo-label — bindings are the
        # raw extraction, not filtered by sufficiency judgment.
        bindings = {}
        for t in r.slot_traces:
            binds = t.binding_contexts
            # S1 truth = any binding has country=="Poland"
            # S2 truth = any binding has pop=="38 million" (or country=="Poland")
            s1_ok = any(
                str(b.get("country", "")).strip().lower() == "poland"
                for b in binds if isinstance(b, dict))
            s2_ok = any(
                (str(b.get("pop", "")).strip().lower() == "38 million")
                or (str(b.get("country", "")).strip().lower() == "poland")
                for b in binds if isinstance(b, dict))
            if t.slot_id == "S1":
                bindings["S1"] = s1_ok
            elif t.slot_id == "S2":
                bindings["S2"] = s2_ok
        return r, evid, bindings

    # sanity: does S2 truth fall outside the first window for its query?
    s2_res = retriever.search(S2_SLOT_QUERY)
    s2_all = [rr.passage.id for rr in s2_res]
    s2_rank = s2_all.index(GOLD["S2"]) if GOLD["S2"] in s2_all else -1
    print("self-check: %s rank=%d, in first window(%d)? %s  (must be False to make S2 scarce)"
          % (GOLD["S2"], s2_rank, args.first_window, GOLD["S2"] in s2_all[:args.first_window]))

    rows = []
    per_budget = {}
    for budget in budgets:
        kept_s1, kept_s2 = [], []
        for run in range(args.n):
            res, evid, bindings = run_with(budget)
            kept_s1.append(bindings.get("S1", False))
            kept_s2.append(bindings.get("S2", False))
            rows.append({
                "budget": budget, "run": run,
                "status": res.status, "calls": res.metrics.retrieval_calls,
                "keep_s1": GOLD["S1"] in evid, "keep_s2": GOLD["S2"] in evid,
                "bind_s1": bindings.get("S1", False), "bind_s2": bindings.get("S2", False),
                "evidence_ids": sorted(evid), "actions": res.metrics.physical_action_executed,
            })
        per_budget[budget] = {
            "keep_s1_rate": sum(kept_s1) / max(len(kept_s1), 1),
            "keep_s2_rate": sum(kept_s2) / max(len(kept_s2), 1),
        }
        print("budget=%d: BIND S1(truth doc1)=%.2f BIND S2(truth doc8)=%.2f"
              % (budget, per_budget[budget]["keep_s1_rate"], per_budget[budget]["keep_s2_rate"]))

    # differential signal: does starvation drop S2 before/independently of S1?
    b_min, b_max = min(budgets), max(budgets)
    s2_at_min = per_budget.get(b_min, {}).get("keep_s2_rate", None)
    s2_at_max = per_budget.get(b_max, {}).get("keep_s2_rate", None)
    s1_at_min = per_budget.get(b_min, {}).get("keep_s1_rate", None)
    s1_at_max = per_budget.get(b_max, {}).get("keep_s1_rate", None)
    differential = (
        s2_at_min is not None and s2_at_max is not None
        and abs(s2_at_min - s2_at_max) > 1e-9
        and abs(s1_at_min - s1_at_max) < 1e-9
    )
    print("\n=== differential (counterfactual) signal ===")
    print("S2 truth keep: min-budget=%.2f -> max-budget=%.2f" % (s2_at_min, s2_at_max))
    print("S1 truth keep: min-budget=%.2f -> max-budget=%.2f" % (s1_at_min, s1_at_max))
    print("DIFFERENTIAL signal present (S2 collapses, S1 stable)?", differential)
    if not differential:
        print("HONEST: no differential counterfactual signal in this fixture.")

    Path(args.out).write_text(json.dumps({
        "conclusion": {
            "differential_signal_present": differential,
            "interpretation": (
                "S2 (scarce truth) is the high-importance slot IF starving it "
                "drops evidence while S1 is robust. That per-slot budget->evidence "
                "dependence is a usable pseudo-label for a G5 importance estimator."
                if differential else
                "no usable signal — budget does not discriminate slots in this fixture."),
        },
        "per_budget": per_budget,
        "bulget_sweep": budgets,
        "first_window": args.first_window,
        "expand_target": EXPAND_TARGET,
        "s2_truth_rank": s2_rank,
        "runs": rows,
    }, ensure_ascii=False, indent=2))
    print("Wrote %s" % args.out)


if __name__ == "__main__":
    main()