"""Offline construction of development-only sufficiency and oracle examples."""

from __future__ import annotations

import json
import hashlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ..models import BindingRow, Passage, RetrievalResult, Slot
from ..sufficiency import (
    EvidenceContext,
    EvidenceSufficiencyCalibrator,
    SufficiencyCalibrationArtifact,
    SufficiencyExample,
)


def _normalize(value: object) -> str:
    return " ".join(
        "".join(char if char.isalnum() else " " for char in str(value or "").casefold()).split()
    )


def _answer_in_text(answers: list[str], text: str) -> bool:
    haystack = _normalize(text)
    return bool(haystack and any(_normalize(answer) in haystack for answer in answers if _normalize(answer)))


def _canonical_id(source_id: object, passage: Passage | None = None) -> str:
    if passage is not None:
        original = passage.metadata.get("source_passage_id")
        if original:
            return str(original).split("#chunk-", 1)[0]
    value = str(source_id or "").split("#chunk-", 1)[0]
    parts = value.split(":")
    return parts[-1] if len(parts) >= 3 else value


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _samples(run_dir: Path, stage: str) -> dict[tuple[str, str], dict[str, Any]]:
    output: dict[tuple[str, str], dict[str, Any]] = {}
    root = run_dir / "samples" / stage
    for path in sorted(root.glob("*.jsonl")):
        dataset = path.stem
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            if metadata.get("split") not in {None, "train"}:
                raise ValueError(
                    f"development analysis refuses non-train sample {dataset}/{record.get('id')}"
                )
            output[(str(metadata.get("dataset") or dataset), str(record.get("id") or ""))] = record
    return output


def _items(run_dir: Path, stage: str) -> list[tuple[Path, dict[str, Any]]]:
    root = run_dir / "items" / stage
    return [(path, _read_json(path)) for path in sorted(root.rglob("*.json"))]


def _passage_from_mapping(value: dict[str, Any]) -> Passage | None:
    text = str(value.get("text") or "").strip()
    if not text:
        return None
    return Passage(
        id=str(value.get("id") or ""),
        doc_id=str(value.get("doc_id")) if value.get("doc_id") is not None else None,
        text=text,
        metadata=dict(value.get("metadata") or {}),
    )


def _passage_lookup(
    run_dir: Path,
    samples: dict[tuple[str, str], dict[str, Any]],
    items: list[tuple[Path, dict[str, Any]]],
) -> dict[str, Passage]:
    lookup: dict[str, Passage] = {}
    wanted: set[str] = set()
    corpus_manifests: set[Path] = set()
    for sample in samples.values():
        for raw in sample.get("passages", []):
            if not isinstance(raw, dict):
                continue
            passage = _passage_from_mapping(raw)
            if passage is not None:
                lookup[passage.id] = passage
    for _path, item in items:
        for slot_trace in (item.get("result") or {}).get("slot_traces", []):
            for materialization in slot_trace.get("materializations", []):
                wanted.update(str(value) for value in materialization.get("selected_source_ids", []))
                for search in materialization.get("searches", []):
                    wanted.update(
                        str(candidate.get("source_id"))
                        for candidate in search.get("candidates", [])
                        if candidate.get("source_id") is not None
                    )
        manifest_value = item.get("corpus_manifest")
        if manifest_value:
            manifest_path = Path(str(manifest_value))
            if not manifest_path.is_absolute():
                manifest_path = run_dir / manifest_path
            corpus_manifests.add(manifest_path)
    missing = wanted - set(lookup)
    for manifest_path in sorted(corpus_manifests):
        manifest = _read_json(manifest_path)
        artifact_name = manifest.get("passage_artifact")
        if not artifact_name:
            continue
        artifact_path = manifest_path.parent / str(artifact_name)
        with artifact_path.open(encoding="utf-8") as handle:
            for line in handle:
                raw = json.loads(line)
                source_id = str(raw.get("id") or "")
                if source_id not in missing:
                    continue
                passage = _passage_from_mapping(raw)
                if passage is not None:
                    lookup[source_id] = passage
                    missing.discard(source_id)
                if not missing:
                    break
    return lookup


def _retrieval_result(candidate: dict[str, Any], passage: Passage) -> RetrievalResult:
    return RetrievalResult(
        passage=passage,
        score=float(candidate.get("score") or 0.0),
        bm25_score=candidate.get("bm25_score"),
        dense_score=candidate.get("dense_score"),
        rerank_score=candidate.get("rerank_score"),
    )


