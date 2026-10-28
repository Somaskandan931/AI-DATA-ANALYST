"""Create the configured SQL generator without changing pipeline safety."""

import os

from dotenv import load_dotenv

from ai_data_analyst.sql_agent.generator import SQLGenerator


def create_sql_generator() -> SQLGenerator:
    """Build the SQL generator selected by LLM_PROVIDER."""
    load_dotenv()

    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    model = os.getenv("LLM_MODEL", "").strip()

    if provider == "gemini":
        from ai_data_analyst.sql_agent.gemini_generator import GeminiSQLGenerator

        return GeminiSQLGenerator(model=model or None)

    if provider == "ollama":
        from ai_data_analyst.sql_agent.ollama_generator import OllamaSQLGenerator

        return OllamaSQLGenerator(model=model or "qwen2.5-coder:7b")

    raise ValueError("Unsupported LLM_PROVIDER. Choose 'gemini' or 'ollama'.")
