from __future__ import annotations

import re
import string
from collections import Counter
from typing import Any

from ..models import ExecutionResult, QuestionRecord


def normalize_answer(value: str) -> str:
    """HotpotQA/SQuAD normalization."""
    value = value.lower()
    value = "".join(char for char in value if char not in set(string.punctuation))
    value = re.sub(r"\b(a|an|the)\b", " ", value)
    return " ".join(value.split())


def exact_match(prediction: str, answers: list[str]) -> float:
    normalized = normalize_answer(prediction)
    return float(any(normalized == normalize_answer(answer) for answer in answers)) if answers else 0.0


def token_f1(prediction: str, answers: list[str]) -> float:
    predicted = normalize_answer(prediction).split()
    best = 0.0
    for answer in answers:
        gold = normalize_answer(answer).split()
        if not predicted or not gold:
            best = max(best, float(predicted == gold))
            continue
        common = sum((Counter(predicted) & Counter(gold)).values())
        if common:
            precision = common / len(predicted)
            recall = common / len(gold)
            best = max(best, 2 * precision * recall / (precision + recall))
    return best


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def _normalize_drop(value: str) -> str:
    normalized: list[str] = []
    for token in re.split(r"[\s-]+", value.lower()):
        if not _is_number(token):
            token = "".join(char for char in token if char not in set(string.punctuation))
        if token in {"a", "an", "the"} or not token:
            continue
        if _is_number(token):
            token = str(float(token))
        normalized.append(token)
    return " ".join(normalized)


def drop_scores(prediction: str, answers: list[str]) -> tuple[float, float]:
    pred_normalized = _normalize_drop(prediction)
    pred = set(pred_normalized.split())
    pred_numbers = {token for token in pred if _is_number(token)}
    best_em = 0.0
    best_f1 = 0.0
    for answer in answers:
        gold_normalized = _normalize_drop(answer)
        gold = set(gold_normalized.split())
        gold_numbers = {token for token in gold if _is_number(token)}
        best_em = max(best_em, float(pred_normalized == gold_normalized))
        if gold_numbers and not (gold_numbers & pred_numbers):
            continue
        common = len(pred & gold)
        if not pred or not gold:
            score = float(pred == gold)
        elif common:
            precision = common / len(pred)
            recall = common / len(gold)
            score = 2 * precision * recall / (precision + recall)
        else:
            score = 0.0
        best_f1 = max(best_f1, round(score, 2))
    return best_em, best_f1


def _boolean(value: str) -> bool | None:
    tokens = re.findall(r"[a-z]+", value.lower())
    for token in tokens:
        if token in {"true", "yes"}:
            return True
        if token in {"false", "no"}:
            return False
    return None


def boolean_accuracy(prediction: str, answers: list[str]) -> float:
    predicted = _boolean(prediction)
    gold = {_boolean(answer) for answer in answers}
    gold.discard(None)
    return float(predicted is not None and predicted in gold)


def evidence_scores(result: ExecutionResult, question: QuestionRecord) -> tuple[float | None, float | None]:
    if not question.metadata.get("evidence_available") or not question.gold_evidence:
        return None, None
    gold = set(question.gold_evidence)
    ranked: list[str] = []
    for item in result.evidence:
        canonical = item.source_id.split("#chunk-", 1)[0]
        if canonical not in ranked:
            ranked.append(canonical)
    found = set(ranked)
    recall = len(found & gold) / len(gold)
    reciprocal_rank = 0.0
    for rank, source_id in enumerate(ranked, start=1):
        if source_id in gold:
            reciprocal_rank = 1.0 / rank
            break
    return recall, reciprocal_rank


def score_record(dataset: str, question: QuestionRecord, result: ExecutionResult) -> dict[str, Any]:
    prediction = result.answer or ""
    em = exact_match(prediction, question.answers)
    f1 = token_f1(prediction, question.answers)
    accuracy: float | None = None
    drop_em: float | None = None
    drop_f1: float | None = None
    if dataset == "strategyqa":
        accuracy = boolean_accuracy(prediction, question.answers)
    if dataset == "drop":
        drop_em, drop_f1 = drop_scores(prediction, question.answers)
    evidence_recall, evidence_mrr = evidence_scores(result, question)
    primary = accuracy if dataset == "strategyqa" else drop_f1 if dataset == "drop" else f1
    return {
        "em": em,
        "f1": f1,
        "accuracy": accuracy,
        "drop_em": drop_em,
        "drop_f1": drop_f1,
        "primary_score": float(primary or 0.0),
        "evidence_recall": evidence_recall,
        "evidence_mrr": evidence_mrr,
    }