def _candidate_inventory(
    materialization: dict[str, Any],
    lookup: dict[str, Passage],
) -> tuple[list[RetrievalResult], list[RetrievalResult], list[str]]:
    selected_ids = [str(value) for value in materialization.get("selected_source_ids", [])]
    selected_set = set(selected_ids)
    all_results: list[RetrievalResult] = []
    seen: set[str] = set()
    missing: list[str] = []
    for search in materialization.get("searches", []):
        for candidate in search.get("candidates", []):
            source_id = str(candidate.get("source_id") or "")
            if not source_id or source_id in seen:
                continue
            seen.add(source_id)
            passage = lookup.get(source_id)
            if passage is None:
                missing.append(source_id)
                continue
            all_results.append(_retrieval_result(candidate, passage))
    selected = [result for result in all_results if result.passage.id in selected_set]
    selected.sort(key=lambda result: selected_ids.index(result.passage.id))
    return selected, all_results, missing


def _binding_rows(
    slot_id: str,
    materialization: dict[str, Any],
    lookup: dict[str, Passage],
) -> tuple[list[BindingRow], list[str]]:
    rows: list[BindingRow] = []
    missing: list[str] = []
    for raw in materialization.get("extracted_rows", []):
        source_id = str(raw.get("source_id") or "")
        passage = lookup.get(source_id)
        if passage is None:
            missing.append(source_id)
            continue
        rows.append(BindingRow(
            slot_id=slot_id,
            bindings={str(key): str(value) for key, value in (raw.get("bindings") or {}).items()},
            source_id=source_id,
            source_span=passage.text,
            confidence=float(raw.get("confidence") or 0.0),
            retrieval_score=raw.get("retrieval_score"),
        ))
    return rows, missing


