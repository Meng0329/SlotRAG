from __future__ import annotations

import hashlib
import heapq
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from ..data import question_from_record, sha256_file
from ..errors import DatasetError
from ..models import QuestionRecord


Stratifier = Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    train_file: str
    evaluation_file: str
    primary_metric: str
    stratifier: Stratifier
    evidence_mode: str = "unavailable"

    def path(self, root: Path, split: str) -> Path:
        relative = self.train_file if split == "train" else self.evaluation_file
        return root / relative


def _musique_hops(record: dict[str, Any]) -> str:
    prefix = str(record.get("id", "unknown")).split("__", 1)[0]
    if prefix.startswith("2hop"):
        return "2hop"
    if prefix.startswith("3hop"):
        return "3hop"
    if prefix.startswith("4hop"):
        return "4hop"
    return "unknown"


def _strategy_answer(record: dict[str, Any]) -> str:
    answers = record.get("answers", [])
    value = answers[0] if isinstance(answers, list) and answers else answers
    return str(value).strip().lower() or "unknown"


DATASETS: dict[str, DatasetSpec] = {
    "hotpotqa": DatasetSpec(
        name="hotpotqa",
        train_file="hotpotqa/hotpotqa_train.jsonl",
        evaluation_file="hotpotqa/hotpotqa_validation.jsonl",
        primary_metric="f1",
        stratifier=lambda record: str(record.get("type") or "unknown"),
        evidence_mode="hotpot_titles",
    ),
    "2wikimultihop": DatasetSpec(
        name="2wikimultihop",
        train_file="2wikimultihop/2wikimultihop_train.jsonl",
        evaluation_file="2wikimultihop/2wikimultihop_dev.jsonl",
        primary_metric="f1",
        stratifier=lambda record: str(record.get("type") or "unknown"),
        evidence_mode="pair_titles",
    ),
    "musique": DatasetSpec(
        name="musique",
        train_file="musique/musique_train.jsonl",
        evaluation_file="musique/musique_validation.jsonl",
        primary_metric="f1",
        stratifier=_musique_hops,
    ),
    "strategyqa": DatasetSpec(
        name="strategyqa",
        train_file="strategyqa/strategyqa_train.jsonl",
        evaluation_file="strategyqa/strategyqa_test.jsonl",
        primary_metric="accuracy",
        stratifier=_strategy_answer,
    ),
    "drop": DatasetSpec(
        name="drop",
        train_file="drop/drop_train.jsonl",
        evaluation_file="drop/drop_validation.jsonl",
        primary_metric="drop_f1",
        stratifier=lambda record: str(record.get("operation_type") or "unknown"),
    ),
}


