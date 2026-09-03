#!/usr/bin/env python3
"""H-STRUCT-3 §7-§12 — natural-population A' effect + chain efficiency + feasibility.

CPU-only (scoring EM uses gold answers; no LLM/retrieval). Data:
  - validation_confirmatory_results.csv (static + chain, 350 each)
  - hstruct2_flat_results.csv           (flat, 350)
  - budget_feasibility_frontier.csv     (350 feasibility)
  - V1.2 census P(eligible ∧ executable) = 0.05390
"""
import pandas as pd
import numpy as np
import json, pathlib, sys
from collections import Counter
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from slotrag.benchmarking.metrics import score_record, ExecutionResult
from slotrag.benchmarking.datasets import DATASETS as SPECS, iter_jsonl, adapt_record

REPO = pathlib.Path(__file__).resolve().parents[1]
CENSUS = REPO / "research" / "hstruct_validation_census"
RES_VAL = CENSUS / "validation_confirmatory_results.csv"
RES_FLAT = CENSUS / "hstruct2_flat_results.csv"
FRONTIER = CENSUS / "budget_feasibility_frontier.csv"
P_EXEC = 0.05390
SEED = 2027


def build_lookup():
    lookup = {}
    for ds_name, spec in SPECS.items():
        for split_attr in ("evaluation_file", "train_file"):
            rel = getattr(spec, split_attr, None)
            if not rel:
                continue
            path = REPO / "benchmark" / rel
            if not path.exists():
                continue
            split = "validation" if split_attr == "evaluation_file" else "train"
            for idx, record in iter_jsonl(path):
                q = adapt_record(spec, record, idx, split=split)
                lookup[(ds_name, q.id)] = q
    return lookup


def add_score(df, lookup):
    out = []
    for _, row in df.iterrows():
        r = dict(row)
        q = lookup.get((row["dataset"], row["question_id"]))
        em, f1 = 0.0, 0.0
        if q is not None and not pd.isna(row.get("answer")) and str(row.get("answer", "")).strip():
            res = score_record(row["dataset"], q, ExecutionResult(answer=str(row["answer"])))
            em = float(res.get("em", 0.0)); f1 = float(res.get("f1", 0.0))
        r["em"] = em; r["f1"] = f1
        out.append(r)
    return pd.DataFrame(out)


