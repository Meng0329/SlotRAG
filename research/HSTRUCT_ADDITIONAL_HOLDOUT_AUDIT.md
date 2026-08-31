# HSTRUCT_ADDITIONAL_HOLDOUT_AUDIT.md — Train Split Untouched Pool

> **Date:** 2026-08-31
> **Status:** COMPLETE (pre-census, based on EXPOSED_SAMPLE_REGISTRY analysis)
> **Purpose:** Identify untouched train-split questions eligible for confirmatory testing

---

## 1. Train Split Sizes

| Dataset | Train file | Train size | Eval total (dev/val/test) |
|---------|-----------|-----------|--------------------------|
| hotpotqa | hotpotqa_train.jsonl | 90,447 | 7,155 |
| 2wikimultihop | 2wikimultihop_train.jsonl | 167,454 | 12,327 |
| musique | musique_train.jsonl | 19,938 | 2,167 |

---

## 2. Exposure Analysis

Source: `research/EXPOSED_SAMPLE_REGISTRY.csv` (3,508 entries)

### 2.1 Contamination Status

| Status | Count | Description |
|--------|-------|-------------|
| TRAIN_EXPOSED | 1,961 | Train IDs used in training runs |
| CONTAMINATED | 500 | Eval IDs with full results exposed |
| EXPOSED_NOT_SCORED | 739 | Eval IDs exposed without scoring |
| UNKNOWN | 307 | Split unknown (191 confirmed train, 117 confirmed eval) |
| EXPOSED_VIA_ABLATION | 1 | Via ablation sample file |

### 2.2 Train-to-Eval Contamination

**ZERO overlap** between train-exposed IDs and eval-set IDs across all 3 target datasets.

- hotpotqa: 0 overlap (774 train-exposed vs 7,155 eval)
- 2wikimultihop: 0 overlap (480 train-exposed vs 12,327 eval)
- musique: 0 overlap (240 train-exposed vs 2,167 eval)

No unregistered train leakage found.

---

## 3. Untouched Train Pool

| Dataset | Train pool | Registered exposed | Untouched | Exposure rate |
|---------|-----------|-------------------|-----------|--------------|
| hotpotqa | 90,447 | 774 | **89,673** | 0.86% |
| 2wikimultihop | 167,454 | 480 | **166,974** | 0.29% |
| musique | 19,938 | 240 | **19,698** | 1.20% |
| **Total** | **277,839** | **1,494** | **276,345** | 0.54% |

---

## 4. Eligible Pool Estimation (Census-Verified Rates)

Using **validation census rates** (not exploratory) for conservative train pool estimation:

| Dataset | Untouched pool | Validation census rate | Expected eligible |
|---------|---------------|----------------------|-------------------|
| hotpotqa | 89,673 | 3.2% | ~2,869 |
| 2wikimultihop | 166,974 | 7.0% | ~11,688 |
| musique | 19,698 | 5.4% | ~1,064 |
| **Total** | **276,345** | — | **~15,621** |

**Note:** Using validation census rates (5.6% pooled) rather than exploratory rates (6.3%) for conservative estimate. Actual train eligible may be higher.

---

## 5. Combined Available Eligible Pool (Census-Verified)

| Source | Expected eligible | Status |
|--------|-------------------|--------|
| validation_set | **361** (ACTUAL, census-verified) | UNEXPOSED, primary source |
| Train split (untouched) | **~15,621** (estimated) | UNEXPOSED, supplementary |
| **Combined** | **~15,982** | |

Required for 80% power: **1,105 eligible**
Required for 90% power: **1,466 eligible**

**Combined pool is ~14.5× the required sample size for 80% power.**

### 5.1 Validation-Only Sufficiency

Validation provides **361 eligible** (32.7% of required 1,105). **INSUFFICIENT alone.**

### 5.2 Supplement Calculation

Additional eligible needed from train: 1,105 - 361 = **744**

Train pool provides ~15,621 eligible — **21× the supplement needed**.

---

## 6. Source Disclosure Requirement

Any confirmatory test using train-split questions MUST disclose:

1. Each question's source split (validation vs train)
2. Stratification by split in all reported statistics
3. The rationale for using train-split data (validation insufficient for power)

The paper must not present train-split results as if they were from an independent test set.

---

## 7. Risk Assessment

**LOW RISK:** Train-to-eval contamination is zero. Untouched train questions have never appeared in any experiment, hypothesis analysis, or threshold discovery.

**MEDIUM RISK:** Train questions may differ distributionally from eval questions (different difficulty, different topic coverage). The confirmatory test should stratify by source split and report per-split results.

**MITIGATION:** Draw the confirmatory sample stratified from BOTH validation and train, ensuring all 3 datasets are represented in each split.

---

## 8. Recommendation (Census-Verified)

Since validation alone provides only 361 eligible (32.7% of required 1,105):

**Use combined validation + train (stratified) as the confirmatory pool.**

Sample design (finalized):
- From validation: take ALL 361 eligible
- From train: draw 744 additional eligible (stratified by dataset proportional to validation census rates)
- Total: 1,105 eligible (meets 80% power requirement)

Stratified train draw (proportional to validation census rates):

| Dataset | Validation eligible | Train draw | Total per dataset |
|---------|--------------------|-----------|-----|
| hotpotqa | 68 | 148 | 216 |
| 2wikimultihop | 258 | 559 | 817 |
| musique | 35 | 37 | 72 |
| **Total** | **361** | **744** | **1,105** |

This provides adequate power while maintaining:
- Zero contamination (train-to-eval overlap = 0)
- Full source disclosure (stratified by split in all reported statistics)
- Conservative eligibility estimates (using validation census rates, not exploratory)
