from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import ConfigurationError


class ServiceConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base_url: str
    model: str
    api_key_env: str
    timeout_seconds: float = Field(gt=0)
    max_retries: int = Field(default=2, ge=0, le=8)
    retry_backoff_seconds: float = Field(default=0.25, ge=0, le=30)

    @property
    def api_key(self) -> str:
        key = os.getenv(self.api_key_env, "").strip()
        if not key:
            raise ConfigurationError(f"missing API key environment variable: {self.api_key_env}")
        return key

    def url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"


class AgnesConfig(ServiceConfig):
    max_tokens: int = Field(default=2048, gt=0)
    temperature: float = Field(default=0.0, ge=0, le=2)


class EmbeddingConfig(ServiceConfig):
    dimension: int = Field(default=1024, gt=0)
    batch_size: int = Field(default=32, gt=0)


class RerankerConfig(ServiceConfig):
    enabled: bool = True
    top_n: int = Field(default=10, gt=0)


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bm25_k: int = Field(default=50, gt=0)
    dense_k: int = Field(default=50, gt=0)
    final_k: int = Field(default=10, gt=0)
    rrf_k: int = Field(default=60, gt=0)
    bm25_weight: float = Field(default=0.5, ge=0)
    dense_weight: float = Field(default=0.5, ge=0)
    chunk_tokens: int = Field(default=384, gt=0)
    chunk_overlap: int = Field(default=64, ge=0)
    sparse_index_mode: Literal["body", "bm25f"] = "body"
    sparse_title_weight: float = Field(default=2.0, gt=0, le=20)


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_replans: int = Field(default=16, gt=0)
    default_slot_cost: float = Field(default=1.0, gt=0)
    unbound_argument_cost: float = Field(default=2.0, gt=0)
    random_seed: int = 2027
    materialization_top_k: int = Field(default=5, gt=0, le=50)
    max_binding_contexts: int = Field(default=2, gt=0, le=50)
    max_retrieval_calls: int = Field(default=4, gt=0, le=100)
    entity_answer_contract: bool = Field(default=False)


class DataConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cache_dir: Path = Path("data/raw")
    processed_dir: Path = Path("data/processed")


class TraceConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    include_payloads: bool = False


class RateLimitConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider_rpm: float = Field(default=30.0, gt=0)
    operational_rpm: float = Field(default=20.0, gt=0)
    max_concurrency: int = Field(default=4, gt=0, le=4096)
    agnes_provider_rpm: float | None = Field(default=None, gt=0)
    agnes_operational_rpm: float | None = Field(default=None, gt=0)
    agnes_max_concurrency: int | None = Field(default=None, gt=0, le=4096)
    embedding_provider_rpm: float | None = Field(default=None, gt=0)
    embedding_operational_rpm: float | None = Field(default=None, gt=0)
    embedding_max_concurrency: int | None = Field(default=None, gt=0, le=4096)
    reranker_provider_rpm: float | None = Field(default=None, gt=0)
    reranker_operational_rpm: float | None = Field(default=None, gt=0)
    reranker_max_concurrency: int | None = Field(default=None, gt=0, le=4096)
    # Keep the provider rate-limiter state on NVMe (/tmp), not on /data (7200 RPM
    # HDD). The limiter writes a tiny .slot file per API call; under the HDD the
    # ext4 jbd2 journal commit stalls behind another job's heavy writeback, wedging
    # every benchmark call in jbd2_log_wait_commit. NVMe avoids the journal stall.
    state_dir: Path = Path("/tmp/tkde_runs/.rate-limits")

    @model_validator(mode="after")
    def validate_operational_limit(self) -> "RateLimitConfig":
        if self.operational_rpm > self.provider_rpm:
            raise ValueError("operational_rpm cannot exceed provider_rpm")
        for service in ("agnes", "embedding", "reranker"):
            provider_rpm = getattr(self, f"{service}_provider_rpm") or self.provider_rpm
            operational_rpm = getattr(self, f"{service}_operational_rpm") or self.operational_rpm
            if operational_rpm > provider_rpm:
                raise ValueError(f"{service}_operational_rpm cannot exceed {service}_provider_rpm")
        return self


