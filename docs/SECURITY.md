# Security Model (MVP)

## CSV and analysis

- Accept CSV only; validate actual parsing, not just filename extension.
- Enforce configurable upload, row, column, and execution limits.
- Treat cell contents as data, never as model/system instructions.
- Do not execute model-generated Python, shell, SQL from CSV content, or serialized objects.
- Expose a finite catalogue of typed operations and validate all arguments.
- Preserve source data and document transformations.

## SQL

- Use a read-only database account/connection and a dedicated test database.
- Allow only one SELECT statement, optionally beginning with a WITH clause, after parsing and validation.
- Reject DDL, DML, multiple statements, unauthorized tables/columns, and unsupported syntax.
- Use bound parameters for values. Do not claim parameters can replace identifiers; identifiers must be selected from allow-lists.
- Apply a row cap, timeout, and dialect-appropriate query safeguards.
- Do not rely on regex checks alone or on an LLM prompt as a security control.
- Keep credentials out of source control; use environment variables for local configuration.
- Parse with a real SQL parser (`sqlglot`) and validate the syntax tree, never the raw string.

### SQLite specifics

SQLite has no database users, so a "read-only identity" is built from layered controls. Use all of them:

- Open the file read-only with the URI form `file:path?mode=ro` (via SQLAlchemy's `creator`/`connect_args`, `uri=True`).
- Execute `PRAGMA query_only = ON` on every connection.
- Keep the SQLite file for evaluation separate from any writable copy.
- SQLite has no per-query timeout. Enforce one with `sqlite3.Connection.set_progress_handler` (abort after a deadline) or by running the query in a separate process that can be terminated.
- Block dangerous constructs at the parser layer: `ATTACH`, `PRAGMA`, `load_extension`, and table-valued/system functions not on the allow-list.
- Apply the row cap inside the executor (fetch at most `MAX_RESULT_ROWS + 1` and flag truncation), not only in the generated SQL.

## Privacy and logs

- Use synthetic/public sample data by default.
- Disclose external model calls and avoid sending raw data when a smaller profile/sample is sufficient.
- Never log credentials, tokens, or unnecessary raw row contents.
- Record validation outcomes and sanitized metadata for evaluation.

## Release gate

All unsafe-query fixtures must be blocked before execution. A passing test suite is evidence for the tested cases, not proof of universal security.

## Audit events

Callers in `ingestion/`, `analysis/` and `sql_agent/` are responsible for building `AuditEvent` values and passing them to an `AuditSink`. The security package does not emit events automatically.

The record contains: `schema_version`, `event_type`, `module`, `outcome`, `timestamp` (timezone-aware, zero UTC offset), optional `correlation_id`, `reason_codes`, `operation`, `dataset_fingerprint`, `subject_hash`, `referenced_tables`, `row_count`, `duration_ms`, and `truncated`.

Only enums, patterned reason/operation/table codes, lowercase SHA-256 hashes, numbers and booleans are allowed. There is no free-text field: events must not carry SQL, parameter values, cell values, file contents, credentials or messages. M1 events may carry `operation` and `dataset_fingerprint`; M2 events may carry `referenced_tables` and `truncated`.

A sink failure must never change a caller's validation or execution outcome. Use `safe_emit`, which catches `Exception` (not `BaseException`) and returns `False` without logging the exception or event contents.

Hashes identify normalized SQL or canonical plan/step parameters; they are not anonymization. A low-entropy value (short SQL with literals, a small parameter set) can be guessed by brute force.

Oversized or malformed uploads emit `upload_rejected` with the ingestion error code; `limit_exceeded` is reserved for runtime limits such as an SQL timeout or result truncation.

### Reason-code vocabulary

| Code | Source |
| --- | --- |
| `unsupported_extension` | ingestion `IngestionErrorCode` |
| `file_too_large` | ingestion `IngestionErrorCode` |
| `empty_file` | ingestion `IngestionErrorCode` |
| `not_text` | ingestion `IngestionErrorCode` |
| `bad_encoding` | ingestion `IngestionErrorCode` |
| `parse_error` | ingestion `IngestionErrorCode` |
| `missing_header` | ingestion `IngestionErrorCode` |
| `duplicate_column` | ingestion `IngestionErrorCode` |
| `ragged_row` | ingestion `IngestionErrorCode` |
| `too_many_rows` | ingestion `IngestionErrorCode` |
| `too_many_columns` | ingestion `IngestionErrorCode` |
| `parse_error` | `sql_agent` `ViolationCode` |
| `multiple_statements` | `sql_agent` `ViolationCode` |
| `not_select` | `sql_agent` `ViolationCode` |
| `unsupported_syntax` | `sql_agent` `ViolationCode` |
| `unknown_table` | `sql_agent` `ViolationCode` |
| `unresolved_column` | `sql_agent` `ViolationCode` |
| `too_complex` | `sql_agent` `ViolationCode` |
| `internal_check_failed` | `sql_agent` `ViolationCode` |
| `filter_unknown_column` | proposed row filter contract |
| `filter_bad_operator` | proposed row filter contract |
| `filter_type_mismatch` | proposed row filter contract |
| `filter_bad_value` | proposed row filter contract |
| `filter_too_many` | proposed row filter contract |
