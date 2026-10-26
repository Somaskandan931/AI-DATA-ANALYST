"""Typed evaluation metrics shared by benchmark and scoring code."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """One measured metric: name, value, sample count and benchmark version."""

    metric_name: str
    value: float
    sample_count: int
    benchmark_version: str

    def __post_init__(self) -> None:
        if not self.metric_name:
            raise ValueError("metric_name must not be empty")
        if not math.isfinite(self.value):
            raise ValueError("value must be finite")
        if self.sample_count < 0:
            raise ValueError("sample_count must be non-negative")
        if not self.benchmark_version:
            raise ValueError("benchmark_version must not be empty")
