#!/usr/bin/env python3
"""H-STRUCT-3 offline replay — CPU-only, no new LLM/retrieval/answer execution.

Rebuilds the four-policy comparison and A' (= Policy A', gate_flat) outcome from
the existing three-arm exploratory traces (research/depth_analysis/structural_per_question.csv:
25,948 rows / 8,660 questions / static+flat+chain arms, per-question em/f1/llm_calls/
retrieval_calls/budget_exceeded + structural_hops).

No new execution: every number below is a combination of already-observed outcomes.

Policies:
  P_static     : always static arm
  P_flat       : always flat arm
  P_chain      : always chain arm
  P_gate_flat  : A' = flat if (structural_hops>=2 AND executable) else static
"""
import pandas as pd
import numpy as np
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
TRACE = REPO / "research" / "depth_analysis" / "structural_per_question.csv"
OUT_CSV = REPO / "research" / "hstruct_validation_census" / "policy_replay_per_question.csv"
OUT_SUMMARY = REPO / "research" / "hstruct_validation_census" / "hstruct3_four_policy_summary.csv"

BE = "budget_exceeded"
METRICS = ["em", "f1", "llm_calls", "retrieval_calls", BE]
ARMS = ["static", "flat", "chain"]


def main():
    df = pd.read_csv(TRACE)
    key = ["dataset", "question_id"]

    # per-question attributes (structural_hops, topology) taken from any arm row
    attrs = df.groupby(key, as_index=False).agg(
        structural_hops=("structural_hops", "first"),
        topology=("topology_full", "first"),
    )

    wide = None
    for m in METRICS:
        t = df.pivot_table(index=key, columns="arm", values=m, aggfunc="first")
        t.columns = [f"{m}_{a}" for a in t.columns]
        wide = t if wide is None else wide.join(t)
    wide = wide.reset_index()
    wide.columns.name = None

    status = df.pivot_table(index=key, columns="arm", values="status", aggfunc="first")
    status.columns = [f"status_{a}" for a in status.columns]
    status = status.reset_index()
    status.columns.name = None

    out = wide.merge(attrs, on=key).merge(status, on=key)
    out["executable"] = 1  # all three arms present => plans compiled & ran

    # strict pairing: every metric/arm cell present
    req = [f"{m}_{a}" for m in METRICS for a in ARMS]
    n_before = len(out)
    out = out.dropna(subset=req)
    print(f"strict three-arm paired questions: {len(out)} (from {n_before} candidate)")

    # --- Policy A' ---
    gate_on = (out["structural_hops"] >= 2) & (out["executable"] == 1)
    for m in METRICS:
        out[f"A_prime_{m}"] = np.where(gate_on, out[f"{m}_flat"], out[f"{m}_static"])
    out["A_prime_status"] = np.where(gate_on, out["status_flat"], out["status_static"])
    out["selected_policy_Aprime"] = np.where(gate_on, "flat", "static")

    rename = {
        "em_static": "static_em", "em_flat": "flat_em", "em_chain": "chain_em", "A_prime_em": "A_prime_em",
        "f1_static": "static_f1", "f1_flat": "flat_f1", "f1_chain": "chain_f1", "A_prime_f1": "A_prime_f1",
        "llm_calls_static": "static_llm_calls", "llm_calls_flat": "flat_llm_calls", "llm_calls_chain": "chain_llm_calls", "A_prime_llm_calls": "A_prime_llm_calls",
        "retrieval_calls_static": "static_retrieval_calls", "retrieval_calls_flat": "flat_retrieval_calls", "retrieval_calls_chain": "chain_retrieval_calls", "A_prime_retrieval_calls": "A_prime_retrieval_calls",
        "budget_exceeded_static": "budget_exceeded_static", "budget_exceeded_flat": "budget_exceeded_flat", "budget_exceeded_chain": "budget_exceeded_chain", "A_prime_budget_exceeded": "budget_exceeded_Aprime",
    }
    final_cols = [
        "dataset", "question_id", "structural_hops", "topology", "executable", "selected_policy_Aprime",
        "static_em", "flat_em", "chain_em", "A_prime_em",
        "static_f1", "flat_f1", "chain_f1", "A_prime_f1",
        "static_llm_calls", "flat_llm_calls", "chain_llm_calls", "A_prime_llm_calls",
        "static_retrieval_calls", "flat_retrieval_calls", "chain_retrieval_calls", "A_prime_retrieval_calls",
        "budget_exceeded_static", "budget_exceeded_flat", "budget_exceeded_chain", "budget_exceeded_Aprime",
    ]
    out = out.rename(columns=rename)
    out.to_csv(OUT_CSV, columns=final_cols, index=False)
    print(f"wrote {OUT_CSV}: {len(out)} strict three-arm paired questions")

    # ---- four-policy summary per dataset + macro/micro ----
    polmap = {"P_static": "static", "P_flat": "flat", "P_chain": "chain", "P_gate_flat": "A_prime"}

    def _mn2col(mn, m):
        # em/f1/llm_calls/retrieval_calls renamed to {arm}_{metric}; budget_exceeded kept as budget_exceeded_{arm}
        if m == "budget_exceeded":
            return "budget_exceeded_Aprime" if mn == "A_prime" else f"budget_exceeded_{mn}"
        if mn == "A_prime":
            return f"A_prime_{m}"
        return f"{mn}_{m}"

    def _row(pol, ds, scope, n, sub):
        mn = polmap[pol]
        sc = f"status_{mn}" if mn != "A_prime" else "A_prime_status"
        return {
            "policy": pol, "dataset": ds, "scope": scope, "n": n,
            "em": sub[_mn2col(mn, "em")].mean(),
            "f1": sub[_mn2col(mn, "f1")].mean(),
            "llm_calls": sub[_mn2col(mn, "llm_calls")].mean(),
            "retrieval_calls": sub[_mn2col(mn, "retrieval_calls")].mean(),
            "budget_exceeded": int(sub[_mn2col(mn, "budget_exceeded")].sum()),
            "budget_exceeded_rate": sub[_mn2col(mn, "budget_exceeded")].mean(),
            "successful_completion_rate": (sub[sc] == "ok").mean(),
        }

    rows = []
    for pol in polmap:
        for ds in sorted(out["dataset"].unique()):
            rows.append(_row(pol, ds, "dataset", len(out[out["dataset"] == ds]), out[out["dataset"] == ds]))
    for pol in polmap:
        rows.append(_row(pol, "pooled_micro", "micro", len(out), out))
    for pol in polmap:
        mn = polmap[pol]
        sc = f"status_{mn}" if mn != "A_prime" else "A_prime_status"
        be_col = _mn2col(mn, "budget_exceeded")
        be_mean = out.groupby("dataset").apply(lambda g: (g[be_col]).mean(), include_groups=False).mean()
        ok_mean = out.groupby("dataset").apply(lambda g: (g[sc] == "ok").mean(), include_groups=False).mean()
        rows.append({
            "policy": pol, "dataset": "macro", "scope": "macro", "n": len(out),
            "em": out.groupby("dataset")[_mn2col(mn, "em")].mean().mean(),
            "f1": out.groupby("dataset")[_mn2col(mn, "f1")].mean().mean(),
            "llm_calls": out.groupby("dataset")[_mn2col(mn, "llm_calls")].mean().mean(),
            "retrieval_calls": out.groupby("dataset")[_mn2col(mn, "retrieval_calls")].mean().mean(),
            "budget_exceeded": int(out[be_col].sum()),
            "budget_exceeded_rate": be_mean,
            "successful_completion_rate": ok_mean,
        })
    s = pd.DataFrame(rows)
    s.to_csv(OUT_SUMMARY, index=False)
    print(f"wrote {OUT_SUMMARY}")
    print("\n=== MACRO four-policy ===")
    print(s[s["scope"] == "macro"][["policy", "em", "f1", "llm_calls", "retrieval_calls", "budget_exceeded_rate", "successful_completion_rate"]].to_string(index=False))
    print("\n=== MICRO four-policy ===")
    print(s[s["scope"] == "micro"][["policy", "em", "f1", "llm_calls", "retrieval_calls", "budget_exceeded_rate", "successful_completion_rate"]].to_string(index=False))
    print("\n=== per-dataset EM ===")
    print(s[s["scope"] == "dataset"][["policy", "dataset", "n", "em", "llm_calls", "budget_exceeded_rate"]].pivot(index="dataset", columns="policy", values="em").to_string())
    print("\n=== hops distribution (pooled) ===")
    print(out["structural_hops"].value_counts().sort_index().to_string())
    print("\n=== shallow (hops<2) vs deep n by dataset ===")
    out["stratum"] = np.where(out["structural_hops"] < 2, "shallow", "deep")
    print(out.groupby(["dataset", "stratum"]).size().unstack().to_string())


if __name__ == "__main__":
    main()