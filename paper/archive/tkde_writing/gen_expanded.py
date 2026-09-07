"""Batch figure/table generator for the TKDE paper (maximal, all from frozen).

Every number is read from frozen SEALED_TEST items (no hand-typing). Produces
many figures and large CSV tables that the paper can cite. Run:

    PYTHONPATH=src:. python /data/mzb/SlotRAG/paper/tkde_writing/gen_expanded.py
"""
import json, glob, os, csv, collections, statistics as st
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

def load():
    d = {ds: {m: [] for m in ARMS} for ds in DS}
    for ds in DS:
        for m in ARMS:
            for f in glob.glob(f"{OUT}/items/g7-sealed/{ds}/{m}/*.json"):
                j = json.load(open(f))
                r = j.get("result") or {}
                sc = j.get("scores") or {}
                mets = r.get("metrics") or {}
                d[ds][m].append({
                    "status": r.get("status"),
                    "em": sc.get("em"), "f1": sc.get("f1"),
                    "acc": sc.get("accuracy"),
                    "ev_recall": sc.get("evidence_recall"),
                    "ev_mrr": sc.get("evidence_mrr"),
                    "retr": mets.get("retrieval_calls"),
                    "llm": mets.get("llm_calls"),
                    "docs": mets.get("documents_accessed"),
                    "lat": mets.get("latency_ms"),
                    "retr_util": mets.get("retrieval_budget_utilization"),
                    "llm_util": mets.get("llm_budget_utilization"),
                    "plan_complexity": mets.get("plan_complexity"),
                    "plan_slots": mets.get("plan_slot_count"),
                    "phys_actions": mets.get("physical_action_executions"),
                    "dual_batches": mets.get("dual_access_batches"),
                    "embedding_calls": mets.get("embedding_calls"),
                    "reranker_calls": mets.get("reranker_calls"),
                    "prompt_tok": mets.get("prompt_tokens"),
                    "comp_tok": mets.get("completion_tokens"),
                })
    return d

data = load()

def ok(recs): return [r for r in recs if r["status"] == "ok" and r["em"] is not None]
def col_ok(recs, key):
    return [r[key] for r in ok(recs) if r.get(key) is not None]
def mean(xs): return sum(xs)/len(xs) if xs else 0.0

# =================== FIGURES ===================
def save(fig, name):
    fig.tight_layout(); fig.savefig(f"{FIG}/{name}.pdf", bbox_inches="tight")
    print(f"  -> {name}.pdf")

# FigA: retrieval-calls distribution (box) per arm x dataset
fig, axes = plt.subplots(1, 3, figsize=(10, 3.0), sharey=True)
for ax, ds in zip(axes, DS):
    bp = [col_ok(data[ds][m], "retr") for m in ARMS]
    ax.boxplot(bp, labels=[LAB[m] for m in ARMS], showmeans=True, meanprops={"marker":"D","color":"r"})
    ax.set_title(SHORT[ds], fontsize=9)
    ax.set_ylabel("retrieval calls", fontsize=8)
    ax.grid(axis="y", alpha=0.3)
fig.suptitle("Retrieval-call distribution by arm (answered questions)", fontsize=10)
save(fig, "fig_a_retr_dist")

# FigB: LLM-calls distribution (box)
fig, axes = plt.subplots(1, 3, figsize=(10, 3.0), sharey=True)
for ax, ds in zip(axes, DS):
    bp = [col_ok(data[ds][m], "llm") for m in ARMS]
    ax.boxplot(bp, labels=[LAB[m] for m in ARMS], showmeans=True, meanprops={"marker":"D","color":"r"})
    ax.set_title(SHORT[ds], fontsize=9); ax.set_ylabel("LLM calls", fontsize=8); ax.grid(axis="y", alpha=0.3)
fig.suptitle("LLM-call distribution by arm (answered questions)", fontsize=10)
save(fig, "fig_b_llm_dist")

# FigC: latency distribution (box, seconds)
fig, axes = plt.subplots(1, 3, figsize=(10, 3.0), sharey=True)
for ax, ds in zip(axes, DS):
    bp = [ [v/1000 for v in col_ok(data[ds][m], "lat")] for m in ARMS]
    ax.boxplot(bp, labels=[LAB[m] for m in ARMS], showmeans=True, meanprops={"marker":"D","color":"r"})
    ax.set_title(SHORT[ds], fontsize=9); ax.set_ylabel("latency (s)", fontsize=8); ax.grid(axis="y", alpha=0.3)
