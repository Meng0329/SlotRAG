# HSTRUCT_INVALIDATED_ARTIFACTS.md — Invalidation Registry

> **Created:** 2026-09-01 (H-STRUCT-1 Frozen-Plan Semantics Repair)
> **Reason:** All previous train/ validation extraction artifacts used incorrect compile path
> **Invalidation scope:** Any artifact relying on bare `SlotCompiler.compile()` or `MinimalQR`

---

## Invalidation Rule

Any artifact produced by `SlotCompiler.compile(question.question)` (without `slotrag_compile_options`)
or using `MinimalQR` (missing passages/metadata) is **INVALID** for confirmatory use.

The frozen protocol requires `compile_slotrag_plan(METHODS["slotrag"], dataset, full_question_record, agnes_client)`.

---

## Invalidated Artifacts

| Artifact | Invalidated | Commit SHA | Timestamp | Reason |
|---|---|---|---|---|
| `research/hstruct_validation_census/validation_plan_manifest_with_plans.jsonl` | **YES** | `551dbd6` | 2026-09-01T18:27 | Compiled with bare `SlotCompiler.compile()` (missing `slotrag_compile_options`). 71/361 plans structurally diverge from census. All records lack `compiler_options`. |
| `research/hstruct_confirmatory/train_compile_census.csv` | **YES** | `551dbd6` | 2026-09-01 (3323 rows, 106 eligible) | Produced by `train_compile_census.py` using `MinimalQR` (passages=[], no metadata). Not comparable to real runner QuestionRecords. |
| `research/hstruct_confirmatory/train_eligible_manifest.jsonl` | **YES** | `551dbd6` | 2026-09-01 (26 rows) | Derived from INVALID train_compile_census. Contains plans compiled with wrong QuestionRecord. |
| `research/hstruct_confirmatory/train_supplement_draw.jsonl` | **YES** | `551dbd6` | 2026-09-01 | Question ID pool is valid, but downstream census used MinimalQR. Pool may be reused if re-filtered with full records. |

---

## Preserved (NOT Invalidated)

| Artifact | Status | Reason |
|---|---|---|
| `research/hstruct_validation_census/validation_structural_census.csv` | **VALID** (V1.1 census) | Produced by `validation_compile_census.py` which correctly used `compile_slotrag_plan(SPEC, ...)`. Census eligibility is authoritative. |
| `research/H_STRUCT_1_PRE_REGISTRATION_V1_1.md` | **VALID** | Pre-registration document. Plan-freezing infrastructure may be superseded to V1.2, but policy/hypotheses unchanged. |

---

## Readiness Impact

- G4 (eligible >= 1105): **FAIL** (440 combined, train invalidated)
- G5 (manifest SHA256 frozen): **FAIL** (validation manifest invalidated)
- All downstream scoring/analysis: **BLOCKED** until artifacts are regenerated with correct compile path

---

## Notes

- The validation census (`validation_structural_census.csv`) remains the canonical eligibility source.
- Re-extraction must use `compile_slotrag_plan(SPEC, dataset, full_question_record, agnes_client)`.
- Train census must be restarted from scratch with full QuestionRecords.
