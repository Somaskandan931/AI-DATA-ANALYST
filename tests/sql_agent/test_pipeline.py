import sqlite3

import pytest

from ai_data_analyst.sql_agent.contracts import (
    ColumnSchema,
    SchemaSnapshot,
    TableSchema,
)
from ai_data_analyst.sql_agent.generator import StaticSQLGenerator
from ai_data_analyst.sql_agent.pipeline import (
    SQLPipelineError,
    SQLQueryDenied,
    run_sql_pipeline,
)


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "sample.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE people (id INTEGER, name TEXT)")
        connection.executemany(
            "INSERT INTO people VALUES (?, ?)",
            [(1, "Asha"), (2, "Ravi")],
        )
    return path


@pytest.fixture
def schema():
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


def test_pipeline_generates_validates_and_executes(database, schema):
    result = run_sql_pipeline(
        question="Show all names",
        schema=schema,
        db_path=database,
        generator=StaticSQLGenerator("SELECT name FROM people ORDER BY id"),
    )

    assert result.columns == ("name",)
    assert result.rows == (("Asha",), ("Ravi",))


def test_pipeline_denies_unsafe_sql(database, schema):
    with pytest.raises(SQLQueryDenied):
        run_sql_pipeline(
            question="Delete all people",
            schema=schema,
            db_path=database,
            generator=StaticSQLGenerator("DELETE FROM people"),
        )

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM people").fetchone()[0] == 2


def test_pipeline_rejects_empty_question(database, schema):
    with pytest.raises(SQLPipelineError, match="question is required"):
        run_sql_pipeline(
            question="  ",
            schema=schema,
            db_path=database,
            generator=StaticSQLGenerator("SELECT id FROM people"),
        )


def test_pipeline_rejects_empty_schema(database):
    with pytest.raises(SQLPipelineError, match="schema"):
        run_sql_pipeline(
            question="Show all names",
            schema=SchemaSnapshot(),
            db_path=database,
            generator=StaticSQLGenerator("SELECT 1"),
        )


def test_pipeline_sanitizes_generator_failure(database, schema):
    class BrokenGenerator:
        def generate(self, question, schema):
            raise RuntimeError("private provider details")

    with pytest.raises(SQLPipelineError, match="SQL generation failed") as exc:
        run_sql_pipeline(
            question="Show all names",
            schema=schema,
            db_path=database,
            generator=BrokenGenerator(),
        )

    assert "private provider details" not in str(exc.value)
