"""Replaceable interface for natural-language-to-SQL generation."""

from typing import Protocol

from ai_data_analyst.sql_agent.contracts import SchemaSnapshot, SQLCandidate


class SQLGenerator(Protocol):
    """Interface implemented by fake and real SQL generation providers."""

    def generate(self, question: str, schema: SchemaSnapshot) -> SQLCandidate:
        """Generate an untrusted SQL candidate for a question and schema."""
        ...


class StaticSQLGenerator:
    """Deterministic generator for tests and local pipeline development.

    This is not an LLM. It returns a configured candidate so the pipeline
    can be tested without API keys, network access, or model costs.
    """

    def __init__(self, sql: str) -> None:
        self._sql = sql

    def generate(self, question: str, schema: SchemaSnapshot) -> SQLCandidate:
        del schema  # The fake returns configured SQL; it does not infer from schema.
        return SQLCandidate(sql=self._sql, question=question)
