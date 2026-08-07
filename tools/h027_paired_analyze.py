#!/usr/bin/env python3
"""H-027 配对分析: slotrag-grounded-frontier-perpath-guard-samplevote (treatment)
vs slotrag-grounded-frontier-perpath-guard (control).

H-027 gate (sampled majority-vote answer aggregation):
  - selection-failure recovery: 2wiki samples where evidence held gold but the
    greedy generator picked the wrong candidate should rise in F1 after N=5
    sampling + majority vote (H-022: 20 selection failures).
  - no regression: full-matrix F1 must not drop (Δ ≥ -2pt), especially the
    already-correct greedy answers (majority vote must not flip them wrong).
  - cost transparency: llm_calls/generation_llm_calls rise by roughly the sampled
    multiplier; report TRUE counts, do not hide the N=5 cost.

主测:
  - paired F1 (2wiki) / drop_f1 (drop) —— same-20 samples
  - wins/losses/ties, wilcoxon p, bootstrap CI
  - generation_llm_calls (真实调用数) —— cost transparency

用法: python3 tools/h027_paired_analyze.py [items_root]
"""
import json, glob, sys
from pathlib import Path
import numpy as np
from scipy import stats

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else 'runs/slotrag-phase3x-h027-dev/items/h027_tier1')
TREAT = 'slotrag-grounded-frontier-perpath-guard-samplevote'
GUARD = 'slotrag-grounded-frontier-perpath-guard'
DATASETS = ['2wikimultihop', 'drop']


def load_items(ds, method):
    out = {}
    for f in glob.glob(str(ROOT / ds / method / '*.json')):
        if '.lock' in f:
            continue
        d = json.load(open(f))
        out[d['question_id']] = d
    return out


def primary(ds, item):
    s = item.get('scores', {}) or {}
    if ds == '2wikimultihop':
        return s.get('f1', 0.0)
    return s.get('drop_f1') or s.get('primary_score') or s.get('f1') or 0.0


def metric_sum(item, key):
    m = (item.get('result', {}) or {}).get('metrics', {}) or {}
    return m.get(key, 0)


for ds in DATASETS:
    treat = load_items(ds, TREAT)
    guard = load_items(ds, GUARD)
    common = sorted(set(treat) & set(guard))

    print(f"\n{'='*72}\n===== {ds} =====\n{'='*72}")
    print(f"paired n={len(common)}  (guard-only={len(set(guard)-set(treat))}, treat-only={len(set(treat)-set(guard))})")

    if not common:
        continue

    t = np.array([primary(ds, treat[q]) for q in common])
    g = np.array([primary(ds, guard[q]) for q in common])
    diff = t - g
    dmu = np.mean(diff)

    p = 1.0
    if np.any(diff != 0) and len(common) > 1:
        try:
            p = stats.wilcoxon(t, g, zero_method='wilcox').pvalue
        except Exception:
            p = 1.0

    rng = np.random.default_rng(7)
    boots = [np.mean(diff[rng.integers(0, len(common), len(common))]) for _ in range(2000)]
    lo, hi = np.percentile(boots, [2.5, 97.5])

    eps = 0.05
    wins = int(np.sum(diff > eps))
    losses = int(np.sum(diff < -eps))
    ties = len(common) - wins - losses

    print(f"  {ds:<12} n={len(common):<4} mean  treat={np.mean(t):.4f}  guard={np.mean(g):.4f}  Δ={dmu:+.4f}  "
          f"wins={wins} losses={losses} ties={ties}  p={p:.4f}  CI=[{lo:+.4f},{hi:+.4f}]")

    # ---- H-027 gate 1 & 2: per-sample F1 direction (recovery vs regression) ----
    recover = []   # sample was guard-wrong (F1<0.5) but treat rose
    regress = []   # sample was guard-right (F1>=0.5) but treat dropped
    for q in common:
        tg, gt = primary(ds, treat[q]), primary(ds, guard[q])
        if gt < 0.5 and tg > gt + 0.05:
            recover.append(q)
        if gt >= 0.5 and tg < gt - 0.05:
            regress.append(q)
    print(f"  [H-027 gate] recover(gold-wrong->treated-up)={len(recover)}  regress(correct-but-flipped)={len(regress)}")
    if len(regress) <= 12:
        print(f"    regressed qids: {sorted(regress)}")
    if len(recover) <= 12:
        print(f"    recovered qids: {sorted(recover)}")

    # ---- H-027 gate 3: cost transparency (TRUE metric, split by guard==treat) ----
    t_gen = np.array([metric_sum(treat[q], 'generation_llm_calls') for q in common])
    g_gen = np.array([metric_sum(guard[q], 'generation_llm_calls') for q in common])
    print(f"  [H-027 cost] generation_llm_calls  treat_total={t_gen.sum()}  guard_total={g_gen.sum()}  "
          f"multiplier={t_gen.sum()/max(g_gen.sum(),1):.2f}x  "
          f"treat_mean={t_gen.mean():.2f}  guard_mean={g_gen.mean():.2f} | treat_llm_total={sum(metric_sum(treat[q],'llm_calls') for q in common)}  "
          f"guard_llm_total={sum(metric_sum(guard[q],'llm_calls') for q in common)}")

print(f"\n\n⚠️  说明:")

print(f"  - RECOVER: guard F1<0.5 且 treat 上涨 (H-022 selection-failure 候选体)。")
print(f"  - REGRESS: guard F1>=0.5 且 treat 下跌 (majority vote 把 already-correct 翻转) —— 门禁红线。")
print(f"  - 成本: sample=$N x 生成调用, 报告中如实报告乘数。")