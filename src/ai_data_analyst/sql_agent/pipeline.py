"""Orchestration for the validated, read-only SQL Agent flow."""

from collections.abc import Mapping, Sequence
from pathlib import Path

from ai_data_analyst.security.limits import LimitsConfig
from ai_data_analyst.sql_agent.contracts import (
    SchemaSnapshot,
    SQLCandidate,
    SQLValidationResult,
)
from ai_data_analyst.sql_agent.executor import (
    SQLExecutionError,
    SQLExecutionResult,
    execute_sql,
)
from ai_data_analyst.sql_agent.generator import SQLGenerator
from ai_data_analyst.sql_agent.validator import validate_sql


class SQLPipelineError(RuntimeError):
    """Safe failure while generating or preparing a SQL query."""


class SQLQueryDenied(SQLPipelineError):
    """The generated SQL did not pass deterministic validation."""

    def __init__(self, validation: SQLValidationResult) -> None:
        super().__init__("The generated SQL query was denied by validation.")
        self.validation = validation


def run_sql_pipeline(
    question: str,
    schema: SchemaSnapshot,
    db_path: str | Path,
    generator: SQLGenerator,
    parameters: Sequence[object] | Mapping[str, object] | None = None,
    limits: LimitsConfig | None = None,
) -> SQLExecutionResult:
    """Generate, validate, and execute SQL without bypassing validation."""
    if not question.strip():
        raise SQLPipelineError("A question is required.")

    if not schema.tables:
        raise SQLPipelineError("No accessible database schema is available.")

    try:
        candidate = generator.generate(question, schema)
    except Exception:
        raise SQLPipelineError("SQL generation failed.") from None

    if not isinstance(candidate, SQLCandidate):
        raise SQLPipelineError("The generator returned an invalid SQL candidate.")

    # Attach the caller's question even if the provider omitted it.
    if candidate.question is None:
        candidate = candidate.model_copy(update={"question": question})

    validation = validate_sql(candidate, schema)
    if not validation.allowed:
        raise SQLQueryDenied(validation)

    try:
        return execute_sql(
            db_path=db_path,
            validation=validation,
            snapshot=schema,
            parameters=parameters,
            limits=limits,
        )
    except SQLExecutionError:
        raise
