#!/usr/bin/env python3
"""Evaluate generic query formulations against frozen global-corpus traces."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from slotrag.models import Passage  # noqa: E402
from slotrag.query_optimization import (  # noqa: E402
    QueryVariant,
    canonical_evidence_id,
    formulate_query,
    reciprocal_rank_fusion,
    select_development_strategy,
    summarize_strategy_records,
)
from slotrag.retrieval import (  # noqa: E402
    FieldedSparseBM25Index,
    HybridRetriever,
    SparseBM25Index,
)


VARIANTS: tuple[QueryVariant, ...] = (
    "question",
    "question_plus_slot",
    "lexical_slot",
    "question_plus_lexical_slot",
)
PROBE_VARIANTS: tuple[QueryVariant, ...] = ("slot", *VARIANTS)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _find_index_dir(index_root: Path, dataset: str) -> Path:
    candidates = (
        index_root / dataset / "index",
        index_root / dataset,
    )
    for candidate in candidates:
        if (candidate / "manifest.json").exists() and (candidate / "bm25.pkl").exists():
            return candidate
    raise FileNotFoundError(f"no persisted sparse index for {dataset} below {index_root}")


def _load_retriever(index_dir: Path, *, candidate_k: int) -> tuple[HybridRetriever, dict[str, Any]]:
    manifest = _read_json(index_dir / "manifest.json")
    passage_path = index_dir / str(manifest["passage_artifact"])
    passages: list[Passage] = []
    with passage_path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                passages.append(Passage.model_validate_json(line))
    sparse_path = index_dir / str(manifest["sparse_index_artifact"])
    sparse_class = (
        FieldedSparseBM25Index
        if manifest.get("sparse_index_mode") == "bm25f"
        else SparseBM25Index
    )
    sparse = sparse_class.load(
        sparse_path,
        expected_passage_count=len(passages),
        expected_sha256=str(manifest["sparse_index_sha256"]),
    )
    retriever = HybridRetriever(
        passages,
        None,
        None,
        bm25_k=max(50, candidate_k),
        final_k=candidate_k,
        rerank_enabled=False,
        dense_enabled=False,
        sparse_index=sparse,
    )
    return retriever, manifest


def _load_samples(run_dir: Path, stage: str) -> dict[tuple[str, str], dict[str, Any]]:
    samples: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted((run_dir / "samples" / stage).glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                sample = json.loads(line)
                metadata = sample.get("metadata") or {}
                split = metadata.get("split")
                if split not in {None, "train"}:
                    raise ValueError(
                        f"query development analysis refuses non-train sample {path}:{sample.get('id')}"
                    )
                dataset = str(metadata.get("dataset") or path.stem)
                samples[(dataset, str(sample["id"]))] = sample
    if not samples:
        raise ValueError(f"no samples found for stage {stage!r}")
    return samples


def _load_materializations(
    run_dir: Path,
    stage: str,
    samples: dict[tuple[str, str], dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    by_dataset: dict[str, list[dict[str, Any]]] = defaultdict(list)
    questions: dict[str, dict[str, Any]] = {}
    for path in sorted((run_dir / "items" / stage).rglob("*.json")):
        item = _read_json(path)
        if item.get("retrieval_protocol") != "global_corpus":
            raise ValueError(f"query headroom requires global_corpus records: {path}")
        dataset = str(item["dataset"])
        question_id = str(item["question_id"])
        sample = samples.get((dataset, question_id))
        if sample is None:
            raise ValueError(f"sample missing for {dataset}/{question_id}")
        question_key = f"{dataset}:{question_id}"
        questions[question_key] = {
            "dataset": dataset,
            "question_id": question_id,
            "question": str(sample["question"]),
            "gold_ids": sorted({canonical_evidence_id(value) for value in sample.get("gold_evidence", [])}),
        }
        slot_traces = ((item.get("result") or {}).get("slot_traces") or [])
        for slot_index, slot_trace in enumerate(slot_traces):
            for materialization_index, materialization in enumerate(
                slot_trace.get("materializations") or []
            ):
                searches = materialization.get("searches") or []
                slot_search = next(
                    (search for search in searches if search.get("query_variant") == "slot"),
                    searches[0] if searches else None,
                )
                if not slot_search:
                    continue
                candidate_ids = [
                    str(candidate["source_id"])
                    for candidate in slot_search.get("candidates") or []
                    if candidate.get("source_id")
                ]
                selected_ids = [
                    str(value) for value in materialization.get("selected_source_ids") or []
                ]
                by_dataset[dataset].append({
                    "materialization_id": (
                        f"{question_key}:{slot_trace.get('slot_id')}:{slot_index}:{materialization_index}"
                    ),
                    "question_key": question_key,
                    "dataset": dataset,
                    "question_id": question_id,
                    "slot_id": str(slot_trace.get("slot_id") or materialization.get("slot_id") or ""),
                    "question": str(sample["question"]),
                    "slot_query": str(slot_search.get("query") or ""),
                    "baseline_candidates": candidate_ids,
                    "baseline_selected": selected_ids,
                    "has_rows": bool(materialization.get("extracted_rows")),
                    "binding_count": len(materialization.get("binding_context") or {}),
                })
    return dict(by_dataset), questions


def _run_queries(
    retriever: HybridRetriever,
    materializations: list[dict[str, Any]],
    *,
    workers: int,
    candidate_k: int,
) -> dict[tuple[str, str], list[str]]:
    queries: dict[tuple[str, str], str] = {}
    for materialization in materializations:
        for variant in PROBE_VARIANTS:
            query = formulate_query(
                materialization["question"],
                materialization["slot_query"],
                variant,
            )
            queries[(variant, query)] = query

    output: dict[tuple[str, str], list[str]] = {}

    def source_ids(results: list[Any]) -> list[str]:
        values = []
        for result in results:
            original_id = result.passage.metadata.get("source_passage_id")
            values.append(str(original_id or canonical_evidence_id(result.passage.id)))
        return values

    ordered_keys = sorted(queries)
    search_batch = getattr(retriever, "search_batch", None)
    if search_batch is not None:
        rankings = search_batch(
            [queries[key] for key in ordered_keys],
            top_k=candidate_k,
        )
        return {
            key: source_ids(results)
            for key, results in zip(ordered_keys, rankings)
        }

    def execute(key: tuple[str, str]) -> tuple[tuple[str, str], list[str]]:
        results = retriever.search(queries[key], top_k=candidate_k)
        return key, source_ids(results)

    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        futures = [pool.submit(execute, key) for key in ordered_keys]
        for future in as_completed(futures):
            key, source_ids = future.result()
            output[key] = source_ids
    return output


def _materialization_strategies(
    materialization: dict[str, Any],
    query_results: dict[tuple[str, str], list[str]],
    *,
    top_k: int,
    candidate_k: int,
) -> dict[str, tuple[list[str], int]]:
    baseline_candidates = [
        canonical_evidence_id(value)
        for value in materialization["baseline_candidates"][:candidate_k]
    ]
    baseline_selected = [
        canonical_evidence_id(value)
        for value in materialization["baseline_selected"][:top_k]
    ]
    strategies: dict[str, tuple[list[str], int]] = {"slot": (baseline_selected, 0)}
    for variant in PROBE_VARIANTS:
        query = formulate_query(
            materialization["question"],
            materialization["slot_query"],
            variant,
        )
        alternate = [canonical_evidence_id(value) for value in query_results[(variant, query)]]
        direct_name = "reindexed_slot" if variant == "slot" else variant
        strategies[direct_name] = (alternate[:top_k], 0)
        fused = reciprocal_rank_fusion(
            [baseline_candidates, alternate[:candidate_k]],
            top_k=top_k,
        )
        fusion_name = f"slot_plus_{direct_name}"
        strategies[fusion_name] = (fused, 1)
        adaptive_name = f"adaptive_empty_{fusion_name}"
        strategies[adaptive_name] = (
            (fused, 1) if not materialization["has_rows"] else (baseline_selected, 0)
        )
    return strategies


def _question_records(
    materializations: list[dict[str, Any]],
    questions: dict[str, dict[str, Any]],
    query_results: dict[tuple[str, str], list[str]],
    *,
    top_k: int,
    candidate_k: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    retrieved: dict[tuple[str, str], set[str]] = defaultdict(set)
    extra_calls: dict[tuple[str, str], int] = defaultdict(int)
    raw: list[dict[str, Any]] = []
    for materialization in materializations:
        strategies = _materialization_strategies(
            materialization,
            query_results,
            top_k=top_k,
            candidate_k=candidate_k,
        )
        for strategy, (source_ids, calls) in strategies.items():
            key = (materialization["question_key"], strategy)
            retrieved[key].update(source_ids)
            extra_calls[key] += calls
        raw.append({
            "materialization_id": materialization["materialization_id"],
            "dataset": materialization["dataset"],
            "question_id": materialization["question_id"],
            "slot_id": materialization["slot_id"],
            "slot_query": materialization["slot_query"],
            "has_rows": materialization["has_rows"],
            "binding_count": materialization["binding_count"],
            "strategies": {
                strategy: {"source_ids": ids, "extra_calls": calls}
                for strategy, (ids, calls) in sorted(strategies.items())
            },
        })
    records: list[dict[str, Any]] = []
    strategy_names = sorted({strategy for _question, strategy in retrieved})
    question_keys = sorted({materialization["question_key"] for materialization in materializations})
    for question_key in question_keys:
        question = questions[question_key]
        gold = set(question["gold_ids"])
        if not gold:
            continue
        for strategy in strategy_names:
            found = retrieved[(question_key, strategy)]
            hits = gold.intersection(found)
            records.append({
                "dataset": question["dataset"],
                "question_id": question["question_id"],
                "strategy": strategy,
                "gold_count": len(gold),
                "hit_count": len(hits),
                "recall": len(hits) / len(gold),
                "full_support": hits == gold,
                "any_support": bool(hits),
                "extra_calls": extra_calls[(question_key, strategy)],
                "gold_ids": sorted(gold),
                "retrieved_gold_ids": sorted(hits),
            })
    return records, raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        type=Path,
        action="append",
        required=True,
        help="Development trace run; repeat to combine disjoint dataset runs.",
    )
    parser.add_argument("--stage", required=True)
    parser.add_argument("--index-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--role",
        choices=("development_selection", "disjoint_validation"),
        required=True,
    )
    parser.add_argument("--frozen-selection", type=Path)
    parser.add_argument("--workers", type=int, default=64)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=10)
    parser.add_argument("--retrieval-call-penalty", type=float, default=0.02)
    args = parser.parse_args()

    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(f"immutable output directory is not empty: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.role == "disjoint_validation" and args.frozen_selection is None:
        raise ValueError("disjoint_validation requires --frozen-selection")

    materializations_by_dataset: dict[str, list[dict[str, Any]]] = defaultdict(list)
    questions: dict[str, dict[str, Any]] = {}
    for run_dir in args.run_dir:
        samples = _load_samples(run_dir, args.stage)
        current_materializations, current_questions = _load_materializations(
            run_dir,
            args.stage,
            samples,
        )
        for dataset, rows in current_materializations.items():
            materializations_by_dataset[dataset].extend(rows)
        duplicate_questions = set(questions).intersection(current_questions)
        if duplicate_questions:
            raise ValueError(
                "combined runs contain duplicate questions: "
                + ", ".join(sorted(duplicate_questions)[:5])
            )
        questions.update(current_questions)
    all_records: list[dict[str, Any]] = []
    all_raw: list[dict[str, Any]] = []
    index_provenance: dict[str, Any] = {}
    for dataset, materializations in sorted(materializations_by_dataset.items()):
        index_dir = _find_index_dir(args.index_root, dataset)
        retriever, index_manifest = _load_retriever(index_dir, candidate_k=args.candidate_k)
        query_results = _run_queries(
            retriever,
            materializations,
            workers=args.workers,
            candidate_k=args.candidate_k,
        )
        records, raw = _question_records(
            materializations,
            questions,
            query_results,
            top_k=args.top_k,
            candidate_k=args.candidate_k,
        )
        all_records.extend(records)
        all_raw.extend(raw)
        index_provenance[dataset] = {
            "index_dir": str(index_dir),
            "index_id": index_manifest.get("index_id"),
            "chunk_count": index_manifest.get("chunk_count"),
            "passage_artifact_sha256": index_manifest.get("passage_artifact_sha256"),
            "sparse_index_sha256": index_manifest.get("sparse_index_sha256"),
        }
        del retriever, query_results
        gc.collect()

    report = summarize_strategy_records(all_records, baseline_strategy="slot")
    diagnostic_selected, ranking = select_development_strategy(
        report,
        baseline_strategy="slot",
        retrieval_call_penalty=args.retrieval_call_penalty,
    )
    if args.role == "development_selection":
        selected = diagnostic_selected
        validation_used_for_selection = False
        frozen_selection_sha256 = None
    else:
        frozen = _read_json(args.frozen_selection)
        selected = str(frozen["selected_strategy"])
        if selected not in report:
            raise ValueError(f"frozen strategy {selected!r} is absent from validation report")
        validation_used_for_selection = False
        frozen_selection_sha256 = _sha256(args.frozen_selection)

    _write_jsonl(args.output_dir / "materialization-strategies.jsonl", all_raw)
    _write_jsonl(args.output_dir / "question-strategy-records.jsonl", all_records)
    _write_json(args.output_dir / "strategy-report.json", report)
    selection = {
        "schema_version": 1,
        "role": args.role,
        "selected_strategy": selected,
        "selection_criterion": (
            "mean_recall - retrieval_call_penalty * mean_extra_calls; "
            "then full-support, paired net gains, cost, stable name"
        ),
        "retrieval_call_penalty": args.retrieval_call_penalty,
        "ranking": ranking if args.role == "development_selection" else None,
        "validation_diagnostic_ranking": ranking if args.role == "disjoint_validation" else None,
        "validation_used_for_selection": validation_used_for_selection,
        "frozen_selection_sha256": frozen_selection_sha256,
        "selected_metrics": report[selected],
    }
    _write_json(args.output_dir / "selection.json", selection)
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "role": args.role,
        "source_runs": [str(path) for path in args.run_dir],
        "source_stage": args.stage,
        "source_manifest_sha256": {
            str(path): _sha256(path / "manifest.json") for path in args.run_dir
        },
        "workers": args.workers,
        "top_k": args.top_k,
        "candidate_k": args.candidate_k,
        "provider_calls": 0,
        "question_count": len({(row["dataset"], row["question_id"]) for row in all_records}),
        "materialization_count": len(all_raw),
        "strategy_count": len(report),
        "index_provenance": index_provenance,
        "artifacts": {},
    }
    for name in (
        "materialization-strategies.jsonl",
        "question-strategy-records.jsonl",
        "strategy-report.json",
        "selection.json",
    ):
        manifest["artifacts"][name] = _sha256(args.output_dir / name)
    _write_json(args.output_dir / "manifest.json", manifest)
    print(json.dumps({
        "output_dir": str(args.output_dir),
        "selected_strategy": selected,
        "selected_metrics": report[selected],
        "question_count": manifest["question_count"],
        "materialization_count": manifest["materialization_count"],
        "provider_calls": 0,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
