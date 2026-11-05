"""Create the configured SQL generator without changing pipeline safety."""

import os

from dotenv import load_dotenv

from ai_data_analyst.sql_agent.errors import LLMConfigurationError
from ai_data_analyst.sql_agent.generator import SQLGenerator


def create_sql_generator() -> SQLGenerator:
    """Build the SQL generator selected by LLM_PROVIDER."""
    load_dotenv()

    raw_provider = os.getenv("LLM_PROVIDER") or ""
    provider = raw_provider.strip().lower() or "gemini"
    model = os.getenv("LLM_MODEL", "").strip()

    if provider == "gemini":
        from ai_data_analyst.sql_agent.gemini_generator import GeminiSQLGenerator

        return GeminiSQLGenerator(model=model or None)

    if provider == "ollama":
        from ai_data_analyst.sql_agent.ollama_generator import OllamaSQLGenerator

        return OllamaSQLGenerator(model=model or "qwen2.5-coder:7b")

    raise LLMConfigurationError(
        f"Unsupported LLM_PROVIDER value {raw_provider.strip()!r}. "
        "Supported values are 'gemini' and 'ollama'."
    )
