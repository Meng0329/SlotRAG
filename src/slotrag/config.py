from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .errors import ConfigurationError


class ServiceConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base_url: str
    model: str
    api_key_env: str
    timeout_seconds: float = Field(gt=0)

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


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_replans: int = Field(default=16, gt=0)
    default_slot_cost: float = Field(default=1.0, gt=0)
    unbound_argument_cost: float = Field(default=2.0, gt=0)
    random_seed: int = 2027


class DataConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cache_dir: Path = Path("data/raw")
    processed_dir: Path = Path("data/processed")
    qobench_url: str = ""
    qobench_sha256: str = ""


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agnes: AgnesConfig
    embedding: EmbeddingConfig
    reranker: RerankerConfig
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    data: DataConfig = Field(default_factory=DataConfig)

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
        }
        for env_name, (section, field) in mappings.items():
            value = os.getenv(env_name)
            if value:
                raw.setdefault(section, {})[field] = value

    def public_dict(self) -> dict[str, Any]:
        """Return a manifest-safe config with no secrets."""
        return self.model_dump(mode="json", exclude_none=True)
