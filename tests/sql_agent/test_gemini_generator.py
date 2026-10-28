from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ai_data_analyst.sql_agent.contracts import ColumnSchema, SchemaSnapshot, TableSchema
from ai_data_analyst.sql_agent.gemini_generator import GeminiSQLGenerator


@pytest.fixture
def schema() -> SchemaSnapshot:
    return SchemaSnapshot(
        tables=[
            TableSchema(
                name="people",
                columns=[
                    ColumnSchema(name="id", declared_type="INTEGER"),
                    ColumnSchema(name="name", declared_type="TEXT"),
                ],
            )
        ]
    )


@patch("ai_data_analyst.sql_agent.gemini_generator.genai.Client")
def test_generates_sql_candidate(mock_client_class, schema):
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = SimpleNamespace(
        text="SELECT name FROM people"
    )
    mock_client_class.return_value = mock_client

    generator = GeminiSQLGenerator(api_key="test-key")
    candidate = generator.generate("Show all names", schema)

    assert candidate.sql == "SELECT name FROM people"
    assert candidate.question == "Show all names"


@patch("ai_data_analyst.sql_agent.gemini_generator.genai.Client")
def test_strips_markdown_fences(mock_client_class, schema):
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = SimpleNamespace(
        text="```sql\nSELECT name FROM people\n```"
    )
    mock_client_class.return_value = mock_client

    generator = GeminiSQLGenerator(api_key="test-key")
    candidate = generator.generate("Show names", schema)

    assert candidate.sql == "SELECT name FROM people"


@pytest.mark.parametrize("response_text", ["", "   ", None])
@patch("ai_data_analyst.sql_agent.gemini_generator.genai.Client")
def test_rejects_empty_response(mock_client_class, response_text, schema):
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = SimpleNamespace(text=response_text)
    mock_client_class.return_value = mock_client

    generator = GeminiSQLGenerator(api_key="test-key")

    with pytest.raises(ValueError, match="empty or invalid response"):
        generator.generate("Show names", schema)


def test_requires_api_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    with (
        patch("ai_data_analyst.sql_agent.gemini_generator.load_dotenv"),
        pytest.raises(ValueError, match="LLM_API_KEY is not configured"),
    ):
        GeminiSQLGenerator()
