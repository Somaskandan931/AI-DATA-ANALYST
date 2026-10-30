"""End-to-end enforcement checks through the SQL module's public API.

Imports only public modules (``sql_agent.validator``, ``sql_agent.executor``,
``sql_agent.schema`` and ``sql_agent.contracts``); no SQL module code is changed.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import quote

import pytest

from ai_data_analyst.security import LimitsConfig
from ai_data_analyst.sql_agent import executor
from ai_data_analyst.sql_agent.contracts import (
    SchemaSnapshot,
    SQLCandidate,
    SQLValidationResult,
)
from ai_data_analyst.sql_agent.executor import SQLExecutionError, execute_sql
from ai_data_analyst.sql_agent.schema import SchemaAllowList, discover_schema
from ai_data_analyst.sql_agent.validator import validate_sql

SLOW_QUERY = (
    "SELECT COUNT(*) FROM numbers AS a "
    "JOIN numbers AS b ON a.id <= b.id "
    "JOIN numbers AS c ON b.id <= c.id"
)

PAYLOAD = "Robert'); DROP TABLE people; --"

ConnectCall = tuple[tuple[object, ...], dict[str, object]]


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


def _people_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute("INSERT INTO people (name) VALUES ('Asha')")


def _validated_select(path: Path, sql: str) -> tuple[SchemaSnapshot, SQLValidationResult]:
    snapshot = discover_schema(path, SchemaAllowList(tables={"people": None}))
    allowed = validate_sql(SQLCandidate(sql=sql), snapshot)
    assert allowed.allowed, allowed.violations
    return snapshot, allowed


def _normalize_statement(statement: str) -> str:
    return " ".join(statement.split()).casefold()


def assert_readonly_setup(
    connect_calls: Sequence[ConnectCall],
    traced_statements: Sequence[str],
) -> None:
    """Assert the recorded connection was opened read-only before any query ran."""
    assert connect_calls, "the executor never opened a connection"
    args, kwargs = connect_calls[-1]
    assert args, "sqlite3.connect was called without a URI"
    uri = args[0]
    assert isinstance(uri, str) and uri.startswith("file:"), uri
    assert "mode=ro" in uri, uri
    assert kwargs.get("uri") is True

    normalized = [_normalize_statement(statement) for statement in traced_statements]
    pragma = "pragma query_only = on"
    assert pragma in normalized, traced_statements
    select_index = next(
        (index for index, statement in enumerate(normalized) if statement.startswith("select")),
        None,
    )
    assert select_index is not None, traced_statements
    assert normalized.index(pragma) < select_index, traced_statements


def _connect_call(
    uri: str = "file:/tmp/people.sqlite?mode=ro",
    uri_kwarg: bool = True,
) -> ConnectCall:
    return ((uri,), {"uri": uri_kwarg})


def test_readonly_helper_accepts_a_correct_setup() -> None:
    assert_readonly_setup(
        [_connect_call()],
        ["PRAGMA query_only = ON", "SELECT name FROM people"],
    )


def test_readonly_helper_rejects_a_uri_without_mode_ro() -> None:
    with pytest.raises(AssertionError):
        assert_readonly_setup(
            [_connect_call(uri="file:/tmp/people.sqlite")],
            ["PRAGMA query_only = ON", "SELECT name FROM people"],
        )


def test_readonly_helper_rejects_a_missing_uri_flag() -> None:
    with pytest.raises(AssertionError):
        assert_readonly_setup(
            [_connect_call(uri_kwarg=False)],
            ["PRAGMA query_only = ON", "SELECT name FROM people"],
        )


def test_readonly_helper_rejects_a_missing_pragma() -> None:
    with pytest.raises(AssertionError):
        assert_readonly_setup(
            [_connect_call()],
            ["SELECT name FROM people"],
        )


def test_readonly_helper_rejects_a_pragma_after_the_select() -> None:
    with pytest.raises(AssertionError):
        assert_readonly_setup(
            [_connect_call()],
            ["SELECT name FROM people", "PRAGMA query_only = ON"],
        )


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


def test_sqlite_rejects_writes_with_the_documented_readonly_settings(tmp_path: Path) -> None:
    # This checks SQLite's own behaviour with the documented URI and pragma.
    # test_executor_opens_a_read_only_connection checks that execute_sql uses them.
    path = tmp_path / "readonly.sqlite"
    _people_database(path)

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


def test_executor_opens_a_read_only_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "people.sqlite"
    _people_database(path)
    snapshot, allowed = _validated_select(path, "SELECT name FROM people")

    connect_calls: list[ConnectCall] = []
    traced_statements: list[str] = []
    original_connect = sqlite3.connect

    def spy_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        connect_calls.append((args, kwargs))
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(traced_statements.append)
        return connection

    monkeypatch.setattr(executor.sqlite3, "connect", spy_connect)

    result = execute_sql(path, allowed, snapshot)

    assert result.rows == (("Asha",),)
    assert_readonly_setup(connect_calls, traced_statements)


def test_executing_a_select_does_not_change_the_database_bytes(tmp_path: Path) -> None:
    path = tmp_path / "people.sqlite"
    _people_database(path)
    snapshot, allowed = _validated_select(path, "SELECT name FROM people")
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    result = execute_sql(path, allowed, snapshot)

    after = hashlib.sha256(path.read_bytes()).hexdigest()
    assert result.rows == (("Asha",),)
    assert after == before


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
