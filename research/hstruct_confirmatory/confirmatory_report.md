# H-STRUCT-1 Confirmatory Report

> **Status:** POST-EXECUTION (all 1105×2 completed)
> **Protocol:** H-STRUCT-1 V1.1 (frozen)
> **NO MODIFICATIONS** were made to policy, threshold, or analysis plan.

## 1. Primary Result (H-STRUCT-1A: Eligible-Stratum)

- **n_eligible:** 350
- **Static EM:** 0.1714
- **Chain EM:** 0.2571
- **ΔEM:** +0.0857
- **Discordant pairs:** b=36, c=6
- **Odds ratio:** 5.615
- **McNemar χ²:** 20.024
- **p (two-sided):** 0.0000
- **p (one-sided):** 0.0000
- **95% CI (ΔEM):** [-0.1328, -0.0508]

**Verdict:** **CONFIRMED** — Chain beneficial for eligible questions

### Per-Dataset Breakdown

| Dataset | n | Static EM | Chain EM | ΔEM | b | c | OR | McNemar p (2s) |
|---------|---|-----------|----------|-----|---|---|-----|---------------|
| 2wikimultihop | 256 | 0.1523 | 0.2422 | +0.0898 | 27 | 4 | 6.111 | 0.0000 |
| hotpotqa | 64 | 0.2344 | 0.3125 | +0.0781 | 6 | 1 | 4.333 | 0.0703 |
| musique | 30 | 0.2000 | 0.2667 | +0.0667 | 3 | 1 | 2.333 | 0.3750 |

## 2. Secondary Analyses

### Validation-only
- n=350, ΔEM=+0.0857, McNemar p (2s)=0.0000

### Holm-Corrected p-values (secondary)
- Validation-only: raw p=0.0000, corrected p=0.0000

## 3. Population Effect (H-STRUCT-1B)

| Dataset | Prevalence | ATE_eligible | ATE_population |
|---------|-----------|-------------|---------------|
| hotpotqa | 0.0317 | +0.0781 | +0.0025 |
| 2wikimultihop | 0.0698 | +0.0898 | +0.0063 |
| musique | 0.0538 | +0.0667 | +0.0036 |

## 4. Efficiency Metrics

- ΔLLM_calls: -1.6
- Static F1: 0.2529
- Chain F1: 0.4086
- ΔF1: +0.1558

## 5. Declaration

This is a confirmatory test. No modifications were made to the policy,
threshold, or analysis plan after the compile census was frozen.
All results are reported honestly, including non-significant findings.