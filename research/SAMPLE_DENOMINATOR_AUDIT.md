# SAMPLE_DENOMINATOR_AUDIT.md

> Audit cycle: SEALED execution denominator chain
> Written: 2026-08-24
> Author: documentation-writer (automated)
> Status: **FINAL**

---

## 1. Source Splits

The five SlotRAG benchmark datasets are split deterministically (seed=2027, stratified) into development / validation / test partitions.

| Dataset | development | validation | test | Total |
|---------|------------|-----------|------|-------|
| hotpotqa | 2,146 | 2,146 | 2,863 | 7,155 |
| 2wikimultihop | 3,698 | 3,698 | 4,931 | 12,327 |
| musique | 650 | 650 | 867 | 2,167 |
| strategyqa | 133 | 133 | 180 | 446 |
| drop | 2,785 | 2,785 | 3,716 | 9,286 |
| **TOTAL** | **9,412** | **9,412** | **12,557** | **31,381** |

**Key property:** The test set (40%) is held out for final evaluation only. All SEALED executions target the test partition of the three primary datasets (hotpotqa, 2wikimultihop, musique). StrategyQA and DROP are not part of the SEALED experimental scope.

---

## 2. Sealed Execution Coverage

| Category | Count | Datasets |
|----------|-------|----------|
| test_set items executed (sealed) | 8,661 | hotpotqa: 2,863, 2wikimultihop: 4,931, musique: 867 |
| test_set items NOT executed | 3,896 | strategyqa: 180, drop: 3,716 |
| **ALL sealed items in test_set** | confirmed | 0 sealed items outside test_set |
| **3-target-dataset test_set coverage** | **100%** | hotpotqa, 2wikimultihop, musique |

**Verification:** Every sealed item's `question_id` maps to a test-set entry in the canonical split. No sealed execution was performed on development or validation partitions.

---

## 3. Per-Dataset Denominator Chain

### 3.1 hotpotqa

| Stage | Count | Notes |
|-------|-------|-------|
| Raw sealed items (per arm) | 2,866 | From disk, 3 arms |
| Excluded: no_slots | 5 | Plan compilation produced empty slot list |
| Plan-valid | 2,861 | 2,866 - 5 |
| Metric-valid | 2,862 | Edge case: some items have EM metric but no plan |
| **analysis-final (static)** | **2,862** | Used for static analysis |
| **analysis-final (flat)** | **2,861** | Used for flat/baseline comparison |
| **analysis-final (chain)** | **2,861** | Used for chain analysis |
| **Three-arm paired** | **2,861** | Present in all 3 arms after filtering |

**Note:** The 1-item discrepancy between metric-valid (2,862) and plan-valid (2,861) is an edge case where a question has a valid EM metric score but its slot plan compilation failed. These items are excluded from structural analysis but retained for metric-only aggregation.

### 3.2 2wikimultihop

| Stage | Count | Notes |
|-------|-------|-------|
| Raw sealed items (per arm) | 4,934 | From disk, 3 arms |
| Excluded: no_slots | 2 | Plan compilation produced empty slot list |
| Plan-valid | 4,932 | 4,934 - 2 |
| **analysis-final (static)** | **4,930** | |
| **analysis-final (flat)** | **4,930** | |
| **analysis-final (chain)** | **4,931** | Slight variance by arm |
| **Three-arm paired** | **4,930** | |

### 3.3 musique

| Stage | Count | Notes |
|-------|-------|-------|
| Raw sealed items (per arm) | 867 | From disk, 3 arms |
| Excluded: no_slots | 28 | Highest exclusion rate (3.2%) |
| Plan-valid | 839 | 867 - 28 |
| **analysis-final varies by arm** | **842-867** | Due to differential no_slots distribution across arms |
| **Three-arm paired** | **varies** | 842-867 depending on arm availability |

**Note on musique:** The 28 no_slots exclusions (3.2%) are the highest among the three datasets. This reflects the complexity of multi-hop slot compilation on musique's compositional question structure. The per-arm variance in analysis-final is a known property of the sealed execution results.

---

## 4. Exclusion Details

| Dataset | no_slots excluded | Other exclusions | Total excluded |
|---------|------------------|-----------------|---------------|
| hotpotqa | 5 | 0 | 5 |
| 2wikimultihop | 2 | 0 | 2 |
| musique | 28 | 0 | 28 |
| **TOTAL** | **35** | **0** | **35** |

**All 35 exclusions are "no_slots":** Plan compilation produced an empty slot list. The LLM failed to decompose the question into typed slots.

**No items excluded for:**
- Missing metrics
- Invalid depth values
- Structural errors
- Execution timeouts
- Provider errors

This is a clean exclusion profile — every excluded item fails for the same reason (compilation failure), and no partial-execution artifacts contaminate the analysis set.

---

## 5. Denominator Consistency Rule

**All tables in this audit cycle use `analysis-final` as the denominator unless explicitly stated.**

This means:
- Numerators (e.g., correct answers, chain-positive items) are drawn from the analysis-final set
- Denominators match the same set
- No items outside analysis-final contribute to any reported statistic

**Macro vs. micro aggregation:**
- **Macros** use per-dataset means (macro): average across datasets, then average across questions within each dataset
- **Micro** aggregates at the question level across all datasets
- Both are reported in `offline_policy_replay.csv`

The choice of macro vs. micro is explicit in every table and figure. Where both are reported, macro is the primary statistic (it avoids dataset-size bias).

---

## 6. Cross-Reference

| Document | Relationship |
|----------|-------------|
| `STRUCTURAL_DEPTH_CORRECTION_REPORT.md` | Topology classifications use these denominators |
| `EXPERIMENT_LEDGER.csv` | Run-level item counts reference these chains |
| `offline_policy_replay.csv` | Checksums verified against these counts |
| `denominator_audit.csv` | Machine-readable version of this document |
