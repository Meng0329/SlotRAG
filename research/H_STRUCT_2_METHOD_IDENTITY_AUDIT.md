# H_STRUCT_2_METHOD_IDENTITY_AUDIT.md — Flat vs Chain vs Static Identity

> **Date:** 2026-09-03
> **Status:** DONE (verified from source before flat execution)

---

## 1. Purpose

Per H_STRUCT_2_PRE_REGISTRATION §3.1, flat and chain must differ **only** in
`requirement_importance`. This audit verifies the claim by tracing the
execution path for each arm.

## 2. MethodSpec definitions

```
slotrag-g7-static:
  physical_plan=True, physical_plan_optimizer=False
  → uses compile_physical_plan() (deterministic, uniform allocation)

slotrag-g7-flat:
  physical_plan=True, physical_plan_optimizer=True
  plan_optimizer_importance="flat"
  → uses search_physical_plans()
  → importance=None → requirement_importance={} → optimizer defaults to 1.0

slotrag-g7-chain:
  physical_plan=True, physical_plan_optimizer=True
  plan_optimizer_importance="chain-rule"
  → uses search_physical_plans()
  → importance={sid: 2*(idx+1)-1}
```

All three share: `adaptive_binding_beam=True`, `physical_action_policy=True`,
`complementary_retrieval=True`, `primary_query_variant=question_plus_lexical_slot`.
None of the sufficiency/typed-contract/extraction flags are set for any of the
three `g7-*` arm specs (they are "no sufficiency" variants).

## 3. Shared frozen-plan execution path

From `methods.py:1774-1782`:
```python
if frozen_plan is None:
    plan, compiler_metrics = ...    # compile from scratch
else:
    plan = frozen_plan              # slot compilation SKIPPED
    compiler_metrics = _slot_plan_metrics(plan, frozen_plan_replays=1)
```

The logical plan is always derived from the SAME frozen SlotPlan:
```python
logical = logical_plan_from_slot_plan(plan)
```

Physical plan per arm (methods.py:1866-1910):
- **static**: `compile_physical_plan(logical)` — deterministic, uniform top_k.
- **flat**: `search_physical_plans(logical, requirement_importance={})` — explicit search, all importance 1.0.
- **chain**: `search_physical_plans(logical, requirement_importance={sid: 2*(idx+1)-1})` — explicit search, chain-rule importance.

## 4. Optimizer search space (importance-independent)

From `optimizer.py:313-336`:
- Orders: `_dependency_respecting_orders(logical)` → `_join_adjacent_orders(...)` — same for all, no importance dependency.
- Strategy variants: controlled by `spec.plan_optimizer_strategy_variants` — `False` for both flat and chain.
- Candidate dedup key: `(order, allocation_items, strategy_items)` — allocation differs across flat/chain but this only filters duplicates, does not add candidates.

The search space (set of enumerated candidate physical plans) is identical for
flat and chain. Only `_allocate_budget_between(order, importance, budget)` and
`_estimate_plan_utility(logical, order, allocation, params, ...)` consume the
importance vector, affecting which candidate wins — not which candidates are
considered.

## 5. Matched budget

All three arms execute with identical budgets (set by run_confirmatory.py):
```python
run_method(..., max_steps=8, max_retrieval_calls=8, frozen_plan=plan)
```
`_BudgetedAgnes(agnes, 96)` caps LLM calls at 96 identically.

## 6. Corpus / retriever / reranker / generator

All three arms use the same:
- `HybridRetriever(passages, embedding, reranker, ...)` — identical config
- `EmbeddingCache()` — per-execution (isolated), but config is identical
- Generator: qwen3.5-9b via Agnes (`config.agnes`)
- Same corpus (same passages for same question)
- Same prompt (no per-arm prompt customization)

## 7. ALLOWED differences (exhaustive)

| property | flat | chain |
|----------|------|-------|
| `requirement_importance` | `{}` (all default 1.0) | `{sid: 2*(idx+1)-1}` |
| `plan_optimizer_importance` label | `"flat"` | `"chain-rule"` |
| Result: allocation + selected order | may differ | may differ |
| Result: utility estimate | may differ | may differ |

**No other differences exist in the execution path.** The identity
requirement from H-STRUCT-2_PRE_REGISTRATION §3.1 is satisfied.

## 8. STOP condition check

If ANY of the following were true, execution must STOP:
- flat and chain have different frozen SlotPlans (same plan_json, plan hash)
- flat and chain call different retrieval functions (same HybridRetriever)
- flat and chain use different generators (same Agnes provider)
- flat and chain have different budgets (same 8/8/96)
- flat uses compile_physical_plan instead of search_physical_plans
  (flat has physical_plan_optimizer=True, so it uses search_physical_plans)
- chain lacks physical_plan_optimizer (it has physical_plan_optimizer=True)

**All conditions verified: NONE trigger STOP.**

## 9. plan_hash identity (pre-execution verification)

The plan_hash written to the results CSV is:
```python
hashlib.sha256(plan_json.encode()).hexdigest()[:16]
```

Since all three arms receive the same frozen `plan_json` from the manifest,
the plan_hash column will be identical across arms for every question.
This will be verified computationally BEFORE flat execution (P7 pre-check).
