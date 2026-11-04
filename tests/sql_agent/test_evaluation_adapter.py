
import sqlite3

import pytest

from ai_data_analyst.security.limits import LimitsConfig
from ai_data_analyst.sql_agent.ambiguity import detect_ambiguity
from ai_data_analyst.sql_agent.contracts import SQLCandidate
from ai_data_analyst.sql_agent.evaluation_adapter import M2BenchmarkSystem
from ai_data_analyst.sql_agent.generator import StaticSQLGenerator
from ai_data_analyst.sql_agent.schema import SchemaAllowList, discover_schema


@pytest.fixture
def benchmark_database(tmp_path):
    db_path = tmp_path / "benchmark.db"

    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE customers (
                customer_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                city TEXT
            );

            INSERT INTO customers VALUES
                (1, 'Asha', 'Chennai'),
                (2, 'Ravi', 'Bengaluru'),
                (3, 'Mina', 'Chennai');

            """
        )

    return db_path


@pytest.fixture
def benchmark_system(benchmark_database):
    allow_list = SchemaAllowList(
        tables={
            "customers": (
                "customer_id",
                "name",
                "city",
            )
        }
    )

    schema = discover_schema(benchmark_database, allow_list)

    generator = StaticSQLGenerator(
        "SELECT name FROM customers ORDER BY customer_id"
    )

    return M2BenchmarkSystem(
        generator=generator,
        schema=schema,
        db_path=benchmark_database,
        limits=LimitsConfig(),
    )


def test_generate_returns_sql(benchmark_system):
    sql = benchmark_system.generate("Show customer names")

    assert sql == "SELECT name FROM customers ORDER BY customer_id"


def test_generate_returns_none_for_ambiguous_question(benchmark_system):
    question = "Show the highest demand"

    result = benchmark_system.generate(question)

    assert result is None


def test_validate_denies_unknown_column(benchmark_system):
    result = benchmark_system.validate(
        "SELECT secret FROM customers"
    )

    assert result.allowed is False
    assert result.reason_codes


def test_execute_returns_expected_rows(benchmark_system):
    sql = "SELECT name FROM customers ORDER BY customer_id"

    validation = benchmark_system.validate(sql)

    assert validation.allowed is True
    assert validation.normalized_sql is not None

    result = benchmark_system.execute(validation.normalized_sql)

    assert result.columns == ("name",)
    assert result.rows == (
        ("Asha",),
        ("Ravi",),
        ("Mina",),
    )
    assert result.truncated is False
    assert result.timed_out is False


def test_sql_override_is_used(benchmark_system):
    override_sql = "SELECT city FROM customers ORDER BY customer_id"

    system = M2BenchmarkSystem(
        generator=benchmark_system.generator,
        schema=benchmark_system.schema,
        db_path=benchmark_system.db_path,
        limits=LimitsConfig(),
        sql_overrides={"Show customer cities": override_sql},
    )

    assert system.generate("Show customer cities") == override_sql
