from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Iterable

from .models import ExecutionResult, QuestionRecord


def normalize_answer(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def exact_match(prediction: str, answers: list[str]) -> float:
    normalized = normalize_answer(prediction)
    return float(any(normalized == normalize_answer(answer) for answer in answers)) if answers else 0.0


def token_f1(prediction: str, answers: list[str]) -> float:
    prediction_tokens = normalize_answer(prediction).split()
    if not prediction_tokens or not answers:
        return 0.0
    best = 0.0
    for answer in answers:
        gold_tokens = normalize_answer(answer).split()
        if not gold_tokens:
            continue
        common = sum((__import__("collections").Counter(prediction_tokens) & __import__("collections").Counter(gold_tokens)).values())
        if not common:
            continue
        precision = common / len(prediction_tokens)
        recall = common / len(gold_tokens)
        best = max(best, 2 * precision * recall / (precision + recall))
    return best


def evidence_recall(result: ExecutionResult, question: QuestionRecord) -> float:
    if not question.gold_evidence:
        return 0.0
    found = {item.source_id for item in result.evidence}
    gold = set(question.gold_evidence)
    if not gold:
        return 0.0
    return len(found & gold) / len(gold)


def result_row(question: QuestionRecord, result: ExecutionResult) -> dict[str, object]:
    return {
        "question_id": question.id,
        "question": question.question,
        "status": result.status,
        "answer": result.answer or "",
        "em": exact_match(result.answer or "", question.answers),
        "f1": token_f1(result.answer or "", question.answers),
        "evidence_recall": evidence_recall(result, question),
        "order": "|".join(result.order),
        "rows": len(result.rows),
        "documents_accessed": result.metrics.documents_accessed,
        "passages_processed": result.metrics.passages_processed,
        "llm_calls": result.metrics.llm_calls,
        "prompt_tokens": result.metrics.prompt_tokens,
        "completion_tokens": result.metrics.completion_tokens,
        "latency_ms": result.metrics.latency_ms,
        "reoptimizations": result.metrics.reoptimizations,
        "error": result.error or "",
    }


def write_jsonl(rows: Iterable[dict[str, object]], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return destination


def write_csv(rows: list[dict[str, object]], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        destination.write_text("\n", encoding="utf-8")
        return destination
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return destination


def summarize(rows: list[dict[str, object]]) -> dict[str, float | int]:
    if not rows:
        return {"count": 0, "em": 0.0, "f1": 0.0, "evidence_recall": 0.0}
    def mean(key: str) -> float:
        return sum(float(row.get(key, 0.0) or 0.0) for row in rows) / len(rows)
    return {
        "count": len(rows),
        "em": mean("em"),
        "f1": mean("f1"),
        "evidence_recall": mean("evidence_recall"),
        "documents_accessed": mean("documents_accessed"),
        "passages_processed": mean("passages_processed"),
        "llm_calls": mean("llm_calls"),
        "latency_ms": mean("latency_ms"),
    }
