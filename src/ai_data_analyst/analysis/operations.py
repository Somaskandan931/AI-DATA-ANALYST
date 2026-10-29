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
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from ..models import DatasetProfile
from ..security import LimitsConfig
from .artifact import AnalysisArtifact, Provenance
from .cleaning import CleanedView
from .plan import (
    AnalysisPlan,
    AnalysisStep,
    ClusteringParams,
    CorrelationParams,
    DistributionParams,
    GroupedAggregationParams,
    OperationName,
    OutlierSummaryParams,
    PcaParams,
    SummaryStatsParams,
    step_columns,
    validate_plan,
)

_DECIMALS = 6
_SILHOUETTE_SAMPLE = 2_000
_SCALE_RATIO_WARNING = 10.0


class ExecutionTimeError(RuntimeError):
    """The plan exceeded ``max_execution_seconds`` between steps."""


class OperationInputError(ValueError):
    """The data cannot support the requested operation (too few rows, constant columns, ...).

    Raised instead of returning a made-up result. ``step`` is the 0-based plan step, when known.
    """

    def __init__(self, message: str, step: int | None = None) -> None:
        super().__init__(message if step is None else f"step {step}: {message}")
        self.step = step


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
            "min": _num(np.min(values)),
            "q1": _num(q1),
            "median": _num(median),
            "q3": _num(q3),
            "max": _num(np.max(values)),
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


def _complete_rows(
    frame: pd.DataFrame, columns: tuple[str, ...]
) -> tuple[np.ndarray[Any, np.dtype[np.float64]], list[str]]:
    """Rows with no missing value in *columns* as a float matrix, plus warnings."""
    subset = frame[list(columns)]
    complete = subset.dropna()
    warnings: list[str] = []
    excluded = len(subset) - len(complete)
    if excluded:
        warnings.append(
            f"{excluded} rows with a missing value in the selected columns were excluded"
        )
    matrix = complete.to_numpy(dtype=np.float64)
    for position, name in enumerate(columns):
        if matrix.shape[0] > 0 and np.ptp(matrix[:, position]) == 0:
            warnings.append(f"{name}: all values are identical")
    return matrix, warnings


def _scale_warning(matrix: np.ndarray[Any, np.dtype[np.float64]]) -> list[str]:
    """Warn when unscaled columns differ so much in spread that one will dominate."""
    spreads = matrix.std(axis=0, ddof=1) if matrix.shape[0] > 1 else np.zeros(matrix.shape[1])
    positive = spreads[spreads > 0]
    if positive.size > 1 and float(np.max(positive) / np.min(positive)) > _SCALE_RATIO_WARNING:
        return [
            "columns are on very different scales and were not standardized; "
            "the largest-scale column will dominate the result"
        ]
    return []


def _prepare(
    matrix: np.ndarray[Any, np.dtype[np.float64]], standardize: bool
) -> np.ndarray[Any, np.dtype[np.float64]]:
    if not standardize:
        return matrix
    return np.asarray(StandardScaler().fit_transform(matrix), dtype=np.float64)


def _clustering(frame: pd.DataFrame, params: ClusteringParams) -> OperationOutput:
    original, warnings = _complete_rows(frame, params.columns)
    rows = original.shape[0]
    if rows < params.k:
        raise OperationInputError(
            f"clustering into k={params.k} needs at least {params.k} complete rows, found {rows}"
        )
    distinct = int(np.unique(original, axis=0).shape[0])
    if distinct < params.k:
        raise OperationInputError(
            f"clustering into k={params.k} needs at least {params.k} distinct rows, "
            f"found {distinct}"
        )
    if not params.standardize:
        warnings.extend(_scale_warning(original))
    data = _prepare(original, params.standardize)
    with threadpool_limits(limits=1):  # one BLAS/OpenMP thread: identical results on any machine
        model = KMeans(
            n_clusters=params.k,
            n_init=10,
            max_iter=300,
            algorithm="lloyd",
            random_state=params.random_state,
        ).fit(data)
    labels = model.labels_.astype(np.int64)
    sizes = np.bincount(labels, minlength=params.k)
    centroids = np.vstack([original[labels == c].mean(axis=0) for c in range(params.k)])
    # Number clusters by size (largest first); ties broken by centroid so labels are stable.
    order = sorted(range(params.k), key=lambda c: (-int(sizes[c]), tuple(centroids[c])))
    silhouette: float | None = None
    if 1 < np.unique(labels).size < rows:  # silhouette is undefined for 1 cluster or k == rows
        sampled = rows > _SILHOUETTE_SAMPLE
        if sampled:
            warnings.append(
                f"silhouette was estimated on a random sample of {_SILHOUETTE_SAMPLE} rows"
            )
        with threadpool_limits(limits=1):
            silhouette = _num(
                silhouette_score(
                    data,
                    labels,
                    sample_size=_SILHOUETTE_SAMPLE if sampled else None,
                    random_state=params.random_state,
                )
            )
    clusters: list[JsonValue] = [
        {
            "cluster": rank,
            "size": int(sizes[c]),
            "fraction": _num(sizes[c] / rows),
            "centroid": {name: _num(centroids[c][i]) for i, name in enumerate(params.columns)},
        }
        for rank, c in enumerate(order)
    ]
    result: dict[str, JsonValue] = {
        "k": params.k,
        "columns": [*params.columns],
        "standardized": params.standardize,
        "random_state": params.random_state,
        "rows_clustered": rows,
        "inertia": _num(model.inertia_),
        "inertia_space": "standardized" if params.standardize else "original",
        "iterations": int(model.n_iter_),
        "silhouette": silhouette,
        "clusters": clusters,
    }
    return OperationOutput(result, rows, warnings)


