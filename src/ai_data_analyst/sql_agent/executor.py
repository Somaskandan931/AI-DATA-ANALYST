"""Read-only SQLite execution for validated SQL Agent queries."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from ai_data_analyst.security.limits import LimitsConfig
from ai_data_analyst.sql_agent.contracts import (
    SchemaSnapshot,
    SQLCandidate,
    SQLValidationResult,
)
from ai_data_analyst.sql_agent.validator import validate_sql


class SQLExecutionError(RuntimeError):
    """Safe, user-facing SQL execution failure."""


@dataclass(frozen=True, slots=True)
class SQLExecutionResult:
    """Query output with column metadata and an explicit truncation flag."""

    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    truncated: bool


def execute_sql(
    db_path: str | Path,
    validation: SQLValidationResult,
    snapshot: SchemaSnapshot,
    parameters: Sequence[object] | Mapping[str, object] | None = None,
    limits: LimitsConfig | None = None,
) -> SQLExecutionResult:
    """Execute only independently revalidated SQL against a read-only SQLite file.

    Parameter values are bound by sqlite3; they are never interpolated into SQL.
    """
    effective_limits = limits or LimitsConfig()

    if not validation.allowed or validation.normalized_sql is None:
        raise SQLExecutionError("The SQL query was not approved for execution.")

    # Revalidate the exact SQL that will execute. Do not trust a caller-created
    # SQLValidationResult just because its `allowed` field is True.
    try:
        checked = validate_sql(
            SQLCandidate(sql=validation.normalized_sql),
            snapshot,
        )
    except Exception:
        raise SQLExecutionError("The SQL query could not be verified.") from None

    if not checked.allowed or checked.normalized_sql != validation.normalized_sql:
        raise SQLExecutionError("The SQL query could not be verified.")

    path = Path(db_path).expanduser().resolve()

    if not path.is_file():
        raise SQLExecutionError("The database file is unavailable.")

    # Quote URI-sensitive characters while preserving Windows drive/path syntax.
    encoded_path = quote(path.as_posix(), safe="/:")
    uri = f"file:{encoded_path}?mode=ro"
    deadline = time.monotonic() + effective_limits.sql_timeout_seconds
    timed_out = False

    def progress_handler() -> int:
        nonlocal timed_out
        if time.monotonic() >= deadline:
            timed_out = True
            return 1
        return 0

    connection: sqlite3.Connection | None = None

    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.execute("PRAGMA query_only = ON")
        connection.set_progress_handler(progress_handler, 1000)

        cursor = connection.execute(
            checked.normalized_sql,
            parameters if parameters is not None else (),
        )

        columns = tuple(description[0] for description in (cursor.description or ()))
        if cursor.description is None:
            raise SQLExecutionError("The SQL query did not return a result set.")

        limit = effective_limits.max_result_rows
        fetched = cursor.fetchmany(limit + 1)
        truncated = len(fetched) > limit
        rows = tuple(tuple(row) for row in fetched[:limit])

        return SQLExecutionResult(
            columns=columns,
            rows=rows,
            truncated=truncated,
        )

    except SQLExecutionError:
        raise
    except sqlite3.OperationalError:
        if timed_out:
            raise SQLExecutionError("The SQL query exceeded its time limit.") from None
        raise SQLExecutionError("The SQL query could not be executed safely.") from None
    except sqlite3.Error:
        raise SQLExecutionError("The SQL query could not be executed safely.") from None
    finally:
        if connection is not None:
            connection.close()
