"""Shared, versioned data contracts used across modules.

``DatasetProfile`` is the contract between profiling, analysis, chat, reporting and
evaluation. Any breaking change must bump ``PROFILE_SCHEMA_VERSION``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROFILE_SCHEMA_VERSION = "1.0"

InferredType = Literal["integer", "float", "boolean", "date", "string"]


class ColumnProfile(BaseModel):
    """Deterministic profile of one column. Numeric-only fields are None for other types."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    inferred_type: InferredType
    missing_count: int = Field(ge=0)
    unique_count: int = Field(ge=0, description="Distinct non-missing values")
    min: float | str | None = None
    max: float | str | None = None
    mean: float | None = None
    median: float | None = None
    std: float | None = Field(default=None, description="Sample standard deviation (ddof=1)")
    q1: float | None = Field(default=None, description="25th percentile, linear interpolation")
    q3: float | None = Field(default=None, description="75th percentile, linear interpolation")
    outlier_count: int | None = Field(
        default=None, ge=0, description="Values outside [q1 - 1.5*IQR, q3 + 1.5*IQR]"
    )


class DatasetProfile(BaseModel):
    """Versioned structured profile of a dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = PROFILE_SCHEMA_VERSION
    dataset_fingerprint: str = Field(description="SHA-256 of the raw file bytes")
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    duplicate_row_count: int = Field(
        ge=0, description="Rows identical to an earlier row (first occurrence is not counted)"
    )
    columns: list[ColumnProfile]

    @model_validator(mode="after")
    def _column_count_matches(self) -> DatasetProfile:
        if self.column_count != len(self.columns):
            raise ValueError("column_count must equal len(columns)")
        return self
