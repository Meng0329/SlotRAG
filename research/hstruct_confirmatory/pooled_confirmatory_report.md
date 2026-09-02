# H-STRUCT-1 Confirmatory Report

> **Status:** POST-EXECUTION (all 1105×2 completed)
> **Protocol:** H-STRUCT-1 V1.1 (frozen)
> **NO MODIFICATIONS** were made to policy, threshold, or analysis plan.

## 1. Primary Result (H-STRUCT-1A: Eligible-Stratum)

- **n_eligible:** 1092
- **Static EM:** 0.0907
- **Chain EM:** 0.2326
- **ΔEM:** +0.1419
- **Discordant pairs:** b=164, c=9
- **Odds ratio:** 17.316
- **McNemar χ²:** 137.087
- **p (two-sided):** 0.0000
- **p (one-sided):** 0.0000
- **95% CI (ΔEM):** [0.0994, 0.1460]

**Verdict:** **CONFIRMED** — Chain beneficial for eligible questions

### Per-Dataset Breakdown

| Dataset | n | Static EM | Chain EM | ΔEM | b | c | OR | McNemar p (2s) |
|---------|---|-----------|----------|-----|---|---|-----|---------------|
| 2wikimultihop | 815 | 0.0528 | 0.1755 | +0.1227 | 106 | 6 | 16.385 | 0.0000 |
| hotpotqa | 212 | 0.2217 | 0.4434 | +0.2217 | 49 | 2 | 19.800 | 0.0000 |
| musique | 65 | 0.1385 | 0.2615 | +0.1231 | 9 | 1 | 6.333 | 0.0117 |

## 2. Secondary Analyses

### Validation-only
- n=350, ΔEM=+0.0857, McNemar p (2s)=0.0000

### Train-only
- n=742, ΔEM=+0.1685, McNemar p (2s)=0.0000

### Holm-Corrected p-values (secondary)
- Validation-only: raw p=0.0000, corrected p=0.0000
- Train-only: raw p=0.0000, corrected p=0.0000

## 3. Population Effect (H-STRUCT-1B)

| Dataset | Prevalence | ATE_eligible | ATE_population |
|---------|-----------|-------------|---------------|
| hotpotqa | 0.0317 | +0.2217 | +0.0070 |
| 2wikimultihop | 0.0698 | +0.1227 | +0.0086 |
| musique | 0.0538 | +0.1231 | +0.0066 |

## 4. Efficiency Metrics

- ΔLLM_calls: -1.2
- Static F1: 0.1294
- Chain F1: 0.3642
- ΔF1: +0.2348

## 5. Declaration

This is a confirmatory test. No modifications were made to the policy,
threshold, or analysis plan after the compile census was frozen.
All results are reported honestly, including non-significant findings.