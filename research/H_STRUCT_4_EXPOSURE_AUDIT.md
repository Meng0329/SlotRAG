# H-STRUCT-4 EXPOSURE AUDIT REPORT

> **Date**: 2026-09-07
> **Pre-Outcome Commit SHA**: e64ab9d6e978a3b41b88a2d38a0dca1cc47da22d
> **Status**: BLOCKED — Zero unexposed shallow candidates with full frozen plan snapshots
> **RQ**: Under matched-budget B=8 protocol, does applying the global budget-aware flat optimizer to shallow compiled plans reduce answer quality relative to static physical execution?

---

## 1. Source Data

| Source | Rows | Description |
|--------|------|-------------|
| V1.2 validation census (`validation_structural_census.csv`) | 6,494 | All validation questions; census_plan_hash, structural_hops, eligible |
| V1.2 frozen plan manifest (`validation_plan_manifest_v12.jsonl`) | 361 | Full SlotPlan plan_json for census-deep eligible questions only |
| Frozen snapshot store (`hstruct_frozen_validation/`) | 361 | 361 JSON files, schema_version=1, plan_sha256 |
| Confirmatory results (`validation_confirmatory_results.csv`) | 700 | static 350 + chain 350 |
| H-STRUCT-2 flat results (`hstruct2_flat_results.csv`) | 350 | flat arm |
| H-STRUCT-1 train results (`validation_confirmatory_results.csv` train split) | 742 | static 742 + chain 742 |

---

## 2. Census Shallow Pool

Questions with `structural_hops < 2`:

| hops | count |
|------|-------|
| 0 | 5,490 |
| 1 | 566 |
| -1 | 77 |
| **total** | **6,133** |

None of these 6,133 questions have full frozen plan snapshots anywhere in the repository. The census stored only `plan_hash` (string reference) for these questions, not the full SlotPlan JSON.

---

## 3. V12 Frozen Shallow Plans (All False Positives)

The V12 manifest contains 77 rows with `structural_hops < 2`. These are **not** census-shallow questions:

- **Census classification**: all 77 have `census_hops >= 2` (census-deep)
- **hash_match**: all 77 have `hash_match = False` (plan re-compiled after census, producing different hash and different hops)
- **Exposure**: 76/77 already executed in H-STRUCT-1/2 confirmatory runs

These re-compiled plans cannot serve as census-shallow candidates per §3 ("must use V1.2 frozen census structural_hops<2").

---

## 4. Primary Candidate Pool Size: **0**

```
census_shallow (h<2): 6,133
  ├── no frozen plan snapshot: 6,133
  └── with frozen plan snapshot: 0

overlap(census_shallow, v12_frozen): 0

execution eligibility:
  primary candidates: 0
  exclusion: all 6,133 lack frozen SlotPlan plan_json
```

---

## 5. §5 Constraint (Prohibiting Workaround)

Per spec §5: "如果 frozen snapshot: missing / corrupt / hash mismatch → 该题不可进入 primary pool。使用下一个预先冻结的 reserve candidate。禁止重新编译该题来修复。"

Reserve candidates also require pre-frozen plans. No reserve pool of frozen shallow plans exists anywhere in the repository.

**Workaround prohibition**: SlotCompiler calls must equal 0 (no re-compilation allowed). Therefore the 6,133 shallow questions cannot acquire frozen plans without violating this constraint.

---

## 6. Exposure Audit (Complete Census × Execution × V12 Overlap)

| exclusion_reason | count |
|-----------------|-------|
| no_frozen_plan_snapshot | 6,133 |
| deep_hops_not_shallow | 361 |
| **total** | **6,494** |

Full per-question audit: `research/hstruct4/exposure_audit.csv` (6,494 rows, all fields).

- **Execution**: INFEASIBLE under §5 constraints. Primary manifest cannot be built.
- **Reserve pool**: Also empty (no pre-frozen shallow plans exist).
- **Power analysis**: Completed (see `H_STRUCT_4_POWER.md`) using exploratory rates from H-STRUCT-3 (p10=261/8085, p01=431/8085). Required N: 1,428 @80%, 1,912 @90% (two-sided). The validation census contains 6,133 shallow questions — sufficient in count, but no frozen plan snapshots exist for execution.
- **Root cause**: The V1.2 census persisted only plan_hash (not plan_json) for questions classified as non-eligible (hops<2). Only the 361 eligible (hops>=2) questions received full plan snapshots.
