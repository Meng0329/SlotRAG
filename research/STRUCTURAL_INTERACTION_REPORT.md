# STRUCTURAL_INTERACTION_REPORT.md — Phase 5 Results

## 1. Interaction Tests

### 1.1 Dataset-Stratified Paired Permutation (10k perms)

Test: chain-static Delta EM in deep regime (hops>=2) vs shallow (hops<2)

Dataset | Deep n | Deep Delta EM | Shallow n | Shallow Delta EM | Observed diff | Permutation p
hotpotqa | 260 | +0.142 | 2601 | -0.013 | +0.155 | 0.000
2wikimultihop | 229 | -0.031 | 4701 | -0.040 | +0.009 | 0.398
musique | 58 | +0.052 | 784 | -0.001 | +0.053 | 0.007
pooled | 547 | +0.060 | 8086 | -0.027 | +0.088 | 0.000

### 1.2 Topology Interaction (chain vs non-chain)

Dataset | Chain n | Chain Delta EM | Non-chain n | Non-chain Delta EM | diff | p
hotpotqa | 747 | -0.030 | 2114 | +0.012 | -0.042 | 1.000
2wikimultihop | 1941 | -0.023 | 2989 | -0.050 | +0.027 | 0.007
musique | 154 | +0.026 | 688 | -0.003 | +0.029 | 0.010
pooled | 2842 | -0.022 | 5791 | -0.022 | -0.001 | 0.548

### 1.3 Clustered OLS Regression

Model: chain_minus_static_em ~ 1 + structural_hops + is_chain_topology
Clustered by dataset (3 clusters), HC1 robust SE.

Variable | Coefficient | SE | z | p (approx)
intercept | -0.026 | 0.018 | -1.44 | 0.150
structural_hops | +0.077 | 0.044 | 1.73 | 0.084
is_chain_topology | -0.092 | 0.075 | -1.22 | 0.222

R-squared = 0.015

## 2. Interpretation

The depth interaction is:
- Statistically significant in permutation tests (p=0.000 pooled)
- Positive and directionally consistent across HotpotQA and MuSiQue
- NOT significant in regression (p=0.084) due to limited cluster count (3 datasets)
- NOT significant for 2Wiki individually (p=0.398)

The topology interaction is:
- Significant for 2Wiki (p=0.007) and MuSiQue (p=0.010)
- NOT significant pooled (p=0.548) — effects cancel across datasets

The regression R-squared=0.015 indicates that structural_hops explains very little variance in chain-static Delta EM. The practical effect is real but small: ~0.08 EM improvement per additional hop in the deep regime.
