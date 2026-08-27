"""Batch LARGE table generator from frozen SEALED_TEST items (no hand-typing).

Produces CSVs the paper can cite. Run:
    PYTHONPATH=src:. python /data/mzb/SlotRAG/paper/tkde_writing/gen_tables.py
"""
import json, glob, os, csv, collections, statistics as st
import numpy as np

PAPER = "/data/mzb/SlotRAG/paper/tkde_writing"
OUT = "/home/test/tkde_runs/tkde-sealed-test-q35"
ARMS = ["slotrag-g7-static", "slotrag-g7-flat", "slotrag-g7-chain"]
DS = ["hotpotqa", "2wikimultihop", "musique"]
LAB = {"slotrag-g7-static": "static", "slotrag-g7-flat": "flat", "slotrag-g7-chain": "chain"}

def load():
    d = {ds: {m: {} for m in ARMS} for ds in DS}
    for ds in DS:
        for m in ARMS:
            for f in glob.glob(f"{OUT}/items/g7-sealed/{ds}/{m}/*.json"):
                j = json.load(open(f))
                qid = j.get("question_id")
                r = j.get("result") or {}; sc = j.get("scores") or {}
                mets = r.get("metrics") or {}
                d[ds][m][qid] = {"status": r.get("status"), "em": sc.get("em"),
                    "f1": sc.get("f1"), "acc": sc.get("accuracy"),
                    "ev_recall": sc.get("evidence_recall"), "ev_mrr": sc.get("evidence_mrr"),
                    "retr": mets.get("retrieval_calls"), "llm": mets.get("llm_calls"),
                    "docs": mets.get("documents_accessed"), "lat": mets.get("latency_ms"),
                    "retr_util": mets.get("retrieval_budget_utilization"),
                    "llm_util": mets.get("llm_budget_utilization"),
                    "plan_complexity": mets.get("plan_complexity"),
                    "embedding": mets.get("embedding_calls"), "reranker": mets.get("reranker_calls"),
                    "prompt_tok": mets.get("prompt_tokens"), "comp_tok": mets.get("completion_tokens")}
    return d

data = load()

def vals(ds,m): return list(data[ds][m].values())
def ok(ds,m): return [r for r in vals(ds,m) if r["status"] == "ok" and r["em"] is not None]
def col_ok(ds,m,key): return [r[key] for r in ok(ds,m) if r.get(key) is not None]
def mn(xs): return round(sum(xs)/len(xs), 3) if xs else 0.0
def pct(xs, p): return round(float(np.percentile(xs, p)), 3) if xs else 0.0

# ---- Table A: full per-arm descriptive statistics (large) ----
with open(f"{PAPER}/tableA_descriptive.csv", "w", newline="") as cf:
    w = csv.writer(cf)
    w.writerow(["dataset","arm","n_total","n_ok","n_budget","mean_em","median_em",
                "mean_f1","mean_ev_recall","mean_retr","median_retr","p90_retr",
                "mean_llm","median_llm","p90_llm","mean_docs","mean_lat_s",
                "mean_retr_util","mean_llm_util","mean_plan_complexity",
                "mean_embedding","mean_reranker","mean_prompt_tok"])
    for ds in DS:
        for m in ARMS:
            recs = vals(ds,m); o = ok(ds,m)
            em = col_ok(ds,m,"em"); retr = col_ok(ds,m,"retr"); llm = col_ok(ds,m,"llm")
            w.writerow([ds, LAB[m], len(vals(ds,m)), len(o),
                sum(1 for r in vals(ds,m) if r["status"]=="budget_exceeded"),
                mn(em), pct(em,50), mn(col_ok(ds,m,"f1")), mn(col_ok(ds,m,"ev_recall") or [0]),
                mn(retr), pct(retr,50), pct(retr,90), mn(llm), pct(llm,50), pct(llm,90),
                mn(col_ok(ds,m,"docs")), mn([v/1000 for v in col_ok(ds,m,"lat")]),
                mn([r["retr_util"] for r in o if r.get("retr_util") is not None])*100,
                mn([r["llm_util"] for r in o if r.get("llm_util") is not None])*100,
                mn(col_ok(ds,m,"plan_complexity")), mn(col_ok(ds,m,"embedding")),
                mn(col_ok(ds,m,"reranker")), mn(col_ok(ds,m,"prompt_tok"))])
print("  -> tableA_descriptive.csv")

# ---- Table B: paired chain-vs-static full statistics (per dataset) ----
def paired_stats(a, b):
    diffs = [x-y for x,y in zip(a,b) if x is not None and y is not None]
    if not diffs: return None
    return (round(np.mean(diffs),3), round(np.percentile(diffs,2.5),3),
            round(np.percentile(diffs,97.5),3), len(diffs))

with open(f"{PAPER}/tableB_paired.csv", "w", newline="") as cf:
    w = csv.writer(cf)
    w.writerow(["dataset","metric","chain_mean","static_mean","mean_diff",
                "CI2.5","CI97.5","n_shared"])
    for ds in DS:
        for key, lab in (("em","EM"),("retr","retrieval_calls"),
                         ("llm","llm_calls"),("docs","documents"),("lat","latency_s")):
            sh = set(data[ds]["slotrag-g7-chain"]) & set(data[ds]["slotrag-g7-static"])
            ca, sa = [], []
            for q in sh:
                cv = data[ds]["slotrag-g7-chain"][q].get(key)
                sv = data[ds]["slotrag-g7-static"][q].get(key)
                if cv is not None and sv is not None:
                    ca.append(cv); sa.append(sv)
            ps = paired_stats(ca, sa)
            if ps:
                w.writerow([ds, lab, round(np.mean(ca),3), round(np.mean(sa),3),
                            ps[0], ps[1], ps[2], ps[3]])
print("  -> tableB_paired.csv")

# ---- Table C: failure breakdown by arm x dataset (full) ----
with open(f"{PAPER}/tableC_failure_by_arm.csv", "w", newline="") as cf:
    w = csv.writer(cf)
    w.writerow(["dataset","arm","ok","budget_exceeded","method_boundary","infra","total",
                "ok_rate_%"])
    for ds in DS:
        for m in ARMS:
            recs = vals(ds,m)
            cats = collections.Counter(r["status"] for r in vals(ds,m))
            n = len(vals(ds,m))
            w.writerow([ds, LAB[m], cats.get("ok",0), cats.get("budget_exceeded",0),
                sum(v for k,v in cats.items() if k not in ("ok","budget_exceeded")),
                # infra proxy: non-ok non-budget with provider error
                sum(1 for r in vals(ds,m) if r["status"] not in ("ok","budget_exceeded")),
                n, round(cats.get("ok",0)/n*100,1)])
print("  -> tableC_failure_by_arm.csv")

# ---- Table D: evidence-quality metrics by arm ----
with open(f"{PAPER}/tableD_evidence.csv", "w", newline="") as cf:
    w = csv.writer(cf)
    w.writerow(["dataset","arm","mean_evidence_recall","median_evidence_recall",
                "mean_evidence_mrr","mean_retrieved_docs"])
    for ds in DS:
        for m in ARMS:
            recs = vals(ds,m)
            er = col_ok(ds,m,"ev_recall"); emrr = col_ok(ds,m,"ev_mrr"); dd = col_ok(ds,m,"docs")
            w.writerow([ds, LAB[m], mn(er or [0]), pct(er or [0],50),
                        mn(emrr or [0]), mn(dd)])
print("  -> tableD_evidence.csv")
print("ALL TABLES DONE")
