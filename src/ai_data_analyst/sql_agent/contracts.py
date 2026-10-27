"""Typed contracts for the M2 Natural-Language-to-SQL module.

These models are intentionally small. They describe *data* flowing between M2
steps; none of the text they carry (schema names, questions, SQL) is ever
treated as an instruction by the code.

Validation results are deliberately not defined here yet: their shape depends
on what the SQL validator produces, so they are added in that stage.
"""

from typing import Optional, Tuple

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
    columns: Tuple[ColumnSchema, ...] = Field(min_length=1)

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
    def column_names(self) -> Tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    def has_column(self, name: str) -> bool:
        key = fold_identifier(name)
        return any(fold_identifier(column.name) == key for column in self.columns)


class SchemaSnapshot(_Contract):
    """The only schema M2 may expose to generators and validators.

    An empty snapshot is valid and means "nothing is accessible".
    """

    tables: Tuple[TableSchema, ...] = ()

    @model_validator(mode="after")
    def _unique_tables(self) -> "SchemaSnapshot":
        seen = set()
        for table in self.tables:
            key = fold_identifier(table.name)
            if key in seen:
                raise ValueError(f"duplicate table name: {table.name!r}")
            seen.add(key)
        return self

    def get_table(self, name: str) -> Optional[TableSchema]:
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
    question: Optional[str] = None

    @model_validator(mode="after")
    def _not_blank(self) -> "SQLCandidate":
        if not self.sql.strip():
            raise ValueError("sql must not be blank")
        return self
