"""Typed evaluation metrics shared by benchmark and scoring code."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EvaluationResult(BaseModel):
    """One measured metric: name, value, sample count and benchmark version."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    metric_name: str = Field(min_length=1)
    value: float
    sample_count: int = Field(ge=0)
    benchmark_version: str = Field(min_length=1)
