#!/usr/bin/env python3
"""Tier 1 结果分析：对比 baseline vs H-001 vs H-002

用法: python3 research/analyze_tier1.py [output_dir]
"""
import csv, json, glob, sys
from collections import defaultdict

OUT_ROOT = sys.argv[1] if len(sys.argv) > 1 else 'runs/slotrag-phase3-dev'
CONFIGS = ['baseline', 'h001-finalk20', 'h002-morebudget']
STAGE = 'tier1_dev'
DATASETS = ['hotpotqa', '2wikimultihop', 'musique', 'strategyqa', 'drop']

def load_per_question(cfg):
    """加载 per_question.csv"""
    path = f'{OUT_ROOT}/{cfg}/summaries/{STAGE}/per_question.csv'
    if not glob.glob(path):
        return {}
    data = defaultdict(dict)
    with open(path) as f:
        for row in csv.DictReader(f):
            ds = row['dataset']
            qid = row['question_id']
            data[(ds, qid)] = {
                'em': float(row.get('em', 0)),
                'f1': float(row.get('f1', 0)),
                'primary_score': float(row.get('primary_score', 0)),
                'evidence_recall': float(row.get('evidence_recall', 0) or 0),
                'status': row.get('status'),
                'llm_calls': float(row.get('llm_calls', 0) or 0),
            }
    return data

def main():
    results = {}
    for cfg in CONFIGS:
        results[cfg] = load_per_question(cfg)

    # 按数据集聚合
    print("=== Tier 1 结果对比 ===\n")
    print(f"{'数据集':<16}{'配置':<16}{'primary':>8}{'EM':>7}{'F1':>7}{'ev_recall':>10}{'n':>5}{'failed':>7}")
    print("-" * 80)

    summary = {}
    for ds in DATASETS:
        for cfg in CONFIGS:
            items = [(k, v) for k, v in results[cfg].items() if k[0] == ds]
            if not items:
                continue
            valid = [v for _, v in items if v['status'] == 'ok']
            if not valid:
                continue
            primary = sum(v['primary_score'] for v in valid) / len(valid)
            em = sum(v['em'] for v in valid) / len(valid)
            f1 = sum(v['f1'] for v in valid) / len(valid)
            ev_recall = sum(v['evidence_recall'] for v in valid) / len(valid)
            failed = len(items) - len(valid)
            print(f"{ds:<16}{cfg:<16}{primary:>8.4f}{em:>7.4f}{f1:>7.4f}{ev_recall:>10.4f}{len(valid):>5}{failed:>7}")
            summary[(ds, cfg)] = {
                'primary': primary, 'em': em, 'f1': f1,
                'ev_recall': ev_recall, 'n': len(valid), 'failed': failed,
            }
        print()

    # 假设判定
    print("\n=== 假设判定 (hotpotqa primary_score) ===")
    if ('hotpotqa', 'baseline') in summary and ('hotpotqa', 'h001-finalk20') in summary:
        base = summary[('hotpotqa', 'baseline')]['primary']
        h001 = summary[('hotpotqa', 'h001-finalk20')]['primary']
        delta = h001 - base
        print(f"  H-001: baseline={base:.4f} → h001={h001:.4f} delta={delta:+.4f}")
        verdict = "✅ 支持" if delta >= 0.03 else ("❌ 拒绝" if delta < 0 else "❓ 无效应")
        print(f"  判定: {verdict} (需 +3% 支持)")
    if ('hotpotqa', 'baseline') in summary and ('hotpotqa', 'h002-morebudget') in summary:
        base = summary[('hotpotqa', 'baseline')]['primary']
        h002 = summary[('hotpotqa', 'h002-morebudget')]['primary']
        delta = h002 - base
        print(f"  H-002: baseline={base:.4f} → h002={h002:.4f} delta={delta:+.4f}")
        verdict = "✅ 支持" if delta >= 0.03 else ("❌ 拒绝" if delta < 0 else "❓ 无效应")
        print(f"  判定: {verdict} (需 +3% 支持)")

    print("\n=== musique (H-002 目标: budget_exceeded) ===")
    if ('musique', 'baseline') in summary and ('musique', 'h002-morebudget') in summary:
        base = summary[('musique', 'baseline')]
        h002 = summary[('musique', 'h002-morebudget')]
        print(f"  baseline: primary={base['primary']:.4f} failed={base['failed']}")
        print(f"  h002:     primary={h002['primary']:.4f} failed={h002['failed']}")
        print(f"  failed 变化: {base['failed']} → {h002['failed']}")

    print("\n=== 结果已保存: 请查看上方分析 ===")

if __name__ == '__main__':
    main()
