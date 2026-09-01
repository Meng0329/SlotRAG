#!/usr/bin/env python3
"""
mcnemar_power.py — McNemar power calculation (optimized)

Methods:
1. Normal approximation (fast, primary for n>100)
2. Monte Carlo simulation (100k sims, seed=2027, validation)

Input: exploratory discordant rates from n=547 eligible questions.
"""

import math
import random
from scipy.stats import norm, chi2
from scipy.stats import binom as binom_dist


def mcnemar_power_normal(n, p10, p01, alpha=0.05, two_sided=True,
                          continuity_correction=True):
    """
    McNemar power via normal approximation.

    Under H1:
        E[b-c] = n * (p10 - p01)
        Var[b-c] = n * (p10 + p01) * (1 - (p10-p01)^2/(p10+p01))
                 = n * p_disc * (4 * p_cond * (1-p_cond))

    Test statistic (continuity-corrected):
        Z = (|b-c| - 1) / sqrt(b+c)

    Under H0: b+c ~ n*p_disc, so sqrt(b+c) ≈ sqrt(n*p_disc)
    """
    p_disc = p10 + p01
    if p_disc == 0 or p_disc >= 1:
        return 0.0

    p_cond = p10 / p_disc
    delta = p10 - p01  # expected ΔEM

    # Variance of (b-c) under H1
    var_diff = n * p_disc * 4 * p_cond * (1 - p_cond)
    se_diff = math.sqrt(var_diff)

    if se_diff == 0:
        return 1.0 if delta > 0 else 0.0

    # Non-centrality parameter
    ncp = delta * n / se_diff

    # Under H0: test statistic ~ N(0, 1) approximately
    # Rejection region
    if two_sided:
        z_crit = norm.ppf(1 - alpha / 2)
    else:
        z_crit = norm.ppf(1 - alpha)

    # Power: P(reject H0 | H1)
    if two_sided:
        # Reject if |Z| > z_crit where Z = (|b-c|-1)/sqrt(n*p_disc)
        cc = 1.0 / math.sqrt(n * p_disc) if continuity_correction else 0
        # P(Z > z_crit | H1) + P(Z < -z_crit | H1)
        # Z = (|b-c|-1)/sqrt(n*p_disc) ≈ (|b-c|/se_diff * se_diff/sqrt(n*p_disc)) - cc
        # Simpler: power of two-sided test with effect size delta/se_diff
        power = (1 - norm.cdf(z_crit - ncp)) + norm.cdf(-z_crit - ncp)
    else:
        cc = 1.0 / math.sqrt(n * p_disc) if continuity_correction else 0
        power = 1 - norm.cdf(z_crit - ncp)

    return max(0.0, min(1.0, power))


def find_required_n_normal(p10, p01, target_power=0.80, alpha=0.05,
                            two_sided=True, continuity_correction=True,
                            max_n=5000):
    """Find minimum n achieving target power (normal approximation)."""
    lo, hi = 10, max_n
    while lo < hi:
        mid = (lo + hi) // 2
        power = mcnemar_power_normal(mid, p10, p01, alpha, two_sided,
                                     continuity_correction)
        if power >= target_power:
            hi = mid
        else:
            lo = mid + 1
    return lo


def monte_carlo_power(n, p10, p01, alpha=0.05, two_sided=True,
                       continuity_correction=True,
                       n_sims=100_000, seed=2027):
    """
    Monte Carlo power estimation for McNemar's test.
    """
    rng = random.Random(seed)
    p_disc = p10 + p01

    rejections = 0

    for _ in range(n_sims):
        b_count = 0
        c_count = 0
        for _ in range(n):
            u = rng.random()
            if u < p10:
                b_count += 1
            elif u < p10 + p01:
                c_count += 1

        n_disc = b_count + c_count
        if n_disc == 0:
            continue

        if two_sided:
            if continuity_correction:
                stat = (abs(b_count - c_count) - 1) ** 2 / n_disc
            else:
                stat = (b_count - c_count) ** 2 / n_disc
            p_val = 1 - chi2.cdf(stat, df=1)
        else:
            if b_count >= c_count:
                p_val = 1 - binom_dist.cdf(b_count - 1, n_disc, 0.5)
            else:
                p_val = binom_dist.cdf(b_count, n_disc, 0.5)

        if p_val < alpha:
            rejections += 1

    power = rejections / n_sims
    se = math.sqrt(power * (1 - power) / n_sims)
    return power, se


