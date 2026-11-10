
# SQL Analyst (M2): Implementation Guide

## 1. Overview

M2 implements the Natural-Language-to-SQL Agent for the AI Data Analyst project.

The SQL Agent accepts a natural-language question, generates a SQL query using a configured language-model provider, validates the query against the available schema, and executes approved SQL against a read-only SQLite database.

This guide documents the implemented components, setup, execution flow, security controls, tests, and known limitations. It is intended to help developers understand and continue the M2 implementation.

## 2. Implementation Status

Implemented capabilities include:

- Natural-language SQL generation.
- Gemini and Ollama generator integrations.
- Environment-based provider selection.
- SQL parsing and validation using SQLGlot with the SQLite dialect.
- Default-deny SQL syntax-tree validation.
- Table and column checks against a `SchemaSnapshot`.
- Normalized SQL revalidation and stable fixed-point checks.
- Rejection of multiple statements and unsupported SQL constructs.
- Read-only SQLite connections and `PRAGMA query_only = ON`.
- Revalidation of the exact normalized SQL before execution.
- Parameter binding instead of interpolating parameter values into SQL.
- Query timeout handling using SQLite's progress handler.
- Maximum result-row limits and a result-truncation indicator.
- Pipeline orchestration for generation, validation, and execution.
- Unit and integration tests for SQL Agent components.
- SQL Analyst Streamlit workspace (`ui/sql_analyst.py`) with sample and uploaded SQLite databases, ambiguity clarification, and specific configuration and provider error messages.

The SQL Agent does not make every PRD requirement complete automatically. Audit events in the SQL pipeline and wider accuracy and latency evaluation are still open and must be evaluated separately before being marked complete.

## 3. Technology Stack

| Component | Technology |
|---|---|
| Language | Python |
| SQL parsing and validation | SQLGlot |
| Database execution | SQLite |
| Language-model provider | Gemini or Ollama |
| Configuration | Environment variables |
| Testing | pytest |

## 4. Source Code Structure

The primary implementation is located in:

`src/ai_data_analyst/sql_agent/`

| File | Responsibility |
|---|---|
| `contracts.py` | Typed contracts and data structures shared by SQL Agent components |
| `schema.py` | Schema snapshot and schema-related functionality |
| `generator.py` | SQL generator interface and shared generator abstractions |
| `gemini_generator.py` | Gemini-backed SQL generation |
| `ollama_generator.py` | Ollama-backed SQL generation |
| `provider_factory.py` | Creates a generator based on configuration |
| `validator.py` | Parses and validates generated SQL |
| `executor.py` | Safely executes validated SQL against SQLite |
| `pipeline.py` | Coordinates generation, validation, and execution |

Tests are located in:

`tests/sql_agent/`

## 5. Architecture and Execution Flow

The pipeline follows this sequence:

1. Receive a natural-language question.
2. Pass the question and schema context to the configured SQL generator.
3. Receive the generated SQL candidate.
4. Parse and validate the candidate using SQLGlot.
5. Check permitted SQL syntax and referenced tables and columns.
6. Reject SQL that violates validation rules.
7. Revalidate the normalized SQL before execution.
8. Execute the approved query against a read-only SQLite connection.
9. Return the result columns, rows, and truncation status.

```text
Natural-language question
          |
          v
    SQL Generator
    /           \
 Gemini         Ollama
    \           /
          |
          v
     SQL Candidate
          |
          v
   SQL Validator
          |
     +----+----+
     |         |
   Denied    Allowed
     |         |
     v         v
   Reject   Normalized SQL
                |
                v
       Revalidation in Executor
                |
                v
       Read-only SQLite Execution
                |
                v
      Columns + Rows + Truncation
```

The generator proposes SQL; it does not authorize execution. The validator and executor enforce the safety checks.

## 6. Environment Setup

Run commands from the repository root in PowerShell.

Activate the existing virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

If the virtual environment has not been created, create it first:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the project's dependencies using its existing dependency-management configuration. For a project that uses `pyproject.toml`, this may be:

```powershell
python -m pip install -e ".[dev]"
```

Use the repository's actual dependency configuration if it differs.

## 7. Gemini Configuration

Configure the provider and model through environment variables in the local `.env` file.

Example configuration:

```dotenv
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.5-flash
LLM_API_KEY=your_actual_api_key
```

Replace the placeholder with your own valid API key. Never commit `.env`, publish API keys, or include secret values in documentation or logs.

The configured provider is selected through `provider_factory.py`. Blank or whitespace-only values are treated as unset, so an empty `LLM_PROVIDER` selects `gemini`. `AIDA_MAX_UPLOAD_BYTES` (default 25 MB) in the same environment also caps SQLite database uploads in the SQL Analyst workspace.

