from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from ai_data_analyst.evaluation.benchmark import load_benchmark
from ai_data_analyst.evaluation.runner import (
    RunMetadata,
    run_benchmark,
    write_run_json,
)
from ai_data_analyst.security.limits import LimitsConfig
from ai_data_analyst.sql_agent.evaluation_adapter import M2BenchmarkSystem
from ai_data_analyst.sql_agent.provider_factory import create_sql_generator
from ai_data_analyst.sql_agent.schema import SchemaAllowList, discover_schema

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_PATH = ROOT / "data" / "expected" / "sql_benchmark_stage3.json"
SEED_PATH = ROOT / "data" / "expected" / "sql_benchmark_seed.sql"
OUTPUT_DIR = ROOT / "data" / "benchmark_runs"

ALLOW_LIST = SchemaAllowList(
    tables={
        "customers": ("customer_id", "name", "city"),
        "orders": ("order_id", "customer_id", "amount"),
    }
)


def create_test_database(db_path: Path) -> None:
    seed_sql = SEED_PATH.read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as connection:
        connection.executescript(seed_sql)


def build_sql_overrides(suite) -> dict[str, str]:
    deterministic_categories = {
        "window_functions",
        "disallowed_tables_columns",
        "write_statements",
        "multiple_statements",
        "null_behavior",
        "empty_results",
        "comments_obfuscation",
    }

    overrides = {
        case.question: case.reference_sql
        for case in suite.cases
        if case.category in deterministic_categories and case.reference_sql is not None
    }

    # Deliberately exceed the validator's AST node limit.
    # This tests complexity validation independently of LLM generation.
    for case in suite.cases:
        if case.category == "resource_heavy_queries":
            overrides[case.question] = "SELECT " + " + ".join(["1"] * 1100)

    return overrides


def main() -> None:
    load_dotenv()

    if not BENCHMARK_PATH.is_file():
        raise FileNotFoundError(f"Benchmark file not found: {BENCHMARK_PATH}")

    if not SEED_PATH.is_file():
        raise FileNotFoundError(f"Seed SQL file not found: {SEED_PATH}")

    suite = load_benchmark(BENCHMARK_PATH)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    seed_hash = hashlib.sha256(SEED_PATH.read_bytes()).hexdigest()

    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    model = os.getenv("LLM_MODEL", "").strip()

    if not model:
        model = "qwen2.5-coder:7b" if provider == "ollama" else "gemini-2.5-flash"

    print(f"Benchmark version: {suite.benchmark_version}")
    print(f"Test cases: {len(suite.cases)}")
    print(f"Provider: {provider}")
    print(f"Model: {model}")
    print("Preparing temporary benchmark database...")

    with tempfile.TemporaryDirectory(prefix="m2_sql_benchmark_") as temp_dir:
        db_path = Path(temp_dir) / "benchmark.db"
        create_test_database(db_path)

        schema = discover_schema(db_path, ALLOW_LIST)

        system = M2BenchmarkSystem(
            generator=create_sql_generator(),
            schema=schema,
            db_path=db_path,
            limits=LimitsConfig(),
            sql_overrides=build_sql_overrides(suite),
        )

        metadata = RunMetadata(
            model=model,
            provider=provider,
            model_version=model,
            prompt_version="m2-sql-stage3-v1",
            database_fingerprint=seed_hash,
        )

        run = run_benchmark(
            suite,
            system,
            started_at=datetime.now(UTC),
            run_metadata=metadata,
        )

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"m2_sql_benchmark_{timestamp}.json"

    write_run_json(run, output_path)

    print("\n========== STAGE 3 BENCHMARK RESULTS ==========")
    print(f"Cases executed: {run.sample_count}")
    print(f"Passed: {run.sample_count - len(run.failures)}")
    print(f"Failed: {len(run.failures)}")
    print(f"Missing categories: {list(run.missing_categories)}")

    print("\nMetrics:")
    for metric in run.results:
        print(f"{metric.metric_name}: {metric.value:.4f} (samples={metric.sample_count})")

    print("\nCase details:")
    for record in run.records:
        status = "PASS" if record.passed else "FAIL"
        print(
            f"{status} | {record.case_id} | "
            f"{record.category} | {record.observed_outcome} | "
            f"reasons={list(record.reason_codes)}"
        )

    print(f"\nGeneration latency: {run.latency['generation']}")
    print(f"Validation latency: {run.latency['validation']}")
    print(f"Execution latency: {run.latency['execution']}")
    print(f"\nReport saved to: {output_path}")


if __name__ == "__main__":
    main()
