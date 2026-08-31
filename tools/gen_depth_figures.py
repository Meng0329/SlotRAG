"""Generate publication-ready figures for the Depth-Stratified Mechanism Audit.

All figures from frozen per_question.csv — no LLM, no retrieval.
"""
import csv, os, collections
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RESEARCH = "/data/mzb/SlotRAG/research/depth_analysis"
FIG = f"{RESEARCH}/figures"
os.makedirs(FIG, exist_ok=True)

DS = ["hotpotqa", "2wikimultihop", "musique"]
DS_LABEL = {"hotpotqa": "HotpotQA", "2wikimultihop": "2Wiki", "musique": "MuSiQue"}
ARM_COLORS = {"static": "#444", "flat": "#2a7", "chain": "#27a"}

def load_per_q():
    rows = []
    with open(f"{RESEARCH}/per_question.csv") as f:
        for r in csv.DictReader(f):
            for k in ["em","f1","retrieval_calls","llm_calls","documents_accessed","latency_ms",
                       "n_slots","n_joins","trace_depth","dag_depth","branching_factor","budget_exceeded"]:
                v = r.get(k)
                r[k] = float(v) if v and v != "" else None
            rows.append(r)
    return rows

rows = load_per_q()

def save(fig, name):
    fig.tight_layout()
    fig.savefig(f"{FIG}/{name}.pdf", bbox_inches="tight")
    fig.savefig(f"{FIG}/{name}.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {name}.pdf + .png")

# ──────────────────────────────────────────────────────
# Figure D1: Dependency depth distribution (per dataset)
# ──────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(12, 3.5))
for ax, ds in zip(axes, DS):
    depths = [r["dag_depth"] for r in rows if r["dataset"] == ds and r["dag_depth"] is not None and r["dag_depth"] >= 1]
    max_d = int(max(depths))
    bins = list(range(1, max_d + 2))
    ax.hist(depths, bins=bins, edgecolor="white", color="#555", alpha=0.85)
    ax.set_xlabel("Dependency Depth (DAG longest path)", fontsize=9)
    ax.set_ylabel("Count", fontsize=9)
    ax.set_title(DS_LABEL[ds], fontsize=10, fontweight="bold")
    ax.set_xticks(range(1, max_d + 1))
    ax.grid(axis="y", alpha=0.3)
fig.suptitle("Figure D1: Dependency Depth Distribution", fontsize=11, y=1.02)
save(fig, "fig_d1_depth_distribution")

# ──────────────────────────────────────────────────────
# Figure D2: chain-static ΔEM vs depth (with 95% CI)
# ──────────────────────────────────────────────────────
# Compute paired deltas per dataset × depth
by_q = collections.defaultdict(dict)
for r in rows:
    by_q[(r["dataset"], r["question_id"])][r["arm"]] = r

fig, axes = plt.subplots(1, 3, figsize=(13, 4), sharey=False)
for ax, ds in zip(axes, DS):
    depth_vals = sorted(set(int(r["dag_depth"]) for r in rows if r["dataset"] == ds and r["dag_depth"] is not None and r["dag_depth"] >= 1))
    x, y, ci_lo, ci_hi, ns = [], [], [], [], []
    for d in depth_vals:
        chain_em, static_em = [], []
        for (dds, qid), arms in by_q.items():
            if dds != ds:
                continue
            c = arms.get("chain")
            s = arms.get("static")
            if not c or not s:
                continue
            if int(c.get("dag_depth", 0) or 0) != d:
                continue
            ce, se = c.get("em"), s.get("em")
            if ce is not None and se is not None:
                chain_em.append(ce)
                static_em.append(se)
        if len(chain_em) < 3:
            continue
        diff = np.array(chain_em) - np.array(static_em)
        n = len(diff)
        rng = np.random.RandomState(2027)
        boot = np.array([rng.choice(diff, size=n, replace=True).mean() for _ in range(5000)])
        x.append(d)
        y.append(np.mean(diff))
        ci_lo.append(np.percentile(boot, 2.5))
        ci_hi.append(np.percentile(boot, 97.5))
        ns.append(n)

    x, y, ci_lo, ci_hi = np.array(x), np.array(y), np.array(ci_lo), np.array(ci_hi)
    ax.errorbar(x, y, yerr=[y - ci_lo, ci_hi - y], fmt="o-", color="#27a", capsize=4, markersize=6)
    ax.axhline(0, color="#999", linestyle="--", linewidth=0.8)
    ax.set_xlabel("Dependency Depth", fontsize=9)
    ax.set_ylabel("chain − static ΔEM", fontsize=9)
    ax.set_title(DS_LABEL[ds], fontsize=10, fontweight="bold")
    ax.set_xticks(x)
    for i, n in enumerate(ns):
        ax.annotate(f"n={n}", (x[i], y[i]), textcoords="offset points", xytext=(0, 10), fontsize=7, ha="center", color="#666")
    ax.grid(alpha=0.3)
fig.suptitle("Figure D2: chain − static ΔEM by Dependency Depth (95% bootstrap CI)", fontsize=11, y=1.03)
save(fig, "fig_d2_delta_em_vs_depth")

