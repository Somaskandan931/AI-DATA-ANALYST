"""Cleaning working view (EDA-04).

Cleaning never touches the ingested data. It takes the typed analysis frame, applies a short
list of explicit, allow-listed steps to a *copy*, and returns the result together with a
human-readable log. The log travels with every artifact (``Provenance.cleaning``), so a chart
or report can always say which rows were removed or filled in before a number was computed.

Nothing is cleaned unless a :class:`CleaningPlan` asks for it: the default analysis path
(``execute_plan`` on :func:`~ai_data_analyst.analysis.view.typed_frame`) keeps missing cells.
Cleaning steps carry no expressions or code, and ``extra="forbid"`` rejects unknown fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Final, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..ingestion import IngestedCSV
from ..models import DatasetProfile
from .plan import ANALYSIS_SCHEMA_VERSION, PlanValidationError
from .view import typed_frame

MAX_CLEANING_STEPS: Final = 10
_NUMERIC_TYPES: Final = frozenset({"integer", "float"})


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


CleaningStep = Annotated[
    DropDuplicatesStep | DropMissingRowsStep | ImputeStep, Field(discriminator="kind")
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


def apply_cleaning(plan: CleaningPlan, frame: pd.DataFrame, profile: DatasetProfile) -> CleanedView:
    """Apply *plan* to a copy of *frame*; neither *frame* nor any ingested data changes."""
    validate_cleaning(plan, profile)
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
