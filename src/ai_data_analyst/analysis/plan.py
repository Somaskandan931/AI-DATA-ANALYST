"""Typed analysis plans (EDA-06, EDA-07).

An :class:`AnalysisPlan` is the only thing a model (or a person) may hand to the executor. It
is a list of *named* operations from a closed allow-list, each with explicit, bounded
parameters. There is no free-text, expression or code field anywhere in these types, so a
plan cannot carry model-authored code. ``extra="forbid"`` makes unknown fields fail loudly.

Pydantic checks the shape of a plan; :func:`validate_plan` then checks it against a
:class:`~ai_data_analyst.models.DatasetProfile` (columns exist, types suit the operation).
Both fail closed: nothing runs unless the whole plan validates.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..models import ColumnProfile, DatasetProfile

ANALYSIS_SCHEMA_VERSION: Final = "1.0"

OperationName = Literal[
    "summary_stats",
    "grouped_aggregation",
    "correlation",
    "distribution",
    "outlier_summary",
    "clustering",
    "pca",
]
Aggregation = Literal["count", "mean", "median", "sum", "min", "max", "std"]

MAX_STEPS: Final = 20
MAX_COLUMNS_PER_STEP: Final = 50
MAX_GROUP_COLUMNS: Final = 3
MAX_CLUSTERS: Final = 10
MAX_CLUSTER_COLUMNS: Final = 10
MAX_PCA_COLUMNS: Final = 20
MAX_PCA_COMPONENTS: Final = 10
MAX_RANDOM_STATE: Final = 2**31 - 1

_NUMERIC_TYPES: Final = frozenset({"integer", "float"})
_GROUPABLE_TYPES: Final = frozenset({"integer", "boolean", "date", "string"})


class PlanValidationError(ValueError):
    """A plan does not fit the dataset. ``step`` is the 0-based index of the failing step."""

    def __init__(self, step: int, message: str) -> None:
        super().__init__(f"step {step}: {message}")
        self.step = step


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ValueError("columns must not repeat")
    return values


class SummaryStatsParams(_Params):
    operation: Literal["summary_stats"] = "summary_stats"
    columns: tuple[str, ...] = Field(min_length=1, max_length=MAX_COLUMNS_PER_STEP)

    _no_repeats = field_validator("columns")(_unique)


class GroupedAggregationParams(_Params):
    operation: Literal["grouped_aggregation"] = "grouped_aggregation"
    group_by: tuple[str, ...] = Field(min_length=1, max_length=MAX_GROUP_COLUMNS)
    value_column: str
    aggregations: tuple[Aggregation, ...] = Field(min_length=1, max_length=7)
    max_groups: int = Field(default=50, ge=1, le=1000, description="Groups returned, by key order")

    @field_validator("group_by")
    @classmethod
    def _group_by_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _unique(value)

    @field_validator("aggregations")
    @classmethod
    def _aggregations_unique(cls, value: tuple[Aggregation, ...]) -> tuple[Aggregation, ...]:
        if len(set(value)) != len(value):
            raise ValueError("aggregations must not repeat")
        return value


class CorrelationParams(_Params):
    operation: Literal["correlation"] = "correlation"
    columns: tuple[str, ...] = Field(min_length=2, max_length=20)
    method: Literal["pearson", "spearman"] = "pearson"

    _no_repeats = field_validator("columns")(_unique)


class DistributionParams(_Params):
    operation: Literal["distribution"] = "distribution"
    column: str
    bins: int = Field(default=10, ge=2, le=100, description="Histogram bins (numeric columns)")
    top_n: int = Field(default=10, ge=1, le=100, description="Categories shown (other columns)")


class OutlierSummaryParams(_Params):
    operation: Literal["outlier_summary"] = "outlier_summary"
    columns: tuple[str, ...] = Field(min_length=1, max_length=MAX_COLUMNS_PER_STEP)
    iqr_factor: float = Field(default=1.5, gt=0, le=10)

    _no_repeats = field_validator("columns")(_unique)


class ClusteringParams(_Params):
    """K-means on numeric columns. Rows with a missing value in them are excluded."""

    operation: Literal["clustering"] = "clustering"
    columns: tuple[str, ...] = Field(min_length=2, max_length=MAX_CLUSTER_COLUMNS)
    k: int = Field(ge=2, le=MAX_CLUSTERS, description="Number of clusters")
    standardize: bool = Field(default=True, description="Scale columns to mean 0, std 1 first")
    random_state: int = Field(default=0, ge=0, le=MAX_RANDOM_STATE, description="Fixed seed")

    _no_repeats = field_validator("columns")(_unique)


class PcaParams(_Params):
    """Principal component analysis of numeric columns (rows with missing values excluded)."""

    operation: Literal["pca"] = "pca"
    columns: tuple[str, ...] = Field(min_length=2, max_length=MAX_PCA_COLUMNS)
    n_components: int = Field(default=2, ge=1, le=MAX_PCA_COMPONENTS)
    standardize: bool = Field(default=True, description="Scale columns to mean 0, std 1 first")

    _no_repeats = field_validator("columns")(_unique)

    @model_validator(mode="after")
    def _components_fit_columns(self) -> PcaParams:
        if self.n_components > len(self.columns):
            raise ValueError("n_components must not exceed the number of columns")
        return self


AnalysisStep = Annotated[
    SummaryStatsParams
    | GroupedAggregationParams
    | CorrelationParams
    | DistributionParams
    | OutlierSummaryParams
    | ClusteringParams
    | PcaParams,
    Field(discriminator="operation"),
]


class AnalysisPlan(BaseModel):
    """Ordered allow-listed steps. Steps are independent; each yields one artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: str = ANALYSIS_SCHEMA_VERSION
    steps: tuple[AnalysisStep, ...] = Field(min_length=1, max_length=MAX_STEPS)

    @field_validator("schema_version")
    @classmethod
    def _schema_version_must_be_current(cls, value: str) -> str:
        if value != ANALYSIS_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {ANALYSIS_SCHEMA_VERSION!r}")
        return value


