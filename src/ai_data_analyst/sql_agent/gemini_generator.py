
"""Gemini-backed SQL generation provider."""

import os
import re

from dotenv import load_dotenv
from google import genai

from ai_data_analyst.sql_agent.contracts import (
    SchemaSnapshot,
    SQLCandidate,
)


class GeminiSQLGenerator:
    """Generate SQL candidates using Google's Gemini API."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        load_dotenv()

        self._model = (
            model
            or os.getenv("LLM_MODEL")
            or "gemini-2.5-flash"
        )

        resolved_api_key = (
            api_key
            or os.getenv("LLM_API_KEY")
        )

        if not resolved_api_key:
            raise ValueError("LLM_API_KEY is not configured.")

        self._client = genai.Client(
            api_key=resolved_api_key
        )

    def generate(
        self,
        question: str,
        schema: SchemaSnapshot,
    ) -> SQLCandidate:
        """Generate a SQL candidate from a question and schema."""

        schema_description = schema.model_dump_json(
            indent=2
        )

        prompt = f"""
You are a SQL generation assistant.

Generate exactly one read-only SQL SELECT query
for the user's question.

Rules:
- Generate only SELECT statements.
- Never generate INSERT, UPDATE, DELETE, DROP,
  ALTER, CREATE, or other modification statements.
- Use only tables and columns present in the schema.
- Do not invent table names or column names.
- Do not include explanations or Markdown.
- Return only the SQL query.

Database schema:
{schema_description}

User question:
{question}
"""

        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
        )

        response_text = getattr(
            response,
            "text",
            None,
        )

        if not response_text or not response_text.strip():
            raise ValueError(
                "Gemini returned an empty or invalid response."
            )

        sql = response_text.strip()

        # Remove Markdown code fences if Gemini adds them.
        sql = re.sub(
            r"^```(?:sql)?\s*",
            "",
            sql,
            flags=re.IGNORECASE,
        )

        sql = re.sub(
            r"\s*```$",
            "",
            sql,
        ).strip()

        if not sql:
            raise ValueError(
                "Gemini returned an empty or invalid response."
            )

        return SQLCandidate(
            question=question,
            sql=sql,
        )
