# H-STRUCT-4 FINAL REPORT — INDEPENDENT SHALLOW-GATE CONFIRMATION

> **Date**: 2026-09-07
> **Status**: BLOCKED — INFEASIBLE (zero frozen shallow plan snapshots)
> **Pre-Outcome Commit SHA**: e64ab9d6e978a3b41b88a2d38a0dca1cc47da22d
> **Regime**: Pre-execution freeze + exposure audit + power analysis. **No answers were generated.**
> **Verdict**: Execution CANNOT proceed under §5 constraints. All deliverables below are the honest pre-execution record.

---

## 1. What Could Not Be Done

The independent shallow-gate confirmation (H-STRUCT-4A) requires:
1. Two-sided exact McNemar on paired static/flat EM for census-shallow (structural_hops < 2) questions.
2. Execution under matched-budget B=8 with arms slotrag-g7-static and slotrag-g7-flat, qwen3.5-9b.
3. SLotCompiler calls = 0 (frozen plans only).

**This could not be executed because zero (0) census-shallow questions have full frozen SlotPlan snapshots.**

---

## 2. Why (Root Cause)

- The V1.2 validation census persists `structural_hops`, `plan_hash`, and `eligible` for all 6,494 questions, but **only stores full `plan_json` for the 361 census-deep eligible questions**.
- The 6,133 shallow questions (hops: 0=5,490, 1=566, -1=77) have **no frozen plan_json anywhere** — only a `plan_hash` string reference (non-reversible; no SlotPlan dict).
- The 77 v12-manifest "shallow" plans are **re-compilations of census-deep questions** (all hash_match=False) and 76/77 were already executed in H-STRUCT-1/2. They cannot serve as census-shallow candidates (que floor: §3 requires census structural_hops < 2 + frozen + unexposed).

**Consequence**: §5's rule ("if frozen snapshot missing → question cannot enter primary pool; re-compilation prohibited") makes the primary pool empty. There is no reserve pool either — no pre-frozen shallow plan snapshot exists anywhere in the repository.

---

## 3. Exposure Audit (Complete)

Full 6,494-row overlap census × v12-frozen × confirmatory-execution ccsv: `research/hstruct4/exposure_audit.csv`

| exclusion_reason | count |
|-----------------|-------|
| no_frozen_plan_snapshot | 6,133 |
| deep_hops_not_shallow | 361 |
| **total** | **6,494** |

Primary candidates: **0**. This is exhaustive over the V1.2 census population (no single question can enter the primary pool).

---

## 4. Power Analysis (Completed, Moot)

Exploratory shallow discordants (H-STRUCT-3, n=8,085): b=261, c=431, p10=0.0323, p01=0.0533, discordant rate=8.56%.

| Target | Required N |
|--------|-----------|
| 80% two-sided | 1,428 |
| 90% two-sided | 1,912 |

Census shallow pool = 6,133 (sufficient). The blocker is infrastructure, not statistical power.

---

## 5. Honest Options Considered (All Rejected)

| Option | Why rejected |
|--------|-------------|
| Re-compile 6,133 shallow plans to create fresh frozen snapshots | Violates §5 (SlotCompiler calls must be 0) and the pre-registration freeze |
| Use the 77 v12-shallow plans as "frozen shallow" | 77/77 are census-DEEP re-compiles (hash mismatch); 76/77 already exposed; 0 overlap with census-shallow population |
| Execute a fresh sample without frozen plans | Violates the matched-budget protocol (unfrozen plans = different experiment) |
| Fabricate scores / fake manifests | Unacceptable; violates the honesty contract of the research program |

---

## 6. What This Means for the Research Program

- **H-STRUCT-4 verdict: NOT EXECUTABLE. No CASES (A/B/C) applied.** The shallow-gate confirmation cannot be run against V1.2 frozen data.
- The structural claim (H-STRUCT-3, GATE NECESSARY) stands on its exploratory evidence (shallow flat ΔEM −0.0210, CI [−0.0273, −0.0146], p<0.001 — n=8,085). It is **not** independently confirmed at confirmatory level by H-STRUCT-4.
- The infeasibility is itself a finding: the V1.2 census snapshot infrastructure did not persist plans for non-eligible questions, so any future confirmatory check of the shallow domain requires a fresh census-and-freeze phase (a protocol-level infrastructure gap, recorded in DECISIONS.md).

---

## 7. Protocol-identity guarantees honored

- Policy A′ untouched, structural_hops definition untouched, no threshold search, no learned router, no new optimizer, no static/flat modification, no deep re-run, no exploratory-driven adjustment.
- SlotCompiler calls: **0** (zero plan compilation during this audit).
- Model/arms/budget: no live services contacted.

---

## 8. File Record

| File | Content |
|------|---------|
| `H_STRUCT_4_PRE_REGISTRATION.md` | Full spec, estimand, feasibility block documented at pre-registration time |
| `H_STRUCT_4_POWER.md` | Power analysis (1,428 @80% / 1,912 @90%) |
| `H_STRUCT_4_EXPOSURE_AUDIT.md` | Root cause + candidate pool size 0 |
| `H_STRUCT_4_PROTOCOL_IDENTITY_AUDIT.md` | Identity + exposure verification |
| `hstruct4/exposure_audit.csv` | 6,494-row overlap table |
| (primary/reserve manifests) | **Empty — N/A** (no eligible candidates) |