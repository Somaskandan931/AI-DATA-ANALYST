"""SQL Analyst result rendering, persistence, and source-change clearing."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from ai_data_analyst.sql_agent.contracts import ColumnSchema, SchemaSnapshot, TableSchema  # noqa: E402
from ai_data_analyst.sql_agent.executor import SQLExecutionResult  # noqa: E402
from ai_data_analyst.sql_agent.pipeline import SQLPipelineResult  # noqa: E402
from ai_data_analyst.ui import sql_analyst  # noqa: E402


def _details() -> SQLPipelineResult:
    return SQLPipelineResult(
        normalized_sql="SELECT 1 AS x, 2 AS x",
        execution=SQLExecutionResult(columns=("x", "x"), rows=((1, 2),), truncated=False),
    )


def _schema(*columns: str) -> SchemaSnapshot:
    return SchemaSnapshot(
        tables=(
            TableSchema(
                name="records",
                columns=tuple(ColumnSchema(name=column) for column in columns),
            ),
        )
    )


def test_result_frame_keeps_duplicate_column_names() -> None:
    frame = sql_analyst._result_frame(_details().execution)

    assert list(frame.columns) == ["x", "x"]
    assert frame.iloc[0].tolist() == [1, 2]


def test_display_frame_disambiguates_duplicate_labels() -> None:
    frame = sql_analyst._display_frame(_details().execution)

    assert list(frame.columns) == ["x", "x [2]"]
    assert frame.iloc[0].tolist() == [1, 2]


def test_last_query_persists_and_clears(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sql_analyst.st, "session_state", {})
    details = _details()

    sql_analyst._remember_query("show the duplicate columns", details)

    assert sql_analyst._last_query() == ("show the duplicate columns", details)

    sql_analyst._clear_query_result()

    assert sql_analyst._last_query() == (None, None)


def test_same_source_keeps_result_and_database_change_clears_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sql_analyst.st, "session_state", {})
    database = Path("sample.db")
    schema = _schema("id", "region")
    details = _details()

    sql_analyst._sync_query_source(database, schema)
    sql_analyst._remember_query("question", details)
    sql_analyst._sync_query_source(database, schema)

    assert sql_analyst._last_query() == ("question", details)

    sql_analyst._sync_query_source(Path("uploaded.db"), schema)

    assert sql_analyst._last_query() == (None, None)


def test_schema_change_clears_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sql_analyst.st, "session_state", {})
    database = Path("sample.db")
    details = _details()

    sql_analyst._sync_query_source(database, _schema("id", "region"))
    sql_analyst._remember_query("question", details)
    sql_analyst._sync_query_source(database, _schema("id"))

    assert sql_analyst._last_query() == (None, None)
