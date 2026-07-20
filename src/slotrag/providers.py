from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Any, Iterable

import httpx
from pydantic import BaseModel, Field

from .config import AgnesConfig, EmbeddingConfig, RerankerConfig
from .errors import ProviderError, SchemaError


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ToolCall(BaseModel):
    id: str | None = None
    name: str
    arguments: dict[str, Any]


class ChatResult(BaseModel):
    request_id: str | None = None
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: Usage = Field(default_factory=Usage)
    latency_ms: float = 0.0


class RerankResult(BaseModel):
    index: int = Field(ge=0)
    score: float
    document: str
    meta_info: dict[str, Any] = Field(default_factory=dict)


class _HTTPProvider:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def _post(self, url: str, key: str, payload: dict[str, Any], timeout: float) -> Any:
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        started = time.perf_counter()
        try:
            if self._client is None:
                response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
            else:
                response = self._client.post(url, headers=headers, json=payload, timeout=timeout)
        except httpx.HTTPError as exc:
            raise ProviderError(f"request failed for {url}: {exc.__class__.__name__}") from exc
        elapsed = (time.perf_counter() - started) * 1000
        if response.status_code >= 400:
            body = response.text[:300].replace("\n", " ")
            raise ProviderError(f"provider returned HTTP {response.status_code}: {body}")
        try:
            return response.json(), elapsed
        except ValueError as exc:
            raise SchemaError(f"provider returned non-JSON response from {url}") from exc


class AgnesClient(_HTTPProvider):
    def __init__(self, config: AgnesConfig, client: httpx.Client | None = None) -> None:
        super().__init__(client)
        self.config = config

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        body, elapsed = self._post(self.config.url("chat/completions"), self.config.api_key, payload, self.config.timeout_seconds)
        if not isinstance(body, dict):
            raise SchemaError("Agnes response must be an object")
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise SchemaError("Agnes response has no choices")
        choice = choices[0]
        message = choice.get("message") or {}
        if not isinstance(message, dict):
            raise SchemaError("Agnes choice message must be an object")
        calls: list[ToolCall] = []
        for raw_call in message.get("tool_calls") or []:
            if not isinstance(raw_call, dict):
                raise SchemaError("Agnes tool call must be an object")
            function = raw_call.get("function") or {}
            if not isinstance(function, dict) or not function.get("name"):
                raise SchemaError("Agnes tool call has no function name")
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError as exc:
                    raise SchemaError("Agnes tool arguments are not valid JSON") from exc
            if not isinstance(arguments, dict):
                raise SchemaError("Agnes tool arguments must be an object")
            calls.append(ToolCall(id=raw_call.get("id"), name=function["name"], arguments=arguments))
        usage_raw = body.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(usage_raw.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage_raw.get("completion_tokens", 0) or 0),
        )
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise SchemaError("Agnes message content must be a string or null")
        return ChatResult(
            request_id=body.get("id"),
            content=content,
            tool_calls=calls,
            finish_reason=choice.get("finish_reason"),
            usage=usage,
            latency_ms=elapsed,
        )

    def require_tool(self, result: ChatResult, name: str) -> dict[str, Any]:
        calls = [call for call in result.tool_calls if call.name == name]
        if len(calls) != 1:
            raise SchemaError(f"expected exactly one Agnes tool call named {name}")
        return calls[0].arguments


class EmbeddingClient(_HTTPProvider):
    def __init__(self, config: EmbeddingConfig, client: httpx.Client | None = None) -> None:
        super().__init__(client)
        self.config = config

    def embed(self, texts: str | list[str]) -> list[list[float]]:
        inputs = [texts] if isinstance(texts, str) else list(texts)
        if not inputs or any(not isinstance(item, str) or not item for item in inputs):
            raise ValueError("embedding input must contain non-empty strings")
        body, _ = self._post(
            self.config.url("embeddings"),
            self.config.api_key,
            {"model": self.config.model, "input": inputs if len(inputs) > 1 else inputs[0], "encoding_format": "float"},
            self.config.timeout_seconds,
        )
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise SchemaError("embedding response must contain a data list")
        rows = body["data"]
        if len(rows) != len(inputs):
            raise SchemaError("embedding response count does not match input count")
        ordered: list[list[float] | None] = [None] * len(inputs)
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("index"), int):
                raise SchemaError("embedding row has no integer index")
            index = row["index"]
            vector = row.get("embedding")
            if index < 0 or index >= len(inputs) or not isinstance(vector, list):
                raise SchemaError("embedding row has an invalid vector or index")
            if len(vector) != self.config.dimension or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in vector):
                raise SchemaError(f"embedding vector must contain {self.config.dimension} finite numbers")
            ordered[index] = [float(v) for v in vector]
        if any(vector is None for vector in ordered):
            raise SchemaError("embedding response contains duplicate or missing indexes")
        return [vector for vector in ordered if vector is not None]


class RerankerClient(_HTTPProvider):
    def __init__(self, config: RerankerConfig, client: httpx.Client | None = None) -> None:
        super().__init__(client)
        self.config = config

    def rerank(self, query: str, documents: list[str], top_n: int | None = None) -> list[RerankResult]:
        if not query or not documents:
            return []
        body, _ = self._post(
            self.config.url("rerank"),
            self.config.api_key,
            {"model": self.config.model, "query": query, "documents": documents, "top_n": top_n or self.config.top_n},
            self.config.timeout_seconds,
        )
        rows = body.get("results") if isinstance(body, dict) else body
        if not isinstance(rows, list):
            raise SchemaError("reranker response must be an array or {results: array}")
        results: list[RerankResult] = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("index"), int):
                raise SchemaError("reranker row has no integer index")
            index = row["index"]
            if index < 0 or index >= len(documents):
                raise SchemaError("reranker row has an invalid document index")
            results.append(RerankResult(index=index, score=float(row.get("score", 0.0)), document=documents[index], meta_info=row.get("meta_info") or {}))
        return results


def provider_clients(config: Any, client: httpx.Client | None = None) -> tuple[AgnesClient, EmbeddingClient, RerankerClient]:
    return AgnesClient(config.agnes, client), EmbeddingClient(config.embedding, client), RerankerClient(config.reranker, client)
