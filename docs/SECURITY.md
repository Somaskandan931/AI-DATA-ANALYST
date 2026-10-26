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
