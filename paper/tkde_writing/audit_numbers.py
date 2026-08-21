"""Complete paper-to-data audit, v4 — added ΔEM half-up check + per-dataset EM rounding."""
import json, glob
import numpy as np

ARMS = ["slotrag-g7-chain", "slotrag-g7-flat", "slotrag-g7-static"]
RUNS = {
    "hotpotqa": "/data/mzb/SlotRAG/runs/tkde-g6-qwen38/items/g6-effective/hotpotqa",
    "2wikimultihop": "/data/mzb/SlotRAG/runs/tkde-g6-2wiki-qwen38/items/g6-effective/2wikimultihop",
    "musique": "/data/mzb/SlotRAG/runs/tkde-g11-musique-qwen38/items/g11-musique-3hop/musique",
}
SHORT = {"hotpotqa":"hotpotqa", "2wikimultihop":"2wiki", "musique":"musique"}
# Paper claims for ΔEM half-up: (em_static, em_chain, delta_rounded_halfup)
PAPER_DELTA = {"hotpotqa": (37.5, 43.8, 6.3), "2wiki": (52.9, 58.8, 5.9), "musique": (36.4, 45.5, 9.1)}
def load_all(base):
    out = {m: {} for m in ARMS}
    for m in ARMS:
        for f in glob.glob(f"{base}/{m}/*.json"):
            j = json.load(open(f)); qid = j.get("question_id")
            plan = j.get("result", {}).get("plan", {}) or {}
            out[m][qid] = {"cat": j.get("failure_category"),
                "calls": j.get("result", {}).get("metrics", {}).get("retrieval_calls", 0),
                "lat": j.get("result", {}).get("metrics", {}).get("latency_ms", 0),
                "docs": j.get("result", {}).get("metrics", {}).get("documents_accessed", 0),
                "nslots": len(plan.get("slots") or []),
                "em": int((j.get("scores") or {}).get("em", 0) == 1)}
    return out
def boot_p(x, B=200000, seed=2027):
    r = np.random.default_rng(seed)
    boot = np.array([x[r.integers(0, len(x), len(x))].mean() for _ in range(B)])
    return (boot >= 0).mean()

def round_half_up(x, ndigits=1):
    """Python round() is banker's; the paper uses half-up."""
    import decimal
    return float(decimal.Decimal(str(x)).quantize(decimal.Decimal('1e-%d' % ndigits),
                                                   rounding=decimal.ROUND_HALF_UP))

data = {SHORT[ds]: load_all(base) for ds, base in RUNS.items()}

# ---- pooled ----
print("── pooled (paper 55 / 41.8 / 49.1 / -0.16) ──")
n=0; es=0; ec=0; dcsum=0
for full in data.values():
    ids = set(full["slotrag-g7-chain"]) & set(full["slotrag-g7-static"])
    for q in ids:
        if full["slotrag-g7-chain"][q]["cat"]=="ok" and full["slotrag-g7-static"][q]["cat"]=="ok":
            n+=1; es+=full["slotrag-g7-static"][q]["em"]; ec+=full["slotrag-g7-chain"][q]["em"]
            dcsum += full["slotrag-g7-chain"][q]["calls"]-full["slotrag-g7-static"][q]["calls"]
print(f"  n={n} (paper 55) | EM_s={es/n*100:.1f}% (paper 41.8) | EM_c={ec/n*100:.1f}% (paper 49.1) | Δcalls={dcsum/n:+.3f} (paper -0.16)")

# ---- pooled EM bootstrap CI (NEW in v4, paper [-5.5,+20.0]) ----
print("\n── pooled EM bootstrap CI (paper [-5.5,+20.0]pt, seed 2027, B=200k) ──")
alld=[]
for full in data.values():
    ids = set(full["slotrag-g7-chain"]) & set(full["slotrag-g7-static"])
    for q in ids:
        if full["slotrag-g7-chain"][q]["cat"]=="ok" and full["slotrag-g7-static"][q]["cat"]=="ok":
            alld.append((full["slotrag-g7-chain"][q]["em"]-full["slotrag-g7-static"][q]["em"])*100)
alld=np.array(alld)
r=np.random.default_rng(2027)
boot=np.array([alld[r.integers(0,len(alld),len(alld))].mean() for _ in range(200000)])
lo,hi=np.percentile(boot,[2.5,97.5])
print(f"  n={len(alld)} mean ΔEM={alld.mean():+.1f}pt | CI=[{lo:+.1f},{hi:+.1f}]pt (paper [-5.5,+20.0]) "
      f"[{'OK' if abs(lo+5.5)<0.15 and abs(hi-20.0)<0.15 else 'MISMATCH'}]")

