# HSTRUCT_METHOD_IDENTITY_AUDIT.md — Method Key & Spec Comparison

> **Created:** 2026-09-01 (H-STRUCT-1 Frozen-Plan Semantics Repair)
> **Purpose:** Confirm exploratory and confirmatory use identical method keys and MethodSpec fields

---

## Exploratory Sealed Run (tkde-sealed-test-q35)

Config: `configs/experiments/tkde-sealed-test-q35.yaml`

| Arm | Method Key | Source |
|-----|-----------|--------|
| static | `slotrag-g7-static` | frozen_plan_source: slotrag-g7-static |
| cost-only | `slotrag-g7-flat` | — |
| chain-rule | `slotrag-g7-chain` | τ=2·depth−1 |

---

## Confirmatory Runner (run_confirmatory.py — PRE-FIX)

| Arm | Method Key Used | Status |
|-----|----------------|--------|
| static | `slotrag-static` | **NONEXISTENT** — would crash |
| chain | `slotrag-depth-chain` | **NONEXISTENT** — would crash |

---

## Corrected Confirmatory Keys

| Arm | Correct Method Key |
|-----|-------------------|
| static | `slotrag-g7-static` |
| chain | `slotrag-g7-chain` |

---

## MethodSpec Comparison: slotrag-g7-static vs slotrag-g7-chain

| Field | static | chain | Treatment Difference |
|-------|--------|-------|---------------------|
| key | slotrag-g7-static | slotrag-g7-chain | — |
| family | slotrag | slotrag | same |
| physical_plan | True | True | same |
| physical_plan_optimizer | **False** | **True** | **ONLY DIFFERENCE** |
| plan_optimizer_importance | chain-rule | chain-rule | same |
| adaptive_binding_beam | True | True | same |
| physical_action_policy | True | True | same |
| topk_expansion_mode | disabled | disabled | same |
| complementary_retrieval | True | True | same |
| primary_query_variant | question_plus_lexical_slot | question_plus_lexical_slot | same |
| evidence_sufficiency | False | False | same |
| All other fields | default | default | same |

**Sole treatment difference:** `physical_plan_optimizer` (static=False uses `compile_physical_plan` uniform allocation; chain=True uses `search_physical_plans` with chain-rule importance τ=2·depth−1).

This is the **only** physical allocation difference between arms. All other execution paths (retrieval, generation, binding, action policy) are identical.

---

## Key Invariant

```
slotrag-g7-static.physical_plan_optimizer == False
slotrag-g7-chain.physical_plan_optimizer == True
slotrag-g7-chain.plan_optimizer_importance == "chain-rule"
```

All other MethodSpec fields are **identical** between the two arms.

---

## Note on frozen_plan_source

Both arms replay the SAME frozen plan (compiled by `slotrag-g7-static`). The frozen plan is the **logical plan** (SlotPlan); the physical allocation is determined at execution time by the MethodSpec's optimizer setting. This means:

1. Static arm: uniform allocation over the frozen plan's slots
2. Chain arm: chain-rule allocation (τ=2·depth−1) over the SAME frozen plan's slots

The frozen plan is shared; only the physical allocation differs.
