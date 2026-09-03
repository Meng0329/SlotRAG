#!/usr/bin/env python3
"""H-STRUCT-3 §10 + final-reply numbers — A' vs always-flat paired deltas.

CPU-only. Reads policy_replay_per_question.csv (8,632 strict three-arm paired).
"""
import pandas as pd
import numpy as np
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from slotrag.benchmarking.statistics import paired_bootstrap_vector

REPO = pathlib.Path(__file__).resolve().parents[1]
IN = REPO / "research" / "hstruct_validation_census" / "policy_replay_per_question.csv"
OUT = REPO / "research" / "hstruct_validation_census" / "hstruct3_aprime_vs_flat.csv"


def main():
    df = pd.read_csv(IN)
    n = len(df)
    print(f"n = {n}")

    def delta_ci(a, b, label):
        a = np.asarray(a, float); b = np.asarray(b, float)
        r = paired_bootstrap_vector(a, b, iterations=10000, seed=2027, level=0.95)
        print(f"  {label}: Δ={r['mean_difference']:+.4f}  CI[{r['ci_low']:+.4f},{r['ci_high']:+.4f}]  p_boot={r['p_value']:.4f}")
        return r

    rows = []
    # §10 A' vs always-flat: quality / cost / retrieval
    print("=== §10 A' vs always-flat (pooled, 8,632) ===")
    q = delta_ci(df["flat_em"], df["A_prime_em"], "ΔEM (A' − flat)")
    rows.append({"comparison": "Aprime_minus_flat", "metric": "EM", **{k: q[k] for k in ("mean_difference", "ci_low", "ci_high", "p_value")}})
    l = delta_ci(df["flat_llm_calls"], df["A_prime_llm_calls"], "ΔLLM (A' − flat)")
    rows.append({"comparison": "Aprime_minus_flat", "metric": "LLM_calls", **{k: l[k] for k in ("mean_difference", "ci_low", "ci_high", "p_value")}})
    tr = delta_ci(df["flat_retrieval_calls"], df["A_prime_retrieval_calls"], "ΔRetrieval (A' − flat)")
    rows.append({"comparison": "Aprime_minus_flat", "metric": "Retrieval_calls", **{k: tr[k] for k in ("mean_difference", "ci_low", "ci_high", "p_value")}})
    f1 = delta_ci(df["flat_f1"], df["A_prime_f1"], "ΔF1 (A' − flat)")
    rows.append({"comparison": "Aprime_minus_flat", "metric": "F1", **{k: f1[k] for k in ("mean_difference", "ci_low", "ci_high", "p_value")}})

    # also A' vs static (context) and per-dataset A' vs flat EM
    print("\n=== per-dataset ΔEM (A' − flat) ===")
    for ds, g in df.groupby("dataset"):
        r = delta_ci(g["flat_em"], g["A_prime_em"], f"{ds}")
        rows.append({"comparison": "Aprime_minus_flat", "dataset": ds, "metric": "EM", **{k: r[k] for k in ("mean_difference", "ci_low", "ci_high", "p_value")}})

    # final-reply numbers: four-policy macro (from hstruct3_four_policy_summary)
    print("\n=== four-policy MACRO (mean-of-dataset-means) ===")
    s = pd.read_csv(REPO / "research" / "hstruct_validation_census" / "hstruct3_four_policy_summary.csv")
    macro = s[s["scope"] == "macro"][["policy", "em", "f1", "llm_calls", "retrieval_calls", "budget_exceeded_rate"]]
    print(macro.to_string(index=False))

    pd.DataFrame(rows).to_csv(OUT, index=False)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()