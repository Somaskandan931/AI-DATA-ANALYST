from unittest.mock import Mock, patch

import pytest

from ai_data_analyst.sql_agent.contracts import (
    ColumnSchema,
    SchemaSnapshot,
    TableSchema,
)
from ai_data_analyst.sql_agent.ollama_generator import OllamaSQLGenerator


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


@patch("ai_data_analyst.sql_agent.ollama_generator.ollama.Client")
def test_generates_sql_candidate(mock_client_class, schema):
    mock_client = Mock()
    mock_client_class.return_value = mock_client
    mock_client.chat.return_value.message.content = "SELECT name FROM people ORDER BY id"

    generator = OllamaSQLGenerator()
    candidate = generator.generate("Show all names", schema)

    assert candidate.sql == "SELECT name FROM people ORDER BY id"
    assert candidate.question == "Show all names"
    mock_client.chat.assert_called_once()


@patch("ai_data_analyst.sql_agent.ollama_generator.ollama.Client")
def test_removes_markdown_fences(mock_client_class, schema):
    mock_client = Mock()
    mock_client_class.return_value = mock_client
    mock_client.chat.return_value.message.content = "```sql\nSELECT name FROM people\n```"

    candidate = OllamaSQLGenerator().generate("Show names", schema)

    assert candidate.sql == "SELECT name FROM people"


@pytest.mark.parametrize("content", ["", "   ", None])
@patch("ai_data_analyst.sql_agent.ollama_generator.ollama.Client")
def test_rejects_empty_or_invalid_response(mock_client_class, content, schema):
    mock_client = Mock()
    mock_client_class.return_value = mock_client
    mock_client.chat.return_value.message.content = content

    with pytest.raises(ValueError, match="empty or invalid response"):
        OllamaSQLGenerator().generate("Show names", schema)
