"""One enforcement check per LimitsConfig field, through public functions only."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import pytest

from ai_data_analyst.analysis import (
    AnalysisPlan,
    ClusteringParams,
    ExecutionTimeError,
    execute_plan,
)
from ai_data_analyst.ingestion import IngestionError, load_csv, load_csv_path
from ai_data_analyst.profiling import profile_ingested
from ai_data_analyst.security import LimitsConfig
from ai_data_analyst.sql_agent.contracts import (
    ColumnSchema,
    SchemaSnapshot,
    SQLCandidate,
    SQLValidationResult,
    TableSchema,
)
from ai_data_analyst.sql_agent.executor import SQLExecutionError, execute_sql
from ai_data_analyst.sql_agent.validator import validate_sql

SLOW_QUERY = (
    "SELECT COUNT(*) FROM numbers AS a "
    "JOIN numbers AS b ON a.id <= b.id "
    "JOIN numbers AS c ON b.id <= c.id"
)


def _csv_bytes(rows: list[list[str]]) -> bytes:
    lines = "".join(",".join(row) + "\n" for row in rows)
    return lines.encode("utf-8")


def _people_snapshot() -> SchemaSnapshot:
    return SchemaSnapshot(
        tables=(
            TableSchema(
                name="people",
                columns=(
                    ColumnSchema(name="id", declared_type="INTEGER"),
                    ColumnSchema(name="name", declared_type="TEXT"),
                ),
            ),
        )
    )


def _people_database(path: Path, rows: int) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT)")
        connection.executemany(
            "INSERT INTO people (name) VALUES (?)",
            [(f"person-{number}",) for number in range(rows)],
        )


def _validate(sql: str, snapshot: SchemaSnapshot) -> SQLValidationResult:
    result = validate_sql(SQLCandidate(sql=sql), snapshot)
    assert result.allowed, result.violations
    return result


def test_max_upload_bytes_is_enforced() -> None:
    with pytest.raises(IngestionError) as exc_info:
        load_csv(b"a,b\n1,2\n", "upload.csv", LimitsConfig(max_upload_bytes=4))
    assert exc_info.value.code == "file_too_large"


def test_max_rows_is_enforced() -> None:
    content = _csv_bytes([["a", "b"], ["1", "2"], ["3", "4"], ["5", "6"]])
    with pytest.raises(IngestionError) as exc_info:
        load_csv(content, "upload.csv", LimitsConfig(max_rows=2))
    assert exc_info.value.code == "too_many_rows"


def test_max_columns_is_enforced() -> None:
    content = _csv_bytes([["a", "b", "c"], ["1", "2", "3"]])
    with pytest.raises(IngestionError) as exc_info:
        load_csv(content, "upload.csv", LimitsConfig(max_columns=2))
    assert exc_info.value.code == "too_many_columns"


def test_max_execution_seconds_is_enforced(tmp_path: Path) -> None:
    path = tmp_path / "numeric.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["x", "y", "z"])
        for number in range(60_000):
            writer.writerow([number % 97, (number * 7) % 89, (number * 13) % 83])

    ingested = load_csv_path(path)
    profile = profile_ingested(ingested)
    step = ClusteringParams(columns=("x", "y", "z"), k=5)
    plan = AnalysisPlan(steps=tuple(step for _ in range(20)))

    with pytest.raises(ExecutionTimeError):
        execute_plan(
            plan,
            ingested.frame,
            profile,
            LimitsConfig(max_execution_seconds=1),
        )


def test_sql_timeout_seconds_is_enforced(tmp_path: Path) -> None:
    path = tmp_path / "numbers.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE numbers (id INTEGER PRIMARY KEY, value INTEGER)")
        connection.executemany(
            "INSERT INTO numbers (value) VALUES (?)",
            [(number,) for number in range(2000)],
        )

    snapshot = SchemaSnapshot(
        tables=(
            TableSchema(
                name="numbers",
                columns=(
                    ColumnSchema(name="id", declared_type="INTEGER"),
                    ColumnSchema(name="value", declared_type="INTEGER"),
                ),
            ),
        )
    )
    allowed = _validate(SLOW_QUERY, snapshot)

    with pytest.raises(SQLExecutionError):
        execute_sql(path, allowed, snapshot, limits=LimitsConfig(sql_timeout_seconds=1))


def test_max_result_rows_is_enforced(tmp_path: Path) -> None:
    path = tmp_path / "people.sqlite"
    _people_database(path, rows=3)
    snapshot = _people_snapshot()
    allowed = _validate("SELECT id FROM people ORDER BY id", snapshot)

    result = execute_sql(path, allowed, snapshot, limits=LimitsConfig(max_result_rows=2))

    assert len(result.rows) == 2
    assert result.truncated is True
