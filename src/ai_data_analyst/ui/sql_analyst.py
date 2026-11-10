"""Streamlit UI for the M2 Natural-Language-to-SQL workspace."""

import csv
import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st
from streamlit.runtime.uploaded_file_manager import UploadedFile

from ai_data_analyst.security.limits import LimitsConfig
from ai_data_analyst.sql_agent.contracts import SchemaSnapshot
from ai_data_analyst.sql_agent.errors import LLMConfigurationError
from ai_data_analyst.sql_agent.executor import SQLExecutionError, SQLExecutionResult
from ai_data_analyst.sql_agent.pipeline import (
    SQLClarificationRequired,
    SQLPipelineError,
    SQLPipelineResult,
    SQLQueryDenied,
    run_sql_pipeline_with_details,
)
from ai_data_analyst.sql_agent.provider_factory import create_sql_generator
from ai_data_analyst.sql_agent.schema import (
    SchemaAllowList,
    SchemaError,
    discover_schema,
    inspect_database,
)

from . import evidence, layout
from .theme import fresh_class

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_DB = PROJECT_ROOT / "data" / "sample" / "electricity_demand.db"
SAMPLE_CSV = PROJECT_ROOT / "data" / "sample" / "electricity_demand.csv"
SAMPLE_BUILD_DIR = Path(tempfile.gettempdir()) / "ai_data_analyst_sample"
SAMPLE_TABLE = "electricity_demand"
_SAMPLE_REAL_COLUMNS = frozenset({"demand_mwh", "temperature_c"})


def _build_sample_database(destination: Path) -> None:
    """Create the sample SQLite database from the committed CSV (empty cells become NULL)."""
    with SAMPLE_CSV.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows = [[None if row[c] == "" else row[c] for c in columns] for row in reader]

    definitions = ", ".join(
        f'"{c}" {"REAL" if c in _SAMPLE_REAL_COLUMNS else "TEXT"}' for c in columns
    )
    placeholders = ", ".join("?" for _ in columns)
    connection = sqlite3.connect(destination)
    try:
        connection.execute(f'CREATE TABLE "{SAMPLE_TABLE}" ({definitions})')
        connection.executemany(f'INSERT INTO "{SAMPLE_TABLE}" VALUES ({placeholders})', rows)
        connection.commit()
    finally:
        connection.close()


def _ensure_sample_database() -> Path | None:
    """Return the sample database, building it from the CSV when the .db file is absent.

    ``*.db`` is gitignored, so fresh clones and CI never contain the binary file.
    """
    if SAMPLE_DB.is_file():
        return SAMPLE_DB
    if not SAMPLE_CSV.is_file():
        return None

    built = SAMPLE_BUILD_DIR / "electricity_demand.db"
    if built.is_file():
        return built

    partial = built.with_name(f"{built.stem}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        built.parent.mkdir(parents=True, exist_ok=True)
        _build_sample_database(partial)
        partial.replace(built)
    except (OSError, sqlite3.Error):
        return None
    finally:
        partial.unlink(missing_ok=True)
    return built


ALLOWED_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}

PENDING_QUESTION_KEY = "sql_pending_question"
PENDING_CLARIFICATION_KEY = "sql_pending_clarification"
LAST_RESULT_KEY = "sql_last_result"
LAST_QUESTION_KEY = "sql_last_question"
QUERY_SOURCE_KEY = "sql_query_source"


def _clear_pending_clarification() -> None:
    """Clear any stored clarification state."""
    st.session_state.pop(PENDING_QUESTION_KEY, None)
    st.session_state.pop(PENDING_CLARIFICATION_KEY, None)


def _result_frame(result: SQLExecutionResult) -> pd.DataFrame:
    """Build the result frame without collapsing duplicate column names."""
    return pd.DataFrame.from_records(result.rows, columns=result.columns)


def _display_frame(result: SQLExecutionResult) -> pd.DataFrame:
    """Return a display copy with unique labels; Arrow rejects duplicate columns."""
    frame = _result_frame(result)
    labels: list[str] = []
    seen: dict[str, int] = {}
    for column in frame.columns:
        count = seen.get(str(column), 0) + 1
        seen[str(column)] = count
        labels.append(str(column) if count == 1 else f"{column} [{count}]")
    if labels == list(frame.columns):
        return frame
    display = frame.copy()
    display.columns = labels
    return display


def _remember_query(question: str, details: SQLPipelineResult) -> None:
    """Keep the last successful result so ordinary reruns do not lose it."""
    st.session_state[LAST_RESULT_KEY] = details
    st.session_state[LAST_QUESTION_KEY] = question


