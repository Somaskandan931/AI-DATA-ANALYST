# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-11-10

First public release.

### Added

- **Auto-EDA workspace:** validated CSV ingestion, deterministic profiling, cleaning, row
  filters, allow-listed analysis (summary statistics, grouped aggregation, correlation,
  distributions, outliers, clustering, PCA), charts, HTML and Markdown reports, and grounded chat.
- **SQL Analyst workspace:** natural-language-to-SQL with Gemini or Ollama, default-deny
  validation with `sqlglot`, read-only SQLite execution with timeout and row cap, ambiguity
  clarification, and specific configuration and provider error messages.
- **Evaluation:** Auto-EDA evaluation runner and a 15-case SQL benchmark with recorded runs.
- **Deployment:** `requirements.txt`, `Dockerfile`, Streamlit configuration and an optional
  `APP_PASSWORD` gate; see `docs/DEPLOYMENT.md`.

### Changed

- A blank `LLM_PROVIDER` now selects `gemini` instead of raising.
- SQLite uploads use the shared `AIDA_MAX_UPLOAD_BYTES` limit; the default drops from 50 MB to
  25 MB.

### Known gaps

- Audit events in the SQL pipeline are not implemented.
- SQL accuracy beyond the 15-case benchmark has not been measured.
