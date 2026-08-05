#!/usr/bin/env python3
"""S0-S9 stage audit classifier for SlotRAG wrong answers.

Phase 3R corrective protocol: for every EM=0 sample, classify the FIRST
irreversible information-loss stage in the pipeline. This replaces the
coarse "recall=1.0 & EM=0 → entity selection error" attribution.

Stage definitions (first-loss point, checked in order):
  S0_GOLD_SOURCE_NOT_RETRIEVED  — gold source never in retrieval pool
  S1_GOLD_SOURCE_NOT_SELECTED   — gold source retrieved but not kept for materialization
  S2_GOLD_SOURCE_NOT_BUNDLED    — gold source selected but excluded from evidence bundle
  S3_BUNDLE_EMPTY_OR_PARTIAL    — evidence bundle empty / missing gold source
  S4_GOLD_SPAN_NOT_EXTRACTED    — bundle has gold source but no rows for it
  S5_GOLD_BINDING_MISSING       — gold span in context but binding missing/wrong value
  S6_ENTITY_SELECTION_ERROR     — correct gold binding present but wrong entity chosen
  S7_PATH_BINDING_NOT_SURVIVED  — correct binding lost across join/aggregation
  S8_GENERATION_EM_WRONG        — correct final entity but EM mismatch (format/extra words)
  S9_UNRESOLVED                 — cannot attribute; needs human review

Each stage's check uses only observable trace fields; no oracle LLM calls.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


def _norm(tokens: str) -> str:
    """Normalize a string for EM-style comparison (lowercase, collapse spaces)."""
    return re.sub(r"\s+", " ", tokens.lower().strip())


def _f1_tokens(a: str, b: str) -> float:
    a_tok = _norm(a).split()
    b_tok = _norm(b).split()
    if not a_tok or not b_tok:
        return 0.0
    common = Counter(a_tok) & Counter(b_tok)
    n = sum(common.values())
    if not n:
        return 0.0
    precision = n / len(a_tok)
    recall = n / len(b_tok)
    return 2 * precision * recall / (precision + recall)


def _safe_binding_values(bindings: dict | None) -> list[str]:
    if not bindings:
        return []
    vals = []
    for k, v in bindings.items():
        if isinstance(v, str):
            vals.append(v)
        elif isinstance(v, list):
            vals.extend(str(x) for x in v if x)
    return vals


def load_sample_questions(sample_path: Path) -> dict[str, dict]:
    """Load question→(answers, gold_evidence) from the pre-generated sample file."""
    out = {}
    if not sample_path.exists():
        return out
    for line in sample_path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        out[rec.get("id")] = {
            "question": rec.get("question", ""),
            "answers": rec.get("answers", ""),
            "gold_evidence": rec.get("gold_evidence", []),
            "metadata": rec.get("metadata", {}),
        }
    return out


def classify_one(item: dict, sample: dict) -> dict:
    """Return stage classification for one item dict (schema_version 32)."""
    qid = item.get("question_id", "?")
    scores = item.get("scores", {})
    em = scores.get("em")
    f1 = scores.get("f1")
    gold = (sample or {}).get("answers", "")
    pred = str((item.get("result", {}) or {}).get("answer", "") or "")
    gold_str = str(gold or "")

    inventory = item.get("evidence_inventory", {})
    gold_ids = inventory.get("gold_evidence_ids", []) or []
    retrieved_ids = inventory.get("retrieved_evidence_ids", []) or []
    avail_ids = inventory.get("available_evidence_ids", []) or []

    result = item.get("result", {})
    rows = result.get("rows", []) or []
    evidence = result.get("evidence", []) or []
    slot_traces = result.get("slot_traces", []) or []
    final_answer = result.get("answer", "")
    status = result.get("status", "")
    plan = result.get("plan")

    # EM hit — nothing to classify.
    is_correct = (em is not None and em >= 1.0) or (pred and gold_str and _norm(pred) == _norm(gold_str))
    if is_correct:
        return {"stage": "EM_HIT", "confidence": "high", "detail": "answer correct"}

    # ---- Candidate pool: every source that ever appeared in a retrieval candidate ----
    # This is the TRUE "was it retrieved" signal. `retrieved_evidence_ids` only
    # records what was finally selected into evidence, which conflates retrieval
    # misses with selection failures.
    candidate_pool: set[str] = set()
    selected_ids: set[str] = set()
    for st in slot_traces:
        for mat in st.get("materializations", []):
            for search in mat.get("searches", []) or []:
                for cand in search.get("candidates", []) or []:
                    candidate_pool.add(cand.get("source_id", ""))
            sel = mat.get("selected_source_ids") or []
            selected_ids.update(sel)
    evidence_ids = set(e.get("source_id", "") for e in evidence if e.get("source_id"))
    selected_ids |= evidence_ids

    # ---- S0: gold source never in any retrieval candidate ----
    gold_not_candidate = [g for g in gold_ids if g not in candidate_pool]
    if gold_not_candidate:
        return {
            "stage": "S0_GOLD_SOURCE_NOT_RETRIEVED",
            "confidence": "high",
            "detail": f"gold never in retrieval candidates: {gold_not_candidate[:3]}",
        }

    # ---- S1: gold retrieved (in candidate) but not selected for materialization ----
    gold_not_selected = [g for g in gold_ids if g not in selected_ids]
    if gold_not_selected:
        return {
            "stage": "S1_GOLD_SOURCE_NOT_SELECTED",
            "confidence": "high",
            "detail": f"gold in candidates but not selected for materialization: {gold_not_selected[:3]}",
        }

    # ---- S2: gold source not in evidence bundle ----
    # ---- S2: gold selected but not in final evidence bundle ----
    if gold_not_in_evidence(gold_ids, evidence, rows):
        return {
            "stage": "S2_GOLD_SOURCE_NOT_BUNDLED",
            "confidence": "medium",
            "detail": f"gold in selection but absent from evidence bundle: {gold_ids}",
        }

    # ---- S3: evidence bundle has gold but no rows extracted ----
    # Gold IS in evidence (S2 passed) but extraction produced no rows.
    if not rows:
        return {
            "stage": "S3_BUNDLE_EMPTY_OR_PARTIAL",
            "confidence": "high",
            "detail": f"gold in evidence but no rows extracted (status={status}, evidence={len(evidence)} items)",
        }

    # ---- Collect trace-level extraction bindings (the raw bindings at extraction time) ----
    # These come from slot_traces[].materializations[].extracted_rows[].bindings.
    # They are more faithful than the final rows/evidence which may have been
    # post-processed (grounding, dedup, ordering).
    trace_bindings: list[str] = []  # all binding values from extracted_rows
    trace_row_bindings: list[dict] = []  # raw extracted rows
    for st in slot_traces:
        for mat in st.get("materializations", []):
            for er in mat.get("extracted_rows", []) or []:
                b = er.get("bindings") or {}
                trace_row_bindings.append(b)
                trace_bindings.extend(_safe_binding_values(b))

    # ---- S5: gold answer core missing from extracted bindings ----
    gold_tokens = set(_norm(gold_str).split())
    row_values = trace_bindings
    # Does ANY extracted binding value contain ALL gold tokens?
    # If not, the binding extraction lost parts of the gold answer → S5.
    gold_token_set = set(_norm(gold_str).split())
    binding_covers_gold = any(gold_token_set <= set(_norm(str(v)).split()) for v in row_values)
    best_binding_f1 = max([_f1_tokens(str(v), gold_str) for v in row_values], default=0.0)
    if gold_tokens and not binding_covers_gold:
        return {
            "stage": "S5_GOLD_BINDING_MISSING",
            "confidence": "high",
            "detail": f"gold '{gold_str}' not fully covered by bindings {row_values[:4]} (best_f1={best_binding_f1:.2f})",
        }

    # ---- S6 vs S8: gold core present in bindings ----
    # S6: gold (or close match) IS among bindings, but final answer is a
    #     DIFFERENT candidate that was also bound → wrong entity chosen.
    # S8: binding carries the gold core, but final answer lost precision in
    #     generation/aggregation (format, prefix/suffix, casing).
    ev_binding_values: list[str] = []
    for e in evidence:
        ev_binding_values.extend(_safe_binding_values(e.get("bindings")))
    # gold_in_bindings: any binding (trace or evidence) covers the full gold.
    all_binding_values = trace_bindings + ev_binding_values
    gold_in_bindings = gold_tokens and (
        any(set(_norm(str(v)).split()) >= gold_token_set for v in all_binding_values)
    )

    # If gold appears nowhere in bindings → binding loss (S5), already handled above
    # (trace_token_overlap empty). But final rows/evidence bindings may carry gold
    # even when trace doesn't (post-processing). Check again:
    if not gold_in_bindings and gold_tokens:
        return {
            "stage": "S5_GOLD_BINDING_MISSING",
            "confidence": "medium",
            "detail": f"gold '{gold_str}' absent from all bindings (trace={row_values[:3]})",
        }

    # gold core present in bindings. Determine selection vs generation failure.
    pred_tokens = set(_norm(str(pred)).split()) if pred else set()
    final_tokens = set(_norm(str(final_answer)).split()) if final_answer else set()
    pred_covers_gold = bool(pred_tokens) and gold_token_set <= pred_tokens
    # Multiple distinct candidate entities were bound (selection is ambiguous).
    distinct_candidates = {_norm(v) for v in all_binding_values}
    if len(distinct_candidates) > 1:
        # Check if gold core is among them but a DIFFERENT one was chosen.
        gold_covers_candidate = any(
            set(_norm(c).split()) >= gold_token_set for c in distinct_candidates
        )
        if gold_covers_candidate and not pred_covers_gold:
            return {
                "stage": "S6_ENTITY_SELECTION_ERROR",
                "confidence": "high",
                "detail": f"candidates={sorted(distinct_candidates)[:4]} gold='{gold_str}' final='{final_answer}'",
            }

    # pred covers gold (or is a close superset) → generation/aggregation EM
    # mismatch: answer carries the correct entity but is over-broad, missing
    # precision, or format-different.
    if pred_covers_gold or _f1_tokens(pred, gold_str) >= 0.6:
        return {
            "stage": "S8_GENERATION_EM_WRONG",
            "confidence": "high",
            "detail": f"pred covers gold but imprecise: pred='{pred}' gold='{gold_str}' (f1={_f1_tokens(pred, gold_str):.2f})",
        }

    # gold core in bindings but pred does NOT cover it → wrong candidate selected.
    if len(slot_traces) <= 1:
        return {
            "stage": "S6_ENTITY_SELECTION_ERROR",
            "confidence": "low",
            "detail": f"gold '{gold_str}' in bindings but final='{final_answer}' (f1={_f1_tokens(pred, gold_str):.2f})",
        }

    # ---- S9 fallback ----
    return {
        "stage": "S9_UNRESOLVED",
        "confidence": "low",
        "detail": f"cannot attribute; pred='{pred}' gold='{gold_str}'",
    }


def gold_not_in_evidence(gold_ids, evidence, rows) -> bool:
    ev_ids = set(e.get("source_id", "") for e in evidence if e.get("source_id"))
    row_sources = set()
    for row in rows:
        if isinstance(row, dict) and row.get("source_id"):
            row_sources.add(row["source_id"])
    covered = ev_ids | row_sources
    return any(g not in covered for g in gold_ids)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default="runs/slotrag-phase3r-dev")
    ap.add_argument("--datasets", nargs="*", default=["hotpotqa", "2wikimultihop", "musique"])
    ap.add_argument("--stage", default="h007_dev")
    ap.add_argument("--method", default="slotrag")
    ap.add_argument("--out-csv", default="research/ANSWER_PIPELINE_AUDIT.csv")
    args = ap.parse_args()

    base = Path(args.output_dir)
    all_rows: list[dict] = []
    for ds in args.datasets:
        item_dir = base / "items" / args.stage / ds / args.method
        sample_path = base / "samples" / args.stage / f"{ds}.jsonl"
        sample_q = load_sample_questions(sample_path)
        files = sorted(item_dir.glob("*.json")) if item_dir.exists() else []
        for f in files:
            item = json.loads(f.read_text())
            qid = item.get("question_id", f.stem)
            sample = sample_q.get(qid, {})
            scores = item.get("scores", {})
            cls = classify_one(item, sample)
            all_rows.append({
                "dataset": ds,
                "question_id": qid,
                "em": scores.get("em"),
                "f1": scores.get("f1"),
                "evidence_recall": scores.get("evidence_recall"),
                "stage": cls["stage"],
                "confidence": cls["confidence"],
                "detail": cls["detail"][:200],
                "gold": str(sample.get("answers", ""))[:80],
                "pred": str((item.get("result", {}) or {}).get("answer", ""))[:80],
            })

    # Write CSV
    with open(args.out_csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(all_rows[0].keys()) if all_rows else [])
        w.writeheader()
        for r in all_rows:
            w.writerow(r)

    # Summaries per dataset
    per_ds = defaultdict(Counter)
    for r in all_rows:
        per_ds[r["dataset"]][r["stage"]] += 1
    print(f"Wrote {len(all_rows)} rows to {args.out_csv}")
    for ds, c in per_ds.items():
        total = sum(c.values())
        print(f"\n=== {ds} (n={total}) ===")
        for stage, n in c.most_common():
            pct = 100.0 * n / total
            print(f"  {stage:45s} {n:4d} ({pct:.1f}%)")


if __name__ == "__main__":
    main()
