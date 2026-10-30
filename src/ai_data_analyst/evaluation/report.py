"""Machine-readable evaluation report and metric helpers shared by Auto-EDA and SQL runs.

Pure and module-agnostic: no M1 or M2 imports, so either side can build a report with it.
Latency percentiles use the nearest-rank method on the raw samples (no interpolation).
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version

from pydantic import BaseModel, ConfigDict, Field

from .results import EvaluationResult

REPORT_SCHEMA_VERSION = "1.0"


class LatencySummary(BaseModel):
    """Median and p95 of one timed operation, in milliseconds."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    sample_count: int = Field(ge=1)
    median_ms: float = Field(ge=0)
    p95_ms: float = Field(ge=0)
    min_ms: float = Field(ge=0)
    max_ms: float = Field(ge=0)


class CaseFailure(BaseModel):
    """One benchmark case that did not pass, with the metric it counts against."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    case_id: str = Field(min_length=1)
    metric_name: str = Field(min_length=1)
    detail: str


class DatasetInfo(BaseModel):
    """The dataset a run used, so numbers are never separated from their data."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    name: str = Field(min_length=1)
    fingerprint: str = Field(min_length=1)
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)


class EvaluationReport(BaseModel):
    """Everything EVALUATION.md requires next to a published number."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    report_schema_version: str = REPORT_SCHEMA_VERSION
    benchmark_version: str = Field(min_length=1)
    subject: str = Field(min_length=1, description="What was evaluated, e.g. 'auto-eda'")
    method: str = Field(min_length=1)
    dataset: DatasetInfo
    environment: dict[str, str]
    metrics: tuple[EvaluationResult, ...]
    latency: dict[str, LatencySummary]
    failures: tuple[CaseFailure, ...] = ()


def ratio_result(
    metric_name: str, passed: int, total: int, benchmark_version: str
) -> EvaluationResult:
    """``passed / total`` as a metric. A ratio over zero cases is undefined, so it raises."""
    if total <= 0:
        raise ValueError(f"{metric_name}: no cases to score")
    if not 0 <= passed <= total:
        raise ValueError(f"{metric_name}: passed={passed} is outside 0..{total}")
    return EvaluationResult(
        metric_name=metric_name,
        value=passed / total,
        sample_count=total,
        benchmark_version=benchmark_version,
    )


def summarize_latency(samples_ms: Sequence[float]) -> LatencySummary:
    """Median and nearest-rank p95 of *samples_ms* (milliseconds)."""
    if not samples_ms:
        raise ValueError("no latency samples")
    ordered = sorted(samples_ms)
    rank = math.ceil(0.95 * len(ordered))
    return LatencySummary(
        sample_count=len(ordered),
        median_ms=statistics.median(ordered),
        p95_ms=ordered[rank - 1],
        min_ms=ordered[0],
        max_ms=ordered[-1],
    )


def library_versions(names: Sequence[str]) -> dict[str, str]:
    """Installed versions of *names*; a missing package is recorded as ``not installed``."""
    found: dict[str, str] = {}
    for name in names:
        try:
            found[name] = version(name)
        except PackageNotFoundError:
            found[name] = "not installed"
    return found
