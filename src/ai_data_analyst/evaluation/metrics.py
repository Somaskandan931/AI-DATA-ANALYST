"""Per-phase latency summaries for benchmark runs.

Percentiles use linear interpolation between the two nearest samples, matching
the convention requested for the benchmark runner.

These types are distinct from the nearest-rank ``LatencySummary`` and
``summarize_latency`` in :mod:`ai_data_analyst.evaluation.report`, which the
Auto-EDA runner uses and which have different fields. They are not re-exported
from :mod:`ai_data_analyst.evaluation`; the two summaries will be reconciled
with the M1 owner before either becomes the single project-wide convention.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = ["PhaseLatency", "linear_percentile", "summarize_phase_latency"]


class PhaseLatency(BaseModel):
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


def summarize_phase_latency(values_ms: Sequence[float]) -> PhaseLatency:
    """Summarize durations with linear-interpolation percentiles.

    Negative, NaN and infinite samples are rejected rather than silently
    summarized.
    """
    for value in values_ms:
        if not math.isfinite(value) or value < 0:
            raise ValueError("latency samples must be finite and non-negative")
    if not values_ms:
        return PhaseLatency(count=0)
    ordered = sorted(values_ms)
    return PhaseLatency(
        count=len(ordered),
        median_ms=_percentile(ordered, 0.5),
        p95_ms=_percentile(ordered, 0.95),
        max_ms=ordered[-1],
    )


def linear_percentile(values: Sequence[float], percent: float) -> float:
    """The *percent* percentile (0..100) of *values*, using linear interpolation."""
    if not values:
        raise ValueError("at least one value is required")
    for value in values:
        if not math.isfinite(value):
            raise ValueError("percentile values must be finite")
    if not math.isfinite(percent) or not 0 <= percent <= 100:
        raise ValueError("percent must be finite and between 0 and 100")
    return _percentile(sorted(values), percent / 100)


def _percentile(ordered: Sequence[float], fraction: float) -> float:
    if not 0 <= fraction <= 1:
        raise ValueError("fraction must be between 0 and 1")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight
