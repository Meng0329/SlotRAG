from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np


METRICS = [
    "primary_score",
    "em",
    "f1",
    "accuracy",
    "drop_f1",
    "drop_em",
    "evidence_recall",
    "evidence_mrr",
    "documents_accessed",
    "passages_processed",
    "llm_calls",
    "retrieval_calls",
    "embedding_calls",
    "reranker_calls",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "latency_ms",
    "wall_latency_ms",
    "provider_latency_ms",
    "retry_count",
    "cache_hits",
    "cache_misses",
    "materialization_requests",
    "materialization_cache_hits",
    "binding_contexts_pruned",
    "join_input_rows",
    "join_output_rows",
    "early_stops",
    "structured_output_failures",
    "structured_output_repairs",
    "plan_fallbacks",
    "operators_executed",
    "peak_rss_mb",
    "max_intermediate_binding_size",
    "reoptimizations",
    "mean_selectivity_error",
    "planner_regret",
    "index_build_latency_ms",
    "index_bytes",
]


def load_records(output_dir: Path, stage: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    root = output_dir / "items" / stage
    if not root.exists():
        return records
    for path in sorted(root.rglob("*.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def _flat(record: dict[str, Any]) -> dict[str, Any]:
    result = record["result"]
    metrics = result["metrics"]
    return {
        "dataset": record["dataset"],
        "method": record["method_label"],
        "base_method": record["method"],
        "question_id": record["question_id"],
        "seed": record["seed"],
        "status": result["status"],
        **record["scores"],
        **metrics,
        "total_tokens": metrics["prompt_tokens"] + metrics["completion_tokens"],
        "max_intermediate_binding_size": max(metrics["intermediate_binding_sizes"], default=0),
        "mean_selectivity_error": _mean(metrics["slot_selectivity_errors"]),
    }


def _mean(values: list[float]) -> float | None:
    return float(np.mean(values)) if values else None


def aggregate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        row = _flat(record)
        grouped[(row["dataset"], row["method"])].append(row)
    output: list[dict[str, Any]] = []
    for (dataset, method), rows in sorted(grouped.items()):
        summary: dict[str, Any] = {
            "dataset": dataset,
            "method": method,
            "count": len(rows),
            "failed": sum(row["status"] in {"failed", "budget_exceeded"} for row in rows),
            "empty": sum(row["status"] == "empty" for row in rows),
            "success_rate": _mean([float(row["status"] == "ok") for row in rows]),
        }
        failures: dict[str, int] = defaultdict(int)
        for record in records:
            if record["dataset"] == dataset and record["method_label"] == method:
                error = record["result"].get("error")
                if error:
                    failures[error.split(":", 1)[0]] += 1
        summary["failure_categories"] = json.dumps(dict(sorted(failures.items())), ensure_ascii=False)
        for metric in METRICS:
            values = [float(row[metric]) for row in rows if row.get(metric) is not None]
            summary[metric] = _mean(values)
            if metric in {"wall_latency_ms", "provider_latency_ms"} and values:
                summary[f"{metric}_p50"] = float(np.percentile(values, 50))
                summary[f"{metric}_p95"] = float(np.percentile(values, 95))
        output.append(summary)
    return output


def macro_average(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    dataset_method_seed: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in summaries:
        dataset_method_seed[(row["dataset"], row["method"].split("@", 1)[0])].append(row)
    for (_dataset, method), rows in dataset_method_seed.items():
        for metric in METRICS:
            values = [float(row[metric]) for row in rows if row.get(metric) is not None]
            if values:
                grouped[method][metric].append(float(np.mean(values)))
    return [
        {"method": method, "dataset_count": len(grouped[method].get("primary_score", [])), **{metric: _mean(values) for metric, values in metrics.items()}}
        for method, metrics in sorted(grouped.items())
    ]


def seed_variance(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in summaries:
        if "@" in row["method"] and row.get("primary_score") is not None:
            grouped[(row["dataset"], row["method"].split("@", 1)[0])].append(float(row["primary_score"]))
    return [
        {
            "dataset": dataset,
            "method": method,
            "seed_count": len(values),
            "primary_mean": float(np.mean(values)),
            "primary_std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
            "primary_min": min(values),
            "primary_max": max(values),
        }
        for (dataset, method), values in sorted(grouped.items())
    ]


def _holm(pairs: list[dict[str, Any]]) -> None:
    ranked = sorted(enumerate(pairs), key=lambda item: item[1]["p_value"])
    adjusted = [0.0] * len(pairs)
    running = 0.0
    total = len(pairs)
    for rank, (index, pair) in enumerate(ranked):
        running = max(running, min(pair["p_value"] * (total - rank), 1.0))
        adjusted[index] = running
    for pair, value in zip(pairs, adjusted):
        pair["p_holm"] = value


def paired_bootstrap(records: list[dict[str, Any]], *, reference: str = "slotrag", iterations: int = 10_000, seed: int = 2027) -> list[dict[str, Any]]:
    rows = [_flat(record) for record in records]
    raw_values: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in rows:
        raw_values[(row["dataset"], row["base_method"], row["question_id"])].append(float(row["primary_score"]))
    by_dataset_method: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    for (dataset, method, question_id), values in raw_values.items():
        by_dataset_method[(dataset, method)][question_id] = float(np.mean(values))
    datasets = sorted({row["dataset"] for row in rows})
    methods = sorted({row["base_method"] for row in rows if row["base_method"] != reference})
    rng = np.random.default_rng(seed)
    comparisons: list[dict[str, Any]] = []
    for dataset in datasets:
        reference_values = by_dataset_method.get((dataset, reference), {})
        for method in methods:
            candidate_values = by_dataset_method.get((dataset, method), {})
            ids = sorted(set(reference_values) & set(candidate_values))
            if not ids:
                continue
            differences = np.asarray([reference_values[item] - candidate_values[item] for item in ids], dtype=float)
            indices = rng.integers(0, len(differences), size=(iterations, len(differences)))
            bootstrap = differences[indices].mean(axis=1)
            p_value = min(1.0, 2 * min(float(np.mean(bootstrap <= 0)), float(np.mean(bootstrap >= 0))))
            comparisons.append({
                "dataset": dataset,
                "reference": reference,
                "comparison": method,
                "count": len(ids),
                "mean_difference": float(differences.mean()),
                "ci_low": float(np.percentile(bootstrap, 2.5)),
                "ci_high": float(np.percentile(bootstrap, 97.5)),
                "p_value": p_value,
            })
    _holm(comparisons)
    return comparisons


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summarize_run(output_dir: Path, stage: str) -> dict[str, Any]:
    records = load_records(output_dir, stage)
    summaries = aggregate(records)
    macro = macro_average(summaries)
    variance = seed_variance(summaries)
    comparisons = paired_bootstrap(records) if records else []
    report = {
        "stage": stage,
        "record_count": len(records),
        "summary": summaries,
        "macro_average": macro,
        "seed_variance": variance,
        "paired_bootstrap": comparisons,
    }
    summary_dir = output_dir / "summaries" / stage
    summary_dir.mkdir(parents=True, exist_ok=True)
    (summary_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(summary_dir / "metrics.csv", summaries)
    _write_csv(summary_dir / "macro_metrics.csv", macro)
    _write_csv(summary_dir / "seed_variance.csv", variance)
    _write_csv(summary_dir / "paired_bootstrap.csv", comparisons)
    lines = ["# SlotRAG Experiment Report", "", f"- Stage: `{stage}`", f"- Records: {len(records)}", "", "## Method Summary", ""]
    for row in summaries:
        lines.append(f"- {row['dataset']} / {row['method']}: primary={row['primary_score']}, failed={row['failed']}/{row['count']}")
    (summary_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
