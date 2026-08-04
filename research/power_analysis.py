#!/usr/bin/env python3
"""阶段 2：功效分析"""
import csv, json, numpy as np
from collections import defaultdict

ALPHA = 0.05
POWER = 0.80
MIN_EFFECT = 0.05
BOOTSTRAP_N = 1000
PER_QUESTION_CSV = 'runs/vldb2027-submission-qwen36-v3-rescored-v2-final/summaries/main_comparison/per_question.csv'

def load_results():
    results = {}
    with open(PER_QUESTION_CSV) as f:
        for row in csv.DictReader(f):
            ds = row['dataset']
            method = row['method']
            if row.get('status', 'ok') != 'ok':
                continue
            em = float(row.get('em', 0))
            f1 = float(row.get('f1', 0))
            key = (ds, method)
            if key not in results:
                results[key] = {'em': [], 'f1': []}
            results[key]['em'].append(em)
            results[key]['f1'].append(f1)
    return results

def estimate_variance(values):
    if len(values) < 2:
        return 0.0
    values = np.array(values, dtype=float)
    boot_means = [np.mean(np.random.choice(values, size=len(values), replace=True)) for _ in range(BOOTSTRAP_N)]
    return float(np.var(boot_means))

def compute_sample_size(variance, effect_size):
    if variance == 0 or effect_size == 0:
        return 1
    from scipy import stats as sp_stats
    z_alpha = sp_stats.norm.ppf(1 - ALPHA / 2)
    z_beta = sp_stats.norm.ppf(POWER)
    n = (z_alpha + z_beta) ** 2 * 2 * variance / effect_size ** 2
    return max(2, int(np.ceil(n)))

def detectable_effect(variance, n):
    if variance == 0 or n < 2:
        return 0.0
    from scipy import stats as sp_stats
    z_alpha = sp_stats.norm.ppf(1 - ALPHA / 2)
    z_beta = sp_stats.norm.ppf(POWER)
    return (z_alpha + z_beta) * np.sqrt(2 * variance / n)

def main():
    print("=== 功效分析 ===\n")
    from scipy import stats as sp_stats
    results = load_results()
    datasets = sorted(set(ds for ds, _ in results.keys()))
    
    recs = []
    print(f"{'数据集':<16}{'指标':<6}{'方法':<12}{'n':>6}{'方差':>10}{'可检测效应':>12}")
    print("-" * 70)
    for ds in datasets:
        for metric in ['em', 'f1']:
            for method in sorted(set(m for d, m in results.keys() if d == ds)):
                vals = results[(ds, method)][metric]
                if len(vals) < 2:
                    continue
                var = estimate_variance(vals)
                det = detectable_effect(var, len(vals))
                print(f"{ds:<16}{metric.upper():<6}{method:<12}{len(vals):>6}{var:>10.6f}{det:>11.4f}")
    
    print("\n\n样本量建议 (α=0.05, power=0.80, δ=5%):")
    print(f"{'数据集':<16}{'指标':<6}{'最大方差':>12}{'所需n':>8}{'当前n':>8}{'状态':>10}")
    print("-" * 65)
    for ds in datasets:
        for metric in ['em', 'f1']:
            max_var = 0
            current_n = 0
            for method in set(m for d, m in results.keys() if d == ds):
                vals = results[(ds, method)][metric]
                if len(vals) > 1:
                    v = estimate_variance(vals)
                    if v > max_var:
                        max_var = v
                    if len(vals) > current_n:
                        current_n = len(vals)
            req_n = compute_sample_size(max_var, MIN_EFFECT) if max_var > 0 else 1
            status = "足够" if current_n >= req_n else "不足"
            print(f"{ds:<16}{metric.upper():<6}{max_var:>12.6f}{req_n:>8}{current_n:>8}{status:>10}")
            recs.append({'dataset': ds, 'metric': metric, 'max_variance': max_var,
                         'required_n': req_n, 'current_n': current_n, 'sufficient': current_n >= req_n})
    
    output = {'analysis_timestamp': '2026-08-04T21:30:00Z',
              'parameters': {'alpha': ALPHA, 'power': POWER, 'min_effect': MIN_EFFECT},
              'recommendations': recs}
    with open('research/power_analysis.json', 'w') as f:
        json.dump(output, f, indent=2)
    print(f"\n结果已保存: research/power_analysis.json")

if __name__ == '__main__':
    main()
