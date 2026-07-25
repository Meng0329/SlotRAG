"""Optional, secret-free provider request/response traces for experiments."""

from __future__ import annotations

import contextvars
import hashlib
import json
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


_TRACE_SETTINGS: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "slotrag_trace_settings", default=None
)
_WRITE_LOCK = threading.Lock()
_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "password",
    "secret",
    "token",
}


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).casefold().replace("-", "_")
            cleaned[str(key)] = "<redacted>" if normalized in _SENSITIVE_KEYS else _sanitize(item)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _canonical(value: Any) -> str:
    return json.dumps(_sanitize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


@contextmanager
def provider_trace(
    path: Path | None,
    *,
    include_payloads: bool = False,
) -> Iterator[None]:
    """Attach a trace destination to provider calls in the current context."""
    if path is None:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # Materialize the trace file even when the guarded operation times out
    # before the first provider event. This keeps zero-event attempts
    # auditable without inventing a provider request.
    path.touch(exist_ok=True)
    token = _TRACE_SETTINGS.set({"path": path, "include_payloads": include_payloads})
    try:
        yield
    finally:
        _TRACE_SETTINGS.reset(token)


def record_provider_event(
    *,
    service: str,
    url: str,
    request: Any,
    response: Any = None,
    status_code: int | None = None,
    latency_ms: float | None = None,
    retry_index: int = 0,
    request_id: str | None = None,
    error: str | None = None,
) -> None:
    settings = _TRACE_SETTINGS.get()
    if settings is None:
        return
    sanitized_request = _sanitize(request)
    sanitized_response = _sanitize(response)
    event: dict[str, Any] = {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "service": service,
        "url": url,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "retry_index": retry_index,
        "request_id": request_id,
        "request_sha256": hashlib.sha256(_canonical(request).encode("utf-8")).hexdigest(),
        "response_sha256": hashlib.sha256(_canonical(response).encode("utf-8")).hexdigest(),
        "error": error,
    }
    if settings["include_payloads"]:
        event["request"] = sanitized_request
        event["response"] = sanitized_response
    else:
        event["request"] = None
        event["response"] = None
    path = Path(settings["path"])
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _WRITE_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)


def trace_metadata(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"enabled": False, "event_count": 0, "path": None, "sha256": None}
    data = path.read_bytes()
    return {
        "enabled": True,
        "event_count": sum(1 for line in data.splitlines() if line.strip()),
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