# ---- ΔEM half-up consistency (NEW in v4) ----
print("\n── ΔEM half-up check (paper +6.3/+5.9/+9.1) ──")
for ds, full in [("hotpotqa","hotpotqa"),("2wiki","2wikimultihop"),("musique","musique")]:
    d = data[ds]; ids = set(d["slotrag-g7-chain"]) & set(d["slotrag-g7-static"])
    ns=nc=nds=0
    for q in ids:
        if d["slotrag-g7-chain"][q]["cat"]=="ok" and d["slotrag-g7-static"][q]["cat"]=="ok":
            ns+=d["slotrag-g7-static"][q]["em"]; nc+=d["slotrag-g7-chain"][q]["em"]; nds+=1
    em_s_ds = round_half_up(ns*100/nds, 1); em_c_ds = round_half_up(nc*100/nds, 1)
    delta = round_half_up(em_c_ds - em_s_ds, 1)
    paper_s, paper_c, paper_delta = PAPER_DELTA[ds]
    status = "OK" if (abs(em_s_ds-paper_s)<1e-9 and abs(em_c_ds-paper_c)<1e-9 and abs(delta-paper_delta)<1e-9) else "MISMATCH"
    print(f"  {ds}: n={nds} EM_s={em_s_ds:.1f} EM_c={em_c_ds:.1f} Δ={delta:+.1f} (paper {paper_s}/{paper_c}/{paper_delta:+.1f}) [{status}]")

# ---- McNemar ----
print("\n── McNemar (paper 2:1 / 3:2 / 3:1) ──")
for ds, full in [("hotpotqa","hotpotqa"),("2wiki","2wikimultihop"),("musique","musique")]:
    d = data[ds]; ids = set(d["slotrag-g7-chain"]) & set(d["slotrag-g7-static"])
    b=c=0
    for q in ids:
        if d["slotrag-g7-chain"][q]["cat"]=="ok" and d["slotrag-g7-static"][q]["cat"]=="ok":
            if d["slotrag-g7-chain"][q]["em"]==1 and d["slotrag-g7-static"][q]["em"]==0: b+=1
            elif d["slotrag-g7-chain"][q]["em"]==0 and d["slotrag-g7-static"][q]["em"]==1: c+=1
    print(f"  {ds}: b={b}, c={c}")

# ---- asymmetric (single-arm-failed) records, §7 EX-P6 (NEW in v4) ----
print("\n── asymmetric cases (§7 EX-P6: HQ 2 budget-exceeded chain-correct + 1 other chain-incorrect; 2W 1 other chain-incorrect; MS none) ──")
for ds, full in [("hotpotqa","hotpotqa"),("2wiki","2wikimultihop"),("musique","musique")]:
    d = data[ds]; ids = set(d["slotrag-g7-chain"]) & set(d["slotrag-g7-static"])
    asym=[]
    for q in sorted(ids):
        c=d["slotrag-g7-chain"][q]; s=d["slotrag-g7-static"][q]
        if (c["cat"]=="ok") != (s["cat"]=="ok"):
            asym.append((q, s["cat"], c["cat"], s["em"], c["em"]))
    print(f"  {ds}: {len(asym)} asymmetric")
    for q, sc, cc, se, ce in asym:
        print(f"    q={q[:28]:<30s} static={sc:<16s}/em={se} | chain={cc:<16s}/em={ce}")

# ---- per-dataset cost bootstrap p + Holm (paper HQ 0.119/0.357, 2W 0.290/0.580, MS 0.376/0.376) ----
print("\n── cost p-values + Holm (paper HQ 0.119/0.357, 2W 0.290/0.581, MS 0.376/0.376) ──")
PAPER_P = {"hotpotqa": (0.119, 0.357), "2wiki": (0.290, 0.581), "musique": (0.376, 0.376)}
raw_ps = []; all_chain_more = 0; ds_chain_more = {}
for ds in ["hotpotqa", "2wiki", "musique"]:
    d = data[ds]; ids = set(d["slotrag-g7-chain"]) & set(d["slotrag-g7-static"])
    diffs = [d["slotrag-g7-chain"][q]["calls"]-d["slotrag-g7-static"][q]["calls"] for q in sorted(ids)
             if d["slotrag-g7-chain"][q]["cat"]=="ok" and d["slotrag-g7-static"][q]["cat"]=="ok"]
    nmore = sum(1 for x in diffs if x > 0)
    ds_chain_more[ds] = nmore; all_chain_more += nmore
    p = boot_p(np.array(diffs)); raw_ps.append(p)
    p3 = round(p, 3)
    print(f"  {ds}: n={len(diffs)} chain-more={nmore} mean={np.mean(diffs):+.3f} p={p:.4f} (3dp={p3}) paper_p={PAPER_P[ds][0]}")
print(f"  TOTAL chain>static: {all_chain_more}/55 (paper §8 disclosure: '6 of the 55 matched pairs') "
      f"[{'OK' if all_chain_more==6 else 'MISMATCH'}]")
print(f"  per-ds: HQ={ds_chain_more['hotpotqa']}/16 2W={ds_chain_more['2wiki']}/17 MS={ds_chain_more['musique']}/22 "
      "(paper: 0/16, 2/17, 4/22)")