def analyze_development_run(run_dir: Path, *, stage: str) -> dict[str, Any]:
    """Build auditable sufficiency examples from a train-stage enriched run."""
    run_dir = Path(run_dir)
    samples = _samples(run_dir, stage)
    items = _items(run_dir, stage)
    lookup = _passage_lookup(run_dir, samples, items)
    examples: list[dict[str, Any]] = []
    missing_sources: list[dict[str, str]] = []
    oracle = Counter()
    supervision_counts = Counter()
    dataset_counts = Counter()
    label_counts: dict[str, Counter[int]] = defaultdict(Counter)

    for item_path, item in items:
        dataset = str(item.get("dataset") or "")
        question_id = str(item.get("question_id") or "")
        sample = samples.get((dataset, question_id))
        if sample is None:
            continue
        answers = [str(value) for value in sample.get("answers", [])]
        gold_ids = {str(value).split("#chunk-", 1)[0] for value in sample.get("gold_evidence", [])}
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        plan = result.get("plan") if isinstance(result.get("plan"), dict) else {}
        slots = {
            str(raw.get("id")): Slot.model_validate(raw)
            for raw in plan.get("slots", [])
            if isinstance(raw, dict)
        }
        joins = plan.get("joins", []) if isinstance(plan.get("joins"), list) else []
        slot_traces = result.get("slot_traces", []) if isinstance(result.get("slot_traces"), list) else []
        cumulative_calls = 0
        for trace_index, trace in enumerate(slot_traces):
            slot_id = str(trace.get("slot_id") or "")
            slot = slots.get(slot_id)
            if slot is None:
                continue
            join_variables = sorted({
                str(join.get(field) or "")
                for join in joins
                if isinstance(join, dict)
                for slot_field, field in (
                    ("left_slot", "left_field"),
                    ("right_slot", "right_field"),
                )
                if str(join.get(slot_field) or "") == slot_id and join.get(field)
            })
            for materialization_index, materialization in enumerate(trace.get("materializations", [])):
                selected, candidates, retrieval_missing = _candidate_inventory(materialization, lookup)
                rows, row_missing = _binding_rows(slot_id, materialization, lookup)
                for source_id in retrieval_missing + row_missing:
                    missing_sources.append({
                        "dataset": dataset,
                        "question_id": question_id,
                        "slot_id": slot_id,
                        "source_id": source_id,
                    })
                if not selected and materialization.get("selected_source_ids"):
                    continue
                cumulative_calls += int(materialization.get("retrieval_calls") or 0)
                binding_context = {
                    str(key): str(value)
                    for key, value in (materialization.get("binding_context") or {}).items()
                }
                selected_canonical = {
                    _canonical_id(result_item.passage.id, result_item.passage)
                    for result_item in selected
                }
                candidate_canonical = {
                    _canonical_id(result_item.passage.id, result_item.passage)
                    for result_item in candidates
                }
                row_gold = any(
                    _canonical_id(row.source_id, lookup.get(row.source_id)) in gold_ids
                    for row in rows
                )
                requested = slot.variables - set(binding_context)
                complete_rows = [
                    row for row in rows
                    if all(str(row.bindings.get(name, "")).strip() for name in requested)
                ]
                if gold_ids:
                    supervision = "strong_gold_evidence"
                    gold_selected = bool(selected_canonical & gold_ids)
                    label = int(gold_selected and row_gold and bool(complete_rows))
                    if not gold_selected and candidate_canonical & gold_ids:
                        oracle["expand_topk_recoverable"] += 1
                    if gold_selected and not complete_rows:
                        oracle["evidence_selected_extraction_failed"] += 1
                else:
                    supervision = "weak_answer_surface"
                    selected_text = " ".join(result_item.passage.text for result_item in selected)
                    rows_text = json.dumps([row.bindings for row in rows], ensure_ascii=False)
                    label = int(_answer_in_text(answers, selected_text) and _answer_in_text(answers, rows_text))
                context = EvidenceContext(
                    retrieval_results=selected,
                    predicate=slot.predicate,
                    requested_variables=sorted(slot.variables),
                    bound_variables=binding_context,
                    join_variables=join_variables,
                    extracted_rows=rows,
                    remaining_plan_depth=max(len(slot_traces) - trace_index - 1, 0),
                    retrieval_calls_used=cumulative_calls,
                    retrieval_budget=int((item.get("budget") or {}).get("max_retrieval_calls") or 0),
                )
                example = SufficiencyExample(
                    example_id=f"{dataset}:{question_id}:{slot_id}:{materialization_index}",
                    label=label,
                    context=context,
                ).model_dump(mode="json")
                examples.append({
                    **example,
                    "dataset": dataset,
                    "question_id": question_id,
                    "slot_id": slot_id,
                    "supervision": supervision,
                    "retrieval_protocol": item.get("retrieval_protocol"),
                    "retrieval_backend": item.get("retrieval_backend"),
                    "primary_score": (item.get("scores") or {}).get("primary_score"),
                    "item_path": str(item_path),
                })
                supervision_counts[supervision] += 1
                dataset_counts[dataset] += 1
                label_counts[dataset][label] += 1

        rows_text = json.dumps(result.get("rows", []), ensure_ascii=False)
        prediction = str((item.get("scores") or {}).get("prediction_scored") or "")
        evidence_text = " ".join(str(raw.get("source_span") or "") for raw in result.get("evidence", []))
        available_text = " ".join(str(raw.get("text") or "") for raw in sample.get("passages", []))
        if _answer_in_text(answers, rows_text) and not _answer_in_text(answers, prediction):
            oracle["rows_correct_final_wrong"] += 1
        if _answer_in_text(answers, available_text) and not _answer_in_text(answers, evidence_text):
            oracle["available_answer_retrieval_miss"] += 1

    return {
        "schema_version": 1,
        "run_dir": str(run_dir),
        "stage": stage,
        "record_count": len(items),
        "example_count": len(examples),
        "examples": examples,
        "supervision_counts": dict(sorted(supervision_counts.items())),
        "dataset_counts": dict(sorted(dataset_counts.items())),
        "label_counts": {
            dataset: {str(label): count for label, count in sorted(counts.items())}
            for dataset, counts in sorted(label_counts.items())
        },
        "missing_source_count": len(missing_sources),
        "missing_sources": missing_sources,
        "oracle_headroom": {
            "expand_topk_recoverable": oracle["expand_topk_recoverable"],
            "evidence_selected_extraction_failed": oracle["evidence_selected_extraction_failed"],
            "rows_correct_final_wrong": oracle["rows_correct_final_wrong"],
            "available_answer_retrieval_miss": oracle["available_answer_retrieval_miss"],
        },
    }