def _last_query() -> tuple[str | None, SQLPipelineResult | None]:
    """Return the stored question and result, if they are still valid."""
    details = st.session_state.get(LAST_RESULT_KEY)
    question = st.session_state.get(LAST_QUESTION_KEY)
    if not isinstance(details, SQLPipelineResult):
        return None, None
    return (question if isinstance(question, str) else None), details


def _clear_query_result() -> None:
    """Drop the last result when the database or approved schema changes."""
    st.session_state.pop(LAST_RESULT_KEY, None)
    st.session_state.pop(LAST_QUESTION_KEY, None)


def _query_source(
    database_path: Path, schema: SchemaSnapshot
) -> tuple[str, tuple[tuple[str, tuple[str, ...]], ...]]:
    """A stable identity for the database and approved columns a result belongs to."""
    return (
        str(database_path),
        tuple(
            (table.name, tuple(column.name for column in table.columns)) for table in schema.tables
        ),
    )


def _sync_query_source(database_path: Path, schema: SchemaSnapshot) -> None:
    """Clear a stored result when the database or approved schema changes."""
    signature = _query_source(database_path, schema)
    previous = st.session_state.get(QUERY_SOURCE_KEY)
    if previous is not None and previous != signature:
        _clear_query_result()
    st.session_state[QUERY_SOURCE_KEY] = signature


def _save_uploaded_database(uploaded_file: UploadedFile) -> Path:
    """Validate and save an uploaded SQLite database to a temporary file."""
    filename = Path(uploaded_file.name)

    if filename.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise SchemaError("Upload a .db, .sqlite, or .sqlite3 file.")

    content = uploaded_file.getvalue()

    if not content:
        raise SchemaError("The uploaded file is empty.")

    limits = LimitsConfig.from_env()
    if len(content) > limits.max_upload_bytes:
        limit_mb = limits.max_upload_bytes / (1024 * 1024)
        raise SchemaError(f"Database upload must not exceed {limit_mb:g} MB.")

    digest = hashlib.sha256(content).hexdigest()
    previous_digest = st.session_state.get("sql_db_upload_digest")
    previous_path = st.session_state.get("sql_db_upload_path")

    if previous_digest == digest and previous_path:
        existing_path = Path(previous_path)
        if existing_path.is_file():
            return existing_path

    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            suffix=filename.suffix.lower(),
            prefix="sql_analyst_",
            delete=False,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_path = Path(temporary_file.name)

        inspect_database(temporary_path)

    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

        raise SchemaError("The uploaded file is not a valid readable SQLite database.") from None

    if previous_path:
        Path(previous_path).unlink(missing_ok=True)

    st.session_state["sql_db_upload_digest"] = digest
    st.session_state["sql_db_upload_path"] = str(temporary_path)

    return temporary_path


def _select_database() -> Path | None:
    """Choose the sample database or an uploaded SQLite database."""
    source = st.radio(
        "Choose database source",
        ["Sample database", "Upload SQLite database"],
        horizontal=True,
        key="sql_database_source",
    )

    if source == "Sample database":
        sample_path = _ensure_sample_database()
        if sample_path is None:
            st.error("The sample database could not be found.")
            return None

        st.session_state["sql_database_name"] = "Electricity Demand Sample"
        st.markdown("**Selected database:** Electricity Demand Sample")
        return sample_path

    limits = LimitsConfig.from_env()
    uploaded_file = st.file_uploader(
        "Upload a SQLite database",
        type=["db", "sqlite", "sqlite3"],
        help=f"Maximum upload size: {limits.max_upload_bytes / (1024 * 1024):g} MB.",
        key="sql_database_upload",
    )

    if uploaded_file is None:
        st.info("Upload a SQLite database to continue.")
        return None

    try:
        database_path = _save_uploaded_database(uploaded_file)
        st.session_state["sql_database_name"] = Path(uploaded_file.name).name
        st.success(f"Database uploaded: {Path(uploaded_file.name).name}")
        return database_path

    except SchemaError as exc:
        st.error(str(exc))
        return None