# Holm on sorted raw p
order = sorted(range(3), key=lambda i: raw_ps[i])
for rank, i in enumerate(order):
    holm = min(raw_ps[i]*(3-rank), 1.0)
    ds = ["hotpotqa","2wiki","musique"][i]
    h3 = round(holm, 3)
    print(f"    {ds} Holm={holm:.4f} (3dp={h3}) paper_Holm={PAPER_P[ds][1]} [{'OK' if h3==PAPER_P[ds][1] else 'MISMATCH'}]")

# ---- ge3 per-dataset + pooled ----
print("\n── ge3 benefit domain (paper: HQ --, 2W 0.364, MS 0.036; pooled 0.036) ──")
for ds in ["hotpotqa","2wiki","musique"]:
    d = data[ds]; ids = set(d["slotrag-g7-chain"]) & set(d["slotrag-g7-static"])
    diffs=[d["slotrag-g7-chain"][q]["calls"]-d["slotrag-g7-static"][q]["calls"] for q in sorted(ids)
           if d["slotrag-g7-chain"][q]["cat"]=="ok" and d["slotrag-g7-static"][q]["cat"]=="ok"
           and d["slotrag-g7-chain"][q]["nslots"]>=3]
    if diffs:
        p=boot_p(np.array(diffs)); print(f"  {ds}: n={len(diffs)} Δ={np.mean(diffs):+.2f} p={p:.4f} (3dp={round(p,3)})")
allp=[]
for d in data.values():
    ids=set(d["slotrag-g7-chain"])&set(d["slotrag-g7-static"])
    for q in sorted(ids):
        if d["slotrag-g7-chain"][q]["cat"]=="ok" and d["slotrag-g7-static"][q]["cat"]=="ok" and d["slotrag-g7-chain"][q]["nslots"]>=3:
            allp.append(d["slotrag-g7-chain"][q]["calls"]-d["slotrag-g7-static"][q]["calls"])
pp=boot_p(np.array(allp)); print(f"  POOLED: n={len(allp)} Δ={np.mean(allp):+.2f} p={pp:.4f}")

# ---- ge3 pooled EM ----
print("\n── ge3 pooled EM (paper chain=static=54.5, flat=45.5) ──")
esl=0; ecl=0; efl=0; g3n=0
for d in data.values():
    ids=set(d["slotrag-g7-chain"])&set(d["slotrag-g7-static"])&set(d["slotrag-g7-flat"])
    for q in ids:
        if all(d[m][q]["cat"]=="ok" for m in ARMS) and d["slotrag-g7-chain"][q]["nslots"]>=3:
            esl+=d["slotrag-g7-static"][q]["em"]; ecl+=d["slotrag-g7-chain"][q]["em"]; efl+=d["slotrag-g7-flat"][q]["em"]; g3n+=1
print(f"  n={g3n} | EM_s={esl/g3n*100:.1f}% EM_c={ecl/g3n*100:.1f}% EM_f={efl/g3n*100:.1f}%")

# ---- overhead table ----
print("\n── §9 overhead (paper: chain 1.50/51677/8504/7.50/43.8; flat 1.75/54152/16624/8.75/43.8; static 1.69/46429/10358/8.44/37.5) ──")
d=data["hotpotqa"]
three=[q for q in set(d["slotrag-g7-chain"])&set(d["slotrag-g7-flat"])&set(d["slotrag-g7-static"]) if all(d[m][q]["cat"]=="ok" for m in ARMS)]
for m,l in [("slotrag-g7-chain","chain"),("slotrag-g7-flat","flat"),("slotrag-g7-static","static")]:
    recs=[d[m][q] for q in three]
    print(f"  {l}: n={len(recs)} calls={np.mean([r['calls'] for r in recs]):.2f} lat_mean={np.mean([r['lat'] for r in recs]):.0f} "
          f"lat_p50={np.median([r['lat'] for r in recs]):.0f} docs={np.mean([r['docs'] for r in recs]):.2f} EM={sum(r['em'] for r in recs)/len(recs)*100:.1f}%")

# ---- slot counts ----
print("\n── slot counts chain arm (paper: HQ 1=13,2=2,ge3=5; 2W 1=9,2=4,ge3=7; MS 1=13,2=3,ge3=7) ──")
for ds in ["hotpotqa","2wiki","musique"]:
    d=data[ds]; dist={}
    for q,r in d["slotrag-g7-chain"].items(): dist[r["nslots"]]=dist.get(r["nslots"],0)+1
    s1=dist.get(1,0); s2=dist.get(2,0); ge3=sum(v for k,v in dist.items() if k>=3)
    print(f"  {ds}: 1-slot={s1}, 2-slot={s2}, ge3={ge3}")

print("\n" + "="*72)
print("AUDIT COMPLETE — compare printed values against paper claims above.")
print("="*72)