# ──────────────────────────────────────────────────────
# Figure D3: chain-static ΔLLM calls vs depth
# ──────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(13, 4), sharey=False)
for ax, ds in zip(axes, DS):
    depth_vals = sorted(set(int(r["dag_depth"]) for r in rows if r["dataset"] == ds and r["dag_depth"] is not None and r["dag_depth"] >= 1))
    x, y, ns = [], [], []
    for d in depth_vals:
        chain_llm, static_llm = [], []
        for (dds, qid), arms in by_q.items():
            if dds != ds:
                continue
            c = arms.get("chain")
            s = arms.get("static")
            if not c or not s:
                continue
            if int(c.get("dag_depth", 0) or 0) != d:
                continue
            cl, sl = c.get("llm_calls"), s.get("llm_calls")
            if cl is not None and sl is not None:
                chain_llm.append(cl)
                static_llm.append(sl)
        if len(chain_llm) < 3:
            continue
        x.append(d)
        y.append(np.mean(np.array(chain_llm) - np.array(static_llm)))
        ns.append(len(chain_llm))

    ax.bar(x, y, color="#27a" if y[0] >= 0 else "#c66", alpha=0.8)
    ax.axhline(0, color="#999", linestyle="--", linewidth=0.8)
    ax.set_xlabel("Dependency Depth", fontsize=9)
    ax.set_ylabel("chain − static ΔLLM calls", fontsize=9)
    ax.set_title(DS_LABEL[ds], fontsize=10, fontweight="bold")
    ax.set_xticks(x)
    for i, n in enumerate(ns):
        ax.annotate(f"n={n}", (x[i], y[i]), textcoords="offset points", xytext=(0, 8), fontsize=7, ha="center", color="#666")
    ax.grid(axis="y", alpha=0.3)
fig.suptitle("Figure D3: chain − static ΔLLM Calls by Dependency Depth", fontsize=11, y=1.03)
save(fig, "fig_d3_delta_llm_vs_depth")

# ──────────────────────────────────────────────────────
# Figure D4: n_slots × dag_depth heatmap
# ──────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(13, 4))
for ax, ds in zip(axes, DS):
    ds_rows = [r for r in rows if r["dataset"] == ds and r["n_slots"] is not None and r["dag_depth"] is not None]
    max_ns = int(max(r["n_slots"] for r in ds_rows))
    max_dd = int(max(r["dag_depth"] for r in ds_rows if r["dag_depth"] >= 1)) if any(r["dag_depth"] >= 1 for r in ds_rows) else 1
    mat = np.zeros((max_ns + 1, max_dd + 1))
    for r in ds_rows:
        ns, dd = int(r["n_slots"]), int(r["dag_depth"])
        mat[ns][dd] += 1
    # Mask zeros for cleaner display
    mat_masked = np.ma.masked_where(mat == 0, mat)
    im = ax.imshow(mat_masked.T, aspect="auto", cmap="YlOrRd", origin="lower")
    ax.set_xlabel("n_slots", fontsize=9)
    ax.set_ylabel("Dependency Depth", fontsize=9)
    ax.set_title(DS_LABEL[ds], fontsize=10, fontweight="bold")
    ax.set_xticks(range(max_ns + 1))
    ax.set_yticks(range(max_dd + 1))
    # Annotate cells
    for i in range(max_ns + 1):
        for j in range(max_dd + 1):
            v = int(mat[i][j])
            if v > 0:
                ax.text(i, j, str(v), ha="center", va="center", fontsize=6, color="white" if v > mat.max() * 0.5 else "black")
    plt.colorbar(im, ax=ax, shrink=0.8)
fig.suptitle("Figure D4: n_slots × Dependency Depth (count)", fontsize=11, y=1.03)
save(fig, "fig_d4_slots_vs_depth_heatmap")

# ──────────────────────────────────────────────────────
# Figure D5: Budget-exceeded rate vs depth
# ──────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(13, 4))
for ax, ds in zip(axes, DS):
    for arm, color in ARM_COLORS.items():
        arm_rows = [r for r in rows if r["dataset"] == ds and r["arm"] == arm and r["dag_depth"] is not None and r["dag_depth"] >= 1]
        depth_vals = sorted(set(int(r["dag_depth"]) for r in arm_rows))
        x, y, ns = [], [], []
        for d in depth_vals:
            subset = [r for r in arm_rows if int(r["dag_depth"]) == d]
            n = len(subset)
            be = sum(r["budget_exceeded"] for r in subset if r["budget_exceeded"] is not None)
            x.append(d)
            y.append(be / n * 100 if n else 0)
            ns.append(n)
        ax.plot(x, y, "o-", color=color, label=arm, markersize=5)
        for i, n in enumerate(ns):
            if n < 50:
                ax.annotate(f"n={n}", (x[i], y[i]), textcoords="offset points", xytext=(0, 8), fontsize=6, ha="center", color=color)
    ax.set_xlabel("Dependency Depth", fontsize=9)
    ax.set_ylabel("Budget-Exceeded Rate (%)", fontsize=9)
    ax.set_title(DS_LABEL[ds], fontsize=10, fontweight="bold")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    ax.set_ylim(-5, 110)
fig.suptitle("Figure D5: Budget-Exceeded Rate by Dependency Depth × Arm", fontsize=11, y=1.03)
save(fig, "fig_d5_budget_exceeded_by_depth")

print("ALL FIGURES DONE")