fig.suptitle("End-to-end latency distribution by arm (answered questions)", fontsize=10)
save(fig, "fig_c_latency_dist")

# FigD: EM distribution (box) per arm x dataset
fig, axes = plt.subplots(1, 3, figsize=(10, 3.0), sharey=True)
for ax, ds in zip(axes, DS):
    bp = [col_ok(data[ds][m], "em") for m in ARMS]
    ax.boxplot(bp, labels=[LAB[m] for m in ARMS], showmeans=True, meanprops={"marker":"D","color":"r"})
    ax.set_title(SHORT[ds], fontsize=9); ax.set_ylabel("EM", fontsize=8); ax.grid(axis="y", alpha=0.3)
fig.suptitle("Exact-match distribution by arm (answered questions)", fontsize=10)
save(fig, "fig_d_em_dist")

# FigE: evidence recall by arm x dataset (bar)
fig, ax = plt.subplots(figsize=(5.6, 3.0))
x = np.arange(len(DS)); w = 0.26
for i, m in enumerate(ARMS):
    vals = [mean(col_ok(data[ds][m], "ev_recall") or [0])*100 for ds in DS]
    ax.bar(x+(i-1)*w, vals, w, label=LAB[m], color=COL[m])
ax.set_xticks(x); ax.set_xticklabels([SHORT[d] for d in DS], fontsize=9)
ax.set_ylabel("evidence recall", fontsize=9); ax.set_ylim(0,100)
ax.set_title("Evidence recall by arm (answered)", fontsize=9); ax.grid(axis="y", alpha=0.3)
ax.legend(fontsize=8, ncol=3)
save(fig, "fig_e_evrecall")

# FigF: budget utilization (retrieval + llm) grouped
fig, ax = plt.subplots(figsize=(6.2, 3.0))
x = np.arange(len(DS)*len(ARMS)); labels=[]
retr_u, llm_u = [], []
for ds in DS:
    for m in ARMS:
        recs = data[ds][m]
        ru = mean([r["retr_util"] for r in ok(recs) if r.get("retr_util") is not None])*100
        lu = mean([r["llm_util"] for r in ok(recs) if r.get("llm_util") is not None])*100
        retr_u.append(ru); llm_u.append(lu); labels.append(f"{SHORT[ds][:3]}-{LAB[m][:1]}")
ax.bar(x, retr_u, 0.4, label="retrieval budget util %", color="#27a")
ax.bar(x, llm_u, 0.4, bottom=retr_u, label="LLM budget util %", color="#e8a")
ax.set_xticks(x); ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
ax.set_ylabel("budget utilization %", fontsize=9); ax.set_title("Matched-budget utilization by arm", fontsize=9)
ax.legend(fontsize=8)
save(fig, "fig_f_budget_util")

# FigG: cost composition (embedding + reranker + llm calls) stacked
fig, ax = plt.subplots(figsize=(6.2, 3.0))
x = np.arange(len(DS)*len(ARMS)); labels=[]
emb, rer, llm = [], [], []
for ds in DS:
    for m in ARMS:
        recs = ok(data[ds][m])
        emb.append(mean([r["embedding_calls"] for r in recs if r.get("embedding_calls") is not None]))
        rer.append(mean([r["reranker_calls"] for r in recs if r.get("reranker_calls") is not None]))
        llm.append(mean([r["llm"] for r in recs if r.get("llm") is not None]))
        labels.append(f"{SHORT[ds][:3]}-{LAB[m][:1]}")
ax.bar(x, emb, 0.5, label="embedding calls", color="#9c6")
ax.bar(x, rer, 0.5, bottom=emb, label="reranker calls", color="#c66")
ax.bar(x, llm, 0.5, bottom=[emb[i]+rer[i] for i in range(len(x))], label="LLM calls", color="#27a")
ax.set_xticks(x); ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
ax.set_ylabel("mean calls / question", fontsize=9); ax.set_title("Invocation composition by arm", fontsize=9)
ax.legend(fontsize=8)
save(fig, "fig_g_cost_comp")

print("ALL FIGURES DONE")
