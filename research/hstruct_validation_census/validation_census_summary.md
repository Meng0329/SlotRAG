# validation_census_summary.md — Phase 5 Outcome-Blind Census

> **Generated:** 2026-08-31
> **FIREWALL:** No retrieval, no answer generation, no EM/F1, no gold-answer inspection.
> **Compiler:** Same frozen SlotCompiler + static-arm MethodSpec used in sealed experiments.

## Per-Dataset Structural Distribution

### hotpotqa
- Total: 2146
- Compile failed: 35
- Eligible (hops ≥ 2): 68 (3.2%)

| structural_hops | count | eligible |
|---|---|---|
| -1 | 35 | no |
| 0 | 1717 | no |
| 1 | 326 | no |
| 2 | 39 | yes |
| 3 | 21 | yes |
| 4 | 6 | yes |
| 6 | 1 | yes |
| 8 | 1 | yes |

| topology | count |
|---|---|
| single | 1717 |
| chain | 356 |
| complex | 38 |
| compile_failed | 35 |

### 2wikimultihop
- Total: 3698
- Compile failed: 32
- Eligible (hops ≥ 2): 258 (7.0%)

| structural_hops | count | eligible |
|---|---|---|
| -1 | 32 | no |
| 0 | 3248 | no |
| 1 | 160 | no |
| 2 | 109 | yes |
| 3 | 146 | yes |
| 4 | 3 | yes |

| topology | count |
|---|---|
| single | 3248 |
| chain | 375 |
| complex | 43 |
| compile_failed | 32 |

### musique
- Total: 650
- Compile failed: 10
- Eligible (hops ≥ 2): 35 (5.4%)

| structural_hops | count | eligible |
|---|---|---|
| -1 | 10 | no |
| 0 | 525 | no |
| 1 | 80 | no |
| 2 | 17 | yes |
| 3 | 14 | yes |
| 4 | 3 | yes |
| 5 | 1 | yes |

| topology | count |
|---|---|
| single | 525 |
| chain | 102 |
| complex | 13 |
| compile_failed | 10 |

## Overall

- Total questions: 6494
- Compile failed: 77
- Eligible (hops ≥ 2): 361 (5.6%)
- Compilation time: 12080.4s (1.86s/question)

## Power Comparison

- Required eligible n (80% power, two-sided): 1,105
- Available eligible (validation only): 361
- Gap: 744 (validation INSUFFICIENT)

## Firewall Audit

- [ ] No retrieval calls made
- [ ] No answer generation calls made
- [ ] No EM/F1 scores computed
- [ ] No gold answers inspected
- [ ] No policy comparison performed
- [ ] Census output contains only structural properties + plan_hash
