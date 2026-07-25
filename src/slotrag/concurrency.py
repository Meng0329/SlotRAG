from __future__ import annotations

import copy
import fcntl
import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, ContextManager, IO, Iterator, Protocol, TypeVar


T = TypeVar("T")


class RateLimiter(Protocol):
    def acquire(self) -> float:
        """Wait for one request permit and return seconds spent waiting."""


class ConcurrencyLimiter(Protocol):
    def permit(self) -> ContextManager[None]:
        """Hold one in-flight request slot."""


@contextmanager
def exclusive_file_lock(path: str | Path) -> Iterator[None]:
    """Hold an advisory process-wide lock associated with a target path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_name(f".{target.name}.lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_write_json(path: str | Path, value: Any, *, ensure_ascii: bool = False, indent: int | None = 2) -> None:
    """Atomically replace a JSON file without sharing temporary filenames."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".part",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=ensure_ascii, indent=indent)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def locked_update_json(
    path: str | Path,
    updater: Callable[[T], T],
    *,
    default: T,
    ensure_ascii: bool = False,
    indent: int | None = 2,
) -> T:
    """Read, update, and atomically replace one JSON value under a file lock."""
    target = Path(path)
    with exclusive_file_lock(target):
        if target.exists():
            current = json.loads(target.read_text(encoding="utf-8"))
        else:
            current = copy.deepcopy(default)
        updated = updater(current)
        atomic_write_json(target, updated, ensure_ascii=ensure_ascii, indent=indent)
        return updated


class FileRateLimiter:
    """Cross-process request pacing backed by a small locked JSON state file."""

    def __init__(
        self,
        path: str | Path,
        *,
        rpm: float,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if rpm <= 0:
            raise ValueError("rpm must be greater than zero")
        self.path = Path(path)
        self.rpm = float(rpm)
        self.interval_seconds = 60.0 / self.rpm
        self._clock = clock
        self._sleeper = sleeper

    def acquire(self) -> float:
        with exclusive_file_lock(self.path):
            if self.path.exists():
                state = json.loads(self.path.read_text(encoding="utf-8"))
            else:
                state = {}
            now = self._clock()
            if "next_available_at" in state:
                next_available_at = float(state["next_available_at"])
            else:
                last_acquired_at = float(state.get("last_acquired_at", now - self.interval_seconds))
                next_available_at = last_acquired_at + self.interval_seconds
            scheduled_at = max(now, next_available_at)
            delay = scheduled_at - now
            atomic_write_json(
                self.path,
                {
                    "schema_version": 2,
                    "rpm": self.rpm,
                    "minimum_interval_seconds": self.interval_seconds,
                    "last_acquired_at": scheduled_at,
                    "next_available_at": scheduled_at + self.interval_seconds,
                    "acquisitions": int(state.get("acquisitions", 0)) + 1,
                },
            )
        if delay > 1e-9:
            self._sleeper(delay)
        return delay


class FileConcurrencyLimiter:
    """Cap in-flight work across processes with advisory lock slots."""

    def __init__(
        self,
        path: str | Path,
        *,
        limit: int,
        poll_seconds: float = 0.01,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be greater than zero")
        self.path = Path(path)
        self.limit = limit
        self.poll_seconds = poll_seconds
        self._sleeper = sleeper

    @contextmanager
    def permit(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        acquired: IO[str] | None = None
        while acquired is None:
            for index in range(self.limit):
                slot_path = self.path.with_name(f"{self.path.name}.{index:04d}.slot")
                handle = slot_path.open("a+", encoding="utf-8")
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    handle.close()
                    continue
                acquired = handle
                break
            if acquired is None:
                self._sleeper(self.poll_seconds)
        try:
            yield
        finally:
            fcntl.flock(acquired.fileno(), fcntl.LOCK_UN)
            acquired.close()
