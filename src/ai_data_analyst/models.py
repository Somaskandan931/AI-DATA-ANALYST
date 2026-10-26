"""Shared, versioned data contracts used across modules.

``DatasetProfile`` is the contract between profiling, analysis, chat, reporting and
evaluation. Any breaking change must bump ``PROFILE_SCHEMA_VERSION``.

Conventions: undefined statistics are ``None`` (never NaN or infinity); ``min``/``max``
for date columns are ISO 8601 calendar dates (``YYYY-MM-DD``); and
``dataset_fingerprint`` is the lowercase hexadecimal SHA-256 of the raw file bytes.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROFILE_SCHEMA_VERSION = "1.0"

InferredType = Literal["integer", "float", "boolean", "date", "string"]

_NUMERIC_ONLY_FIELDS = ("mean", "median", "std", "q1", "q3", "outlier_count")


class ColumnProfile(BaseModel):
    """Deterministic profile of one column. Numeric-only fields are None for other types.

    Undefined statistics are ``None``, never NaN. For date columns, ``min``/``max`` are
    ISO 8601 calendar dates (``YYYY-MM-DD``); a time component is not represented.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    name: str
    inferred_type: InferredType
    missing_count: int = Field(ge=0)
    unique_count: int = Field(ge=0, description="Distinct non-missing values")
    min: float | str | None = Field(
        default=None,
        description="Smallest non-missing value; ISO 8601 date (YYYY-MM-DD) for date columns",
    )
    max: float | str | None = Field(
        default=None,
        description="Largest non-missing value; ISO 8601 date (YYYY-MM-DD) for date columns",
    )
    mean: float | None = None
    median: float | None = None
    std: float | None = Field(default=None, description="Sample standard deviation (ddof=1)")
    q1: float | None = Field(default=None, description="25th percentile, linear interpolation")
    q3: float | None = Field(default=None, description="75th percentile, linear interpolation")
    outlier_count: int | None = Field(
        default=None, ge=0, description="Values outside [q1 - 1.5*IQR, q3 + 1.5*IQR]"
    )

    @model_validator(mode="after")
    def _validate_statistics(self) -> Self:
        if self.inferred_type in ("boolean", "date", "string"):
            for field_name in _NUMERIC_ONLY_FIELDS:
                if getattr(self, field_name) is not None:
                    raise ValueError(
                        f"{field_name} must be None for inferred_type {self.inferred_type!r}"
                    )
        if (
            self.q1 is not None
            and self.median is not None
            and self.q3 is not None
            and not self.q1 <= self.median <= self.q3
        ):
            raise ValueError("quartiles must satisfy q1 <= median <= q3")
        if (
            isinstance(self.min, int | float)
            and isinstance(self.max, int | float)
            and self.min > self.max
        ):
            raise ValueError("min must be less than or equal to max")
        return self


class DatasetProfile(BaseModel):
    """Versioned structured profile of a dataset.

    ``dataset_fingerprint`` is the lowercase hexadecimal SHA-256 of the raw file bytes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: str = PROFILE_SCHEMA_VERSION
    dataset_fingerprint: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="Lowercase hex SHA-256 of the raw file bytes",
    )
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    duplicate_row_count: int = Field(
        ge=0, description="Rows identical to an earlier row (first occurrence is not counted)"
    )
    columns: tuple[ColumnProfile, ...]

    @field_validator("schema_version")
    @classmethod
    def _schema_version_must_be_current(cls, value: str) -> str:
        if value != PROFILE_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {PROFILE_SCHEMA_VERSION!r}")
        return value

    @model_validator(mode="after")
    def _column_count_matches(self) -> Self:
        if self.column_count != len(self.columns):
            raise ValueError("column_count must equal len(columns)")
        return self

    @model_validator(mode="after")
    def _validate_row_consistency(self) -> Self:
        names = [column.name for column in self.columns]
        if len(set(names)) != len(names):
            raise ValueError("column names must be unique")
        for column in self.columns:
            if column.missing_count > self.row_count:
                raise ValueError(f"column {column.name!r}: missing_count must be <= row_count")
            if column.unique_count > self.row_count - column.missing_count:
                raise ValueError(
                    f"column {column.name!r}: unique_count must be <= row_count - missing_count"
                )
        if self.row_count > 0 and self.duplicate_row_count >= self.row_count:
            raise ValueError("duplicate_row_count must be less than row_count")
        return self
