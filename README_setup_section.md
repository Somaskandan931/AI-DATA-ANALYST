## Setup

Requirements: Python 3.11 or newer. A normal install picks the newest compatible releases:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[app,dev,gemini,ollama]"
python -m pytest -q
streamlit run app.py
```

Extras: `app` (Streamlit, Plotly), `dev` (pytest, Ruff, mypy, type stubs, and both LLM
clients so the whole suite runs), `gemini`, `ollama`. The core package, including every
domain module, installs with no extras.

LLM providers are optional for running the test suite: the Ollama integration test is
skipped when no server is available.

### SQL Analyst provider setup

The SQL Analyst reads these variables from the environment or a local `.env` file; see
`.env.example`:

| Variable | Meaning | Default |
|---|---|---|
| `LLM_PROVIDER` | SQL provider: `gemini` or `ollama` | `gemini` |
| `LLM_MODEL` | Optional model override | `gemini-2.5-flash` for Gemini; `qwen2.5-coder:7b` for Ollama |
| `LLM_API_KEY` | Gemini API key; required only for Gemini | none |

Blank or whitespace-only values are treated as unset. Gemini is the default provider and
requires `LLM_API_KEY`. To use a local Ollama server instead, run `ollama serve`, make the
model available with `ollama pull qwen2.5-coder:7b`, then set `LLM_PROVIDER=ollama`
(optionally `LLM_MODEL`); the client connects to `http://localhost:11434`.

`AIDA_MAX_UPLOAD_BYTES` (default 25 MB) caps both CSV uploads and SQLite database uploads
in the SQL Analyst.

### Minimum-version check

The declared lower bounds in `pyproject.toml` are verified, not assumed. To reproduce the
check in a fresh environment with the oldest allowed versions:

```bash
python -m venv .venv-min
source .venv-min/bin/activate
pip install -e ".[app,dev,gemini,ollama]" -c constraints-min.txt
python -m pytest -q && ruff check . && ruff format --check . && mypy
```

Verified on Python 3.12 with pandas 2.2.0, NumPy 1.26.0, SciPy 1.13.0, scikit-learn 1.5.0,
sqlglot 30.13.0, Streamlit 1.38.0 and the other versions listed in `constraints-min.txt`:
all four checks pass. Python 3.11 is declared but was not part of this check.

Notes on the bounds:

- **sqlglot >= 30.13.** The validator uses `exp.Expr`, which first appears in 30.0.0, and
  releases before 30.13 wrongly deny valid queries whose string literals contain a
  semicolon. Both failures are on the safe side (the query is rejected), but they are
  failures.
- **NumPy 1.x needs an older pyarrow.** Streamlit pulls in pyarrow, and the newest pyarrow
  requires NumPy 2. In an environment that pins NumPy below 2, install an older pyarrow
  (the constraints file uses 17.0.0) or the Streamlit workspace fails to start.
- **Dev tool floors** (Ruff 0.13, mypy 1.13, pandas-stubs 3.0, google-genai 1.20,
  ollama 0.4.7) exist because older releases flag rules that were later removed, fail to
  type-check the pandas annotations, ship no typing marker, or pin conflicting `httpx`
  ranges. They affect linting and type checking, not runtime behaviour.
