#!/usr/bin/env python3
"""
run_confirmatory.py — Phase 8-10: Execute H-STRUCT-1 confirmatory static-vs-chain test

Uses frozen plans from the manifest to ensure fairness:
- Both static and chain arms use the SAME SlotPlan (no re-compilation)
- runner.py's _run_slotrag() skips SlotCompiler when frozen_plan is provided

NO-PEEKING: Only logs progress (completed/total, errors, runtime).
No aggregate EM/ΔEM/p-values are emitted during execution.

Usage:
    python tools/run_confirmatory.py --config configs/default.yaml

Requires:
    - confirmatory_eligible_manifest.jsonl (frozen, SHA256 verified)
    - Services running (Agnes/qwen3.5-9b generation, Qwen3-Embedding-0.6B, bge-reranker-v2-m3)
"""

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from slotrag.config import AppConfig
from slotrag.models import SlotPlan, QuestionRecord
from slotrag.benchmarking.methods import METHODS, run_method
from slotrag.benchmarking.datasets import DATASETS, load_all_questions, adapt_record, iter_jsonl

OUTPUT_DIR = REPO / "research" / "hstruct_confirmatory"
MANIFEST_PATH = OUTPUT_DIR / "confirmatory_eligible_manifest.jsonl"
RESULTS_CSV = OUTPUT_DIR / "confirmatory_results.csv"
PROGRESS_FILE = OUTPUT_DIR / "execution_progress.json"

SEED = 2027
ARMS = ["static", "chain"]
METHOD_BY_ARM = {
    "static": "slotrag-g7-static",
    "chain": "slotrag-g7-chain",
}

# No-peeking: only these fields are logged per-item
PROGRESS_FIELDS = ["completed", "total", "errors", "runtime_s", "current_item", "current_arm"]


def load_manifest():
    """Load frozen confirmatory manifest."""
    items = []
    with open(MANIFEST_PATH) as f:
        for line in f:
            items.append(json.loads(line.strip()))
    return items


def load_question_record(dataset: str, question_id: str) -> QuestionRecord | None:
    """Load a full QuestionRecord from benchmark files."""
    spec = DATASETS[dataset]
    eval_path = REPO / "benchmark" / spec.evaluation_file
    if not eval_path.exists():
        return None
    for idx, rec in iter_jsonl(eval_path):
        if rec["id"] == question_id:
            return adapt_record(spec, rec, idx, split="validation")
    return None


def load_question_record_train(dataset: str, question_id: str) -> QuestionRecord | None:
    """Load a full QuestionRecord from train benchmark files."""
    spec = DATASETS[dataset]
    train_path = REPO / "benchmark" / spec.train_file
    if not train_path.exists():
        return None
    for idx, rec in iter_jsonl(train_path):
        if rec["id"] == question_id:
            return adapt_record(spec, rec, idx, split="train")
    return None


def load_question(dataset: str, question_id: str, source_split: str) -> QuestionRecord | None:
    """Load question from the appropriate split."""
    if source_split == "train":
        return load_question_record_train(dataset, question_id)
    else:
        return load_question_record(dataset, question_id)