def _select_schema(database_path: Path) -> SchemaSnapshot | None:
    """Let the user select tables and columns before approving the schema."""
    try:
        available = inspect_database(database_path)
    except SchemaError:
        st.error("The database's tables could not be read.")
        return None

    table_names = list(available)

    selected_tables = st.multiselect(
        "Select tables",
        options=table_names,
        default=table_names,
        key=f"sql_tables_{database_path.name}",
        help="Only the tables you select can be queried.",
    )

    if not selected_tables:
        st.warning("Choose at least one table.")
        return None

    selected_columns: dict[str, tuple[str, ...]] = {}

    with st.expander("Choose columns", expanded=True):
        for table_name in selected_tables:
            available_columns = list(available[table_name])

            columns = st.multiselect(
                f"Columns in {table_name}",
                options=available_columns,
                default=available_columns,
                key=f"sql_columns_{database_path.name}_{table_name}",
            )

            if not columns:
                st.warning(f"Choose at least one column for {table_name}.")
                return None

            selected_columns[table_name] = tuple(columns)

    try:
        allow_list = SchemaAllowList(tables=selected_columns)
        schema = discover_schema(database_path, allow_list)

    except SchemaError:
        st.error("The selected tables could not be read safely.")
        return None

    except ValueError:
        st.error("The selected tables or columns are invalid.")
        return None

    return schema


def _show_execution_error(error: SQLExecutionError) -> None:
    """Display safe, user-friendly SQL execution errors."""
    message = str(error).lower()

    if "timeout" in message or "timed out" in message:
        st.error(
            "The query took too long to execute. "
            "Try simplifying your question or reducing the amount of data."
        )
    elif "row limit" in message or "result limit" in message:
        st.error("The query exceeded the configured result limit. Try narrowing your question.")
    elif "denied" in message or "not allowed" in message:
        st.error("The query was blocked because it did not pass the database safety checks.")
    else:
        st.error("The database could not execute this query. Check your question and try again.")


def _configuration_failure_message(error: LLMConfigurationError) -> str:
    """Describe a provider configuration problem without echoing secret values."""
    if "LLM_PROVIDER" in str(error):
        return (
            "SQL generation is not set up yet. Choose 'gemini' or 'ollama' in the app "
            "settings (LLM_PROVIDER) and restart."
        )

    if "LLM_API_KEY" in str(error):
        return (
            "SQL generation is not set up yet. Add your API key in the app settings "
            "(LLM_API_KEY) and restart."
        )

    return (
        "SQL generation is not set up yet. Check the provider settings "
        "(LLM_PROVIDER and LLM_API_KEY) and restart."
    )


def _show_query_result(details: SQLPipelineResult, question: str | None = None) -> None:
    """Display validated SQL and its execution result."""
    if question:
        st.text(f"Question: {question}")
    st.success("Query executed successfully.")

    result = details.execution
    limits = LimitsConfig.from_env()
    fresh = fresh_class(
        "sql-query-result",
        (question, details.normalized_sql, len(result.rows)),
    )
    layout.evidence_view(
        evidence.query_result_view(
            question or "",
            details.normalized_sql,
            result,
            max_rows=limits.max_result_rows,
        ),
        fresh=bool(fresh),
    )

    st.markdown("**Validated SQL**")
    st.code(details.normalized_sql, language="sql")

    st.markdown("**Query Results**")

    if result.rows:
        display = _display_frame(result)
        layout.table(
            [tuple(row) for row in display.itertuples(index=False, name=None)],
            list(display.columns),
        )
        if list(display.columns) != list(result.columns):
            st.caption("Duplicate column names are preserved; display labels are disambiguated.")
    else:
        st.info("The query completed successfully but returned no rows.")

    st.caption(f"Rows displayed: {len(result.rows)}")

    if result.truncated:
        st.warning("Results were limited by the configured maximum row count.")


def _show_last_query() -> None:
    """Render the stored result after ordinary reruns."""
    question, details = _last_query()
    if details is not None:
        _show_query_result(details, question)


def _run_query(
    question: str,
    schema: SchemaSnapshot,
    database_path: Path,
    skip_ambiguity_check: bool = False,
) -> None:
    """Run the generate, validate, and execute pipeline.

    Skip ambiguity detection only after explicit user clarification.
    """
    _clear_query_result()

    try:
        generator = create_sql_generator()

        with st.spinner("Generating and running SQL..."):
            details = run_sql_pipeline_with_details(
                question=question,
                schema=schema,
                db_path=database_path,
                generator=generator,
                limits=LimitsConfig.from_env(),
                skip_ambiguity_check=skip_ambiguity_check,
            )

        _clear_pending_clarification()
        _remember_query(question, details)

    except SQLClarificationRequired as exc:
        st.session_state[PENDING_QUESTION_KEY] = question
        st.session_state[PENDING_CLARIFICATION_KEY] = exc.clarification_question
        st.rerun()

    except SQLQueryDenied as exc:
        _clear_pending_clarification()
        st.error("The generated query was blocked because it did not pass the safety checks.")

        for violation in exc.validation.violations:
            st.write(f"- {violation.message}")

    except SQLExecutionError as exc:
        _clear_pending_clarification()
        _show_execution_error(exc)

    except SQLPipelineError as exc:
        _clear_pending_clarification()
        st.error(str(exc))

    except LLMConfigurationError as exc:
        _clear_pending_clarification()
        st.error(_configuration_failure_message(exc))

    except Exception:
        _clear_pending_clarification()
        st.error("An unexpected error occurred. Please try again.")


