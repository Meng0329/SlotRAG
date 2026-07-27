from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..errors import ConfigurationError
from .datasets import DATASETS
from .methods import METHODS, slotrag_compiler_signature


class StageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    split: Literal["train", "evaluation"]
    sample_size: int = Field(gt=0)
    methods: list[str] = Field(min_length=1)
    retrieval_protocol: Literal["local_context", "global_corpus"] = "local_context"
    retrieval_backend: Literal["hybrid", "bm25"] = "hybrid"
    shared_index_dir: Path | None = None
    max_corpus_build_minutes: float | None = Field(default=None, gt=0)
    frozen_plan_source: str | None = None
    frozen_plan_import_dir: Path | None = None
    sufficiency_calibrator_path: Path | None = None

    @model_validator(mode="after")
    def validate_methods(self) -> "StageConfig":
        unknown = sorted(set(self.methods) - set(METHODS))
        if unknown:
            raise ValueError(f"unknown methods: {', '.join(unknown)}")
        requires_sufficiency = any(METHODS[method].evidence_sufficiency for method in self.methods)
        if requires_sufficiency and self.sufficiency_calibrator_path is None:
            raise ValueError("sufficiency_calibrator_path is required by evidence-sufficiency methods")
        if not requires_sufficiency and self.sufficiency_calibrator_path is not None:
            raise ValueError("sufficiency_calibrator_path requires an evidence-sufficiency method")
        if self.frozen_plan_source is None:
            if self.frozen_plan_import_dir is not None:
                raise ValueError("frozen_plan_import_dir requires frozen_plan_source")
            return self
        if self.frozen_plan_source not in METHODS:
            raise ValueError(f"unknown frozen plan source: {self.frozen_plan_source}")
        if self.frozen_plan_source not in self.methods:
            raise ValueError("frozen_plan_source must also be listed in stage methods")
        source = METHODS[self.frozen_plan_source]
        if source.family != "slotrag":
            raise ValueError("frozen_plan_source must be a SlotRAG-family method")
        signature = slotrag_compiler_signature(source)
        incompatible = [
            method
            for method in self.methods
            if METHODS[method].family == "slotrag"
            and slotrag_compiler_signature(METHODS[method]) != signature
        ]
        if incompatible:
            raise ValueError(
                "frozen-plan SlotRAG methods must be compiler-compatible with "
                f"{self.frozen_plan_source}: {', '.join(incompatible)}"
            )
        return self


class BenchmarkBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(default=4, gt=0)
    max_llm_calls: int = Field(default=64, gt=0)
    max_retrieval_calls: int = Field(default=4, gt=0)
    question_timeout_seconds: float = Field(default=300.0, gt=0)


class BenchmarkSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmark_root: Path = Path("benchmark")
    output_root: Path = Path("runs")
    datasets: list[str] = Field(default_factory=lambda: list(DATASETS), min_length=1)
    seed: int = 2027
    random_seeds: list[int] = Field(default_factory=lambda: [2027, 2028, 2029, 2030, 2031], min_length=1)
    budget: BenchmarkBudget = Field(default_factory=BenchmarkBudget)
    stages: dict[str, StageConfig]

    @model_validator(mode="after")
    def validate_datasets(self) -> "BenchmarkSuite":
        unknown = sorted(set(self.datasets) - set(DATASETS))
        if unknown:
            raise ValueError(f"unknown datasets: {', '.join(unknown)}")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> "BenchmarkSuite":
        source = Path(path)
        try:
            raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
            return cls.model_validate(raw)
        except OSError as exc:
            raise ConfigurationError(f"cannot read benchmark config {source}: {exc}") from exc
        except (yaml.YAMLError, ValueError) as exc:
            raise ConfigurationError(f"invalid benchmark config {source}: {exc}") from exc

    def stage(self, name: str) -> StageConfig:
        try:
            return self.stages[name]
        except KeyError as exc:
            raise ConfigurationError(f"unknown benchmark stage: {name}") from exc
