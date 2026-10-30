"""Latency summaries for benchmark runs.

Percentiles use linear interpolation between the two nearest samples, matching
the convention requested for the benchmark runner.

This module deliberately does not re-export ``LatencySummary`` or
``summarize_latency`` from :mod:`ai_data_analyst.evaluation`: the package already
publishes a nearest-rank ``LatencySummary`` with different fields from
:mod:`ai_data_analyst.evaluation.report`, which the Auto-EDA runner uses.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LatencySummary(BaseModel):
    """Median, p95 and maximum of one timed phase, in milliseconds.

    A phase that never ran has ``count == 0`` and no percentile values.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    count: int = Field(ge=0)
    median_ms: float | None = Field(default=None, ge=0)
    p95_ms: float | None = Field(default=None, ge=0)
    max_ms: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        values = (self.median_ms, self.p95_ms, self.max_ms)
        if self.count == 0:
            if any(value is not None for value in values):
                raise ValueError("a zero-count summary has no percentile values")
        elif any(value is None for value in values):
            raise ValueError("a non-empty summary needs every percentile value")
        return self


def summarize_latency(values_ms: Sequence[float]) -> LatencySummary:
    """Summarize durations with linear-interpolation percentiles.

    Negative, NaN and infinite samples are rejected rather than silently
    summarized.
    """
    for value in values_ms:
        if not math.isfinite(value) or value < 0:
            raise ValueError("latency samples must be finite and non-negative")
    if not values_ms:
        return LatencySummary(count=0)
    ordered = sorted(values_ms)
    return LatencySummary(
        count=len(ordered),
        median_ms=_percentile(ordered, 0.5),
        p95_ms=_percentile(ordered, 0.95),
        max_ms=ordered[-1],
    )


def _percentile(ordered: Sequence[float], fraction: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight
