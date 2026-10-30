"""Cleaning working view (EDA-04).

Cleaning never touches the ingested data. It takes the typed analysis frame, applies a short
list of explicit, allow-listed steps to a *copy*, and returns the result together with a
human-readable log. The log travels with every artifact (``Provenance.cleaning``), so a chart
or report can always say which rows were removed or filled in before a number was computed.

A :class:`FilterRowsStep` keeps only the rows that satisfy every one of its conditions. A
condition is ``column``, an operator and a typed value; there are no expressions, so nothing
is parsed or evaluated from text. A row with a missing value in the column satisfies only
``is_missing``: every other operator (including ``ne`` and ``not_in``) is false for it.

Nothing is cleaned unless a :class:`CleaningPlan` asks for it: the default analysis path
(``execute_plan`` on :func:`~ai_data_analyst.analysis.view.typed_frame`) keeps missing cells.
Cleaning steps carry no expressions or code, and ``extra="forbid"`` rejects unknown fields.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final, Literal, Self

import numpy as np
import pandas as pd
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from ..ingestion import IngestedCSV
from ..models import DatasetProfile
from .plan import ANALYSIS_SCHEMA_VERSION, PlanValidationError
from .view import typed_frame

MAX_CLEANING_STEPS: Final = 10
MAX_FILTER_CONDITIONS: Final = 10
MAX_FILTER_VALUES: Final = 50
MAX_FILTER_TEXT: Final = 200
_NUMERIC_TYPES: Final = frozenset({"integer", "float"})
_ORDERED_TYPES: Final = frozenset({"integer", "float", "date"})
_ISO_DATE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")


class CleaningError(ValueError):
    """A cleaning step cannot be applied to the data (for example, nothing left to impute)."""


class _Step(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DropDuplicatesStep(_Step):
    """Remove rows identical to an earlier row; the first occurrence is kept."""

    kind: Literal["drop_duplicates"] = "drop_duplicates"


class DropMissingRowsStep(_Step):
    """Remove rows that have a missing value in any of the listed columns."""

    kind: Literal["drop_missing_rows"] = "drop_missing_rows"
    columns: tuple[str, ...] = Field(min_length=1, max_length=50)

    @field_validator("columns")
    @classmethod
    def _unique_columns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("columns must not repeat")
        return value


class ImputeStep(_Step):
    """Fill the missing values of one numeric column with its mean or median."""

    kind: Literal["impute"] = "impute"
    column: str
    strategy: Literal["mean", "median"]


FilterOp = Literal[
    "eq", "ne", "lt", "le", "gt", "ge", "in", "not_in", "is_missing", "is_not_missing"
]
_NO_VALUE_OPS: Final = frozenset({"is_missing", "is_not_missing"})
_LIST_OPS: Final = frozenset({"in", "not_in"})
_ORDER_OPS: Final = frozenset({"lt", "le", "gt", "ge"})
_SYMBOL: Final = {"eq": "=", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}

FilterScalar = (
    Annotated[StrictStr, Field(max_length=MAX_FILTER_TEXT)] | StrictInt | StrictFloat | StrictBool
)


class FilterCondition(BaseModel):
    """``column op value``. ``in``/``not_in`` take a list; ``is_missing`` ops take no value.

    Dates are written ``YYYY-MM-DD``. Strings compare exactly (case-sensitive).
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    column: str
    op: FilterOp
    value: FilterScalar | tuple[FilterScalar, ...] | None = None

    @model_validator(mode="after")
    def _value_matches_operator(self) -> Self:
        if self.op in _NO_VALUE_OPS:
            if self.value is not None:
                raise ValueError(f"{self.op} takes no value")
        elif self.op in _LIST_OPS:
            if not isinstance(self.value, tuple) or not 1 <= len(self.value) <= MAX_FILTER_VALUES:
                raise ValueError(f"{self.op} needs 1 to {MAX_FILTER_VALUES} values")
        elif self.value is None or isinstance(self.value, tuple):
            raise ValueError(f"{self.op} needs one value")
        for item in self.value if isinstance(self.value, tuple) else (self.value,):
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("values must be finite")
        return self


class FilterRowsStep(_Step):
    """Keep only rows that satisfy *all* conditions (logical AND)."""

    kind: Literal["filter_rows"] = "filter_rows"
    conditions: tuple[FilterCondition, ...] = Field(min_length=1, max_length=MAX_FILTER_CONDITIONS)


CleaningStep = Annotated[
    DropDuplicatesStep | DropMissingRowsStep | ImputeStep | FilterRowsStep,
    Field(discriminator="kind"),
]


class CleaningPlan(BaseModel):
    """Ordered cleaning steps, applied in sequence to a copy of the typed frame."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = ANALYSIS_SCHEMA_VERSION
    steps: tuple[CleaningStep, ...] = Field(default=(), max_length=MAX_CLEANING_STEPS)

    @field_validator("schema_version")
    @classmethod
    def _schema_version_must_be_current(cls, value: str) -> str:
        if value != ANALYSIS_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {ANALYSIS_SCHEMA_VERSION!r}")
        return value


@dataclass(frozen=True)
class CleanedView:
    """A cleaned copy of the typed frame, with what was done to produce it."""

    frame: pd.DataFrame
    log: tuple[str, ...]
    rows_before: int
    rows_after: int
    dataset_fingerprint: str


def _check_value(index: int, condition: FilterCondition, column_type: str) -> None:
    values = condition.value if isinstance(condition.value, tuple) else (condition.value,)
    name = condition.column
    for value in values:
        if value is None:
            continue
        ok: bool
        match column_type:
            case "integer" | "float":
                ok = isinstance(value, int | float) and not isinstance(value, bool)
            case "boolean":
                ok = isinstance(value, bool)
            case "date":
                ok = isinstance(value, str) and _is_iso_date(value)
            case _:
                ok = isinstance(value, str)
        if not ok:
            raise PlanValidationError(
                index, f"value {value!r} does not fit {name!r} ({column_type})"
            )


def _is_iso_date(text: str) -> bool:
    if not _ISO_DATE.fullmatch(text):
        return False
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def validate_cleaning(plan: CleaningPlan, profile: DatasetProfile) -> None:
    """Raise :class:`PlanValidationError` unless every step fits *profile*."""
    types = {c.name: c.inferred_type for c in profile.columns}
    for index, step in enumerate(plan.steps):
        match step:
            case DropDuplicatesStep():
                continue
            case DropMissingRowsStep():
                for name in step.columns:
                    if name not in types:
                        raise PlanValidationError(index, f"unknown column {name!r}")
            case ImputeStep():
                if step.column not in types:
                    raise PlanValidationError(index, f"unknown column {step.column!r}")
                if types[step.column] not in _NUMERIC_TYPES:
                    raise PlanValidationError(
                        index,
                        f"cannot impute {step.column!r}: {types[step.column]} is not numeric",
                    )
            case FilterRowsStep():
                for condition in step.conditions:
                    if condition.column not in types:
                        raise PlanValidationError(index, f"unknown column {condition.column!r}")
                    column_type = types[condition.column]
                    if condition.op in _ORDER_OPS and column_type not in _ORDERED_TYPES:
                        raise PlanValidationError(
                            index,
                            f"cannot order {condition.column!r}: {column_type} has no ordering",
                        )
                    _check_value(index, condition, column_type)


def _drop_duplicates(frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    keep = ~frame.duplicated(keep="first")
    removed = int((~keep).sum())
    return frame.loc[keep].reset_index(drop=True), (
        f"Removed {removed} duplicate rows (kept the first occurrence)"
    )


def _drop_missing(frame: pd.DataFrame, columns: tuple[str, ...]) -> tuple[pd.DataFrame, str]:
    keep = frame[list(columns)].notna().all(axis=1)
    removed = int((~keep).sum())
    names = ", ".join(columns)
    return frame.loc[keep].reset_index(drop=True), (
        f"Removed {removed} rows with a missing value in: {names}"
    )


def _impute(frame: pd.DataFrame, step: ImputeStep) -> tuple[pd.DataFrame, str]:
    present = frame[step.column].dropna()
    filled = int(frame[step.column].isna().sum())
    if present.empty:
        raise CleaningError(f"cannot impute {step.column!r}: it has no non-missing values")
    values = present.to_numpy(dtype=np.float64)
    fill = float(np.median(values) if step.strategy == "median" else values.mean())
    result = frame.copy()
    result[step.column] = result[step.column].fillna(fill)
    return result, (
        f"Filled {filled} missing values in {step.column!r} with the {step.strategy} "
        f"({round(fill, 6)})"
    )


def _describe(condition: FilterCondition) -> str:
    def show(value: object) -> str:
        return json.dumps(value) if isinstance(value, str) else str(value)

    if condition.op == "is_missing":
        return f"{condition.column} is missing"
    if condition.op == "is_not_missing":
        return f"{condition.column} is not missing"
    if isinstance(condition.value, tuple):
        listed = ", ".join(show(v) for v in condition.value)
        word = "in" if condition.op == "in" else "not in"
        return f"{condition.column} {word} ({listed})"
    return f"{condition.column} {_SYMBOL[condition.op]} {show(condition.value)}"


def _condition_mask(frame: pd.DataFrame, condition: FilterCondition, column_type: str) -> pd.Series:
    column = frame[condition.column]
    present = column.notna().astype(bool)
    if condition.op == "is_missing":
        return ~present
    if condition.op == "is_not_missing":
        return present

    def convert(value: object) -> object:
        return pd.Timestamp(str(value)) if column_type == "date" else value

    if isinstance(condition.value, tuple):
        members = [convert(v) for v in condition.value]
        hit = column.isin(members)
        result = hit if condition.op == "in" else ~hit
    else:
        value = convert(condition.value)
        match condition.op:
            case "eq":
                result = column == value
            case "ne":
                result = column != value
            case "lt":
                result = column < value
            case "le":
                result = column <= value
            case "gt":
                result = column > value
            case _:
                result = column >= value
    return result.fillna(False).astype(bool) & present


def _filter_rows(
    frame: pd.DataFrame, step: FilterRowsStep, types: Mapping[str, str]
) -> tuple[pd.DataFrame, str]:
    keep = pd.Series(True, index=frame.index)
    for condition in step.conditions:
        keep &= _condition_mask(frame, condition, types[condition.column])
    described = " AND ".join(_describe(c) for c in step.conditions)
    kept = int(keep.sum())
    return frame.loc[keep].reset_index(drop=True), (
        f"Kept {kept} of {len(frame)} rows where {described}"
    )


def apply_cleaning(plan: CleaningPlan, frame: pd.DataFrame, profile: DatasetProfile) -> CleanedView:
    """Apply *plan* to a copy of *frame*; neither *frame* nor any ingested data changes."""
    validate_cleaning(plan, profile)
    types = {c.name: c.inferred_type for c in profile.columns}
    current = frame.copy()
    log: list[str] = []
    for step in plan.steps:
        match step:
            case DropDuplicatesStep():
                current, note = _drop_duplicates(current)
            case DropMissingRowsStep():
                current, note = _drop_missing(current, step.columns)
            case ImputeStep():
                current, note = _impute(current, step)
            case FilterRowsStep():
                current, note = _filter_rows(current, step, types)
        log.append(note)
        if current.empty and len(frame) > 0:
            raise CleaningError("cleaning removed every row; nothing is left to analyse")
    return CleanedView(
        frame=current,
        log=tuple(log),
        rows_before=len(frame),
        rows_after=len(current),
        dataset_fingerprint=profile.dataset_fingerprint,
    )


def cleaned_view(ingested: IngestedCSV, profile: DatasetProfile, plan: CleaningPlan) -> CleanedView:
    """Typed frame from *ingested* with *plan* applied. The raw ingested frame is untouched."""
    return apply_cleaning(plan, typed_frame(ingested, profile), profile)
