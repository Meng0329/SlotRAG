from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import AppConfig


@dataclass
class ServiceStatus:
    name: str
    ok: bool
    message: str


def _post_check(name: str, url: str, key: str, payload: dict, timeout: float) -> ServiceStatus:
    try:
        response = httpx.post(url, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        return ServiceStatus(name, False, f"request failed: {exc.__class__.__name__}")
    if response.status_code >= 400:
        return ServiceStatus(name, False, f"HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        return ServiceStatus(name, False, "response was not JSON")
    if name == "agnes" and (not isinstance(body, dict) or not isinstance(body.get("choices"), list)):
        return ServiceStatus(name, False, "response schema missing choices[]")
    if name == "embedding":
        rows = body.get("data") if isinstance(body, dict) else None
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict) or not isinstance(rows[0].get("embedding"), list):
            return ServiceStatus(name, False, "response schema missing data[].embedding[]")
    if name == "reranker":
        rows = body.get("results") if isinstance(body, dict) else body
        if not isinstance(rows, list):
            return ServiceStatus(name, False, "response schema missing rerank results[]")
    return ServiceStatus(name, True, f"HTTP {response.status_code}")


def check_services(config: AppConfig) -> list[ServiceStatus]:
    statuses: list[ServiceStatus] = []
    for name, service, payload, path in [
        ("agnes", config.agnes, {"model": config.agnes.model, "messages": [{"role": "user", "content": "Return a short health check."}], "max_tokens": 8, "temperature": 0}, "chat/completions"),
        ("embedding", config.embedding, {"model": config.embedding.model, "input": "health", "encoding_format": "float"}, "embeddings"),
        ("reranker", config.reranker, {"model": config.reranker.model, "query": "health", "documents": ["health"] , "top_n": 1}, "rerank"),
    ]:
        try:
            key = service.api_key
        except Exception as exc:
            statuses.append(ServiceStatus(name, False, str(exc)))
            continue
        statuses.append(_post_check(name, service.url(path), key, payload, service.timeout_seconds))
    return statuses
