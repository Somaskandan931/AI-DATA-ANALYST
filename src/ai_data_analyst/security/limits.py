"""Configurable resource limits for uploads, analysis and SQL execution.

Defaults live in :data:`DEFAULT_LIMITS`. Environment overrides use ``AIDA_``-prefixed
variables (see :data:`ENV_VARS`) and must be positive integers.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_LIMITS: Final[Mapping[str, int]] = {
    "max_upload_bytes": 25 * 1024 * 1024,
    "max_rows": 250_000,
    "max_columns": 200,
    "max_execution_seconds": 30,
    "sql_timeout_seconds": 5,
    "max_result_rows": 1_000,
}

ENV_VARS: Final[Mapping[str, str]] = {
    "max_upload_bytes": "AIDA_MAX_UPLOAD_BYTES",
    "max_rows": "AIDA_MAX_ROWS",
    "max_columns": "AIDA_MAX_COLUMNS",
    "max_execution_seconds": "AIDA_MAX_EXECUTION_SECONDS",
    "sql_timeout_seconds": "AIDA_SQL_TIMEOUT_SECONDS",
    "max_result_rows": "AIDA_MAX_RESULT_ROWS",
}


class LimitExceededError(ValueError):
    """Raised when an input exceeds a configured resource limit."""


class LimitsConfig(BaseModel):
    """Frozen, validated resource limits shared by ingestion, analysis and SQL."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_upload_bytes: int = Field(default=DEFAULT_LIMITS["max_upload_bytes"], gt=0)
    max_rows: int = Field(default=DEFAULT_LIMITS["max_rows"], gt=0)
    max_columns: int = Field(default=DEFAULT_LIMITS["max_columns"], gt=0)
    max_execution_seconds: int = Field(default=DEFAULT_LIMITS["max_execution_seconds"], gt=0)
    sql_timeout_seconds: int = Field(default=DEFAULT_LIMITS["sql_timeout_seconds"], gt=0)
    max_result_rows: int = Field(default=DEFAULT_LIMITS["max_result_rows"], gt=0)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> LimitsConfig:
        """Build limits from ``os.environ`` (or *environ*), falling back to defaults."""
        source = os.environ if environ is None else environ
        values: dict[str, int] = {}
        for field_name, env_name in ENV_VARS.items():
            raw = source.get(env_name)
            if raw is None:
                values[field_name] = DEFAULT_LIMITS[field_name]
                continue
            try:
                value = int(raw)
            except ValueError:
                raise ValueError(
                    f"{env_name} ({field_name}) must be a positive integer, got {raw!r}"
                ) from None
            if value <= 0:
                raise ValueError(
                    f"{env_name} ({field_name}) must be a positive integer, got {value}"
                )
            values[field_name] = value
        return cls.model_validate(values)


def check_upload_size(size_bytes: int, limits: LimitsConfig) -> None:
    """Raise :class:`LimitExceededError` when *size_bytes* exceeds ``max_upload_bytes``."""
    if size_bytes > limits.max_upload_bytes:
        raise LimitExceededError(
            f"upload size {size_bytes} bytes exceeds max_upload_bytes={limits.max_upload_bytes}"
        )


def check_shape(row_count: int, column_count: int, limits: LimitsConfig) -> None:
    """Raise :class:`LimitExceededError` when rows or columns exceed their limits."""
    if row_count > limits.max_rows:
        raise LimitExceededError(f"row_count {row_count} exceeds max_rows={limits.max_rows}")
    if column_count > limits.max_columns:
        raise LimitExceededError(
            f"column_count {column_count} exceeds max_columns={limits.max_columns}"
        )
