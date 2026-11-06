"""Orchestration for the validated, read-only SQL Agent flow."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ai_data_analyst.security.limits import LimitsConfig
from ai_data_analyst.sql_agent.ambiguity import detect_ambiguity
from ai_data_analyst.sql_agent.contracts import (
    SchemaSnapshot,
    SQLCandidate,
    SQLValidationResult,
)
from ai_data_analyst.sql_agent.executor import (
    SQLExecutionResult,
    execute_sql,
)
from ai_data_analyst.sql_agent.generator import SQLGenerator
from ai_data_analyst.sql_agent.validator import validate_sql


class SQLPipelineError(RuntimeError):
    """Safe failure while generating or preparing a SQL query."""


class SQLClarificationRequired(SQLPipelineError):
    """Raised when a question needs clarification before SQL generation."""

    def __init__(self, clarification_question: str) -> None:
        super().__init__(clarification_question)
        self.clarification_question = clarification_question


class SQLQueryDenied(SQLPipelineError):
    """The generated SQL did not pass deterministic validation."""

    def __init__(self, validation: SQLValidationResult) -> None:
        super().__init__("The generated SQL query was denied by validation.")
        self.validation = validation


@dataclass(frozen=True, slots=True)
class SQLPipelineResult:
    """Validated SQL and its read-only execution result."""

    normalized_sql: str
    execution: SQLExecutionResult


def _provider_failure_message(error: Exception) -> str:
    """Convert provider exceptions into safe, user-friendly messages."""

    code = getattr(error, "code", None)
    status = getattr(error, "status_code", None)

    if status is None:
        status = code

    status_number: int | None
    try:
        status_number = int(status) if status is not None else None
    except (TypeError, ValueError):
        status_number = None

    details = " ".join(
        str(value)
        for value in (
            getattr(error, "message", ""),
            getattr(error, "status", ""),
            code,
            error.__class__.__name__,
        )
        if value
    ).lower()

    if status_number == 429 or "resource_exhausted" in details or "quota" in details:
        return (
            "The AI provider's request quota has been reached. "
            "Please wait and try again, or check your provider's usage limits."
        )

    if (
        status_number in (401, 403)
        or "unauthorized" in details
        or "permission_denied" in details
        or "forbidden" in details
    ):
        return (
            "The AI provider rejected the credentials or access. "
            "Check your API key and provider permissions."
        )

    if status_number == 404 or "not_found" in details:
        return (
            "The configured AI model or provider resource was not found. "
            "Check the model name in your configuration."
        )

    if isinstance(error, (TimeoutError, ConnectionError, OSError)) or any(
        marker in details
        for marker in (
            "timeout",
            "timed out",
            "connectionerror",
            "connecterror",
            "network",
        )
    ):
        return (
            "Could not connect to the AI provider. Check your internet "
            "connection and provider availability, then try again."
        )

    if isinstance(error, ValueError) and (
        "empty" in str(error).lower() or "invalid response" in str(error).lower()
    ):
        return (
            "The AI provider returned an empty or unusable response. "
            "Please rephrase your question and try again."
        )

    return "SQL generation failed. Check the provider configuration and try again."


def run_sql_pipeline_with_details(
    question: str,
    schema: SchemaSnapshot,
    db_path: str | Path,
    generator: SQLGenerator,
    parameters: Sequence[object] | Mapping[str, object] | None = None,
    limits: LimitsConfig | None = None,
    *,
    skip_ambiguity_check: bool = False,
) -> SQLPipelineResult:
    """Check ambiguity, generate, validate, and execute SQL.

    Set skip_ambiguity_check=True only after the user has explicitly
    answered the clarification question in the UI.
    """

    if not question.strip():
        raise SQLPipelineError("A question is required.")

    if not schema.tables:
        raise SQLPipelineError("No accessible database schema is available.")

    # Check ambiguity before calling the AI provider.
    if not skip_ambiguity_check:
        ambiguity = detect_ambiguity(question, schema)

        if ambiguity.needs_clarification:
            raise SQLClarificationRequired(
                ambiguity.clarification_question or "Please clarify what result you want."
            )

    # Generate SQL candidate.
    try:
        candidate = generator.generate(question, schema)
    except Exception as exc:
        raise SQLPipelineError(_provider_failure_message(exc)) from None

    if not isinstance(candidate, SQLCandidate):
        raise SQLPipelineError("The AI provider returned an invalid SQL response.")

    if candidate.question is None:
        candidate = candidate.model_copy(update={"question": question})

    # Validate generated SQL before execution.
    validation = validate_sql(candidate, schema)

    if not validation.allowed or validation.normalized_sql is None:
        raise SQLQueryDenied(validation)

    # Execute only validated SQL.
    execution = execute_sql(
        db_path=db_path,
        validation=validation,
        snapshot=schema,
        parameters=parameters,
        limits=limits,
    )

    return SQLPipelineResult(
        normalized_sql=validation.normalized_sql,
        execution=execution,
    )


def run_sql_pipeline(
    question: str,
    schema: SchemaSnapshot,
    db_path: str | Path,
    generator: SQLGenerator,
    parameters: Sequence[object] | Mapping[str, object] | None = None,
    limits: LimitsConfig | None = None,
) -> SQLExecutionResult:
    """Backward-compatible pipeline returning only the execution result."""

    result = run_sql_pipeline_with_details(
        question=question,
        schema=schema,
        db_path=db_path,
        generator=generator,
        parameters=parameters,
        limits=limits,
    )

    return result.execution
