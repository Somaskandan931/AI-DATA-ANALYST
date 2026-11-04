"""Adapter connecting the M2 SQL agent to the shared evaluation runner."""

from collections.abc import Mapping
from pathlib import Path

from ai_data_analyst.evaluation.runner import (
    ExecutionOutcome,
    ValidationOutcome,
)
from ai_data_analyst.security.limits import LimitsConfig
from ai_data_analyst.sql_agent.ambiguity import detect_ambiguity
from ai_data_analyst.sql_agent.contracts import (
    SchemaSnapshot,
    SQLCandidate,
)
from ai_data_analyst.sql_agent.executor import execute_sql
from ai_data_analyst.sql_agent.generator import SQLGenerator
from ai_data_analyst.sql_agent.validator import validate_sql


class M2BenchmarkSystem:
    """Expose M2 generation, validation and execution to the benchmark runner."""

    def __init__(
        self,
        generator: SQLGenerator,
        schema: SchemaSnapshot,
        db_path: str | Path,
        limits: LimitsConfig | None = None,
        sql_overrides: Mapping[str, str] | None = None,
    ) -> None:
        self.generator = generator
        self.schema = schema
        self.db_path = Path(db_path)
        self.limits = limits or LimitsConfig()
        self.sql_overrides = dict(sql_overrides or {})

    def generate(self, question: str) -> str | None:
        if question in self.sql_overrides:
            return self.sql_overrides[question]

        ambiguity = detect_ambiguity(question, self.schema)
        if ambiguity.needs_clarification:
            return None

        candidate = self.generator.generate(question, self.schema)
        if not isinstance(candidate, SQLCandidate):
            raise TypeError("The SQL generator returned an invalid candidate.")

        return candidate.sql

    def validate(self, sql: str) -> ValidationOutcome:
        result = validate_sql(SQLCandidate(sql=sql), self.schema)

        return ValidationOutcome(
            allowed=result.allowed,
            reason_codes=tuple(violation.code.value for violation in result.violations),
            normalized_sql=result.normalized_sql,
        )

    def execute(self, normalized_sql: str) -> ExecutionOutcome:
        validation = validate_sql(
            SQLCandidate(sql=normalized_sql),
            self.schema,
        )

        if not validation.allowed:
            raise RuntimeError("The SQL query was denied during revalidation.")

        result = execute_sql(
            db_path=self.db_path,
            validation=validation,
            snapshot=self.schema,
            limits=self.limits,
        )

        return ExecutionOutcome(
            columns=result.columns,
            rows=result.rows,
            truncated=result.truncated,
            timed_out=False,
        )
