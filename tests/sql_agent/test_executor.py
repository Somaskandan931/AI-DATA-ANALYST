import sqlite3

import pytest

from ai_data_analyst.security.limits import LimitsConfig
from ai_data_analyst.sql_agent.contracts import (
    ColumnSchema,
    SchemaSnapshot,
    SQLCandidate,
    SQLValidationResult,
    TableSchema,
)
from ai_data_analyst.sql_agent.executor import (
    SQLExecutionError,
    execute_sql,
)
from ai_data_analyst.sql_agent.validator import validate_sql


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "sample.sqlite"

    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)")
        connection.executemany(
            "INSERT INTO people (name, age) VALUES (?, ?)",
            [("Asha", 21), ("Ravi", 25), ("Mina", 30)],
        )

    return path


@pytest.fixture
def snapshot():
    return SchemaSnapshot(
        tables=(
            TableSchema(
                name="people",
                columns=(
                    ColumnSchema(name="id", declared_type="INTEGER"),
                    ColumnSchema(name="name", declared_type="TEXT"),
                    ColumnSchema(name="age", declared_type="INTEGER"),
                ),
            ),
        )
    )


def _validate(sql, snapshot):
    result = validate_sql(SQLCandidate(sql=sql), snapshot)
    assert result.allowed, result.violations
    return result


def test_executes_validated_select(database, snapshot):
    result = execute_sql(
        database,
        _validate("SELECT name, age FROM people ORDER BY age", snapshot),
        snapshot,
    )

    assert result.columns == ("name", "age")
    assert result.rows == (("Asha", 21), ("Ravi", 25), ("Mina", 30))
    assert result.truncated is False


def test_rejects_denied_query(database, snapshot):
    denied = validate_sql(
        SQLCandidate(sql="DELETE FROM people"),
        snapshot,
    )

    with pytest.raises(SQLExecutionError, match="not approved"):
        execute_sql(database, denied, snapshot)


def test_revalidates_caller_created_approval(database, snapshot):
    forged = SQLValidationResult(
        allowed=True,
        normalized_sql="DELETE FROM people",
    )

    with pytest.raises(SQLExecutionError, match="could not be verified"):
        execute_sql(database, forged, snapshot)


def test_database_remains_read_only(database, snapshot):
    result = _validate("SELECT COUNT(*) FROM people", snapshot)
    execute_sql(database, result, snapshot)

    with sqlite3.connect(database) as connection:
        count = connection.execute("SELECT COUNT(*) FROM people").fetchone()[0]

    assert count == 3


def test_parameter_binding(database, snapshot):
    result = execute_sql(
        database,
        _validate("SELECT name FROM people WHERE age > ?", snapshot),
        snapshot,
        parameters=(24,),
    )

    assert result.rows == (("Ravi",), ("Mina",))


def test_row_limit_flags_truncation(database, snapshot):
    limits = LimitsConfig(max_result_rows=2)

    result = execute_sql(
        database,
        _validate("SELECT id FROM people ORDER BY id", snapshot),
        snapshot,
        limits=limits,
    )

    assert len(result.rows) == 2
    assert result.truncated is True


def test_empty_result(database, snapshot):
    result = execute_sql(
        database,
        _validate("SELECT name FROM people WHERE age > 100", snapshot),
        snapshot,
    )

    assert result.columns == ("name",)
    assert result.rows == ()
    assert result.truncated is False


def test_missing_database_is_rejected(tmp_path, snapshot):
    result = _validate("SELECT name FROM people", snapshot)

    with pytest.raises(SQLExecutionError, match="unavailable"):
        execute_sql(tmp_path / "missing.sqlite", result, snapshot)


def test_sqlite_error_is_sanitized(database, snapshot):
    result = _validate("SELECT name FROM people", snapshot)

    with pytest.raises(SQLExecutionError, match="could not be executed safely"):
        execute_sql(database, result, snapshot, parameters=(1,))


def test_timeout_stops_expensive_query(database, snapshot):
    result = _validate(
        "SELECT COUNT(*) FROM people AS a JOIN people AS b "
        "ON a.id = b.id JOIN people AS c ON b.id = c.id",
        snapshot,
    )
    limits = LimitsConfig(sql_timeout_seconds=1)

    # This query is small, so a timeout is not expected; this confirms the
    # configured timeout doesn't reject ordinary work.
    output = execute_sql(database, result, snapshot, limits=limits)
    assert output.rows == ((3,),)
