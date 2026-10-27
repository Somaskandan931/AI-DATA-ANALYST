"""Deterministic SQLite schema discovery with explicit allow-listing.

Default-deny: only tables named in a ``SchemaAllowList`` are reported, and only
their allow-listed columns. SQLite internal tables (``sqlite_*``) and views are
never reported. Names and declared types read from the database are copied into
the snapshot as plain data and are never interpreted.

Limitation: SQLite lists virtual tables and their shadow tables as tables, so
only allow-list tables you intend to expose.
"""

import sqlite3
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_data_analyst.sql_agent.contracts import (
    ColumnSchema,
    SchemaSnapshot,
    TableSchema,
    fold_identifier,
)

_INTERNAL_PREFIX = "sqlite_"


class SchemaError(Exception):
    """Raised when the schema cannot be read or does not match the allow-list."""


class SchemaAllowList(BaseModel):
    """Explicit allow-list: table name -> column names, or None for all columns."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tables: dict[str, tuple[str, ...] | None] = Field(min_length=1)

    @field_validator("tables")
    @classmethod
    def _check_tables(
        cls, tables: dict[str, tuple[str, ...] | None]
    ) -> dict[str, tuple[str, ...] | None]:
        seen_tables = set()
        for table, columns in tables.items():
            if not table.strip():
                raise ValueError("table names must not be blank")
            key = fold_identifier(table)
            if key.startswith(_INTERNAL_PREFIX):
                raise ValueError(f"internal SQLite tables cannot be allow-listed: {table!r}")
            if key in seen_tables:
                raise ValueError(f"duplicate table in allow-list: {table!r}")
            seen_tables.add(key)
            if columns is None:
                continue
            if len(columns) == 0:
                raise ValueError(f"empty column list for {table!r}; use None to allow all columns")
            seen_columns = set()
            for column in columns:
                if not column.strip():
                    raise ValueError(f"blank column name for table {table!r}")
                column_key = fold_identifier(column)
                if column_key in seen_columns:
                    raise ValueError(f"duplicate column {column!r} for table {table!r}")
                seen_columns.add(column_key)
        return tables


def discover_schema(
    db_path: str | Path, allow_list: SchemaAllowList
) -> SchemaSnapshot:
    """Read allow-listed schema metadata from a SQLite file, read-only."""
    path = Path(db_path)
    if not path.is_file():
        raise SchemaError("database file not found")

    uri = path.resolve().as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise SchemaError("could not open database read-only") from exc

    try:
        connection.execute("PRAGMA query_only = ON")
        return _build_snapshot(connection, allow_list)
    except sqlite3.Error as exc:
        raise SchemaError("could not read schema metadata") from exc
    finally:
        connection.close()


def _build_snapshot(
    connection: sqlite3.Connection, allow_list: SchemaAllowList
) -> SchemaSnapshot:
    available: dict[str, str] = {}
    for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
        if not isinstance(name, str) or fold_identifier(name).startswith(_INTERNAL_PREFIX):
            continue
        available[fold_identifier(name)] = name

    missing = sorted(t for t in allow_list.tables if fold_identifier(t) not in available)
    if missing:
        raise SchemaError(f"allow-listed tables not found: {missing}")

    tables = []
    for requested, wanted_columns in sorted(
        allow_list.tables.items(), key=lambda item: fold_identifier(item[0])
    ):
        real_name = available[fold_identifier(requested)]
        tables.append(_read_table(connection, real_name, wanted_columns))
    return SchemaSnapshot(tables=tuple(tables))


def _read_table(
    connection: sqlite3.Connection,
    table_name: str,
    wanted_columns: tuple[str, ...] | None,
) -> TableSchema:
    # The table name is bound as a parameter, never formatted into SQL.
    rows = connection.execute(
        'SELECT name, type, "notnull", pk FROM pragma_table_info(?) ORDER BY cid',
        (table_name,),
    ).fetchall()

    if wanted_columns is not None:
        present = {fold_identifier(row[0]) for row in rows}
        missing = sorted(c for c in wanted_columns if fold_identifier(c) not in present)
        if missing:
            raise SchemaError(f"allow-listed columns not found in table {table_name!r}: {missing}")
        wanted = {fold_identifier(c) for c in wanted_columns}
        rows = [row for row in rows if fold_identifier(row[0]) in wanted]

    if not rows:
        raise SchemaError(f"table {table_name!r} has no readable columns")

    columns = tuple(
        ColumnSchema(
            name=name,
            declared_type=declared_type or "",
            not_null=bool(not_null),
            primary_key=pk > 0,
        )
        for name, declared_type, not_null, pk in rows
    )
    return TableSchema(name=table_name, columns=columns)