## 8. Ollama Configuration

Ollama can be used as the local-model provider when it is installed and running.

Example configuration:

```dotenv
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5-coder:7b
```

Ensure the selected model is available in your local Ollama installation before running integration tests. The client connects to `http://localhost:11434`; the provider reads only `LLM_PROVIDER` and `LLM_MODEL`, not any `OLLAMA_*` variable.

The Ollama integration test may depend on the local service and downloaded model. A failure caused by an unavailable service or model should be distinguished from a unit-test failure.

## 9. Using the SQL Agent Pipeline

The pipeline connects the generator, schema snapshot, database path, validation, and execution components.

The following is an illustrative integration example. The schema snapshot and database path must be created using the project's actual schema and database setup.

```python
from ai_data_analyst.sql_agent.pipeline import run_sql_pipeline
from ai_data_analyst.sql_agent.provider_factory import create_sql_generator

generator = create_sql_generator()

result = run_sql_pipeline(
    question="Show the first five customers",
    schema=schema_snapshot,
    db_path=database_path,
    generator=generator,
)

print(result)
```

Here, `schema_snapshot` must be a valid `SchemaSnapshot`, and `database_path` must point to the existing SQLite database.

Check the actual function signatures and result contracts in `pipeline.py` and `contracts.py` when integrating with another application module.

## 10. Security Controls

### SQL validation

- SQL is parsed using the SQLite dialect.
- The validator uses an explicit allow-list of permitted syntax-tree constructs.
- Unsupported or disallowed SQL constructs are rejected.
- Multiple statements are rejected.
- Table and column references are checked against the supplied schema snapshot.
- Normalized SQL is revalidated to check that normalization does not bypass validation.
- Validation failures do not expose the candidate SQL in denial messages.

### Read-only execution

- SQLite is opened with the `mode=ro` URI option.
- `PRAGMA query_only = ON` provides an additional database-level restriction.
- The executor independently revalidates the normalized SQL it is about to execute.
- Parameter values are bound through SQLite's parameter interface.
- A progress handler enforces the configured SQL execution time limit.
- Results are limited to the configured maximum number of rows.
- The result includes a truncation indicator when more rows exist than the configured limit.

These controls reduce the risk of unintended database changes and unsafe query execution. They do not, by themselves, establish that the entire application is production-secure.

## 11. Test Commands

Run the complete test suite:

```powershell
python -m pytest -q
```

Run all SQL Agent tests:

```powershell
python -m pytest .\tests\sql_agent\ -v
```

Run the validator tests:

```powershell
python -m pytest .\tests\sql_agent\test_validator.py -v
```

Run the pipeline tests:

```powershell
python -m pytest .\tests\sql_agent\test_pipeline.py -v
```

Run the Gemini generator tests:

```powershell
python -m pytest .\tests\sql_agent\test_gemini_generator.py -v
```

Run the Ollama generator tests:

```powershell
python -m pytest .\tests\sql_agent\test_ollama_generator.py -v
```

Run the Ollama integration test:

```powershell
python -m pytest .\tests\sql_agent\test_ollama_integration.py -v
```

Run benchmark fixture tests:

```powershell
python -m pytest .\tests\sql_agent\test_benchmark_fixtures.py -v
```

## 12. Previously Verified Test Results

The following results were reported during development:

| Test scope | Reported result |
|---|---|
| Complete test suite | 404 passed in 23.77 seconds |
| SQL Agent suite | 229 passed |
| Validator suite | 150 passed |
| Benchmark fixture tests | 15 passed |
| Gemini generator tests | 6 passed |
| Ollama integration | 1 passed in an earlier run |

These are historical results, not a claim that the tests have been rerun after every documentation change. Run the relevant commands to verify the current checkout.

A temporary database cleanup warning occurred during a successful Gemini end-to-end query. The query itself returned the expected names, but the cleanup warning should be investigated separately if it recurs.

## 13. Benchmark and Evaluation Limitations

Passing benchmark fixture tests does not establish the overall SQL-generation accuracy of the language model.

The fixture tests check expected reference SQL and results for the cases they cover. They do not establish a measured, general-purpose execution-accuracy percentage or measured end-to-end latency for all possible natural-language questions.

Do not report an accuracy percentage, latency benchmark, or production-readiness claim unless a corresponding evaluation has actually been run and its results recorded.

## 14. Scope and Pending Verification

This guide covers the M2 Natural-Language-to-SQL Agent only.

Before declaring all product requirements complete, verify the relevant PRD requirements independently, including:

- Frontend or UI integration requirements.
- Clarification behavior for ambiguous questions.
- Logging and audit requirements.
- Provider failure handling and operational behavior.
- End-to-end integration with the wider application.
- Additional evaluation of SQL-generation quality.

