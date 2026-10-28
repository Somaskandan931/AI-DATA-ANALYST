import sqlite3

from ai_data_analyst.sql_agent.contracts import (
    ColumnSchema,
    SchemaSnapshot,
    TableSchema,
)
from ai_data_analyst.sql_agent.ollama_generator import OllamaSQLGenerator
from ai_data_analyst.sql_agent.pipeline import run_sql_pipeline


def test_ollama_generates_and_runs_validated_sql(tmp_path):
    db_path = tmp_path / "sample.sqlite"

    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE people (id INTEGER, name TEXT)")
        connection.executemany(
            "INSERT INTO people VALUES (?, ?)",
            [(1, "Asha"), (2, "Ravi")],
        )

    schema = SchemaSnapshot(
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

    result = run_sql_pipeline(
        question="Show all names of people ordered by id",
        schema=schema,
        db_path=db_path,
        generator=OllamaSQLGenerator(),
    )

    assert "name" in result.columns
    assert result.rows == (("Asha",), ("Ravi",))
