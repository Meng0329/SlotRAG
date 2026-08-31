# HDEPTH_CONFIRMATORY_EXPOSURE_AUDIT.md

## 1. Exposure Assessment

### 1.1 Test Set Exposure (hotpotqa, 2wikimultihop, musique)

ALL 8,661 sealed execution items are drawn from test_set.
For the 3 target datasets, test_set coverage is 100%:
- hotpotqa: 2863/2863 test items executed
- 2wikimultihop: 4931/4931 test items executed
- musique: 867/867 test items executed

CONCLUSION: test_set for these 3 datasets is FULLY EXPOSED.
It was used for:
- Threshold discovery (tau=2 from structural_hops interaction)
- Policy selection (Candidate A/B/C selected by offline replay)
- Failure analysis (2Wiki star topology insight)
- Hypothesis generation (H-STRUCT-1)

The test_set CANNOT serve as independent confirmatory data.

### 1.2 Validation Set Exposure

validation_set has NOT been executed by the sealed pipeline:
- hotpotqa: 2146 items (unexecuted)
- 2wikimultihop: 3698 items (unexecuted)
- musique: 650 items (unexecuted)

These items have NEVER been:
- Used for threshold discovery
- Used for policy selection
- Used for prompt tuning
- Used for method tuning
- Used for failure-driven redesign

CONCLUSION: validation_set is UNEXPOSED and available as independent holdout.

### 1.3 Development Set Exposure

development_set was used for early-stage method development and should NOT be used for confirmatory testing.

### 1.4 Unexecuted Test Items

3,896 test items were not executed:
- strategyqa: 180 (not part of this analysis)
- drop: 3716 (not part of this analysis)

These are independent but from different datasets, not suitable for confirming the depth interaction on the original 3 datasets.

## 2. Independent Holdout Design

Since test_set is fully exposed, the confirmatory test must use validation_set.

### 2.1 Proposed Holdout

Draw a stratified random sample from validation_set:
- hotpotqa: n=200 (from 2146 available)
- 2wikimultihop: n=200 (from 3698 available)
- musique: n=200 (from 650 available)
- Total: n=600

Stratification: by question complexity (if available) or uniform random.

### 2.2 Why Not Use All validation_set?

Budget constraint: 600 items x 3 arms = 1800 executions.
At ~56s/question serial, ~8h with parallel=8.
Full validation_set (6494x3=19482) would require ~38h.

### 2.3 Restrictions

The holdout must NOT be used for:
- Adjusting tau (threshold is frozen at 2)
- Selecting between Candidate A/B/C (frozen at Candidate A)
- Tuning any hyperparameter
- Modifying the policy rule

Any such modification invalidates the confirmatory claim.

## 3. Risk Assessment

RISK: The depth interaction effect is primarily driven by HotpotQA depth>=3 (24 questions).
MITIGATION: Leave-one-stratum-out analysis confirms robustness (macro EM=0.4478 vs 0.4454 without Hotpot depth>=4).

RISK: 2Wiki shows no depth interaction (permutation p=0.40).
MITIGATION: Candidate B avoids 2Wiki harm by requiring chain topology.

RISK: Small sample at structural_hops>=2 (547 paired questions).
MITIGATION: Confirmatory test targets 600 items total, providing adequate power for McNemar test.