def iter_jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    try:
        with path.open(encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise DatasetError(f"record {index} in {path} is not an object")
                yield index, value
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetError(f"cannot stream dataset {path}: {exc}") from exc


def _record_id(record: dict[str, Any], index: int) -> str:
    return str(record.get("id") or record.get("_id") or f"q-{index}")


def _gold_evidence(spec: DatasetSpec, record: dict[str, Any]) -> list[str]:
    raw = record.get("gold_evidence") or []
    if spec.evidence_mode == "hotpot_titles" and isinstance(raw, dict):
        return [f"{title}#0" for title in raw.get("title", [])]
    if spec.evidence_mode == "pair_titles" and isinstance(raw, list):
        return [f"{item[0]}#0" for item in raw if isinstance(item, list) and item]
    return []


def adapt_record(
    spec: DatasetSpec,
    record: dict[str, Any],
    index: int,
    *,
    split: str,
    exclude_facts: bool = False,
) -> QuestionRecord:
    normalized = dict(record)
    strategyqa_facts = spec.name == "strategyqa" and any(
        str(item.get("id", "")).startswith("fact_")
        for item in (record.get("passages") or [])
        if isinstance(item, dict)
    )
    if strategyqa_facts and exclude_facts:
        # StrategyQA's bundled facts are supporting facts, not a corpus available
        # to a shared query-time retriever. Keep them out of the shared index
        # (global_corpus); local_context keeps them as the question's own context.
        normalized["passages"] = []
    normalized["gold_evidence"] = _gold_evidence(spec, record)
    question = question_from_record(normalized, index=index)
    if spec.name == "drop":
        stratum_source = str(record.get("operation_type_source") or "legacy_unknown")
    else:
        stratum_source = "derived"
    metadata = {
        **question.metadata,
        "dataset": spec.name,
        "split": split,
        "stratum": spec.stratifier(record),
        "stratum_source": stratum_source,
        "primary_metric": spec.primary_metric,
        "evidence_available": bool(spec.evidence_mode != "unavailable"),
        "available_evidence": bool(question.passages) and spec.evidence_mode != "unavailable",
    }
    if spec.name == "drop":
        metadata["operation_type_source"] = stratum_source
    if strategyqa_facts:
        metadata.update({
            "available_evidence": False,
            "evidence_protocol": "gold_facts_only",
            "protocol_warning": "strategyqa_facts_are_not_shared_corpus",
        })
        if not exclude_facts:
            # local_context: facts are available as the question's own context
            metadata["available_evidence"] = True
    return question.model_copy(update={"metadata": metadata})


def load_all_questions(spec: DatasetSpec, root: Path, *, split: str) -> list[QuestionRecord]:
    """Load and adapt every record in a split for shared-corpus construction."""
    path = spec.path(root, split)
    if not path.exists():
        raise DatasetError(f"missing {spec.name} {split} file: {path}")
    return [
        adapt_record(spec, record, index, split=split, exclude_facts=True)
        for index, record in iter_jsonl(path)
    ]


def _allocate_quotas(counts: Counter[str], size: int) -> dict[str, int]:
    total = sum(counts.values())
    if size <= 0 or size > total:
        raise DatasetError(f"sample size must be between 1 and {total}")
    strata = sorted(counts)
    quotas = {key: 0 for key in strata}
    remaining = size
    if size >= len(strata):
        for key in strata:
            quotas[key] = 1
        remaining -= len(strata)
    if not remaining:
        return quotas
    available = {key: counts[key] - quotas[key] for key in strata}
    available_total = sum(available.values())
    fractions: list[tuple[float, str]] = []
    for key in strata:
        exact = remaining * available[key] / available_total if available_total else 0
        addition = min(int(exact), available[key])
        quotas[key] += addition
        fractions.append((exact - addition, key))
    left = size - sum(quotas.values())
    for _, key in sorted(fractions, key=lambda item: (-item[0], item[1])):
        if not left:
            break
        if quotas[key] < counts[key]:
            quotas[key] += 1
            left -= 1
    if left:
        for key in strata:
            take = min(left, counts[key] - quotas[key])
            quotas[key] += take
            left -= take
            if not left:
                break
    return quotas


def load_sample(spec: DatasetSpec, root: Path, *, split: str, size: int, seed: int) -> list[QuestionRecord]:
    path = spec.path(root, split)
    if not path.exists():
        raise DatasetError(f"missing {spec.name} {split} file: {path}")
    counts = Counter(spec.stratifier(record) for _, record in iter_jsonl(path))
    quotas = _allocate_quotas(counts, size)
    heaps: dict[str, list[tuple[int, str, int, dict[str, Any]]]] = {key: [] for key in quotas}
    for index, record in iter_jsonl(path):
        stratum = spec.stratifier(record)
        quota = quotas.get(stratum, 0)
        if not quota:
            continue
        record_id = _record_id(record, index)
        score = int.from_bytes(hashlib.sha256(f"{seed}:{spec.name}:{record_id}".encode()).digest(), "big")
        item = (-score, record_id, index, record)
        heap = heaps[stratum]
        if len(heap) < quota:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    selected = [item for heap in heaps.values() for item in heap]
    selected.sort(key=lambda item: (-item[0], item[1]))
    return [adapt_record(spec, record, index, split=split) for _, _, index, record in selected]


def audit_suite(root: Path, names: list[str] | None = None) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for name in names or list(DATASETS):
        spec = DATASETS[name]
        for split in ("train", "evaluation"):
            path = spec.path(root, split)
            count = 0
            invalid = 0
            strata: Counter[str] = Counter()
            if path.exists():
                for index, record in iter_jsonl(path):
                    count += 1
                    strata[spec.stratifier(record)] += 1
                    try:
                        adapt_record(spec, record, index, split=split)
                    except Exception:
                        invalid += 1
            reports.append({
                "dataset": name,
                "split": split,
                "path": str(path),
                "exists": path.exists(),
                "records": count,
                "invalid_records": invalid,
                "strata": dict(sorted(strata.items())),
                "sha256": sha256_file(path) if path.exists() else None,
            })
    return reports
