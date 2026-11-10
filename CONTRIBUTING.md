# Contributing to AIDA

Thanks for your interest. AIDA is a small project with strict engineering rules, so a quick read
of this page saves review time.

## Ground rules

These are never relaxed:

1. **No model-generated code is executed.** Models propose typed plans or SQL; deterministic
   code validates and runs them.
2. **No raw data goes to an external model** without explicit configuration and disclosure.
3. **No accuracy or latency claim** without the benchmark run that produced it.
4. **Fail closed.** Unknown input is rejected, not guessed at.

## Setup

```bash
git clone https://github.com/Somaskandan931/AI_Data_Analyst.git
cd AI_Data_Analyst
python -m venv .venv && source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[app,dev,gemini,ollama]"
python -m pytest -q
```

## Project layout

| Area | Paths |
| --- | --- |
| Auto-EDA | `ingestion/`, `profiling/`, `analysis/`, `visualization/`, `reporting/`, `chat/`, `ui/auto_eda.py` |
| Text-to-SQL | `sql_agent/`, `ui/sql_analyst.py`, SQL benchmark in `data/expected/` |
| Shared contracts | `models.py`, `security/`, `evaluation/` |
| App shell and deployment | `app.py`, `ui/access.py`, `Dockerfile`, `requirements.txt`, `.streamlit/` |

Auto-EDA and Text-to-SQL must not import each other; they share only `models.py`, `security/`
and `evaluation/`. A test enforces this. Domain modules must not import Streamlit.

## Workflow

- Fork or branch, and open a pull request against `main`. `main` stays green.
- Branch names: `feature/<topic>`, `fix/<topic>`, `docs/<topic>`.
- Keep pull requests small and focused on one change.
- A change to `DatasetProfile` or another shared contract must bump the schema version and update
  the fixture and its expected values.

## Definition of done

1. Tests for new behavior, including rejection and failure paths.
2. `ruff check .`, `ruff format --check .`, `mypy` and `python -m pytest -q` all pass.
3. No credentials, `.env` files, raw sensitive data or generated databases committed.
4. Docs and `CHANGELOG.md` updated when behavior, configuration or a contract changes.
5. Anything in `security/`, `sql_agent/` or `ui/access.py` includes a test for the unsafe case.
6. Changes to `Dockerfile`, `requirements.txt` or `.streamlit/` keep `docs/DEPLOYMENT.md` accurate.

## Reporting problems

Bugs and ideas go in GitHub issues. Security problems go through private reporting; see
[.github/SECURITY.md](.github/SECURITY.md).
