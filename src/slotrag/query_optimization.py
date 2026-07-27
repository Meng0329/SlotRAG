"""Provider-free query formulation and complementary-retrieval analysis helpers."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Literal, Sequence


QueryVariant = Literal[
    "slot",
    "question",
    "question_plus_slot",
    "lexical_slot",
    "question_plus_lexical_slot",
]

_PLAN_VARIABLE_RE = re.compile(r"(?:^|\s)\?[\w]+", re.UNICODE)


def canonical_evidence_id(source_id: object) -> str:
    """Map shared-corpus IDs back to the dataset adapter's source-passage ID."""

    value = str(source_id or "").split("#chunk-", 1)[0]
    if ":" not in value:
        return value
    _dataset, remainder = value.split(":", 1)
    suffix_stem = remainder.rsplit("#", 1)[0]
    for index, character in enumerate(remainder):
        if character != ":":
            continue
        candidate = remainder[index + 1 :]
        if remainder[:index] == candidate.rsplit("#", 1)[0]:
            return candidate
    parts = value.split(":")
    return parts[-1] if len(parts) >= 3 else value


def lexicalize_slot_query(slot_query: str) -> str:
    """Remove physical-plan syntax without using predicate-specific rewrites."""

    value = _PLAN_VARIABLE_RE.sub(" ", slot_query.replace("_", " "))
    return " ".join(value.split())


def formulate_query(question: str, slot_query: str, variant: QueryVariant) -> str:
    question = " ".join(question.split())
    slot_query = " ".join(slot_query.split())
    lexical_slot = lexicalize_slot_query(slot_query)
    if variant == "slot":
        return slot_query
    if variant == "question":
        return question
    if variant == "question_plus_slot":
        return " ".join(value for value in (question, slot_query) if value)
    if variant == "lexical_slot":
        return lexical_slot
    if variant == "question_plus_lexical_slot":
        return " ".join(value for value in (question, lexical_slot) if value)
    raise ValueError(f"unsupported query variant: {variant}")


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[str]],
    *,
    top_k: int,
    rrf_k: int = 60,
) -> list[str]:
    """Fuse identifiers while preserving deterministic ordering for exact ties."""

    scores: dict[str, float] = defaultdict(float)
    best_rank: dict[str, int] = {}
    for ranked in ranked_lists:
        for rank, source_id in enumerate(ranked, start=1):
            scores[source_id] += 1.0 / (rrf_k + rank)
            best_rank[source_id] = min(best_rank.get(source_id, rank), rank)
    return sorted(scores, key=lambda value: (-scores[value], best_rank[value], value))[:top_k]


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def _summarize_rows(
    rows: Sequence[dict[str, Any]],
    baseline_by_question: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    gain = tie = loss = 0
    for row in rows:
        key = (str(row["dataset"]), str(row["question_id"]))
        baseline = baseline_by_question[key]
        delta = float(row["recall"]) - float(baseline["recall"])
        if delta > 1e-12:
            gain += 1
        elif delta < -1e-12:
            loss += 1
        else:
            tie += 1
    count = len(rows)
    return {
        "question_count": count,
        "mean_recall": _ratio(sum(float(row["recall"]) for row in rows), count),
        "full_support_rate": _ratio(sum(bool(row["full_support"]) for row in rows), count),
        "any_support_rate": _ratio(sum(bool(row["any_support"]) for row in rows), count),
        "mean_extra_calls": _ratio(sum(int(row["extra_calls"]) for row in rows), count),
        "total_extra_calls": sum(int(row["extra_calls"]) for row in rows),
        "gain_tie_loss": {"gain": gain, "tie": tie, "loss": loss},
    }


def summarize_strategy_records(
    records: Sequence[dict[str, Any]],
    *,
    baseline_strategy: str = "slot",
) -> dict[str, dict[str, Any]]:
    """Summarize question-level evidence recovery and paired deltas."""

    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_strategy[str(record["strategy"])].append(record)
    if baseline_strategy not in by_strategy:
        raise ValueError(f"baseline strategy {baseline_strategy!r} is missing")
    baseline_by_question = {
        (str(row["dataset"]), str(row["question_id"])): row
        for row in by_strategy[baseline_strategy]
    }
    expected_keys = set(baseline_by_question)
    report: dict[str, dict[str, Any]] = {}
    for strategy, rows in sorted(by_strategy.items()):
        keys = {(str(row["dataset"]), str(row["question_id"])) for row in rows}
        if keys != expected_keys:
            raise ValueError(f"strategy {strategy!r} does not cover the baseline question set")
        summary = _summarize_rows(rows, baseline_by_question)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row["dataset"])].append(row)
        summary["by_dataset"] = {
            dataset: _summarize_rows(dataset_rows, baseline_by_question)
            for dataset, dataset_rows in sorted(grouped.items())
        }
        report[strategy] = summary
    return report


def select_development_strategy(
    report: dict[str, dict[str, Any]],
    *,
    baseline_strategy: str = "slot",
    retrieval_call_penalty: float = 0.02,
) -> tuple[str, list[str]]:
    """Freeze one strategy using only development quality-cost evidence.

    Full-support recovery is the primary target. A small explicit per-call penalty
    prevents an all-query strategy from winning on a negligible recall difference.
    """

    if baseline_strategy not in report:
        raise ValueError(f"baseline strategy {baseline_strategy!r} is missing")

    def key(strategy: str) -> tuple[float, float, int, float, str]:
        values = report[strategy]
        utility = float(values["mean_recall"]) - retrieval_call_penalty * float(
            values["mean_extra_calls"]
        )
        paired = values["gain_tie_loss"]
        return (
            utility,
            float(values["full_support_rate"]),
            int(paired["gain"]) - int(paired["loss"]),
            -float(values["mean_extra_calls"]),
            strategy,
        )

    ranking = sorted(report, key=key, reverse=True)
    return ranking[0], ranking
