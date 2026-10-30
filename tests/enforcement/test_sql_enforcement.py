"""End-to-end enforcement checks through the SQL module's public API.

Imports only public modules (``sql_agent.validator``, ``sql_agent.executor``,
``sql_agent.schema`` and ``sql_agent.contracts``); no SQL module code is changed.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from urllib.parse import quote

import pytest

from ai_data_analyst.security import LimitsConfig
from ai_data_analyst.sql_agent.contracts import SchemaSnapshot, SQLCandidate
from ai_data_analyst.sql_agent.executor import SQLExecutionError, execute_sql
from ai_data_analyst.sql_agent.schema import SchemaAllowList, discover_schema
from ai_data_analyst.sql_agent.validator import validate_sql

SLOW_QUERY = (
    "SELECT COUNT(*) FROM numbers AS a "
    "JOIN numbers AS b ON a.id <= b.id "
    "JOIN numbers AS c ON b.id <= c.id"
)

PAYLOAD = "Robert'); DROP TABLE people; --"


@pytest.fixture
def slow_database(tmp_path: Path) -> Path:
    path = tmp_path / "numbers.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE numbers (id INTEGER PRIMARY KEY, value INTEGER)")
        connection.executemany(
            "INSERT INTO numbers (value) VALUES (?)",
            [(number,) for number in range(2000)],
        )
    return path


@pytest.fixture
def slow_snapshot(slow_database: Path) -> SchemaSnapshot:
    return discover_schema(slow_database, SchemaAllowList(tables={"numbers": None}))


def test_timeout_expiry_raises_execution_error(
    slow_database: Path, slow_snapshot: SchemaSnapshot
) -> None:
    allowed = validate_sql(SQLCandidate(sql=SLOW_QUERY), slow_snapshot)
    assert allowed.allowed, allowed.violations

    started = time.monotonic()
    with pytest.raises(SQLExecutionError):
        execute_sql(
            slow_database,
            allowed,
            slow_snapshot,
            limits=LimitsConfig(sql_timeout_seconds=1),
        )
    assert time.monotonic() - started < 30


def test_read_only_connection_rejects_writes(tmp_path: Path) -> None:
    # The executor opens its connection inside execute_sql, which only accepts
    # validated SELECTs, so this replicates its documented URI and pragma setup.
    path = tmp_path / "readonly.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute("INSERT INTO people (name) VALUES ('Asha')")

    encoded_path = quote(path.resolve().as_posix(), safe="/:")
    connection = sqlite3.connect(f"file:{encoded_path}?mode=ro", uri=True, isolation_level=None)
    try:
        connection.execute("PRAGMA query_only = ON")
        for statement in (
            "INSERT INTO people (name) VALUES ('Ravi')",
            "CREATE TABLE intruders (id INTEGER)",
            "DELETE FROM people",
        ):
            with pytest.raises(sqlite3.OperationalError):
                connection.execute(statement)
        assert connection.execute("SELECT COUNT(*) FROM people").fetchone() == (1,)
    finally:
        connection.close()


def test_parameters_are_bound_not_interpolated(tmp_path: Path) -> None:
    path = tmp_path / "people.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute("INSERT INTO people (name) VALUES (?)", (PAYLOAD,))

    snapshot = discover_schema(path, SchemaAllowList(tables={"people": None}))
    allowed = validate_sql(SQLCandidate(sql="SELECT name FROM people WHERE name = ?"), snapshot)
    assert allowed.allowed, allowed.violations

    result = execute_sql(path, allowed, snapshot, parameters=(PAYLOAD,))

    assert result.columns == ("name",)
    assert result.rows == ((PAYLOAD,),)

    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "people" in tables
        assert connection.execute("SELECT COUNT(*) FROM people").fetchone() == (1,)
