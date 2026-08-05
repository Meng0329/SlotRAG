#!/usr/bin/env python3
"""H-009 结果分析：slotrag-per-path-extraction (control) vs slotrag-score-guided-extraction (treatment)

配对对比同 100 样本，指标：EM, F1, S5_WRONG_VALUE 减少。
"""
import json, glob, sys, re
from collections import Counter
from pathlib import Path

ROOT = Path('runs/slotrag-phase3r-h009-dev/items/h009_dev')
CTRL = 'slotrag-per-path-extraction'
TREAT = 'slotrag-score-guided-extraction'
DATASETS = ['hotpotqa', '2wikimultihop']

def norm(s):
    s = ''.join(c for c in str(s).lower() if c.isalnum() or c.isspace())
    return ' '.join(s.split())

def f1(pred, gold):
    p = set(norm(pred).split()); g = set(norm(gold).split())
    if not g or not p: return 0.0
    inter = p & g
    if not inter: return 0.0
    pr = len(inter)/len(p); rc = len(inter)/len(g)
    return 2*pr*rc/(pr+rc)

def em(pred, gold):
    return float(norm(pred) == norm(gold))

def load_items(ds, method):
    out = {}
    for f in glob.glob(str(ROOT/ds/method/'*.json')):
        d = json.load(open(f))
        out[d['question_id']] = d
    return out

for ds in DATASETS:
    ctrl = load_items(ds, CTRL)
    treat = load_items(ds, TREAT)
    common = set(ctrl) & set(treat)
    print(f'\n===== {ds} =====')
    print(f'ctrl={len(ctrl)} treat={len(treat)} paired={len(common)}')

    # 状态
    c_status = Counter(c.get('result',{}).get('status') for c in ctrl.values())
    t_status = Counter(t.get('result',{}).get('status') for t in treat.values())
    print(f'  control status: {dict(c_status)}')
    print(f'  treatment status: {dict(t_status)}')

    pairs = []
    for qid in common:
        c, t = ctrl[qid], treat[qid]
        cr, tr = c.get('result',{}), t.get('result',{})
        if cr.get('status') != 'ok' or tr.get('status') != 'ok': continue
        ca, ta = cr.get('answer'), tr.get('answer')
        gold = (c.get('answers') or [''])[0]
        pairs.append((qid, gold, ca, ta, em(ca,gold), em(ta,gold), f1(ca,gold), f1(ta,gold)))

    if not pairs:
        print('  (treatment 未完成)')
        continue

    n = len(pairs)
    c_em = sum(p[4] for p in pairs)/n
    t_em = sum(p[5] for p in pairs)/n
    c_f1 = sum(p[6] for p in pairs)/n
    t_f1 = sum(p[7] for p in pairs)/n
    wins = sum(p[5] > p[4] for p in pairs)
    losses = sum(p[5] < p[4] for p in pairs)
    ties = sum(p[5] == p[4] for p in pairs)

    print(f'  paired_n={n}')
    print(f'  control EM={c_em:.3f} F1={c_f1:.3f}')
    print(f'  treat   EM={t_em:.3f} F1={t_f1:.3f}')
    print(f'  ΔEM={t_em-c_em:+.3f} ΔF1={t_f1-c_f1:+.3f}')
    print(f'  wins={wins} losses={losses} ties={ties}')
    print(f'  门禁: {"支持" if (t_em-c_em)*100>=3 else "部分支持" if (t_em-c_em)*100>=1 else "拒绝"}')

    # 改进/回归样本明细
    print(f'\n  改进样本 (control错->treat对):')
    for qid, gold, ca, ta, ce, te, cf, tf in pairs:
        if te > ce:
            print(f'    {qid} | gold={gold[:30]!r} | control={ca[:30]!r} | treat={ta[:30]!r}')
    print(f'  回归样本 (control对->treat错):')
    for qid, gold, ca, ta, ce, te, cf, tf in pairs:
        if te < ce:
            print(f'    {qid} | gold={gold[:30]!r} | control={ca[:30]!r} | treat={ta[:30]!r}')