def execute_one(
    config: AppConfig,
    dataset: str,
    question_id: str,
    arm: str,
    source_split: str,
    plan_json: str,
    output_dir: Path,
) -> dict:
    """Execute one arm for one question. Returns result dict."""
    spec_name = METHOD_BY_ARM[arm]
    plan = SlotPlan.model_validate_json(plan_json)

    question = load_question(dataset, question_id, source_split)
    if question is None:
        return {
            "question_id": question_id,
            "dataset": dataset,
            "arm": arm,
            "source_split": source_split,
            "method": spec_name,
            "status": "error",
            "error": "question_not_found",
        }

    # Build providers + retriever the same way BenchmarkRunner._retriever() does
    # (runner.py:311-343): chunk passages, wire embedding/reranker clients, build.
    # Do NOT swallow exceptions here — a failed retriever means a failed execution.
    from slotrag.data import chunk_passages
    from slotrag.providers import provider_clients
    from slotrag.retrieval import EmbeddingCache, HybridRetriever
    from slotrag.benchmarking.runner import _BudgetedAgnes, _BudgetedRetriever

    agnes, embedding, reranker = provider_clients(config)
    passages = chunk_passages(
        question.passages,
        chunk_tokens=config.retrieval.chunk_tokens,
        overlap=config.retrieval.chunk_overlap,
    )
    retriever = HybridRetriever(
        passages,
        embedding,
        reranker,
        bm25_k=config.retrieval.bm25_k,
        dense_k=config.retrieval.dense_k,
        final_k=config.retrieval.final_k,
        rrf_k=config.retrieval.rrf_k,
        bm25_weight=config.retrieval.bm25_weight,
        dense_weight=config.retrieval.dense_weight,
        rerank_enabled=config.reranker.enabled,
        cache=EmbeddingCache(),
        dense_enabled=True,
        sparse_index_mode=config.retrieval.sparse_index_mode,
        sparse_title_weight=config.retrieval.sparse_title_weight,
    )
    retriever.build_index()

    try:
        result = run_method(
            spec_name,
            dataset=dataset,
            question=question,
            retriever=_BudgetedRetriever(retriever, 8),
            client=_BudgetedAgnes(agnes, 96),
            config=config,
            seed=SEED,
            max_steps=8,
            max_retrieval_calls=8,
            frozen_plan=plan,
        )

        answer_text = result.answer or ""
        metrics = result.metrics or None
        status = result.status

        # Step 16: NO scoring during execution. Save raw answer only.
        # Scoring uses score_record() post-execution to avoid CSV boolean bug.
        return {
            "question_id": question_id,
            "dataset": dataset,
            "arm": arm,
            "source_split": source_split,
            "method": spec_name,
            "plan_hash": hashlib.sha256(plan_json.encode()).hexdigest()[:16],
            "status": status,
            "answer": answer_text[:500],
            "llm_calls": getattr(metrics, "llm_calls", 0) if metrics else 0,
            "retrieval_calls": getattr(metrics, "retrieval_calls", 0) if metrics else 0,
            "error": None,
        }

    except Exception as e:
        return {
            "question_id": question_id,
            "dataset": dataset,
            "arm": arm,
            "source_split": source_split,
            "method": spec_name,
            "status": "error",
            "error": str(e)[:500],
        }


def load_completed():
    """Load already-completed items from results CSV."""
    completed = set()
    if RESULTS_CSV.exists():
        with open(RESULTS_CSV) as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("status") == "ok":
                    key = (row["question_id"], row["arm"])
                    completed.add(key)
    return completed


def write_result_row(row: dict, file_handle):
    """Append one result row to CSV."""
    writer = csv.DictWriter(file_handle, fieldnames=[
        "question_id", "dataset", "arm", "source_split", "method",
        "plan_hash", "status", "answer",
        "llm_calls", "retrieval_calls", "error",
    ], extrasaction="ignore")
    writer.writerow(row)
    file_handle.flush()


def update_progress(progress: dict, file_handle):
    """Write no-peeking progress update."""
    file_handle.seek(0)
    file_handle.truncate()
    json.dump(progress, file_handle, indent=2)
    file_handle.flush()