def _pca(frame: pd.DataFrame, params: PcaParams) -> OperationOutput:
    original, warnings = _complete_rows(frame, params.columns)
    rows = original.shape[0]
    if rows < max(2, params.n_components):
        raise OperationInputError(
            f"PCA with {params.n_components} components needs at least "
            f"{max(2, params.n_components)} complete rows, found {rows}"
        )
    if not (original.std(axis=0, ddof=1) > 0).any():
        raise OperationInputError("every selected column is constant; PCA is undefined")
    if not params.standardize:
        warnings.extend(_scale_warning(original))
    data = _prepare(original, params.standardize)
    with threadpool_limits(limits=1):
        model = PCA(n_components=params.n_components, svd_solver="full").fit(data)
    loadings = np.array(model.components_, dtype=np.float64)
    for row in loadings:  # components are defined up to sign; make the largest loading positive
        if row[int(np.argmax(np.abs(row)))] < 0:
            row *= -1
    ratios = [float(r) for r in model.explained_variance_ratio_]
    cumulative = np.cumsum(ratios)
    components: list[JsonValue] = [
        {
            "component": f"PC{index + 1}",
            "explained_variance": _num(model.explained_variance_[index]),
            "explained_variance_ratio": _num(ratios[index]),
            "cumulative_ratio": _num(cumulative[index]),
            "loadings": {name: _num(loadings[index][i]) for i, name in enumerate(params.columns)},
        }
        for index in range(params.n_components)
    ]
    result: dict[str, JsonValue] = {
        "columns": [*params.columns],
        "standardized": params.standardize,
        "n_components": params.n_components,
        "rows_used": rows,
        "total_variance": _num(data.var(axis=0, ddof=1).sum()),
        "components": components,
    }
    return OperationOutput(result, rows, warnings)


OPERATIONS: dict[OperationName, Callable[[pd.DataFrame, Any], OperationOutput]] = {
    "summary_stats": _summary_stats,
    "grouped_aggregation": _grouped_aggregation,
    "correlation": _correlation,
    "distribution": _distribution,
    "outlier_summary": _outlier_summary,
    "clustering": _clustering,
    "pca": _pca,
}


def _library_versions() -> dict[str, str]:
    return {name: version(name) for name in ("pandas", "numpy", "scipy", "scikit-learn")}


def execute_step(
    step: AnalysisStep,
    frame: pd.DataFrame,
    profile: DatasetProfile,
    cleaning: tuple[str, ...] = (),
) -> AnalysisArtifact:
    """Run one validated step on *frame* and wrap the result with provenance.

    *cleaning* is the log of cleaning steps already applied to *frame*; it is recorded in the
    artifact's provenance.
    """
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
            cleaning=cleaning,
        ),
    )


def _run_plan(
    plan: AnalysisPlan,
    frame: pd.DataFrame,
    profile: DatasetProfile,
    limits: LimitsConfig | None,
    expected_rows: int,
    cleaning: tuple[str, ...],
) -> tuple[AnalysisArtifact, ...]:
    active = LimitsConfig() if limits is None else limits
    validate_plan(plan, profile)
    if len(frame) != expected_rows:
        raise ValueError("frame does not match the profile (row count differs)")
    deadline = time.monotonic() + active.max_execution_seconds
    artifacts: list[AnalysisArtifact] = []
    for index, step in enumerate(plan.steps):
        if time.monotonic() > deadline:
            raise ExecutionTimeError(
                f"plan exceeded max_execution_seconds={active.max_execution_seconds}"
            )
        try:
            artifacts.append(execute_step(step, frame, profile, cleaning))
        except OperationInputError as error:
            raise OperationInputError(str(error), step=index) from None
    return tuple(artifacts)


def execute_plan(
    plan: AnalysisPlan,
    frame: pd.DataFrame,
    profile: DatasetProfile,
    limits: LimitsConfig | None = None,
) -> tuple[AnalysisArtifact, ...]:
    """Validate the whole plan, then run every step. Nothing runs if validation fails.

    The time limit is checked between steps (a single step is not interrupted). A step whose
    data cannot support the operation raises :class:`OperationInputError` with its index.
    """
    return _run_plan(plan, frame, profile, limits, profile.row_count, ())


def execute_plan_on_view(
    plan: AnalysisPlan,
    view: CleanedView,
    profile: DatasetProfile,
    limits: LimitsConfig | None = None,
) -> tuple[AnalysisArtifact, ...]:
    """Like :func:`execute_plan`, on a cleaned view; every artifact records the cleaning log."""
    if view.dataset_fingerprint != profile.dataset_fingerprint:
        raise ValueError("cleaned view does not match the profile (fingerprint mismatch)")
    if view.rows_before != profile.row_count:
        raise ValueError("cleaned view does not match the profile (row count differs)")
    return _run_plan(plan, view.frame, profile, limits, view.rows_after, view.log)
