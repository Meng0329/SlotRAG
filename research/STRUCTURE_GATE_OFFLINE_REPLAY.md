# STRUCTURE_GATE_OFFLINE_REPLAY.md — Phase 6-8 Results

## 1. Policy Definitions

P0 (static): Always use static arm.
P1 (flat): Always use flat arm.
P2 (chain): Always use chain arm.
A (depth_only): chain if structural_hops >= 2, else static.
B (depth_x_topo): chain if structural_hops >= 2 AND topology=="chain", else static.
C (depth_x_topo_tree): chain if structural_hops >= 2 AND topology in {chain,tree}, else static. [exploratory]

Threshold tau=2 (structural_hops) corresponds to plans with 3+ nodes.

## 2. Macro EM Comparison

Policy | Macro EM | Micro EM | LLM calls | Budget-ex rate | n
P0_static | 0.4434 | 0.5012 | 27.0 | 4.4% | 8634
P1_flat | 0.4364 | 0.4850 | 21.8 | 3.3% | 8655
P2_chain | 0.4317 | 0.4789 | 23.0 | 3.8% | 8659
A_depth_only | 0.4483 | 0.5049 | 24.8 | 3.5% | 8635
B_depth_x_topo | 0.4443 | 0.5010 | 26.3 | 4.0% | 8635
C_depth_x_topo_tree | 0.4483 | 0.5049 | 24.9 | 3.5% | 8635

## 3. Per-Dataset Comparison (Candidate B vs static)

Dataset | B EM | Static EM | Delta | B LLM | Static LLM
hotpotqa | 0.5419 | 0.5409 | +0.001 | 27.4 | 25.3
2wikimultihop | 0.5158 | 0.5172 | -0.001 | 36.5 | 37.0
musique | 0.2752 | 0.2720 | +0.003 | 15.2 | 18.7

## 4. Leave-One-Stratum-Out (exclude HotpotQA structural_hops>=4)

Policy | Macro EM (LOSA) | Macro EM (full) | Delta
P0_static | 0.4454 | 0.4434 | +0.002
P2_chain | 0.4311 | 0.4317 | -0.001
A_depth_only | 0.4478 | 0.4483 | -0.001
B_depth_x_topo | 0.4460 | 0.4443 | +0.002

Effect PRESERVED after exclusion. Not fragile.

## 5. GO Gate Assessment

GO-1 (no quality regression vs static):
B macro EM=0.4443 vs static=0.4434 -> +0.001 -> PASS (marginal)

GO-2 (reduce shallow/star harm):
Chain harm on 2Wiki: static=0.5172, chain=0.4780 -> damage=-0.039
B on 2Wiki: 0.5158 -> damage=-0.001 -> PASS (97% harm eliminated)

GO-3 (match strongest fixed policy):
Strongest fixed = P0_static (macro EM=0.4434)
B macro EM=0.4443 -> quality parity + LLM reduction (26.3 vs 27.0, -2.6%) -> PASS

GO-4 (not driven by Hotpot depth>=4 only):
LOSA macro EM=0.4460 vs static=0.4454 -> +0.0006 -> PASS (effect survives, reduced but positive)

VERDICT: **CONDITIONAL GO** — all 4 gates passed, but effect sizes are small (<=0.5pt).
Candidate A preferred over B (simpler rule, same or better EM).