def main():
    lookup = build_lookup()
    val = pd.read_csv(RES_VAL)
    flat = pd.read_csv(RES_FLAT)

    static = add_score(val[val["arm"] == "static"], lookup)
    chain = add_score(val[val["arm"] == "chain"], lookup)
    flat = add_score(flat, lookup)
    print(f"scored: static {len(static)}, chain {len(chain)}, flat {len(flat)}")

    for (label, d) in (("static", static), ("chain", chain), ("flat", flat)):
        print(f"{label}: n={len(d)} EM={d['em'].mean():.4f} not-ok={(d['status']!='ok').sum()} llm={d['llm_calls'].mean():.2f}")

    # ---- per-question three-arm join ----
    sf = static[["question_id", "dataset", "em", "f1", "llm_calls", "retrieval_calls", "status"]].rename(columns={"em": "static_em", "f1": "static_f1", "llm_calls": "static_llm", "retrieval_calls": "static_retr", "status": "static_status"})
    cf = chain[["question_id", "dataset", "em", "f1", "llm_calls", "retrieval_calls", "status"]].rename(columns={"em": "chain_em", "f1": "chain_f1", "llm_calls": "chain_llm", "retrieval_calls": "chain_retr", "status": "chain_status"})
    ff = flat[["question_id", "dataset", "em", "f1", "llm_calls", "retrieval_calls", "status"]].rename(columns={"em": "flat_em", "f1": "flat_f1", "llm_calls": "flat_llm", "retrieval_calls": "flat_retr", "status": "flat_status"})
    joined = sf.merge(cf, on=["question_id", "dataset"]).merge(ff, on=["question_id", "dataset"])
    print(f"three-arm joined: {len(joined)}")

    # A' on natural population: non-eligible => static; eligible&executable (all 350) => flat
    d = joined["flat_em"] - joined["static_em"]
    n = len(d)

    # ---- §7/§8 eligible-stratum + population effects ----
    ate_stratum = d.mean()
    boot_rng = np.random.default_rng(SEED)
    B = 10000
    idx = boot_rng.integers(0, n, size=(B, n))
    d_boot = d.values[idx].mean(axis=1)
    pop_boot = P_EXEC * d_boot
    ci_s = np.percentile(d_boot, [2.5, 97.5])
    ci_p = np.percentile(pop_boot, [2.5, 97.5])

    print("\n=== §7/§8 — ATE_exec_eligible (validation 350) ===")
    print(f"  ATE_exec_eligible = E[EM_flat − EM_static | eligible&exec] = {ate_stratum:+.4f}")
    print(f"  eligible-stratum 95% CI = [{ci_s[0]:+.4f}, {ci_s[1]:+.4f}]")
    ates_pop = P_EXEC * ate_stratum
    print(f"  ATE_population (A') = {P_EXEC} × {ate_stratum:+.4f} = {ates_pop:+.6f}")
    print(f"  population 95% CI = [{ci_p[0]:+.6f}, {ci_p[1]:+.6f}]")

    # ---- §9 population budget_exceeded reduction ----
    be_static = int(joined["static_status"].eq("budget_exceeded").sum())
    be_flat = int(joined["flat_status"].eq("budget_exceeded").sum())
    print("\n=== §9 — Policy A' budget effect (natural population) ===")
    print(f"  350 eligible-exec: static BE={be_static} ({be_static/350:.3f}), flat BE={be_flat}")
    # per 1000 natural questions
    be_stat_per1k = P_EXEC * (be_static / n) * 1000
    be_aprime_per1k = P_EXEC * (be_flat / n) * 1000
    print(f"  static BE per 1000 natural = {be_stat_per1k:.2f}")
    print(f"  A'    BE per 1000 natural = {be_aprime_per1k:.2f}")
    print(f"  absolute reduction = {be_stat_per1k - be_aprime_per1k:.2f} / 1000")
    print(f"  relative reduction = {(1 - be_aprime_per1k / be_stat_per1k) * 100:.1f}% of eligible-region static BE")

    # A' vs always-flat on the 350: A'(=flat here) ≈ flat by construction; report macro from replay
    # ---- §11 chain efficiency audit (350 flat/chain pairs) ----
    print("\n=== §11 — chain-vs-flat exploratory efficiency (350 validation pairs) ===")
    d_llm = (joined["chain_llm"] - joined["flat_llm"]).dropna()
    d_retr = (joined["chain_retr"] - joined["flat_retr"]).dropna()
    n_eff = len(d_llm)
    med = lambda x: np.median(x)

    def eff_report(d, label):
        d_arr = d.values
        ne = len(d_arr)
        m = d_arr.mean()
        bd = d_arr[boot_rng.integers(0, ne, size=(B, ne))].mean(axis=1)
        ci = np.percentile(bd, [2.5, 97.5])
        med = np.median(d_arr)
        # paired permutation sign-flip on the mean
        obs_abs = abs(m)
        perms = (np.sign(boot_rng.standard_normal((B, ne))) * d_arr[np.newaxis, :]).mean(axis=1)
        p_perm = (np.abs(perms) >= obs_abs - 1e-12).mean()
        print(f"  {label}: mean Δ={m:+.4f}, median Δ={med:+.4f}, 95% CI [{ci[0]:+.4f},{ci[1]:+.4f}], perm-p={p_perm:.4f}, n={ne}")

    eff_report(d_llm, "LLM (chain − flat)")
    eff_report(d_retr, "Retrieval (chain − flat)")

    # ---- §12 feasibility proposition + confusion matrix (350 frozen plans) ----
    print("\n=== §12 — Feasibility proposition & confusion matrix ===")
    fr = pd.read_csv(FRONTIER)
    def _as_bool(col):
        s = col.astype(str).str.strip().str.lower()
        return s.map({"true": True, "false": False}).fillna(False).astype(bool)

    pred_infeas = ~_as_bool(fr["static_feasible_B8"])
    obs_be = _as_bool(fr["actual_static_budget_exceeded"])
    tn = int(((~pred_infeas) & (~obs_be)).sum())   # feasible, not-exceeded
    fp = int(((~pred_infeas) & (obs_be)).sum())    # feasible, BUT exceeded
    fn = int((pred_infeas & (~obs_be)).sum())      # infeasible, not exceeded
    tp = int((pred_infeas & (obs_be)).sum())       # infeasible, exceeded
    print(f"  Confusion (predicted infeasible → observed budget_exceeded) across 350:")
    print(f"    Feasible(≤8) ∩ not-exceeded   = {tn}")
    print(f"    Feasible(≤8) ∩ exceeded (FP)  = {fp}")
    print(f"    Infeasible(>8) ∩ not-exceeded = {fn}")
    print(f"    Infeasible(>8) ∩ exceeded (TP)= {tp}")
    print(f"    precision(TP/(TP+FP)) = {tp/(tp+fp):.4f}  recall(TP/(TP+FN)) = {tp/(tp+fn):.4f}")

    # save
    joined.to_csv(CENSUS / "hstruct3_validation_350_pairs.csv", index=False)
    summary = {
        "n": n, "P_exec_eligible": P_EXEC,
        "ate_stratum": ate_stratum, "ci_stratum": list(ci_s),
        "ate_population_Aprime": ates_pop, "ci_population_Aprime": list(ci_p),
        "be_static_350": be_static, "be_flat_350": be_flat,
        "be_static_per_1000": be_stat_per1k, "be_Aprime_per_1000": be_aprime_per1k,
        "be_abs_reduction_per_1000": be_stat_per1k - be_aprime_per1k,
        "chain_minus_flat_llm_mean": float(d_llm.mean()), "chain_minus_flat_llm_ci": list(map(float, np.percentile(
            d_llm.values[boot_rng.integers(0, len(d_llm), size=(B, len(d_llm)))].mean(axis=1), [2.5, 97.5]))),
        "chain_minus_flat_retr_mean": float(d_retr.mean()), "chain_minus_flat_retr_ci": list(map(float, np.percentile(
            d_retr.values[boot_rng.integers(0, len(d_retr), size=(B, len(d_retr)))].mean(axis=1), [2.5, 97.5]))),
        "feasibility_confusion": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
    }
    with open(CENSUS / "hstruct3_population_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nwrote {CENSUS/'hstruct3_validation_350_pairs.csv'} + hstruct3_population_summary.json")


if __name__ == "__main__":
    main()