#!/usr/bin/env python3
"""H-008 结果分析：UnionExtractor (control) vs PerPathExtractor (treatment))

配对对比同 100 样本，指标：EM, F1, evidence_recall, 配对 wilcoxon。
"""
import json, glob, sys, math
from collections import Counter
from pathlib import Path

ROOT = Path('runs/slotrag-phase3r-h008-dev/items/h008_dev')
CTRL = 'slotrag-evidence-bundle'
TREAT = 'slotrag-per-path-extraction'

def norm(s):
    s = ''.join(c for c in str(s).lower() if c.isalnum() or c.isspace())
    return ' '.join(s.split())

def f1(pred, gold):
    p = set(norm(pred).split()); g = set(norm(gold).split())
    if not g: return 0.0
    if not p: return 0.0
    inter = p & g
    if not inter: return 0.0
    prec = len(inter)/len(p); rec = len(inter)/len(g)
    return 2*prec*rec/(prec+rec)

def em(pred, gold):
    return float(norm(pred) == norm(gold))

def evidence_recall(item, gold_evidence):
    """最终 bundle 里 gold source 覆盖（简化：用 item 的 evidence_inventory）"""
    ev = item.get('evidence_inventory', {})
    retrieved = set(ev.get('retrieved_evidence_ids', []))
    gold = set(gold_evidence or [])
    if not gold: return 1.0 if retrieved else 0.0
    return len(gold & retrieved)/len(gold)

def load_items(ds, method):
    out = {}
    for f in glob.glob(str(ROOT/ds/method/'*.json')):
        d = json.load(open(f))
        out[d['question_id']] = d
    return out

# gold answers 和 evidence 从 control 的 answers/gold_evidence 取（同 question 相同）
def gold_info(ds, method):
    """从 item 拿 gold：answers 字段 + gold evidence"""
    golds = {}
    for f in glob.glob(str(ROOT/ds/method/'*.json')):
        d = json.load(open(f))
        qid = d['question_id']
        golds[qid] = {'answers': d.get('answers', []), 'gold_evidence': None}
        # gold evidence 可能不在 item 里；若有 gold_evidence 字段则取
        if 'gold_evidence' in d: golds[qid]['gold_evidence'] = d['gold_evidence']
    return golds

for ds in ['hotpotqa', '2wikimultihop', 'musique']:
    ctrl = load_items(ds, CTRL)
    treat = load_items(ds, TREAT)
    common = set(ctrl) & set(treat)
    print(f'\n===== {ds} =====')
    print(f'ctrl={len(ctrl)} treat={len(treat)} paired={len(common)}')

    # 状态分布
    c_status = Counter(c.get('result',{}).get('status') for c in ctrl.values())
    t_status = Counter(t.get('result',{}).get('status') for t in treat.values())
    print(f'  control status: {dict(c_status)}')
    print(f'  treatment status: {dict(t_status)}')

    # 配对 EM/F1（仅 ok 双方）
    pairs = []
    for qid in common:
        c, t = ctrl[qid], treat[qid]
        cr, tr = c.get('result',{}), t.get('result',{})
        if cr.get('status') != 'ok' or tr.get('status') != 'ok': continue
        ca, ta = cr.get('answer'), tr.get('answer')
        gold = (c.get('answers') or [''])[0]
        pairs.append((em(ca, gold), em(ta, gold), f1(ca, gold), f1(ta, gold), cr, tr, c))
    if not pairs:
        print('  (treatment 未完成或配对为空)')
        continue

    n = len(pairs)
    c_em = sum(p[0] for p in pairs)/n
    t_em = sum(p[1] for p in pairs)/n
    c_f1 = sum(p[2] for p in pairs)/n
    t_f1 = sum(p[3] for p in pairs)/n

    # 配对 wilcoxon (signed-rank) 简化：统计胜负
    wins = sum(p[1] > p[0] for p in pairs)
    losses = sum(p[1] < p[0] for p in pairs)
    ties = sum(p[1] == p[0] for p in pairs)

    print(f'  paired_n={n}')
    print(f'  control EM={c_em:.3f} F1={c_f1:.3f}')
    print(f'  treat   EM={t_em:.3f} F1={t_f1:.3f}')
    print(f'  ΔEM={t_em-c_em:+.3f} ΔF1={t_f1-c_f1:+.3f}')
    print(f'  wins={wins} losses={losses} ties={ties}')

    # 只看双方都 ok 里，control 答对 treat 答错的（回归）和反向（改进）
    print(f'  改进样本 (control错->treat对): {wins}')
    print(f'  回归样本 (control对->treat错): {losses}')