Do not mark a requirement complete merely because the underlying SQL Agent pipeline works. Confirm the implementation and tests for that requirement first.

## 15. Developer Handover Checklist

When continuing M2 development:

- [ ] Read `contracts.py` before changing shared data structures.
- [ ] Check `schema.py` to understand the expected schema snapshot.
- [ ] Keep SQL generation separate from deterministic validation.
- [ ] Preserve the default-deny validation policy.
- [ ] Do not bypass executor revalidation.
- [ ] Keep SQLite execution read-only.
- [ ] Use parameter binding for query parameters.
- [ ] Preserve timeout and result-row limits.
- [ ] Add tests for new SQL constructs and rejection cases.
- [ ] Run the relevant SQL Agent tests.
- [ ] Run the full test suite before finalizing a change.
- [ ] Review the Git diff and check for accidental secret exposure.

Useful final checks:

```powershell
python -m pytest -q
git diff --check
git status
git diff --stat
```

## Related Documentation

- Product requirements: `docs/PRD.md`
- Architecture and module boundaries: `docs/ARCHITECTURE.md`
- Security model: `docs/SECURITY.md`
- Evaluation plan and results: `docs/EVALUATION.md`
- Deployment: `docs/DEPLOYMENT.md`

This document describes the M2 implementation and its reported verification status. Update it whenever implementation behavior, commands, test results, or scope changes.

## 16. Stage-wise Implementation and Verification Status

### Stage 1 — Friendly Error Handling

Implemented and integrated friendly error handling for common SQL provider
and pipeline failures.

Capabilities include:

- Categorization of provider quota errors (429).
- Authentication and permission error handling (401/403).
- Model or resource not found handling (404).
- Network and timeout error handling.
- Empty response and unexpected provider error handling.
- Safe user-facing messages without exposing API keys, secrets,
  stack traces, or raw provider responses.
- Explicit SQL execution error handling.
- Generic explanations for restricted tables and columns.

### Stage 2 — Ambiguity Detection and Clarification

Implemented ambiguity detection for ranking questions that do not specify
whether the result should be calculated globally or separately by category.

Capabilities include:

- Detection of ranking terms such as highest, lowest, maximum, minimum,
  top, and bottom.
- Identification of relevant schema columns.
- Recognition of grouping instructions such as per region, by category,
  for each, and overall.
- Clarification when a ranking question is ambiguous.
- Support for continuing the pipeline after the user provides clarification.
- Backward-compatible pipeline integration.

Example clarification:

"Should I find the result across the entire dataset, or separately for
each available category, such as region?"

### Stage 3 — SQL Accuracy and Reliability Evaluation

Implemented the M2 benchmark integration with the shared evaluation framework.

Components include:

- A 15-case SQL benchmark covering all 15 required categories.
- Benchmark execution script: `scripts/run_sql_benchmark.py`.
- M2 evaluation adapter: `src/ai_data_analyst/sql_agent/evaluation_adapter.py`.
- Adapter tests: `tests/sql_agent/test_evaluation_adapter.py`.
- JSON benchmark reports stored under `data/benchmark_runs/`.
- Benchmark definition stored at `data/expected/sql_benchmark_stage3.json`.

The evaluation covers allowed queries, denied queries, clarification
behavior, result-set matching, validation outcomes, and phase-wise latency.

### Stage 3 Evaluation Summary

Three benchmark runs were recorded:

| Run | Result | Description |
|---|---:|---|
| Original model-driven run | 12/15 | Initial LLM generation evaluation |
| Intermediate run | 14/15 | Intermediate regression evaluation |
| Final deterministic run | 15/15 | Deterministic pipeline regression evaluation |

The final deterministic run used SQL overrides for selected benchmark
categories. Therefore, its 15/15 result demonstrates the tested pipeline
behavior and must not be represented as 100% LLM-generated SQL accuracy.

See `docs/EVALUATION.md` for the detailed methodology, metrics, latency,
and benchmark artifacts.

### Full Project Test Verification

The full project test suite was executed and reported:

- Passed: 1,232
- Expected failures (xfail): 1
- Duration: 27.05 seconds

This result is separate from the 15-case SQL benchmark.

## 17. Current M2 Scope and Remaining Work

The three implementation stages described above have been implemented
and tested in the recorded development environment.

The following broader product and operational areas should remain subject
to separate verification:

- Visual design of the SQL Analyst workspace.
- Further evaluation of model-generated SQL accuracy.
- Additional provider and model configurations.
- Operational monitoring of a hosted deployment (see `docs/DEPLOYMENT.md` for how to deploy).
- End-to-end verification with the complete application.

The implementation and evaluation results documented here describe the
verified development work; they do not constitute a production deployment
or a claim of production readiness.
