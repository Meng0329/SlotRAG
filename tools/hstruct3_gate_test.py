#!/usr/bin/env python3
"""H-STRUCT-3 §5 & §6 — Gate Necessity Test + dataset heterogeneity (offline replay).

CPU-only. Uses research/hstruct_validation_census/policy_replay_per_question.csv
built from the 25,948-row exploratory three-arm trace (8,632 strict three-arm
paired questions). No new LLM/retrieval/answer execution.
"""
import pandas as pd
import numpy as np
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from slotrag.benchmarking.statistics import paired_bootstrap_vector

REPO = pathlib.Path(__file__).resolve().parents[1]
IN = REPO / "research" / "hstruct_validation_census" / "policy_replay_per_question.csv"
OUT = REPO / "research" / "hstruct_validation_census" / "hstruct3_gate_test.csv"
HET = REPO / "research" / "hstruct_validation_census" / "hstruct3_heterogeneity.csv"


def _ci(a, b, label):
    a = np.asarray(a, float); b = np.asarray(b, float)
    res = paired_bootstrap_vector(a, b, iterations=10000, seed=2027, level=0.95)
    diff = b.mean() - a.mean()  # b - a
    print(f"  {label}: ΔEM={diff:+.4f}  CI[{res['ci_low']:+.4f},{res['ci_high']:+.4f}]  p_boot={res['p_value']:.4f}  n={res['n']}")
    return diff, res


def summarize_pair(a_arr, b_arr, be_a, be_b):
    a = np.asarray(a_arr, float); b = np.asarray(b_arr, float)
    d = b - a
    wins = int(((a == 0) & (b == 1)).sum())  # b wins (flat better)
    losses = int(((a == 1) & (b == 0)).sum())  # a wins (static better)
    ties = int((a == b).sum())
    return wins, losses, ties, float(d.mean()), float(be_b.mean()), float(be_a.mean())


def main():
    df = pd.read_csv(IN)
    print(f"loaded {len(df)} paired questions")
    df["shallow"] = df["structural_hops"] < 2

    # ===================== §5 Gate Necessity Test =====================
    print("\n=== §5 Gate Necessity Test — shallow (structural_hops<2), flat vs static ===")
    rows = []
    # pooled shallow
    s = df[df["shallow"]]
    for m_out, m_in_a, m_in_b in [("EM", "static_em", "flat_em"),
                                   ("F1", "static_f1", "flat_f1"),
                                   ("LLM", "static_llm_calls", "flat_llm_calls"),
                                   ("Retrieval", "static_retrieval_calls", "flat_retrieval_calls")]:
        d, res = _ci(s[m_in_a], s[m_in_b], m_out)
        rows.append({"stratum": "shallow_all", "metric": m_out, "delta": d,
                     "ci_low": res["ci_low"], "ci_high": res["ci_high"], "p_boot": res["p_value"], "n": res["n"]})
    w, l, t, d, be_b, be_a = summarize_pair(s["static_em"], s["flat_em"], s["budget_exceeded_static"], s["budget_exceeded_flat"])
    print(f"  win/tie/loss (flat wins/static wins): {w}/{t}/{l}  |  BE: static {int(s['budget_exceeded_static'].sum())}/{len(s)} flat {int(s['budget_exceeded_flat'].sum())}/{len(s)}")
    rows.append({"stratum": "shallow_all", "metric": "WLT", "delta": d,
                 "ci_low": np.nan, "ci_high": np.nan, "p_boot": np.nan,
                 "win": w, "tie": t, "loss": l,
                 "be_static": int(s["budget_exceeded_static"].sum()), "be_flat": int(s["budget_exceeded_flat"].sum())})

    # per dataset shallow
    for ds, sub in s.groupby("dataset"):
        for m_out, m_in_a, m_in_b in [("EM", "static_em", "flat_em"),
                                       ("LLM", "static_llm_calls", "flat_llm_calls")]:
            d, res = _ci(sub[m_in_a], sub[m_in_b], f"{ds}-{m_out}")
            rows.append({"stratum": f"shallow_{ds}", "metric": m_out, "delta": d,
                         "ci_low": res["ci_low"], "ci_high": res["ci_high"], "p_boot": res["p_value"], "n": res["n"]})

    # deep stratum comparison (for context)
    deep = df[~df["shallow"]]
    print("\n=== deep (hops>=2) flat vs static, pooled ===")
    _ci(deep["static_em"], deep["flat_em"], "EM-deep")

    pd.DataFrame(rows).to_csv(OUT, index=False)
    print(f"\nwrote {OUT}")

    # ===================== §6 Dataset heterogeneity =====================
    print("\n=== §6 heterogeneity: dataset × structural_hops, flat-static (pooled within stratum) ===")
    het_rows = []
    df["hops_bucket"] = pd.cut(df["structural_hops"], [-0.5, 0.5, 1.5, 99], labels=["hops0", "hops1", "hops>=2"])
    for ds, g in df.groupby("dataset"):
        for hb, sub in g.groupby("hops_bucket", observed=True):
            n = len(sub)
            delta_em = sub["flat_em"].mean() - sub["static_em"].mean()
            delta_llm = sub["flat_llm_calls"].mean() - sub["static_llm_calls"].mean()
            delta_tr = sub["flat_retrieval_calls"].mean() - sub["static_retrieval_calls"].mean()
            het_rows.append({
                "dataset": ds, "hops_bucket": str(hb), "n": n,
                "static_em": sub["static_em"].mean(), "flat_em": sub["flat_em"].mean(),
                "delta_em": delta_em, "delta_llm": delta_llm, "delta_retrieval": delta_tr,
                "static_be": int(sub["budget_exceeded_static"].sum()),
                "flat_be": int(sub["budget_exceeded_flat"].sum()),
                "static_be_rate": sub["budget_exceeded_static"].mean(),
                "flat_be_rate": sub["budget_exceeded_flat"].mean(),
            })
    h = pd.DataFrame(het_rows)
    h.to_csv(HET, index=False)
    print(h.to_string(index=False))
    print(f"\nwrote {HET}")

    # ===== CASE verdict =====
    shallow = df[df["shallow"]]
    sem = shallow["static_em"].values; fem = shallow["flat_em"].values
    delta_em = fem.mean() - sem.mean()
    # quality significance via bootstrap CI excluding 0
    d, res = _ci(sem, fem, "shallow EM CI")
    sig = res["ci_low"] > 0 or res["ci_high"] < 0
    # cost: flat vs static on shallow LLM
    _, resllm = _ci(shallow["static_llm_calls"], shallow["flat_llm_calls"], "shallow LLM")
    flat_cheaper = (resllm["ci_high"] < 0)  # LLM_flat - LLM_static < 0 => flat cheaper
    print(f"\n=== CASE verdict inputs ===")
    print(f"shallow ΔEM={delta_em:+.4f} CI[{res['ci_low']:+.4f},{res['ci_high']:+.4f}] significant={sig}")
    print(f"shallow ΔLLM={resllm['mean_difference']:+.4f} CI[{resllm['ci_low']:+.4f},{resllm['ci_high']:+.4f}] flat_cheaper={flat_cheaper}")
    be_reduction = shallow["budget_exceeded_static"].sum() - shallow["budget_exceeded_flat"].sum()
    print(f"shallow BE: static {int(shallow['budget_exceeded_static'].sum())} flat {int(shallow['budget_exceeded_flat'].sum())} (reduction {be_reduction})")


if __name__ == "__main__":
    main()