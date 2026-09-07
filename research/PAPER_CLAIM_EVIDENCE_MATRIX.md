# PAPER_CLAIM_EVIDENCE_MATRIX.md — Claim-Evidence Traceability for TKDE Paper v4

> **Date**: 2026-09-07
> **Purpose**: Per spec §30, every empirical claim in the paper maps to a raw artifact, script, and test

---

## Claim-Evidence Matrix

| # | Paper Section | Claim | Evidence Level | Raw Artifact | Script/Method | Statistical Test |
|---|---------------|-------|----------------|--------------|---------------|------------------|
| 1 | §1 (intro) | 3-slot plan 4+4+4=12 > B=8 is infeasible | Illustrative | N/A (worked example) | N/A | N/A |
| 2 | §3.2 | structural_hops is deterministic given plan structure | Structural | SlotPlan frozen snapshots | slotrag data normalize | Code inspection + census verification |
| 3 | §3.2 | join_edges = (p,h)·k for k-slot join | Structural | SlotPlan frozen snapshots | slotrag data normalize | Code inspection |
| 4 | §5.1 | Σa_s^static > B ⟹ ∃s truncated | Theoretical | N/A (proof by construction) | N/A | N/A |
| 5 | §5.2 | Σa_i ≤ B is necessary but not sufficient for no BE | Empirical-CONFIRMATORY | hstruct1_corrected_statistics.csv (TP=146/FP=128/FN=0/TN=76) | Extract validation plans + run confirmatory | Confusion matrix; precision=0.533, recall=1.0 |
| 6 | §7.2 | Flat improves EM by 0.0771 over static on deep plans | Empirical-CONFIRMATORY | hstruct2_three_arm_comparison.csv + validation_confirmatory_results.csv | run confirmatory (frozen matched-budget) | Exact McNemar p=1.4e-6, 95% CI [+0.049,+0.109], discordant pairs b=30/c=3 |
| 7 | §7.2 | Flat eliminates 146 budget-exhaustion events | Empirical-CONFIRMATORY | validation_confirmatory_results.csv | run confirmatory | Direct count: static BE=146, flat BE=0 |
| 8 | §7.3 | Chain vs flat ΔEM=+0.0086, p=0.743 (not significant) | Empirical-CONFIRMATORY | hstruct2_three_arm_comparison.csv | run confirmatory | Exact McNemar p=0.743, 95% CI [-0.026,+0.043] |
| 9 | §7.4 | Flat reduces EM by 0.0210 on shallow plans (exploratory) | Empirical-EXPLORATORY | Three-arm trace 8632 paired questions | Historical trace replay | Paired bootstrap |
| 10 | §7.4 | A' improves EM by 0.0197 over always-flat | Empirical-EXPLORATORY | Three-arm trace 8632 paired questions | Historical trace replay | Paired bootstrap p<0.001 |
| 11 | §7.5 | ATE_pop(A') = +0.00416 EM/question | Derived | Census: 361/6494 eligible | Population weighting | ATE = P(eligible) × ATE_exec |
| 12 | §7.5 | 361 eligible out of 6494 total (5.39%) | Empirical-CONFIRMATORY | V1.2 census (hstruct1_corrected_statistics.csv) | slotrag data normalize census | Direct count |
| 13 | §8 | H-STRUCT-4 could not be executed (V1.2 census lacks shallow payloads) | Negative | hstruct4/pool_status.json, census manifest | Audit only, no execution | Zero models contacted, zero answers generated |
| 14 | §8 | Gate threshold hops≥2 is deterministic, non-parametric | Structural | dispatch.py, gate code | Code inspection | Deterministic: same plan → same decision |
| 15 | §8 | Single generator: qwen3.5-9b | Protocol | configs/experiments/*.yaml | Run manifests | Environment documentation |
| 16 | §8 | Natural prevalence of deep plans: ~5.4% | Empirical | V1.2 census | Census | Direct ratio |

---

## Evidence Levels (per spec §17)

- **CONFIRMATORY**: H-STRUCT-1 (census), H-STRUCT-2 (350×2 frozen matched-budget). n≥350 per arm. Independent of historical traces.
- **EXPLORATORY**: H-STRUCT-3 (8632 historical trace replay). Not independent of historical data.
- **INFEASIBLE**: H-STRUCT-4 (pre-registered shallow confirmation). Zero execution — census infrastructure gap.

## Scripts Involved

| Script | Purpose | Status |
|--------|---------|--------|
| `tools/extract_validation_plans.py` | Frozen plan extraction from V1.2 census | Active, committed |
| `tools/run_confirmatory.py` | Frozen matched-budget execution | Active, committed |
| `tools/analyze_hstruct_confirmatory.py` | Statistical analysis of confirmatory results | Active, committed |
| `tools/train_compile_census.py` | Census enumeration + deep/shallow split | Active, committed |