def compute_mde(n, p10, p01, alpha=0.05, two_sided=True, target_power=0.80):
    """
    Compute minimum detectable ΔEM for given n and target power.

    Varies p_cond (fixing p_disc) to find where power = target_power.
    """
    p_disc = p10 + p01
    lo, hi = 0.5, 0.9999
    for _ in range(100):
        mid = (lo + hi) / 2
        p10_mid = p_disc * mid
        p01_mid = p_disc * (1 - mid)
        power = mcnemar_power_normal(n, p10_mid, p01_mid, alpha, two_sided)
        if power >= target_power:
            hi = mid
        else:
            lo = mid
    p_cond_mde = (lo + hi) / 2
    delta_mde = p_disc * (2 * p_cond_mde - 1)
    return delta_mde


if __name__ == "__main__":
    # Exploratory rates
    n_exp = 547
    b_exp = 153
    c_exp = 120
    p10 = b_exp / n_exp
    p01 = c_exp / n_exp

    print("=" * 70)
    print("McNemar Power Analysis — Corrected Implementation")
    print("=" * 70)
    print(f"\nExploratory data:")
    print(f"  n_eligible = {n_exp}")
    print(f"  b = {b_exp}, c = {c_exp}")
    print(f"  p10 = {p10:.4f}, p01 = {p01:.4f}")
    print(f"  p_disc = {p10+p01:.4f}, p_cond = {p10/(p10+p01):.4f}")
    print(f"  ΔEM = {p10-p01:.4f}")

    configs = [
        (0.80, False, "80% one-sided"),
        (0.80, True,  "80% two-sided"),
        (0.90, False, "90% one-sided"),
        (0.90, True,  "90% two-sided"),
    ]

    print(f"\n{'='*70}")
    print("Normal Approximation (primary)")
    print(f"{'='*70}")
    for target, two_sided, label in configs:
        n_req = find_required_n_normal(p10, p01, target, 0.05, two_sided)
        power_at = mcnemar_power_normal(n_req, p10, p01, 0.05, two_sided)
        power_prev = mcnemar_power_normal(n_req - 1, p10, p01, 0.05, two_sided)
        print(f"\n  {label}: n_required = {n_req}")
        print(f"    Power at n={n_req}: {power_at:.4f}")
        print(f"    Power at n={n_req-1}: {power_prev:.4f}")

    print(f"\n{'='*70}")
    print("Monte Carlo Validation (100k sims, seed=2027)")
    print(f"{'='*70}")
    for target, two_sided, label in configs:
        n_req = find_required_n_normal(p10, p01, target, 0.05, two_sided)
        power_mc, se_mc = monte_carlo_power(n_req, p10, p01, 0.05, two_sided,
                                             n_sims=100_000, seed=2027)
        power_norm = mcnemar_power_normal(n_req, p10, p01, 0.05, two_sided)
        print(f"\n  {label} (n={n_req}):")
        print(f"    Normal approx: {power_norm:.4f}")
        print(f"    Monte Carlo:   {power_mc:.4f} ± {se_mc:.4f}")

    print(f"\n{'='*70}")
    print("MDE Verification")
    print(f"{'='*70}")
    n_80 = find_required_n_normal(p10, p01, 0.80, 0.05, True)
    mde = compute_mde(n_80, p10, p01, 0.05, True, 0.80)
    print(f"\n  At n={n_80} (80% two-sided):")
    print(f"    MDE (ΔEM) = {mde:.4f}")
    print(f"    Exploratory ΔEM = {p10-p01:.4f}")

    power_at_1105 = mcnemar_power_normal(1105, p10, p01, 0.05, True)
    print(f"\n  Verification: power at n=1105 with exploratory rates:")
    print(f"    Power = {power_at_1105:.4f}")

    # Also verify MC at 1105
    power_mc_1105, se_mc_1105 = monte_carlo_power(1105, p10, p01, 0.05, True,
                                                    n_sims=100_000, seed=2027)
    print(f"    MC power = {power_mc_1105:.4f} ± {se_mc_1105:.4f}")
