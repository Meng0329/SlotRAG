#!/usr/bin/env python3
"""H-025 配对分析: slotrag-grounded-frontier-perpath-typed-surface (treatment) vs
slotrag-grounded-frontier-perpath-guard (control).

H-025 gate (surface-form typed contract):
  e084 recovers to F1 1.0, operators don't degrade, no regression (Δ≥-2pt),
  typed_parse_success_rate preserved.

主测:
  - paired F1 (2wiki) / drop_f1 (drop) —— same-20 samples
  - typed_extraction_answers / abstentions (typed_path only)
  - typed_parse_success_rate = answers / (answers+abstentions) on typed paths
  - join_output_rows (operator consumption health)

用法: python3 tools/h025_paired_analyze.py [items_root]
"""
import json, glob, sys, os
from pathlib import Path
import numpy as np
from scipy import stats

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else 'runs/slotrag-phase3x-h025-dev/items/h025_tier1')
TREAT = 'slotrag-grounded-frontier-perpath-typed-surface'
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


# --- 重点 e084 恢复核查 ---
# e084 是 H-024 里唯一被 typed_contracts 伤害的样本（surface → ISO 重写毁掉答案格式）。
# 在 guard（typed off）里它应该 F1 1.0；在 typed-surface 里应保持 1.0。
E084_QID = 'e084'


def find(qid, items):
    for q, d in items.items():
        if q.startswith(qid) or qid in q:
            return d
    return None


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

    # wilcoxon
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

    # ---- H-025 gate: typed contract health ----
    t_answers = sum(metric_sum(treat[q], 'typed_extraction_answers') for q in common)
    t_abst = sum(metric_sum(treat[q], 'typed_extraction_abstentions') for q in common)
    t_contracts = sum(metric_sum(treat[q], 'typed_extraction_contracts') for q in common)
    parse_rate = t_answers / (t_answers + t_abst) if (t_answers + t_abst) else float('nan')
    print(f"  [H-025] typed contracts={t_contracts}  answers={t_answers}  abstentions={t_abst}  "
          f"parse_success_rate={parse_rate:.3f}")

    # operator consumption
    t_join = sum(metric_sum(treat[q], 'join_output_rows') for q in common)
    g_join = sum(metric_sum(guard[q], 'join_output_rows') for q in common)
    print(f"  [op] join_output_rows  treat={t_join}  guard={g_join}")


print(f"\n\n⚠️ 说明: typed_extraction_contracts/answers 只在 treatment 侧开启 (guard 侧=0, 无 typed 契约)。")
print(f"检索 e084 恢复核查: 2wiki paired 里 F1 波动样本需逐个盯。")