def _render_clarification(
    current_question: str,
    schema: SchemaSnapshot,
    database_path: Path,
) -> None:
    """Render and process a pending clarification."""
    pending_question = st.session_state.get(PENDING_QUESTION_KEY)
    clarification = st.session_state.get(PENDING_CLARIFICATION_KEY)

    if not pending_question or not clarification:
        return

    st.divider()
    st.markdown("**One clarification needed**")
    st.info(clarification)

    choice = st.radio(
        "How should the results be calculated?",
        [
            "Across the entire dataset",
            "Separately for each available category",
        ],
        key="sql_clarification_choice",
    )

    if st.button(
        "Confirm and Generate SQL",
        type="primary",
        key="sql_confirm_clarification",
    ):
        if choice == "Across the entire dataset":
            clarified_question = f"{pending_question} overall"
        else:
            clarified_question = f"{pending_question} for each available category"

        _clear_pending_clarification()

        _run_query(
            question=clarified_question,
            schema=schema,
            database_path=database_path,
            skip_ambiguity_check=True,
        )


def _database_name() -> str:
    """The human name of the chosen database, independent of any temporary path."""
    return str(st.session_state.get("sql_database_name") or "SQLite database")


def _query_panel(schema: SchemaSnapshot, database_path: Path) -> None:
    """Schema summary, the question box and the clarification flow."""
    table_count = len(schema.tables)
    column_count = sum(len(table.columns) for table in schema.tables)
    table_noun = "table" if table_count == 1 else "tables"
    column_noun = "column" if column_count == 1 else "columns"

    st.caption(f"{table_count:,} {table_noun} available · {column_count:,} {column_noun}")

    with st.expander("Tables available to the query"):
        for table in schema.tables:
            st.write(f"**Table:** `{table.name}`")
            st.write(
                "**Columns available:** "
                + ", ".join(f"`{column.name}`" for column in table.columns)
            )

    question = st.text_area(
        "Ask a question about your database",
        placeholder="Example: Show the average demand for each region.",
        height=100,
        key="sql_analyst_question",
    )

    pending_question = st.session_state.get(PENDING_QUESTION_KEY)

    if pending_question and question.strip() and question.strip() != pending_question:
        _clear_pending_clarification()

    if st.button("Generate SQL and Run", type="primary"):
        if not question.strip():
            st.warning("Enter a question before running the SQL Analyst.")
        else:
            _clear_pending_clarification()
            _run_query(
                question=question.strip(),
                schema=schema,
                database_path=database_path,
            )

    _render_clarification(
        current_question=question.strip(),
        schema=schema,
        database_path=database_path,
    )


def render() -> None:
    """Render the SQL Analyst workspace."""
    rail, canvas = layout.shell()
    with rail:
        layout.section_label("Source")
        database_path = _select_database()
        layout.section_label("Database")
        if database_path is None:
            st.text("No database selected")
        else:
            st.text(_database_name())
            st.text("SQLite · read-only")

    # The schema is chosen in the canvas; the rail is filled in a second pass so the
    # Inspector can name the tables that are actually available.
    schema: SchemaSnapshot | None = None
    with canvas:
        layout.page_header(
            "SQL Analyst",
            "Ask the database",
            "Questions become validated, read-only SQL with the result and its limits visible.",
        )

        if database_path is None:
            _clear_query_result()
            st.session_state.pop(QUERY_SOURCE_KEY, None)
            st.text("Choose a database in the rail to continue.")
        else:
            schema = _select_schema(database_path)
            if schema is None or not schema.tables:
                _clear_query_result()
                st.session_state.pop(QUERY_SOURCE_KEY, None)
            else:
                _sync_query_source(database_path, schema)
                _query_panel(schema, database_path)
                _show_last_query()

    if database_path is not None:
        with rail:
            layout.inspector(
                layout.sql_inspector_sections(
                    database_name=_database_name(),
                    tables=(
                        tuple((table.name, len(table.columns)) for table in schema.tables)
                        if schema is not None
                        else ()
                    ),
                )
            )
