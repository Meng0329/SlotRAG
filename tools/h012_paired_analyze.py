#!/usr/bin/env python3
"""H-012 配对分析：slotrag-grounded-frontier-perpath-guard (treatment) vs 各 baseline (control)

配对对比同 100 样本，主指标按数据集：
- hotpotqa/2wiki/musique: F1 + EM
- strategyqa: accuracy (primary_score)
- drop: drop_f1 (primary_score)

统计：配对 wilcoxon（用系统 python 的 scipy）+ bootstrap CI。
用法: python3 tools/h012_paired_analyze.py [items_root]
"""
import json, glob, sys, re
from pathlib import Path
import numpy as np
from scipy import stats

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else 'runs/slotrag-phase3r-h012-full/items/h012_full')
TREAT = 'slotrag-grounded-frontier-perpath-guard'
BASELINES = ['graphrag', 'hybrid', 'ircot', 'planrag', 'react', 'srag']
DATASETS = ['hotpotqa', '2wikimultihop', 'musique', 'strategyqa', 'drop']

def norm(s):
    s = ''.join(c for c in str(s).lower() if c.isalnum() or c.isspace())
    return ' '.join(s.split())

def em(pred, gold):
    return float(norm(pred) == norm(gold))

def f1(pred, gold):
    p = set(norm(pred).split()); g = set(norm(gold).split())
    if not g or not p: return 0.0
    inter = p & g
    if not inter: return 0.0
    pr = len(inter)/len(p); rc = len(inter)/len(g)
    return 2*pr*rc/(pr+rc) if (pr+rc) else 0.0

def load_items(ds, method):
    out = {}
    for f in glob.glob(str(ROOT/ds/method/'*.json')):
        d = json.load(open(f))
        out[d['question_id']] = d
    return out

# 主指标获取
def primary_score(item):
    return item.get('scores', {}).get('primary_score') or item.get('scores', {}).get('f1') or 0.0

def accuracy(item):
    return item.get('scores', {}).get('accuracy') or item.get('scores', {}).get('primary_score') or 0.0

def drop_f1(item):
    return item.get('scores', {}).get('drop_f1') or item.get('scores', {}).get('primary_score') or 0.0

for ds in DATASETS:
    treat = load_items(ds, TREAT)
    print(f"\n{'='*72}\n===== {ds} =====\n{'='*72}")

    for base in BASELINES:
        b_items = load_items(ds, base)
        common = set(treat) & set(b_items)
        if not common:
            print(f"  {base}: no common items")
            continue

        # 配对主指标 —— 用 scores 里的官方指标（baseline 的 result.answer 可能是 thinking 文本）
        if ds in ('hotpotqa', '2wikimultihop', 'musique'):
            t_scores = [treat[q].get('scores', {}).get('f1', 0.0) for q in common]
            b_scores = [b_items[q].get('scores', {}).get('f1', 0.0) for q in common]
            metric = 'F1'
        elif ds == 'strategyqa':
            t_scores = [accuracy(treat[q]) for q in common]
            b_scores = [accuracy(b_items[q]) for q in common]
            metric = 'acc'
        else:  # drop
            t_scores = [drop_f1(treat[q]) for q in common]
            b_scores = [drop_f1(b_items[q]) for q in common]
            metric = 'drop_f1'

        t_arr = np.array(t_scores); b_arr = np.array(b_scores)
        diff = t_arr - b_arr
        n = len(common)

        # wilcoxon（仅当有差异时）
        if np.any(diff != 0) and n > 1:
            try:
                p = stats.wilcoxon(t_arr, b_arr, zero_method='wilcox').pvalue
            except: p = 1.0
        else:
            p = 1.0

        # bootstrap CI
        rng = np.random.default_rng(42)
        boots = [np.mean(diff[rng.integers(0, n, n)]) for _ in range(2000)]
        lo, hi = np.percentile(boots, [2.5, 97.5])

        # wins/losses：F1/acc 用 0.05 阈值（连续值需明显差异），drop_f1 同理
        eps = 0.05
        wins = np.sum(diff > eps)
        losses = np.sum(diff < -eps)
        ties = n - wins - losses

        mean_t = np.mean(t_arr); mean_b = np.mean(b_arr)
        d = mean_t - mean_b

        # 判定（用配对差异的显著性 + 方向）
        verdict = 'WIN' if (d > 0 and p < 0.05) else ('win' if d > 0 else ('LOSS' if (d < 0 and p < 0.05) else ('loss' if d < 0 else 'tie')))

        print(f"  {base:<12} n={n:<4} {metric}={mean_t:.4f} vs {mean_b:.4f}  Δ={d:+.4f}  wins={wins} losses={losses} ties={ties}  p={p:.4f}  CI=[{lo:+.4f},{hi:+.4f}]  → {verdict}")

print(f"\n\n⚠️ 注意：本分析仅含配对样本（两方法都 ok 的题）。failed/budget_exceeded 样本未计入。")