def main():
    parser = argparse.ArgumentParser(description="Run H-STRUCT-1 confirmatory test")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--parallel", type=int, default=4, help="Parallel questions")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Load config
    config = AppConfig.from_yaml(REPO / args.config)

    # Load manifest
    manifest = load_manifest()
    total_questions = len(manifest)
    total_executions = total_questions * 2  # static + chain per question

    print(f"Loaded {total_questions} questions from frozen manifest")
    print(f"Total executions: {total_executions} ({total_questions} × 2 arms)")

    # Load already-completed
    completed = load_completed()
    remaining = []
    for item in manifest:
        for arm in ARMS:
            key = (item["question_id"], arm)
            if key not in completed:
                remaining.append((item, arm))

    print(f"Already completed: {len(completed)}/{total_executions}")
    print(f"Remaining: {len(remaining)}")

    if args.dry_run:
        print("\n[DRY RUN] Would execute as above.")
        return

    if not remaining:
        print("\nAll executions already complete. Run analyze_hstruct_confirmatory.py for results.")
        return

    # Prepare results CSV
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_exists = RESULTS_CSV.exists()
    csv_file = open(RESULTS_CSV, "a", newline="")
    if not csv_exists:
        # New file: emit header first, else the first data row becomes the
        # header and DictReader parsing (load_completed / analyzer) breaks.
        writer = csv.DictWriter(csv_file, fieldnames=[
            "question_id", "dataset", "arm", "source_split", "method",
            "plan_hash", "status", "answer",
            "llm_calls", "retrieval_calls", "error",
        ])
        writer.writeheader()
        csv_file.flush()
    progress_file = open(PROGRESS_FILE, "w")

    progress = {
        "status": "running",
        "completed": len(completed),
        "total": total_executions,
        "errors": 0,
        "runtime_s": 0,
        "current_item": "",
        "current_arm": "",
    }
    update_progress(progress, progress_file)

    t0 = time.time()
    errors = 0

    def do_one(args_tuple):
        item, arm = args_tuple
        return execute_one(
            config,
            item["dataset"],
            item["question_id"],
            arm,
            item.get("source_split", "validation"),
            item["plan_json"],
            OUTPUT_DIR,
        )

    if args.parallel <= 1:
        for i, (item, arm) in enumerate(remaining):
            result = do_one((item, arm))
            write_result_row(result, csv_file)
            done = len(completed) + i + 1
            elapsed = time.time() - t0
            progress.update({
                "completed": done,
                "errors": errors + (1 if result["status"] == "error" else 0),
                "runtime_s": elapsed,
                "current_item": item["question_id"],
                "current_arm": arm,
            })
            if result["status"] == "error":
                errors += 1
            if (i + 1) % 50 == 0 or (i + 1) == len(remaining):
                update_progress(progress, progress_file)
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                eta = (len(remaining) - i - 1) / rate if rate > 0 else 0
                print(f"[{done}/{total_executions}] {result['status']} | "
                      f"errors={errors} | {elapsed:.0f}s elapsed, ETA {eta:.0f}s")
    else:
        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            futures = {pool.submit(do_one, args_tuple): args_tuple for args_tuple in remaining}
            for i, future in enumerate(as_completed(futures)):
                result = future.result()
                write_result_row(result, csv_file)
                done = len(completed) + i + 1
                elapsed = time.time() - t0
                if result["status"] == "error":
                    errors += 1
                progress.update({
                    "completed": done,
                    "errors": errors,
                    "runtime_s": elapsed,
                })
                if (i + 1) % 50 == 0 or (i + 1) == len(remaining):
                    update_progress(progress, progress_file)
                    rate = (i + 1) / elapsed if elapsed > 0 else 0
                    eta = (len(remaining) - i - 1) / rate if rate > 0 else 0
                    print(f"[{done}/{total_executions}] | errors={errors} | "
                          f"{elapsed:.0f}s elapsed, ETA {eta:.0f}s")

    csv_file.close()
    elapsed = time.time() - t0

    progress.update({
        "status": "complete",
        "completed": len(completed) + len(remaining),
        "errors": errors,
        "runtime_s": elapsed,
    })
    update_progress(progress, progress_file)
    progress_file.close()

    print(f"\n{'='*60}")
    print(f"Execution complete")
    print(f"  Total: {len(completed) + len(remaining)}/{total_executions}")
    print(f"  Errors: {errors}")
    print(f"  Runtime: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"  Results: {RESULTS_CSV}")
    print(f"\n  NO-PEEKING: Run analyze_hstruct_confirmatory.py for results.")


if __name__ == "__main__":
    main()
