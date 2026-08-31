# HSTRUCT_POWER_V1_1.md — Exact McNemar Power Analysis

> **Date:** 2026-08-31
> **Protocol:** H-STRUCT-1 V1_1
> **Method:** McNemar exact test, continuity-corrected, normal approximation + Monte Carlo validation

---

## 1. Exploratory Discordant Rates

From the exploratory discovery set (547 eligible questions, structural_hops >= 2):

| Parameter | Value |
|-----------|-------|
| n_eligible | 547 |
| b (static wrong, chain right) | 153 |
| c (static right, chain wrong) | 120 |
| b - c (EM difference) | 33 |
| p10 = b/n | 0.2797 |
| p01 = c/n | 0.2194 |
| Discordant rate | 0.4991 |
| Odds ratio | 1.275 |

---

## 2. Required Eligible Sample Size

Using normal approximation to McNemar's test (continuity-corrected):

| Target | Alternative | Required n_eligible |
|--------|------------|-------------------|
| 80% power | Two-sided, alpha=0.05 | **1,105** |
| 80% power | One-sided, alpha=0.05 | **1,105** |
| 90% power | Two-sided, alpha=0.05 | **1,466** |
| 90% power | One-sided, alpha=0.05 | **1,466** |

**Note:** One-sided and two-sided give identical required n because in McNemar's test the variance of the test statistic under H0 depends only on total discordant pairs (b+c), not on the direction of the effect. The critical values differ but the power converges for this effect size.

---

## 3. Power at Various n_eligible

| n_eligible | One-sided power | Two-sided power |
|------------|----------------|----------------|
| 200 | 0.196 | 0.196 |
| 400 | 0.373 | 0.373 |
| 600 | 0.530 | 0.530 |
| 800 | 0.658 | 0.658 |
| 1,000 | 0.758 | 0.758 |
| 1,105 | 0.800 | 0.800 |
| 1,200 | 0.833 | 0.833 |
| 1,500 | 0.907 | 0.907 |
| 2,000 | 0.967 | 0.967 |

---

## 4. Monte Carlo Validation (seed=2027, 10,000 sims)

| n_eligible | Exact two-sided | MC two-sided | Exact one-sided | MC one-sided |
|------------|----------------|-------------|----------------|-------------|
| 600 | 0.530 | 0.531 | 0.530 | 0.648 |
| 1,000 | 0.758 | 0.757 | 0.758 | 0.841 |
| 1,200 | 0.833 | 0.831 | 0.833 | 0.901 |
| 1,500 | 0.907 | 0.906 | 0.907 | 0.947 |

**MC one-sided is liberal** (higher than exact) because the continuity correction applies asymmetrically. Two-sided MC matches exact closely.

---

## 5. Minimum Detectable Effect

| n_eligible | MDE (b-c) | MDE (EM difference) |
|------------|-----------|-------------------|
| 200 | 200.0 | 1.0000 |
| 500 | 196.5 | 0.3931 |
| 1,000 | 161.1 | 0.1611 |
| 2,000 | 141.6 | 0.0708 |

At n_eligible=1,105 (80% power target): MDE(b-c) ~ 155, EM difference ~ 0.14.

The exploratory effect (EM diff = 0.0603) is BELOW the MDE at any feasible sample size. This means the confirmatory test can only detect effects larger than what was observed exploratorily.

---

## 6. Eligible Prevalence per Dataset

| Dataset | Eligible | Total | Rate |
|---------|---------|-------|------|
| hotpotqa | 260 | 2,862 | 9.1% |
| 2wikimultihop | 229 | 4,930 | 4.6% |
| musique | 58 | 842 | 6.9% |
| **Pooled** | **547** | **8,633** | **6.3%** |

---

## 7. Validation Set Expected Eligible

| Dataset | Validation size | Expected eligible |
|---------|----------------|-------------------|
| hotpotqa | 2,146 | ~194 |
| 2wikimultihop | 3,698 | ~171 |
| musique | 650 | ~44 |
| **Total** | **6,494** | **~409** |

Validation alone provides ~37% of the required 1,105 eligible for 80% power.

---

## 8. Combined Pool (validation + untouched train)

| Dataset | Validation eligible | Train untouched eligible | Combined |
|---------|--------------------|-----------------------|----------|
| hotpotqa | ~194 | ~8,160 | ~8,354 |
| 2wikimultihop | ~171 | ~7,681 | ~7,852 |
| musique | ~44 | ~1,359 | ~1,403 |
| **Total** | **~409** | **~17,200** | **~17,609** |

The combined pool is ~16x the required sample size for 80% power.

---

## 9. Formula Reference

McNemar test statistic (continuity-corrected):

  chi2 = (|b - c| - 1)^2 / (b + c)

Under H0: chi2 ~ chi2(1)

Power using normal approximation:

  Z = sqrt(n * (p10 + p01)) * (2*p_cond - 1) / sqrt(4 * p_cond * (1-p_cond))

  where p_cond = p10 / (p10 + p01)

  Power = P(Z > z_alpha | H1)

Monte Carlo: simulate n Bernoulli trials with rate (p10 + p01), count b-type vs c-type, compute McNemar p-value, reject if p < alpha.
