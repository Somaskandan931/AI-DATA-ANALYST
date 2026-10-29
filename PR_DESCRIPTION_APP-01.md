# APP-01: Auto-EDA workspace (Streamlit)

**Branch:** `m1/ui`, stacked on `m1/chat`
**Requirement IDs:** APP-01 (Auto-EDA workspace), APP-02 (clear errors), APP-04 (reproducible outputs)
**Owner:** Somaskandan (M1) | **Reviewer:** Nishi or Prathin

## What this adds

| Area | Change |
| --- | --- |
| `ui/workspace.py` (new) | Session state and actions with no Streamlit import: `load_upload`, `load_sample`, `set_cleaning`, `run_step`, `ask`, `charts`, `report_files` |
| `ui/auto_eda.py` (new) | The page: upload or sample, Profile, Cleaning, Analysis, Chat and Report tabs; HTML and Markdown download |
| `app.py` | Auto-EDA and SQL Analyst tabs; the SQL tab is a placeholder for M2 |
| `docs/ARCHITECTURE.md`, `README.md` | updated (status line included) |

## Behaviour

- Pages hold widgets only; every action calls an existing module. No analysis logic was added.
- Upload errors show the stable ingestion code and message; invalid steps, cleaning failures, unsupported operations and report errors are shown as messages, not tracebacks.
- Changing the cleaning plan discards computed analyses and chat history, so every artifact in a session describes the same view of the data. A failed cleaning leaves the session unchanged.
- A repeated analysis (same parameters) is reused. At most 20 analyses per session (the plan and report limit). Chat history keeps the last 50 turns.
- A chat answer that computes something adds its artifact to the session, so it appears under Analysis and in the report.
- Text from the file (column names, values, file name) is shown with `st.text`, tables and widgets only. No `unsafe_allow_html`, no Markdown of file content.
- The report downloads are the deterministic `render_html` and `render_markdown` outputs; no timestamp is added.
- Nothing is sent to a model or an external service.

## Not in this PR (on purpose)

- The SQL Analyst workspace (M2), row filters (filter contract pending), PDF output, saved sessions.

## Results

- `pytest`: 797 passed, 1 skipped (777 before; 20 new). New tests are `tests/unit/test_ui_workspace.py` (workspace actions) and `tests/unit/test_ui_app.py` (the real `app.py` run headlessly with Streamlit's `AppTest`: empty start, sample load, chat answer, unsupported question, analysis form and an error path).
- `ruff check`, `ruff format --check`, `mypy` (strict): clean.

## Review notes

- Please run `streamlit run app.py` once and try an upload, a cleaning plan and both downloads in a browser; the tests do not render pixels.
- Charts are the report's inline SVG, shown with `st.image`, so the page and the report draw the same thing.
- `st.dataframe` is called without a width argument so it works across the supported Streamlit range (`>=1.38`); newer versions may prefer `width="stretch"`.

## Checklist

- [x] Unit tests for new behaviour, including rejection and failure paths
- [x] `ruff check`, `ruff format --check`, `mypy`, `pytest` pass
- [x] No credentials, raw sensitive data or generated databases committed
- [x] Docs updated
- [ ] Review feedback addressed
