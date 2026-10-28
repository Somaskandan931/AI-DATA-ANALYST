"""Typed contracts for the M2 Natural-Language-to-SQL module.

These models are intentionally small. They describe *data* flowing between M2
steps; none of the text they carry (schema names, questions, SQL) is ever
treated as an instruction by the code.

``SQLValidationResult`` (Stage 2) is the structured allow/deny outcome of
``validator.validate_sql``.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_SQL_LENGTH = 10_000


def fold_identifier(name: str) -> str:
    """Case-fold an identifier the way SQLite does (ASCII letters only)."""
    return "".join(ch.lower() if ch.isascii() else ch for ch in name)


class _Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ColumnSchema(_Contract):
    """One column of an allow-listed table."""

    name: str = Field(min_length=1)
    declared_type: str = ""
    not_null: bool = False
    primary_key: bool = False


class TableSchema(_Contract):
    """One allow-listed table and its allow-listed columns."""

    name: str = Field(min_length=1)
    columns: tuple[ColumnSchema, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_columns(self) -> "TableSchema":
        seen = set()
        for column in self.columns:
            key = fold_identifier(column.name)
            if key in seen:
                raise ValueError(f"duplicate column name in table {self.name!r}: {column.name!r}")
            seen.add(key)
        return self

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    def has_column(self, name: str) -> bool:
        key = fold_identifier(name)
        return any(fold_identifier(column.name) == key for column in self.columns)


class SchemaSnapshot(_Contract):
    """The only schema M2 may expose to generators and validators.

    An empty snapshot is valid and means "nothing is accessible".
    """

    tables: tuple[TableSchema, ...] = ()

    @model_validator(mode="after")
    def _unique_tables(self) -> "SchemaSnapshot":
        seen = set()
        for table in self.tables:
            key = fold_identifier(table.name)
            if key in seen:
                raise ValueError(f"duplicate table name: {table.name!r}")
            seen.add(key)
        return self

    def get_table(self, name: str) -> TableSchema | None:
        key = fold_identifier(name)
        for table in self.tables:
            if fold_identifier(table.name) == key:
                return table
        return None

    def has_table(self, name: str) -> bool:
        return self.get_table(name) is not None

    def has_column(self, table: str, column: str) -> bool:
        found = self.get_table(table)
        return found is not None and found.has_column(column)


class SQLCandidate(_Contract):
    """Untrusted SQL text proposed for a user question.

    Holding a candidate says nothing about safety; it must pass validation
    before anything may execute it.
    """

    sql: str = Field(min_length=1, max_length=MAX_SQL_LENGTH)
    question: str | None = None

    @model_validator(mode="after")
    def _not_blank(self) -> "SQLCandidate":
        if not self.sql.strip():
            raise ValueError("sql must not be blank")
        return self


class ViolationCode(StrEnum):
    """Stable, machine-readable reasons a candidate was denied."""

    PARSE_ERROR = "parse_error"
    MULTIPLE_STATEMENTS = "multiple_statements"
    NOT_SELECT = "not_select"
    UNSUPPORTED_SYNTAX = "unsupported_syntax"
    UNKNOWN_TABLE = "unknown_table"
    UNRESOLVED_COLUMN = "unresolved_column"
    TOO_COMPLEX = "too_complex"
    INTERNAL_CHECK_FAILED = "internal_check_failed"


class ValidationViolation(_Contract):
    """One reason for denial.

    ``message`` is always a fixed, library-authored sentence. It never echoes
    text taken from the candidate SQL, so it is safe to log and to show.
    """

    code: ViolationCode
    message: str = Field(min_length=1, max_length=200)


class SQLValidationResult(_Contract):
    """Outcome of validating one ``SQLCandidate`` against a ``SchemaSnapshot``.

    Allowed results carry ``normalized_sql``: the exact text a later stage must
    execute (never the original candidate text). Denied results carry at least
    one violation and no SQL.
    """

    allowed: bool
    normalized_sql: str | None = None
    referenced_tables: tuple[str, ...] = ()
    violations: tuple[ValidationViolation, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> "SQLValidationResult":
        if self.allowed:
            if not self.normalized_sql or not self.normalized_sql.strip():
                raise ValueError("an allowed result must carry normalized_sql")
            if self.violations:
                raise ValueError("an allowed result cannot have violations")
        else:
            if self.normalized_sql is not None or self.referenced_tables:
                raise ValueError("a denied result must not carry SQL or table names")
            if not self.violations:
                raise ValueError("a denied result needs at least one violation")
        return self

    @property
    def reason_codes(self) -> tuple[ViolationCode, ...]:
        return tuple(v.code for v in self.violations)