class BenchmarkRunConfig(BaseModel):
    """Run-time throughput tuning for the benchmark runner (not a protocol field).

    ``parallel_questions`` controls how many questions execute concurrently per
    dataset×method×seed cell. ``sync_items`` controls whether per-question item
    snapshots are fsync'd before the atomic rename (False trades crash
    consistency for throughput — the kernel writeback-QoS layer serializes every
    fsync, which is the dominant serial cost on a spinning-hot path).
    """

    model_config = ConfigDict(extra="ignore")

    parallel_questions: int = Field(default=4, ge=1, le=256)
    sync_items: bool = False


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agnes: AgnesConfig
    embedding: EmbeddingConfig
    reranker: RerankerConfig
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    trace: TraceConfig = Field(default_factory=TraceConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    benchmark: BenchmarkRunConfig = Field(default_factory=BenchmarkRunConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AppConfig":
        config_path = Path(path)
        try:
            raw: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except OSError as exc:
            raise ConfigurationError(f"cannot read config {config_path}: {exc}") from exc
        except yaml.YAMLError as exc:
            raise ConfigurationError(f"invalid YAML in {config_path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigurationError("configuration root must be a mapping")
        cls._apply_env_overrides(raw)
        try:
            return cls.model_validate(raw)
        except Exception as exc:
            raise ConfigurationError(f"invalid configuration: {exc}") from exc

    @staticmethod
    def _apply_env_overrides(raw: dict[str, Any]) -> None:
        mappings = {
            "SLOTRAG_AGNES_BASE_URL": ("agnes", "base_url"),
            "SLOTRAG_AGNES_MODEL": ("agnes", "model"),
            "SLOTRAG_EMBEDDING_BASE_URL": ("embedding", "base_url"),
            "SLOTRAG_EMBEDDING_MODEL": ("embedding", "model"),
            "SLOTRAG_RERANKER_BASE_URL": ("reranker", "base_url"),
            "SLOTRAG_RERANKER_MODEL": ("reranker", "model"),
            "SLOTRAG_PROVIDER_RPM": ("rate_limit", "provider_rpm"),
            "SLOTRAG_OPERATIONAL_RPM": ("rate_limit", "operational_rpm"),
            "SLOTRAG_MAX_CONCURRENCY": ("rate_limit", "max_concurrency"),
            "SLOTRAG_AGNES_PROVIDER_RPM": ("rate_limit", "agnes_provider_rpm"),
            "SLOTRAG_AGNES_OPERATIONAL_RPM": ("rate_limit", "agnes_operational_rpm"),
            "SLOTRAG_AGNES_MAX_CONCURRENCY": ("rate_limit", "agnes_max_concurrency"),
            "SLOTRAG_EMBEDDING_PROVIDER_RPM": ("rate_limit", "embedding_provider_rpm"),
            "SLOTRAG_EMBEDDING_OPERATIONAL_RPM": ("rate_limit", "embedding_operational_rpm"),
            "SLOTRAG_EMBEDDING_MAX_CONCURRENCY": ("rate_limit", "embedding_max_concurrency"),
            "SLOTRAG_RERANKER_PROVIDER_RPM": ("rate_limit", "reranker_provider_rpm"),
            "SLOTRAG_RERANKER_OPERATIONAL_RPM": ("rate_limit", "reranker_operational_rpm"),
            "SLOTRAG_RERANKER_MAX_CONCURRENCY": ("rate_limit", "reranker_max_concurrency"),
            "SLOTRAG_TRACE_ENABLED": ("trace", "enabled"),
            "SLOTRAG_TRACE_INCLUDE_PAYLOADS": ("trace", "include_payloads"),
            "SLOTRAG_BENCHMARK_PARALLEL_QUESTIONS": ("benchmark", "parallel_questions"),
            "SLOTRAG_BENCHMARK_SYNC_ITEMS": ("benchmark", "sync_items"),
        }
        for env_name, (section, field) in mappings.items():
            value = os.getenv(env_name)
            if value:
                raw.setdefault(section, {})[field] = value

        qwen_base_url = os.getenv("QWEN36_BASE_URL")
        qwen_model = os.getenv("QWEN36_MODEL")
        qwen_api_key = os.getenv("QWEN36_API_KEY")
        if qwen_base_url:
            normalized = qwen_base_url.rstrip("/")
            suffix = "/chat/completions"
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]
            raw.setdefault("agnes", {})["base_url"] = normalized
            raw["agnes"]["api_key_env"] = "QWEN36_API_KEY" if qwen_api_key else raw["agnes"].get("api_key_env", "QWEN36_API_KEY")
        if qwen_model:
            raw.setdefault("agnes", {})["model"] = qwen_model

    def public_dict(self) -> dict[str, Any]:
        """Return a manifest-safe config with no secrets."""
        return self.model_dump(mode="json", exclude_none=True)
