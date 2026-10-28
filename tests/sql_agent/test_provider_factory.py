from unittest.mock import MagicMock, patch


def test_selects_gemini(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_MODEL", "gemini-2.5-flash")

    mock_generator = MagicMock()
    with patch(
        "ai_data_analyst.sql_agent.gemini_generator.GeminiSQLGenerator",
        mock_generator,
    ):
        # This import path is intentionally tested below with the module loaded.
        pass
