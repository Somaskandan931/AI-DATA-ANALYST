import pytest

from ai_data_analyst.sql_agent.ambiguity import detect_ambiguity
from ai_data_analyst.sql_agent.contracts import (
    ColumnSchema,
    SchemaSnapshot,
    TableSchema,
)


@pytest.fixture
def schema():
    return SchemaSnapshot(
        tables=(
            TableSchema(
                name="electricity_demand",
                columns=(
                    ColumnSchema(name="record_id"),
                    ColumnSchema(name="region"),
                    ColumnSchema(name="demand_mwh"),
                    ColumnSchema(name="date"),
                ),
            ),
        )
    )


def test_highest_demand_requires_clarification(schema):
    result = detect_ambiguity("Show the highest demand", schema)

    assert result.needs_clarification is True
    assert result.clarification_question is not None


def test_top_five_records_does_not_require_clarification(schema):
    result = detect_ambiguity(
        "Show the top 5 records from electricity_demand",
        schema,
    )

    assert result.needs_clarification is False


def test_explicit_grouping_does_not_require_clarification(schema):
    result = detect_ambiguity(
        "Show the highest demand for each region",
        schema,
    )

    assert result.needs_clarification is False


def test_empty_question_does_not_require_clarification(schema):
    result = detect_ambiguity("", schema)

    assert result.needs_clarification is False


def test_schema_without_grouping_column_does_not_require_clarification():
    simple_schema = SchemaSnapshot(
        tables=(
            TableSchema(
                name="sales",
                columns=(
                    ColumnSchema(name="sale_id"),
                    ColumnSchema(name="revenue"),
                ),
            ),
        )
    )

    result = detect_ambiguity("Show the highest revenue", simple_schema)

    assert result.needs_clarification is False