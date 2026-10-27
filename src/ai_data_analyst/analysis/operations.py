"""Deterministic implementations of the allow-listed operations (EDA-06).

The registry :data:`OPERATIONS` is the allow-list: a step runs only if its ``operation`` is a
key here, and each function receives already-validated parameters. Nothing in this module
evaluates text as code. Conventions match profiling: sample std (ddof=1), linear-interpolation
quartiles, IQR outlier rule, values rounded to 6 decimals, undefined values are ``None``.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from importlib.metadata import version
from typing import Any

import numpy as np
import pandas as pd
from pydantic import JsonValue

from ..models import DatasetProfile
from ..security import LimitsConfig
from .artifact import AnalysisArtifact, Provenance
from .plan import (
    AnalysisPlan,
    AnalysisStep,
    CorrelationParams,
    DistributionParams,
    GroupedAggregationParams,
    OperationName,
    OutlierSummaryParams,
    SummaryStatsParams,
    step_columns,
    validate_plan,
)

_DECIMALS = 6


class ExecutionTimeError(RuntimeError):
    """The plan exceeded ``max_execution_seconds`` between steps."""


class OperationOutput:
    """Result of one operation before it is wrapped into an artifact."""

    __slots__ = ("result", "rows_used", "warnings")

    def __init__(self, result: dict[str, JsonValue], rows_used: int, warnings: list[str]) -> None:
        self.result = result
        self.rows_used = rows_used
        self.warnings = warnings


def _num(value: Any) -> float | None:
    """Round to 6 decimals; NaN and infinity become ``None``."""
    if value is None:
        return None
    number = float(value)
    return round(number, _DECIMALS) if math.isfinite(number) else None


def _present(frame: pd.DataFrame, column: str) -> np.ndarray[Any, np.dtype[np.float64]]:
    return frame[column].dropna().to_numpy(dtype=np.float64)


def _summary_stats(frame: pd.DataFrame, params: SummaryStatsParams) -> OperationOutput:
    stats: dict[str, JsonValue] = {}
    warnings: list[str] = []
    for name in params.columns:
        values = _present(frame, name)
        missing = len(frame) - values.size
        if values.size == 0:
            stats[name] = {"count": 0, "missing": missing}
            warnings.append(f"{name}: no non-missing values")
            continue
        q1, median, q3 = (float(x) for x in np.percentile(values, [25, 50, 75]))
        stats[name] = {
            "count": int(values.size),
            "missing": missing,
            "mean": _num(values.mean()),
            "std": _num(np.std(values, ddof=1)) if values.size > 1 else None,
            "min": _num(values.min()),
            "q1": _num(q1),
            "median": _num(median),
            "q3": _num(q3),
            "max": _num(values.max()),
        }
        if missing:
            warnings.append(f"{name}: {missing} missing values excluded")
    return OperationOutput({"columns": stats}, len(frame), warnings)


_AGG_FUNCTIONS: dict[str, str] = {
    "count": "count",
    "mean": "mean",
    "median": "median",
    "sum": "sum",
    "min": "min",
    "max": "max",
    "std": "std",
}


def _key_value(value: Any) -> JsonValue:
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, np.bool_ | bool):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    return str(value)


def _grouped_aggregation(frame: pd.DataFrame, params: GroupedAggregationParams) -> OperationOutput:
    warnings: list[str] = []
    keys = list(params.group_by)
    with_keys = frame.dropna(subset=keys)
    dropped = len(frame) - len(with_keys)
    if dropped:
        warnings.append(f"{dropped} rows with a missing group key were excluded")
    value = params.value_column
    numeric_value = pd.api.types.is_float_dtype(with_keys[value])
    grouped = with_keys.groupby(keys, sort=True, observed=True)[value]
    aggregated = grouped.agg([_AGG_FUNCTIONS[a] for a in params.aggregations])
    missing_values = int(with_keys[value].isna().sum())
    if missing_values:
        warnings.append(f"{value}: {missing_values} missing values excluded from aggregations")
    total_groups = len(aggregated)
    shown = aggregated.iloc[: params.max_groups]
    groups: list[JsonValue] = []
    for index, row in shown.iterrows():
        parts = index if isinstance(index, tuple) else (index,)
        entry: dict[str, JsonValue] = {
            "keys": {k: _key_value(v) for k, v in zip(keys, parts, strict=True)}
        }
        for agg in params.aggregations:
            cell = row[agg]
            entry[agg] = int(cell) if agg == "count" else (_num(cell) if numeric_value else None)
        groups.append(entry)
    truncated = total_groups > params.max_groups
    if truncated:
        warnings.append(f"showing the first {params.max_groups} of {total_groups} groups")
    result: dict[str, JsonValue] = {
        "group_by": [*keys],
        "value_column": value,
        "aggregations": [*params.aggregations],
        "total_groups": total_groups,
        "truncated": truncated,
        "groups": groups,
    }
    return OperationOutput(result, len(with_keys), warnings)


def _correlation(frame: pd.DataFrame, params: CorrelationParams) -> OperationOutput:
    names = list(params.columns)
    subset = frame[names]
    matrix = subset.corr(method=params.method, min_periods=2)
    present = subset.notna().astype(int)
    pair_counts = present.T.to_numpy() @ present.to_numpy()
    warnings: list[str] = []
    rows: list[JsonValue] = []
    for i, left in enumerate(names):
        row: list[JsonValue] = []
        for j, right in enumerate(names):
            cell = _num(matrix.iloc[i, j])
            row.append(cell)
            if cell is None and i < j:
                warnings.append(f"correlation of {left} and {right} is undefined")
        rows.append(row)
    if (pair_counts < len(frame)).any():
        warnings.append("pairs with a missing value are excluded pairwise")
    result: dict[str, JsonValue] = {
        "method": params.method,
        "columns": [*names],
        "matrix": rows,
        "pair_counts": [[int(c) for c in line] for line in pair_counts],
    }
    return OperationOutput(result, int(subset.notna().all(axis=1).sum()), warnings)


def _distribution(frame: pd.DataFrame, params: DistributionParams) -> OperationOutput:
    cells = frame[params.column].dropna()
    missing = len(frame) - len(cells)
    warnings = [f"{params.column}: {missing} missing values excluded"] if missing else []
    if pd.api.types.is_float_dtype(cells):
        values = cells.to_numpy(dtype=np.float64)
        edges: list[float] = []
        counts: list[int] = []
        if values.size:
            hist, bin_edges = np.histogram(values, bins=params.bins)
            edges, counts = [float(e) for e in bin_edges], [int(c) for c in hist]
        result: dict[str, JsonValue] = {
            "kind": "histogram",
            "column": params.column,
            "missing": missing,
            "bin_edges": [_num(e) for e in edges],
            "counts": [*counts],
        }
        return OperationOutput(result, int(values.size), warnings)
    tally = cells.map(_key_value).astype(str).value_counts()
    ordered = sorted(tally.items(), key=lambda item: (-int(item[1]), str(item[0])))
    shown: list[JsonValue] = [
        {"value": str(k), "count": int(c)} for k, c in ordered[: params.top_n]
    ]
    if len(ordered) > params.top_n:
        warnings.append(f"showing the {params.top_n} most frequent of {len(ordered)} values")
    result = {
        "kind": "categories",
        "column": params.column,
        "missing": missing,
        "distinct": len(ordered),
        "values": shown,
    }
    return OperationOutput(result, len(cells), warnings)


def _outlier_summary(frame: pd.DataFrame, params: OutlierSummaryParams) -> OperationOutput:
    report: dict[str, JsonValue] = {}
    warnings: list[str] = []
    for name in params.columns:
        values = _present(frame, name)
        if values.size == 0:
            report[name] = {"count": 0}
            warnings.append(f"{name}: no non-missing values")
            continue
        q1, q3 = (float(x) for x in np.percentile(values, [25, 75]))
        spread = q3 - q1
        low, high = q1 - params.iqr_factor * spread, q3 + params.iqr_factor * spread
        below, above = int((values < low).sum()), int((values > high).sum())
        report[name] = {
            "count": int(values.size),
            "q1": _num(q1),
            "q3": _num(q3),
            "lower_bound": _num(low),
            "upper_bound": _num(high),
            "below_lower": below,
            "above_upper": above,
            "outlier_count": below + above,
            "outlier_fraction": _num((below + above) / values.size),
        }
    result: dict[str, JsonValue] = {"iqr_factor": params.iqr_factor, "columns": report}
    return OperationOutput(result, len(frame), warnings)


OPERATIONS: dict[OperationName, Callable[[pd.DataFrame, Any], OperationOutput]] = {
    "summary_stats": _summary_stats,
    "grouped_aggregation": _grouped_aggregation,
    "correlation": _correlation,
    "distribution": _distribution,
    "outlier_summary": _outlier_summary,
}


def _library_versions() -> dict[str, str]:
    return {name: version(name) for name in ("pandas", "numpy", "scipy", "scikit-learn")}


def execute_step(
    step: AnalysisStep, frame: pd.DataFrame, profile: DatasetProfile
) -> AnalysisArtifact:
    """Run one validated step on *frame* and wrap the result with provenance."""
    function = OPERATIONS.get(step.operation)
    if function is None:  # unreachable for validated plans; fail closed anyway
        raise ValueError(f"operation {step.operation!r} is not allow-listed")
    output = function(frame, step)
    return AnalysisArtifact(
        operation=step.operation,
        input_columns=step_columns(step),
        parameters=step.model_dump(mode="json"),
        result=output.result,
        warnings=tuple(output.warnings),
        provenance=Provenance(
            dataset_fingerprint=profile.dataset_fingerprint,
            rows_in_dataset=len(frame),
            rows_used=output.rows_used,
            library_versions=_library_versions(),
        ),
    )


def execute_plan(
    plan: AnalysisPlan,
    frame: pd.DataFrame,
    profile: DatasetProfile,
    limits: LimitsConfig | None = None,
) -> tuple[AnalysisArtifact, ...]:
    """Validate the whole plan, then run every step. Nothing runs if validation fails.

    The time limit is checked between steps (a single step is not interrupted).
    """
    active = LimitsConfig() if limits is None else limits
    validate_plan(plan, profile)
    if len(frame) != profile.row_count:
        raise ValueError("frame does not match the profile (row count differs)")
    deadline = time.monotonic() + active.max_execution_seconds
    artifacts: list[AnalysisArtifact] = []
    for step in plan.steps:
        if time.monotonic() > deadline:
            raise ExecutionTimeError(
                f"plan exceeded max_execution_seconds={active.max_execution_seconds}"
            )
        artifacts.append(execute_step(step, frame, profile))
    return tuple(artifacts)
