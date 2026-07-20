from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Iterable

import httpx

from .errors import DatasetError
from .models import Passage, QuestionRecord


def chunk_passage(passage: Passage, *, chunk_tokens: int = 384, overlap: int = 64) -> list[Passage]:
    """Split a passage into deterministic word-token windows with provenance."""
    if chunk_tokens <= 0 or overlap < 0 or overlap >= chunk_tokens:
        raise ValueError("overlap must be non-negative and smaller than chunk_tokens")
    tokens = passage.text.split()
    if len(tokens) <= chunk_tokens:
        return [passage]
    step = chunk_tokens - overlap
    chunks: list[Passage] = []
    for offset, start in enumerate(range(0, len(tokens), step)):
        text = " ".join(tokens[start:start + chunk_tokens])
        if not text:
            break
        chunks.append(Passage(
            id=f"{passage.id}#chunk-{offset}",
            doc_id=passage.doc_id,
            text=text,
            metadata={**passage.metadata, "parent_passage_id": passage.id, "token_start": start, "token_end": min(start + chunk_tokens, len(tokens))},
        ))
        if start + chunk_tokens >= len(tokens):
            break
    return chunks


def chunk_passages(passages: Iterable[Passage], *, chunk_tokens: int = 384, overlap: int = 64) -> list[Passage]:
    result: list[Passage] = []
    for passage in passages:
        result.extend(chunk_passage(passage, chunk_tokens=chunk_tokens, overlap=overlap))
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_dataset(url: str, destination: Path, expected_sha256: str = "", timeout: float = 120.0) -> Path:
    if not url:
        raise DatasetError("dataset URL is empty; set data.qobench_url")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".part")
    try:
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as response:
            response.raise_for_status()
            with temp_path.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
        digest = sha256_file(temp_path)
        if expected_sha256 and digest.lower() != expected_sha256.lower():
            raise DatasetError(f"dataset checksum mismatch: expected {expected_sha256}, got {digest}")
        temp_path.replace(destination)
    except (OSError, httpx.HTTPError) as exc:
        temp_path.unlink(missing_ok=True)
        raise DatasetError(f"dataset download failed: {exc}") from exc
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return destination


def _read_json_records(path: Path) -> list[dict[str, Any]]:
    try:
        if path.suffix.lower() in {".jsonl", ".ndjson"}:
            return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DatasetError(f"cannot parse dataset {path}: {exc}") from exc
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("data", "questions", "records", "items"):
            if isinstance(value.get(key), list):
                return value[key]
    raise DatasetError(f"dataset {path} must contain a list of records")


def _passage_from_record(record: dict[str, Any], index: int) -> Passage:
    text = record.get("text") or record.get("context") or record.get("passage") or record.get("document")
    if isinstance(text, list):
        text = " ".join(str(item) for item in text)
    if not text:
        raise DatasetError(f"record {index} has no passage text")
    doc_id = str(record.get("doc_id") or record.get("document_id") or record.get("title") or f"doc-{index}")
    passage_id = str(record.get("id") or record.get("passage_id") or f"{doc_id}#0")
    return Passage(id=passage_id, doc_id=doc_id, text=str(text), metadata={k: v for k, v in record.items() if k not in {"text", "context", "passage", "document"}})


def load_questions(path: str | Path) -> list[QuestionRecord]:
    source = Path(path)
    if not source.exists():
        raise DatasetError(f"dataset path does not exist: {source}")
    records = _read_json_records(source)
    questions: list[QuestionRecord] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise DatasetError(f"record {index} is not an object")
        question = str(record.get("question") or record.get("query") or record.get("input") or "").strip()
        if not question:
            raise DatasetError(f"record {index} has no question")
        raw_passages = record.get("passages") or record.get("documents") or record.get("context") or []
        if isinstance(raw_passages, str):
            raw_passages = [{"text": raw_passages}]
        passages = [_passage_from_record(item, index * 10000 + offset) if isinstance(item, dict) else Passage(id=f"{index}#{offset}", text=str(item)) for offset, item in enumerate(raw_passages)]
        answers = record.get("answers") or record.get("answer") or []
        if isinstance(answers, str):
            answers = [answers]
        evidence = record.get("gold_evidence") or record.get("supporting_facts") or []
        if isinstance(evidence, dict):
            evidence = list(evidence)
        questions.append(QuestionRecord(
            id=str(record.get("id") or record.get("_id") or f"q-{index}"),
            question=question,
            passages=passages,
            answers=[str(answer) for answer in answers],
            gold_evidence=[str(item) for item in evidence],
            metadata={k: v for k, v in record.items() if k not in {"question", "query", "input", "passages", "documents", "context", "answers", "answer", "gold_evidence", "supporting_facts"}},
        ))
    return questions


class QOBenchAdapter:
    """Normalize a downloaded QO-Bench JSON/JSONL file into SlotRAG records.

    QO-Bench releases have used both ``documents`` and ``context`` names, so
    the adapter deliberately accepts the common wire variants while preserving
    unknown operation metadata for later evaluation.
    """

    def __init__(self, source: str | Path) -> None:
        self.source = Path(source)

    def load(self) -> list[QuestionRecord]:
        return load_questions(self.source)

    def normalize(self, destination: str | Path) -> Path:
        return normalize_jsonl(self.load(), destination)


def normalize_jsonl(records: Iterable[QuestionRecord], destination: str | Path) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.model_dump_json() + "\n")
    return path


def extract_archive(archive: str | Path, destination: str | Path) -> Path:
    source = Path(archive)
    target = Path(destination)
    target.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() != ".zip":
        return source
    try:
        with zipfile.ZipFile(source) as zf:
            for member in zf.infolist():
                member_path = (target / member.filename).resolve()
                if target.resolve() not in member_path.parents and member_path != target.resolve():
                    raise DatasetError("archive contains an unsafe path")
            zf.extractall(target)
    except (OSError, zipfile.BadZipFile) as exc:
        raise DatasetError(f"cannot extract dataset archive: {exc}") from exc
    return target
