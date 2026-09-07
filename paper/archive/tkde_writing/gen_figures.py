"""Generate the three additional data figures for the TKDE paper.

All numbers come from the frozen SEALED_TEST audit CSVs / items --- no hand
typing. Figures:
  fig1_em_overall.pdf   - RQ1: EM_all of static/flat/chain, grouped by dataset
  fig_llm_frontier.pdf  - RQ2: cost frontier (LLM calls vs EM_all) per arm
  fig_budget_stack.pdf  - RQ8: budget-exceeded count, arm x dataset (not chain-skewed)

Run: PYTHONPATH=src:. python paper/tkde_writing/gen_figures.py
"""
import csv, json, glob, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

PAPER = "/data/mzb/SlotRAG/paper/tkde_writing"
FIG = f"{PAPER}/figures"
OUT = "/home/test/tkde_runs/tkde-sealed-test-q35"
os.makedirs(FIG, exist_ok=True)

ARMS = ["slotrag-g7-static", "slotrag-g7-flat", "slotrag-g7-chain"]
DS = ["hotpotqa", "2wikimultihop", "musique"]
SHORT = {"hotpotqa": "HotpotQA", "2wikimultihop": "2Wiki", "musique": "MuSiQue"}
COL = {"slotrag-g7-static": "#444", "slotrag-g7-flat": "#2a7", "slotrag-g7-chain": "#27a"}
LAB = {"slotrag-g7-static": "static", "slotrag-g7-flat": "flat", "slotrag-g7-chain": "chain"}

# ---- load EM_all + cost from frozen items (authoritative, not the hand-copied CSV) ----
def load():
    d = {ds: {m: {"em": [], "llm": [], "budget": 0} for m in ARMS} for ds in DS}
    for ds in DS:
        for m in ARMS:
            for f in glob.glob(f"{OUT}/items/g7-sealed/{ds}/{m}/*.json"):
                j = json.load(open(f))
                r = j.get("result") or {}
                sc = j.get("scores") or {}
                mets = r.get("metrics") or {}
                em = sc.get("em")
                if em is not None:
                    d[ds][m]["em"].append(em)
                llm = mets.get("llm_calls")
                if llm is not None and r.get("status") == "ok":
                    d[ds][m]["llm"].append(llm)
                if r.get("status") == "budget_exceeded":
                    d[ds][m]["budget"] += 1
    return d

data = load()

# EM_all = mean over all items (non-ok implicitly em=0 only if scored; here em None
# for non-ok so we use the answered-mean to match tab:overall EM_ans, and report
# EM_all via the CSV which already scored non-ok as 0).
rows = {}
with open(f"{PAPER}/sealed_main_table.csv") as cf:
    for row in csv.DictReader(cf):
        rows[(row["dataset"], row["method"])] = row
# cost from CSV too (means over ok)
cost = {}
with open(f"{PAPER}/sealed_table5_quality_cost.csv") as cf:
    for row in csv.DictReader(cf):
        cost[(row["dataset"], row["method"])] = row

# ===== Fig1: EM_all grouped bar (RQ1) =====
fig, ax = plt.subplots(figsize=(5.2, 3.0))
x = np.arange(len(DS))
w = 0.26
for i, m in enumerate(ARMS):
    vals = [float(rows[(ds, m)]["EM_all"]) for ds in DS]
    ax.bar(x + (i - 1) * w, vals, w, label=LAB[m], color=COL[m], zorder=3)
ax.set_xticks(x)
ax.set_xticklabels([SHORT[d] for d in DS], fontsize=9)
ax.set_ylabel("EM (all-question denom)", fontsize=9)
ax.set_ylim(0, 65)
ax.set_title("RQ1: end-to-end EM, three arms (SEALED_TEST)", fontsize=9)
ax.grid(axis="y", alpha=0.3)
ax.legend(fontsize=8, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.12))
for i, m in enumerate(ARMS):
    for j, ds in enumerate(DS):
        v = float(rows[(ds, m)]["EM_all"])
        ax.annotate(f"{v:.1f}", (x[j] + (i - 1) * w, v + 0.6), fontsize=6.5, ha="center")
fig.tight_layout()
fig.savefig(f"{FIG}/fig1_em_overall.pdf", bbox_inches="tight")
print("  -> fig1_em_overall.pdf")

# ===== Fig2: cost frontier (LLM calls vs EM) =====
fig, ax = plt.subplots(figsize=(5.2, 3.4))
for m in ARMS:
    xs, ys = [], []
    for ds in DS:
        em = float(rows[(ds, m)]["EM_all"])
        llm = float(cost[(ds, m)]["llm_calls_mean"])
        xs.append(llm); ys.append(em)
        ax.scatter(llm, em, s=90, color=COL[m], label=LAB[m], zorder=3)
        ax.annotate(SHORT[ds], (llm, em), textcoords="offset points",
                    xytext=(4, 4), fontsize=7)
ax.set_xlabel("mean LLM calls / question", fontsize=9)
ax.set_ylabel("EM (all-question denom)", fontsize=9)
ax.set_title("RQ2: cost frontier (LLM calls vs EM)", fontsize=9)
ax.grid(alpha=0.3)
ax.legend(fontsize=8)
fig.tight_layout()
fig.savefig(f"{FIG}/fig2_llm_frontier.pdf", bbox_inches="tight")
print("  -> fig2_llm_frontier.pdf")

# ===== Fig3: budget-exceeded stacked by arm x dataset =====
fig, ax = plt.subplots(figsize=(5.2, 3.0))
arms_short = ["static", "flat", "chain"]
budget = {m: [data[ds][m]["budget"] for ds in DS] for m in ARMS}
x = np.arange(len(DS))
bottoms = np.zeros(len(DS))
for m in ARMS:
    vals = budget[m]
    ax.bar(x, vals, 0.55, bottom=bottoms, label=LAB[m], color=COL[m], zorder=3)
    bottoms += np.array(vals)
ax.set_xticks(x)
ax.set_xticklabels([SHORT[d] for d in DS], fontsize=9)
ax.set_ylabel("budget-exceeded questions", fontsize=9)
ax.set_title("RQ8: budget-exceeded by arm (not chain-skewed)", fontsize=9)
ax.grid(axis="y", alpha=0.3)
ax.legend(fontsize=8, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.12))
for j, ds in enumerate(DS):
    tot = sum(budget[m][j] for m in ARMS)
    ax.annotate(f"{tot}", (j, tot + 12), fontsize=7, ha="center")
fig.tight_layout()
fig.savefig(f"{FIG}/fig3_budget_stack.pdf", bbox_inches="tight")
print("  -> fig3_budget_stack.pdf")

print("DONE: 3 figures generated from frozen SEALED_TEST items.")
