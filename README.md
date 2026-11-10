# AI Data Analyst Agent

A data-analysis assistant with two workspaces in one Streamlit app:

- **Auto-EDA** takes a CSV and produces a profile, a controlled analysis, charts, a report and
  chat answers, all computed by deterministic code.
- **SQL Analyst** takes a question in plain English, has an LLM propose a SQL query, then
  validates that query and runs it read-only against a SQLite database.

The guiding rule: **code computes the facts; the model only proposes or explains.** The model
never runs code, and every number shown can be traced to a computed result.

## Project status

| Area | State |
| --- | --- |
| **M1 Auto-EDA** (`ingestion/`, `profiling/`, `analysis/`, `visualization/`, `reporting/`, `chat/`, `ui/auto_eda.py`) | Working. CSV validation, deterministic profiling, allow-listed analysis plans, cleaning, row filters (first implementation, being aligned with `docs/FILTERS.md`), charts, HTML and Markdown reports, grounded chat. |
| **M2 SQL Analyst** (`sql_agent/`, `ui/sql_analyst.py`) | Working. Gemini and Ollama generators, default-deny SQL validation, read-only execution with timeout and row cap, ambiguity clarification, friendly configuration and provider errors. |
| **Evaluation** (`evaluation/`, `scripts/`) | Auto-EDA runner and 15-case SQL benchmark in place. Method and limits are in `docs/EVALUATION.md`. |
| **Deployment** | Runs on Streamlit Community Cloud, Hugging Face Spaces or Docker, with an optional password gate. See `docs/DEPLOYMENT.md`. |
| **Not done yet** | Audit events inside the SQL pipeline; SQL accuracy and latency figures for the wider question space (the benchmark is 15 cases and its 15/15 run used SQL overrides, so it is not an LLM accuracy claim). |

**Tier:** T2. **Collaborators:** Somaskandan, Nishi, Prathin.

## How it works

```
CSV upload ─► ingestion ─► profiling ─► analysis plan (allow-listed steps) ─► charts, report, chat
                                              ▲
                     model may only propose a plan; code validates and runs it

Question ─► schema snapshot ─► LLM proposes SQL ─► sqlglot validation (default deny)
         ─► re-validation of the exact SQL ─► read-only SQLite (timeout, row cap) ─► result
```

Both workspaces treat uploads, questions, model output and database content as untrusted input.
The security model is in `docs/SECURITY.md` and the module boundaries are in
`docs/ARCHITECTURE.md`.

## Quick start

Requires Python 3.11 or newer.

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[app,dev,gemini,ollama]"
Copy-Item .env.example .env      # then edit .env
python -m pytest -q
streamlit run app.py
```

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[app,dev,gemini,ollama]"
cp .env.example .env             # then edit .env
python -m pytest -q
streamlit run app.py
```

Auto-EDA works with no configuration. The SQL Analyst needs an LLM provider (below).

## Configuration

Settings come from the environment or a local `.env` (never commit it). Blank values count as
unset.

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_PROVIDER` | `gemini` | `gemini` or `ollama` (case-insensitive). |
| `LLM_MODEL` | provider default | Gemini: `gemini-2.5-flash`. Ollama: `qwen2.5-coder:7b`. |
| `LLM_API_KEY` | none | Required for Gemini. Never echoed in messages. |
| `APP_PASSWORD` | none | If set, visitors must enter it before the app renders. |
| `AIDA_MAX_UPLOAD_BYTES` | 25 MiB | Caps CSV and SQLite uploads. |
| `AIDA_MAX_ROWS` / `AIDA_MAX_COLUMNS` | 250000 / 200 | Dataset shape limits. |
| `AIDA_MAX_EXECUTION_SECONDS` | 30 | Analysis time budget, checked between plan steps. |
| `AIDA_SQL_TIMEOUT_SECONDS` | 5 | Per-query SQL timeout. |
| `AIDA_MAX_RESULT_ROWS` | 1000 | Rows returned by one SQL query. |

For Ollama, run `ollama serve`, pull `qwen2.5-coder:7b` and set `LLM_PROVIDER=ollama`. Ollama is
local only (`http://localhost:11434`), so hosted deployments should use Gemini.

If the SQL tab shows "missing its API key" or "provider not supported", set `LLM_API_KEY` or
`LLM_PROVIDER` as described above; nothing else needs changing.

## Deployment

Short version for Streamlit Community Cloud: point it at `app.py`, keep the root
`requirements.txt`, and add `LLM_PROVIDER`, `LLM_API_KEY` and `APP_PASSWORD` under Secrets. A
`Dockerfile` is included for Render, Fly.io, Cloud Run and similar hosts. Full steps and a
pre-launch checklist are in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Checks

CI runs these on Python 3.11 and 3.12, and you should run them before pushing:

```bash
ruff check .
ruff format --check .
mypy
python -m pytest -q
```

The Ollama integration test is skipped when no server is available. To verify the lowest
supported dependency versions, install with `-c constraints-min.txt`:

```bash
pip install -e ".[app,dev,gemini,ollama]" -c constraints-min.txt
```

Two floors matter: `sqlglot >= 30.13` (earlier releases wrongly reject queries whose string
literals contain a semicolon) and, on NumPy 1.x, an older `pyarrow` (the constraints file uses
17.0.0) or Streamlit fails to start.

## Sample data

`data/sample/electricity_demand.csv` is a synthetic, seeded dataset with planted missing values,
duplicates and outliers. Its expected profile in `data/expected/` is computed independently with
the standard library and cross-checked against pandas in the tests. Regenerate with
`python scripts/generate_fixture.py`; the output must be byte-identical.

## Known limitations

- `max_execution_seconds` is checked between plan steps, not inside them, so one slow step can
  run past the limit.
- The SQL Analyst works on SQLite only, and only on a single `SELECT` per question.
- Uploaded SQLite files are kept in the server's temporary directory for the session.
- There are no per-user accounts. `APP_PASSWORD` is one shared password, not user management.

## Documentation

- [Product requirements](docs/PRD.md)
- [Architecture and module boundaries](docs/ARCHITECTURE.md)
- [Security model](docs/SECURITY.md)
- [Evaluation plan and results](docs/EVALUATION.md)
- [Row-filter contract](docs/FILTERS.md)
- [M2 SQL agent handover guide](docs/M2_IMPLEMENTATION.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Contributing](CONTRIBUTING.md)

## License

MIT. See [LICENSE](LICENSE).