def _stable_holdout(question_id: str, fraction: float) -> bool:
    digest = hashlib.sha256(question_id.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") / 2**64
    return bucket < fraction


def calibrate_development_report(
    report: dict[str, Any],
    *,
    training_manifest_sha256: str,
    created_at: str,
    holdout_fraction: float = 0.2,
    minimum_examples: int = 20,
) -> tuple[SufficiencyCalibrationArtifact, dict[str, Any]]:
    """Fit dataset calibrators on strong train supervision with question-disjoint holdout."""
    if not 0 < holdout_fraction < 1:
        raise ValueError("holdout_fraction must be between zero and one")
    strong = [
        example for example in report.get("examples", [])
        if example.get("supervision") == "strong_gold_evidence"
    ]
    if not strong:
        raise ValueError("no strong gold-evidence examples are available for calibration")
    protocols = {str(example.get("retrieval_protocol")) for example in strong}
    backends = {str(example.get("retrieval_backend")) for example in strong}
    if len(protocols) != 1 or len(backends) != 1:
        raise ValueError("calibration examples must share one retrieval protocol and backend")
    protocol = protocols.pop()
    backend = backends.pop()
    if protocol not in {"local_context", "global_corpus"} or backend not in {"bm25", "hybrid"}:
        raise ValueError("calibration examples have unsupported retrieval protocol or backend")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for example in strong:
        grouped[str(example.get("dataset"))].append(example)
    calibrators: dict[str, dict[str, Any]] = {}
    reports: dict[str, dict[str, Any]] = {}
    example_counts: dict[str, int] = {}
    calibration: dict[str, Any] = {
        "schema_version": 1,
        "source_split": "train",
        "retrieval_protocol": protocol,
        "retrieval_backend": backend,
        "holdout_fraction": holdout_fraction,
        "datasets": {},
    }
    for dataset, values in sorted(grouped.items()):
        if len(values) < minimum_examples:
            raise ValueError(
                f"dataset {dataset} has {len(values)} strong examples; minimum is {minimum_examples}"
            )
        fit_rows = [row for row in values if not _stable_holdout(str(row["question_id"]), holdout_fraction)]
        holdout_rows = [row for row in values if _stable_holdout(str(row["question_id"]), holdout_fraction)]
        # Stable hashing can produce a degenerate tiny split. Move whole questions,
        # never individual slot examples, until both sides are evaluable.
        if not fit_rows or not holdout_rows:
            question_ids = sorted({str(row["question_id"]) for row in values})
            cutoff = max(1, min(len(question_ids) - 1, round(len(question_ids) * (1 - holdout_fraction))))
            fit_ids = set(question_ids[:cutoff])
            fit_rows = [row for row in values if str(row["question_id"]) in fit_ids]
            holdout_rows = [row for row in values if str(row["question_id"]) not in fit_ids]
        if not fit_rows or not holdout_rows:
            raise ValueError(f"dataset {dataset} cannot form question-disjoint fit and holdout splits")
        fit_examples = [SufficiencyExample.model_validate({
            "example_id": row["example_id"],
            "label": row["label"],
            "context": row["context"],
        }) for row in fit_rows]
        holdout_examples = [SufficiencyExample.model_validate({
            "example_id": row["example_id"],
            "label": row["label"],
            "context": row["context"],
        }) for row in holdout_rows]
        if len({example.label for example in fit_examples}) < 2:
            raise ValueError(f"dataset {dataset} fit split has only one sufficiency class")
        calibrator = EvidenceSufficiencyCalibrator.fit(fit_examples)
        fit_report = calibrator.evaluate(fit_examples).model_dump(mode="json")
        holdout_report = calibrator.evaluate(holdout_examples).model_dump(mode="json")
        fit_question_ids = sorted({str(row["question_id"]) for row in fit_rows})
        holdout_question_ids = sorted({str(row["question_id"]) for row in holdout_rows})
        dataset_report = {
            "strong_example_count": len(values),
            "fit_example_count": len(fit_examples),
            "holdout_example_count": len(holdout_examples),
            "fit_question_ids": fit_question_ids,
            "holdout_question_ids": holdout_question_ids,
            "fit_label_counts": dict(Counter(example.label for example in fit_examples)),
            "holdout_label_counts": dict(Counter(example.label for example in holdout_examples)),
            "fit": fit_report,
            "holdout": holdout_report,
        }
        calibrators[dataset] = calibrator.to_dict()
        reports[dataset] = dataset_report
        example_counts[dataset] = len(fit_examples)
        calibration["datasets"][dataset] = dataset_report

    artifact = SufficiencyCalibrationArtifact(
        created_at=created_at,
        source_split="train",
        retrieval_protocol=protocol,
        retrieval_backend=backend,
        training_manifest_sha256=training_manifest_sha256,
        label_definition=(
            "selected evidence intersects gold supporting evidence and extraction emits "
            "a complete requested-variable row grounded in gold evidence"
        ),
        calibrators=calibrators,
        reports=reports,
        example_counts=example_counts,
    )
    return artifact, calibration


__all__ = ["analyze_development_run", "calibrate_development_report"]
