import json
import sqlite3
import urllib.request

import pytest

from ai_data_analyst.sql_agent.contracts import (
    ColumnSchema,
    SchemaSnapshot,
    TableSchema,
)
from ai_data_analyst.sql_agent.ollama_generator import OllamaSQLGenerator
from ai_data_analyst.sql_agent.pipeline import run_sql_pipeline

OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5-coder:7b"


def _ollama_model_available() -> bool:
    """True only when a local Ollama server is up and has the model pulled."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=2) as response:
            models = json.load(response).get("models", [])
    except (OSError, ValueError):
        return False
    return any(m.get("name") == OLLAMA_MODEL for m in models)


# Needs a running Ollama server and a pulled model, which CI runners do not have.
# Run it locally with: ollama pull qwen2.5-coder:7b && pytest -m integration
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _ollama_model_available(),
        reason=f"Ollama server with model {OLLAMA_MODEL} is not available",
    ),
]


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
        generator=OllamaSQLGenerator(model=OLLAMA_MODEL, host=OLLAMA_HOST),
    )

    assert "name" in result.columns
    assert result.rows == (("Asha",), ("Ravi",))