def step_columns(step: AnalysisStep) -> tuple[str, ...]:
    """Every dataset column a step reads, in a stable order."""
    match step:
        case (
            SummaryStatsParams()
            | CorrelationParams()
            | OutlierSummaryParams()
            | ClusteringParams()
            | PcaParams()
        ):
            return step.columns
        case GroupedAggregationParams():
            return (*step.group_by, step.value_column)
        case DistributionParams():
            return (step.column,)


def _lookup(profile: DatasetProfile, index: int, name: str) -> ColumnProfile:
    for column in profile.columns:
        if column.name == name:
            return column
    raise PlanValidationError(index, f"unknown column {name!r}")


def _require_numeric(profile: DatasetProfile, index: int, names: tuple[str, ...]) -> None:
    for name in names:
        kind = _lookup(profile, index, name).inferred_type
        if kind not in _NUMERIC_TYPES:
            raise PlanValidationError(
                index, f"column {name!r} is {kind}, expected a numeric column"
            )


def validate_step(step: AnalysisStep, profile: DatasetProfile, index: int = 0) -> None:
    """Raise :class:`PlanValidationError` unless *step* is meaningful for *profile*."""
    match step:
        case SummaryStatsParams() | CorrelationParams() | OutlierSummaryParams():
            _require_numeric(profile, index, step.columns)
        case ClusteringParams():
            _require_numeric(profile, index, step.columns)
            if step.k > profile.row_count:
                raise PlanValidationError(
                    index, f"k={step.k} exceeds the dataset's {profile.row_count} rows"
                )
        case PcaParams():
            _require_numeric(profile, index, step.columns)
            if step.n_components > profile.row_count:
                raise PlanValidationError(
                    index,
                    f"n_components={step.n_components} exceeds the dataset's "
                    f"{profile.row_count} rows",
                )
        case GroupedAggregationParams():
            for name in step.group_by:
                kind = _lookup(profile, index, name).inferred_type
                if kind not in _GROUPABLE_TYPES:
                    raise PlanValidationError(
                        index, f"cannot group by {name!r}: {kind} columns are not groupable"
                    )
            if step.value_column in step.group_by:
                raise PlanValidationError(index, "value_column must not also be a group_by column")
            value_kind = _lookup(profile, index, step.value_column).inferred_type
            if value_kind not in _NUMERIC_TYPES and step.aggregations != ("count",):
                raise PlanValidationError(
                    index,
                    f"column {step.value_column!r} is {value_kind}; only 'count' is allowed",
                )
        case DistributionParams():
            _lookup(profile, index, step.column)


def validate_plan(plan: AnalysisPlan, profile: DatasetProfile) -> None:
    """Validate every step against *profile*; raises on the first problem."""
    for index, step in enumerate(plan.steps):
        validate_step(step, profile, index)
