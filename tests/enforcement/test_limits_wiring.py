"""One enforcement check per LimitsConfig field, through public functions only."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ai_data_analyst.analysis import (
    AnalysisPlan,
    ExecutionTimeError,
    SummaryStatsParams,
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


class _FakeClock:
    """Clock stub for ``operations.time`` that advances on every reading."""

    def __init__(self, step_seconds: float) -> None:
        self._now = 0.0
        self._step_seconds = step_seconds

    def monotonic(self) -> float:
        self._now += self._step_seconds
        return self._now


def _summary_plan() -> AnalysisPlan:
    return AnalysisPlan(steps=tuple(SummaryStatsParams(columns=("demand_mwh",)) for _ in range(3)))


def _small_dataset(sample_csv_path: Path):
    ingested = load_csv_path(sample_csv_path)
    return ingested.frame, profile_ingested(ingested)


def test_max_execution_seconds_is_enforced(
    sample_csv_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_data_analyst.analysis import operations

    # Each reading advances 0.6 s: the deadline (0.6 + 1.0) is crossed at the
    # second per-step check, so the run must stop before the last step.
    monkeypatch.setattr(operations, "time", _FakeClock(step_seconds=0.6))
    frame, profile = _small_dataset(sample_csv_path)

    with pytest.raises(ExecutionTimeError, match="max_execution_seconds=1"):
        execute_plan(
            _summary_plan(),
            frame,
            profile,
            LimitsConfig(max_execution_seconds=1),
        )


def test_max_execution_seconds_allows_a_plan_within_the_limit(
    sample_csv_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_data_analyst.analysis import operations

    monkeypatch.setattr(operations, "time", _FakeClock(step_seconds=0.6))
    frame, profile = _small_dataset(sample_csv_path)
    plan = _summary_plan()

    artifacts = execute_plan(
        plan,
        frame,
        profile,
        LimitsConfig(max_execution_seconds=3600),
    )

    assert len(artifacts) == len(plan.steps)


def test_max_execution_seconds_does_not_fire_without_elapsed_time(
    sample_csv_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_data_analyst.analysis import operations

    monkeypatch.setattr(operations, "time", _FakeClock(step_seconds=0.0))
    frame, profile = _small_dataset(sample_csv_path)
    plan = _summary_plan()

    artifacts = execute_plan(
        plan,
        frame,
        profile,
        LimitsConfig(max_execution_seconds=1),
    )

    assert len(artifacts) == len(plan.steps)


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
