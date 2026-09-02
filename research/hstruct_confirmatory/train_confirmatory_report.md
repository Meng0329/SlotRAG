# H-STRUCT-1 Confirmatory Report

> **Status:** POST-EXECUTION (all 1105×2 completed)
> **Protocol:** H-STRUCT-1 V1.1 (frozen)
> **NO MODIFICATIONS** were made to policy, threshold, or analysis plan.

## 1. Primary Result (H-STRUCT-1A: Eligible-Stratum)

- **n_eligible:** 742
- **Static EM:** 0.0526
- **Chain EM:** 0.2210
- **ΔEM:** +0.1685
- **Discordant pairs:** b=128, c=3
- **Odds ratio:** 36.714
- **McNemar χ²:** 117.374
- **p (two-sided):** 0.0000
- **p (one-sided):** 0.0000
- **95% CI (ΔEM):** [0.1091, 0.1682]

**Verdict:** **CONFIRMED** — Chain beneficial for eligible questions

### Per-Dataset Breakdown

| Dataset | n | Static EM | Chain EM | ΔEM | b | c | OR | McNemar p (2s) |
|---------|---|-----------|----------|-----|---|---|-----|---------------|
| 2wikimultihop | 559 | 0.0072 | 0.1449 | +0.1377 | 79 | 2 | 31.800 | 0.0000 |
| hotpotqa | 148 | 0.2162 | 0.5000 | +0.2838 | 43 | 1 | 29.000 | 0.0000 |
| musique | 35 | 0.0857 | 0.2571 | +0.1714 | 6 | 0 | 13.000 | 0.0156 |

## 2. Secondary Analyses

### Train-only
- n=742, ΔEM=+0.1685, McNemar p (2s)=0.0000

### Holm-Corrected p-values (secondary)
- Train-only: raw p=0.0000, corrected p=0.0000

## 3. Population Effect (H-STRUCT-1B)

| Dataset | Prevalence | ATE_eligible | ATE_population |
|---------|-----------|-------------|---------------|
| hotpotqa | 0.0317 | +0.2838 | +0.0090 |
| 2wikimultihop | 0.0698 | +0.1377 | +0.0096 |
| musique | 0.0538 | +0.1714 | +0.0092 |

## 4. Efficiency Metrics

- ΔLLM_calls: -1.0
- Static F1: 0.0711
- Chain F1: 0.3433
- ΔF1: +0.2721

## 5. Declaration

This is a confirmatory test. No modifications were made to the policy,
threshold, or analysis plan after the compile census was frozen.
All results are reported honestly, including non-significant findings.