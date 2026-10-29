"""Tests for SQL benchmark fixture verification.

This module verifies that reference SQL queries in the benchmark produce
the exact expected results independently of the application's SQL generator.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest


class BenchmarkReferenceQueryVerifier:
    """Verifies benchmark reference queries against expected results."""

    def __init__(self, benchmark_json_path: Path, seed_sql_path: Path):
        """Initialize verifier with benchmark and seed SQL paths.

        Args:
            benchmark_json_path: Path to sql_benchmark.json
            seed_sql_path: Path to sql_benchmark_seed.sql
        """
        self.benchmark_json_path = Path(benchmark_json_path)
        self.seed_sql_path = Path(seed_sql_path)
        self._benchmark_data: dict[str, Any] | None = None

    @property
    def benchmark_data(self) -> dict[str, Any]:
        """Load benchmark JSON lazily."""
        if self._benchmark_data is None:
            with open(self.benchmark_json_path, encoding="utf-8") as f:
                self._benchmark_data = json.load(f)
        return self._benchmark_data

    def get_seed_sql(self) -> str:
        """Load seed SQL from file."""
        with open(self.seed_sql_path, encoding="utf-8") as f:
            return f.read()

    def _is_safe_select_query(self, query: str) -> bool:
        """Validate that query is a read-only SELECT statement.

        Rejects queries that are not SELECT statements, contain multiple
        statements, or use dangerous keywords.

        Args:
            query: SQL query string to validate

        Returns:
            True if query is a safe read-only SELECT, False otherwise.
        """
        clean_query = query.strip()

        # Must start with SELECT (case-insensitive)
        if not clean_query.upper().startswith("SELECT"):
            return False

        # Check for multiple statements (semicolon not at end)
        # Allow optional trailing semicolon
        if clean_query.endswith(";"):
            clean_query = clean_query[:-1].strip()

        if ";" in clean_query:
            return False

        # Reject dangerous keywords that modify state
        dangerous_keywords = [
            "INSERT",
            "UPDATE",
            "DELETE",
            "DROP",
            "CREATE",
            "ALTER",
            "PRAGMA",
            "ATTACH",
            "DETACH",
        ]
        upper_query = clean_query.upper()
        return all(keyword not in upper_query for keyword in dangerous_keywords)

    def create_test_database(self) -> sqlite3.Connection:
        """Create an in-memory SQLite database initialized with seed data.

        Returns:
            sqlite3.Connection: Connection to the test database.
        """
        conn = sqlite3.connect(":memory:")
        conn.isolation_level = None
        seed_sql = self.get_seed_sql()
        conn.executescript(seed_sql)
        return conn

    def execute_reference_query(
        self, conn: sqlite3.Connection, query: str
    ) -> tuple[list[str], list[list[Any]]]:
        """Execute a reference query and return columns and rows.

        Args:
            conn: SQLite database connection
            query: SQL query to execute

        Returns:
            Tuple of (column_names, rows) where rows are lists of values.
        """
        cursor = conn.execute(query)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        rows_as_lists = [list(row) for row in rows]
        return columns, rows_as_lists

    def verify_case(self, case: dict[str, Any]) -> tuple[bool, str]:
        """Verify a single benchmark case against its reference SQL.

        Args:
            case: Benchmark case dictionary from JSON

        Returns:
            Tuple of (passed, message)
        """
        case_id = case.get("id", "UNKNOWN")
        reference_sql = case.get("reference_sql")
        expected_columns = case.get("expected_columns", [])
        expected_rows = case.get("expected_rows", [])

        if not reference_sql:
            return False, f"{case_id}: Missing reference_sql field"

        # Validate query is safe read-only SELECT before execution
        if not self._is_safe_select_query(reference_sql):
            return (
                False,
                f"{case_id}: Query must be read-only SELECT statement",
            )

        conn = None
        try:
            conn = self.create_test_database()
            actual_columns, actual_rows = self.execute_reference_query(conn, reference_sql)
        except sqlite3.Error as e:
            return False, f"{case_id}: SQL execution failed: {e}"
        finally:
            if conn is not None:
                conn.close()

        if actual_columns != expected_columns:
            return (
                False,
                f"{case_id}: Column mismatch. Expected {expected_columns}, got {actual_columns}",
            )

        if actual_rows != expected_rows:
            return (
                False,
                f"{case_id}: Row mismatch. Expected {expected_rows}, got {actual_rows}",
            )

        return True, f"{case_id}: PASS"


@pytest.fixture
def benchmark_verifier() -> BenchmarkReferenceQueryVerifier:
    """Provide benchmark verifier for tests."""
    benchmark_path = (
        Path(__file__).parent.parent.parent / "data" / "expected" / "sql_benchmark.json"
    )
    seed_path = Path(__file__).parent.parent.parent / "data" / "expected" / "sql_benchmark_seed.sql"
    return BenchmarkReferenceQueryVerifier(benchmark_path, seed_path)


class TestBenchmarkReferenceQueries:
    """Test suite for benchmark reference query verification."""

    def test_benchmark_json_exists(self) -> None:
        """Verify benchmark JSON file exists."""
        benchmark_path = (
            Path(__file__).parent.parent.parent / "data" / "expected" / "sql_benchmark.json"
        )
        assert benchmark_path.exists(), f"Benchmark file not found: {benchmark_path}"

    def test_seed_sql_exists(self) -> None:
        """Verify seed SQL file exists."""
        seed_path = (
            Path(__file__).parent.parent.parent / "data" / "expected" / "sql_benchmark_seed.sql"
        )
        assert seed_path.exists(), f"Seed SQL file not found: {seed_path}"

    def test_benchmark_json_valid(
        self, benchmark_verifier: BenchmarkReferenceQueryVerifier
    ) -> None:
        """Verify benchmark JSON has valid structure."""
        data = benchmark_verifier.benchmark_data
        assert "cases" in data, "Missing 'cases' key in benchmark JSON"
        assert isinstance(data["cases"], list), "'cases' must be a list"
        assert len(data["cases"]) == 8, f"Expected 8 cases, got {len(data['cases'])}"

    def test_all_cases_have_reference_sql(
        self, benchmark_verifier: BenchmarkReferenceQueryVerifier
    ) -> None:
        """Verify all benchmark cases have reference_sql field."""
        cases = benchmark_verifier.benchmark_data.get("cases", [])
        for case in cases:
            assert "reference_sql" in case, (
                f"Case {case.get('id', 'UNKNOWN')} missing reference_sql"
            )
            assert case["reference_sql"], (
                f"Case {case.get('id', 'UNKNOWN')} has empty reference_sql"
            )

    def test_all_cases_have_expected_results(
        self, benchmark_verifier: BenchmarkReferenceQueryVerifier
    ) -> None:
        """Verify all benchmark cases have expected_columns and expected_rows."""
        cases = benchmark_verifier.benchmark_data.get("cases", [])
        for case in cases:
            assert "expected_columns" in case, (
                f"Case {case.get('id', 'UNKNOWN')} missing expected_columns"
            )
            assert "expected_rows" in case, (
                f"Case {case.get('id', 'UNKNOWN')} missing expected_rows"
            )
            assert isinstance(case["expected_columns"], list), (
                f"Case {case.get('id', 'UNKNOWN')} expected_columns must be list"
            )
            assert isinstance(case["expected_rows"], list), (
                f"Case {case.get('id', 'UNKNOWN')} expected_rows must be list"
            )

    def test_all_reference_queries_are_select(
        self, benchmark_verifier: BenchmarkReferenceQueryVerifier
    ) -> None:
        """Verify all reference queries are read-only SELECT statements."""
        cases = benchmark_verifier.benchmark_data.get("cases", [])
        invalid_queries = []
        for case in cases:
            query = case.get("reference_sql", "")
            if not benchmark_verifier._is_safe_select_query(query):
                invalid_queries.append(f"{case.get('id', 'UNKNOWN')}: {query}")
        assert not invalid_queries, "Found non-SELECT or unsafe queries:\n" + "\n".join(
            invalid_queries
        )

    def test_reference_query_sql_bench_01(
        self, benchmark_verifier: BenchmarkReferenceQueryVerifier
    ) -> None:
        """Test reference query for SQL-BENCH-01 (basic filter)."""
        cases = benchmark_verifier.benchmark_data.get("cases", [])
        case = next((c for c in cases if c["id"] == "SQL-BENCH-01"), None)
        assert case is not None, "SQL-BENCH-01 not found"
        passed, message = benchmark_verifier.verify_case(case)
        assert passed, message

    def test_reference_query_sql_bench_02(
        self, benchmark_verifier: BenchmarkReferenceQueryVerifier
    ) -> None:
        """Test reference query for SQL-BENCH-02 (null values)."""
        cases = benchmark_verifier.benchmark_data.get("cases", [])
        case = next((c for c in cases if c["id"] == "SQL-BENCH-02"), None)
        assert case is not None, "SQL-BENCH-02 not found"
        passed, message = benchmark_verifier.verify_case(case)
        assert passed, message

    def test_reference_query_sql_bench_03(
        self, benchmark_verifier: BenchmarkReferenceQueryVerifier
    ) -> None:
        """Test reference query for SQL-BENCH-03 (duplicates)."""
        cases = benchmark_verifier.benchmark_data.get("cases", [])
        case = next((c for c in cases if c["id"] == "SQL-BENCH-03"), None)
        assert case is not None, "SQL-BENCH-03 not found"
        passed, message = benchmark_verifier.verify_case(case)
        assert passed, message

    def test_reference_query_sql_bench_04(
        self, benchmark_verifier: BenchmarkReferenceQueryVerifier
    ) -> None:
        """Test reference query for SQL-BENCH-04 (join)."""
        cases = benchmark_verifier.benchmark_data.get("cases", [])
        case = next((c for c in cases if c["id"] == "SQL-BENCH-04"), None)
        assert case is not None, "SQL-BENCH-04 not found"
        passed, message = benchmark_verifier.verify_case(case)
        assert passed, message

    def test_reference_query_sql_bench_05(
        self, benchmark_verifier: BenchmarkReferenceQueryVerifier
    ) -> None:
        """Test reference query for SQL-BENCH-05 (empty results)."""
        cases = benchmark_verifier.benchmark_data.get("cases", [])
        case = next((c for c in cases if c["id"] == "SQL-BENCH-05"), None)
        assert case is not None, "SQL-BENCH-05 not found"
        passed, message = benchmark_verifier.verify_case(case)
        assert passed, message

    def test_reference_query_sql_bench_06(
        self, benchmark_verifier: BenchmarkReferenceQueryVerifier
    ) -> None:
        """Test reference query for SQL-BENCH-06 (boundary)."""
        cases = benchmark_verifier.benchmark_data.get("cases", [])
        case = next((c for c in cases if c["id"] == "SQL-BENCH-06"), None)
        assert case is not None, "SQL-BENCH-06 not found"
        passed, message = benchmark_verifier.verify_case(case)
        assert passed, message

    def test_reference_query_sql_bench_07(
        self, benchmark_verifier: BenchmarkReferenceQueryVerifier
    ) -> None:
        """Test reference query for SQL-BENCH-07 (boundary)."""
        cases = benchmark_verifier.benchmark_data.get("cases", [])
        case = next((c for c in cases if c["id"] == "SQL-BENCH-07"), None)
        assert case is not None, "SQL-BENCH-07 not found"
        passed, message = benchmark_verifier.verify_case(case)
        assert passed, message

    def test_reference_query_sql_bench_08(
        self, benchmark_verifier: BenchmarkReferenceQueryVerifier
    ) -> None:
        """Test reference query for SQL-BENCH-08 (null values)."""
        cases = benchmark_verifier.benchmark_data.get("cases", [])
        case = next((c for c in cases if c["id"] == "SQL-BENCH-08"), None)
        assert case is not None, "SQL-BENCH-08 not found"
        passed, message = benchmark_verifier.verify_case(case)
        assert passed, message

    def test_all_reference_queries_verify(
        self, benchmark_verifier: BenchmarkReferenceQueryVerifier
    ) -> None:
        """Comprehensive test: all benchmark cases produce expected results."""
        cases = benchmark_verifier.benchmark_data.get("cases", [])
        assert len(cases) == 8, f"Expected 8 cases, got {len(cases)}"

        failed_cases = []
        for case in cases:
            passed, message = benchmark_verifier.verify_case(case)
            if not passed:
                failed_cases.append(message)

        assert not failed_cases, (
            f"Reference query verification failed for {len(failed_cases)} case(s):\n"
            + "\n".join(failed_cases)
        )
