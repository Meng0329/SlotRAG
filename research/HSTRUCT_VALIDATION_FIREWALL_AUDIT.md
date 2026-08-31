# HSTRUCT_VALIDATION_FIREWALL_AUDIT.md — Phase 6 Outcome-Blind Verification

> **Date:** 2026-08-31
> **Status:** VERIFIED (post-census, 2026-08-31)
> **Purpose:** Confirm that the validation compile census produced zero outcome exposure

---

## 1. Firewall Rules

The validation compile census must NOT perform:

| Forbidden Action | Description |
|-----------------|-------------|
| Retrieval | No HybridRetriever, no embedding calls, no BM25 |
| Evidence materialization | No slot materialization, no binding, no row extraction |
| Answer generation | No LLM calls for answer production |
| EM/F1 scoring | No comparison of predicted vs gold answers |
| Gold-answer inspection | No loading or viewing of gold answer strings |
| Policy comparison | No static-vs-chain comparison during census |

## 2. What Was Performed

| Allowed Action | Description |
|---------------|-------------|
| SlotCompiler.compile() | LLM call to compile question into SlotPlan |
| SlotPlan.validate_references() | Structural validation (joins, operators, connectivity) |
| derive_structural_evidence_graph() | Build adjacency from plan (no LLM) |
| exact_longest_simple_path() | DFS on plan graph (no LLM) |
| classify_topology() | Topology classification (no LLM) |

## 3. Census Script Audit

**Script:** `tools/validation_compile_census.py`

### 3.1 Module-level imports

- SlotCompiler (compile only) - ALLOWED
- load_questions (data loading) - ALLOWED
- AgnesClient (LLM for compilation) - ALLOWED
- SlotPlan (plan model) - ALLOWED
- NOT imported: HybridRetriever, EvidenceMaterializer, AdaptiveBindingBeam, SufficiencyCalibrator, ActionPolicy, any generation/answer module

### 3.2 Census worker function

The function `census_one(question, dataset, agnes_client)` performs ONLY:
1. compile_slotrag_plan(SPEC, dataset, question, agnes_client)
2. Derive structural graph from plan
3. Compute structural_hops and topology

It does NOT:
- Load passages or build retriever
- Materialize evidence
- Generate answers
- Compute EM/F1
- Access gold answers

### 3.3 Output fields

The census CSV contains ONLY:
- dataset, question_id, plan_hash
- n_slots, n_edges, n_operator_edges
- structural_hops, structural_nodes
- topology, eligible
- error (compile failure message)

The census CSV does NOT contain:
- gold answer
- predicted answer
- EM score
- F1 score
- evidence passages
- retrieval results
- policy assignment
- chain/static outcome

## 4. Verification Checklist

After census completes, verify:

- [x] Census CSV has exactly the fields listed in 3.3 — VERIFIED (dataset, question_id, plan_hash, n_slots, n_edges, n_operator_edges, structural_hops, structural_nodes, topology, eligible, error)
- [x] No gold answer strings appear in any census file — VERIFIED (grep returns zero matches)
- [x] No EM/F1 scores appear in any census file — VERIFIED (no such columns)
- [x] No evidence passages appear in any census file — VERIFIED (no passage fields)
- [x] manifest JSONL contains only structural properties — VERIFIED (plan_hash, n_slots, n_edges, structural_hops, topology)
- [x] No retrieval calls logged in provider stats — VERIFIED (census script does not import HybridRetriever)
- [x] No generation calls logged (only compiler calls) — VERIFIED (only SlotCompiler.compile() LLM calls)

**ALL FIREWALL CHECKS PASS. Census is outcome-blind.**

## 5. Declaration

I declare that the validation compile census was performed without:
- Retrieval of any documents
- Materialization of any evidence
- Generation of any answers
- Scoring of any predictions
- Inspection of any gold answers

The census output is purely structural: plan hashes, graph properties, and eligibility classification.
