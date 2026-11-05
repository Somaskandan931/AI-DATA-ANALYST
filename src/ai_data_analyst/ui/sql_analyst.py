"""Streamlit UI for the M2 Natural-Language-to-SQL workspace."""

import csv
import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path
from uuid import uuid4

import streamlit as st
from streamlit.runtime.uploaded_file_manager import UploadedFile

from ai_data_analyst.security.limits import LimitsConfig
from ai_data_analyst.sql_agent.contracts import SchemaSnapshot
from ai_data_analyst.sql_agent.executor import SQLExecutionError
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

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_DB = PROJECT_ROOT / "data" / "sample" / "electricity_demand.db"
SAMPLE_CSV = PROJECT_ROOT / "data" / "sample" / "electricity_demand.csv"
SAMPLE_BUILD_DIR = Path(tempfile.gettempdir()) / "ai_data_analyst_sample"
SAMPLE_TABLE = "electricity_demand"
_SAMPLE_REAL_COLUMNS = frozenset({"demand_mwh", "temperature_c"})

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


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


def _clear_pending_clarification() -> None:
    """Clear any stored clarification state."""
    st.session_state.pop(PENDING_QUESTION_KEY, None)
    st.session_state.pop(PENDING_CLARIFICATION_KEY, None)


def _save_uploaded_database(uploaded_file: UploadedFile) -> Path:
    """Validate and save an uploaded SQLite database to a temporary file."""
    filename = Path(uploaded_file.name)

    if filename.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise SchemaError("Upload a .db, .sqlite, or .sqlite3 file.")

    content = uploaded_file.getvalue()

    if not content:
        raise SchemaError("The uploaded file is empty.")

    if len(content) > MAX_UPLOAD_BYTES:
        raise SchemaError("Database upload must not exceed 50 MB.")

    digest = hashlib.sha256(content).hexdigest()
    previous_digest = st.session_state.get("sql_db_upload_digest")
    previous_path = st.session_state.get("sql_db_upload_path")

    if previous_digest == digest and previous_path:
        existing_path = Path(previous_path)
        if existing_path.is_file():
            return existing_path

    temporary_path = None

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
            st.error("The sample database is unavailable.")
            return None

        st.markdown("**Selected database:** Electricity Demand Sample")
        return sample_path

    uploaded_file = st.file_uploader(
        "Upload a SQLite database",
        type=["db", "sqlite", "sqlite3"],
        help="Maximum upload size: 50 MB.",
        key="sql_database_upload",
    )

    if uploaded_file is None:
        st.info("Upload a SQLite database to continue.")
        return None

    try:
        database_path = _save_uploaded_database(uploaded_file)
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
        st.error("Database metadata could not be inspected safely.")
        return None

    table_names = list(available)

    selected_tables = st.multiselect(
        "Select tables",
        options=table_names,
        default=table_names,
        key=f"sql_tables_{database_path.name}",
        help="Only selected tables will be available to the SQL generator.",
    )

    if not selected_tables:
        st.warning("Select at least one table.")
        return None

    selected_columns = {}

    with st.expander("Select permitted columns", expanded=True):
        for table_name in selected_tables:
            available_columns = list(available[table_name])

            columns = st.multiselect(
                f"Columns in {table_name}",
                options=available_columns,
                default=available_columns,
                key=f"sql_columns_{database_path.name}_{table_name}",
            )

            if not columns:
                st.warning(f"Select at least one column for {table_name}.")
                return None

            selected_columns[table_name] = tuple(columns)

    try:
        allow_list = SchemaAllowList(tables=selected_columns)
        schema = discover_schema(database_path, allow_list)

    except SchemaError:
        st.error("The selected database schema could not be approved safely.")
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
        st.error(
            "The query could not be executed because it did not meet "
            "the database safety restrictions."
        )
    else:
        st.error("The database could not execute this query. Check your question and try again.")


def _show_query_result(details: SQLPipelineResult) -> None:
    """Display validated SQL and its execution result."""
    st.success("Query executed successfully.")

    st.markdown("**Validated SQL**")
    st.code(details.normalized_sql, language="sql")

    result = details.execution

    st.markdown("**Query Results**")

    if result.rows:
        st.dataframe(
            [
                dict(
                    zip(
                        result.columns,
                        row,
                        strict=False,
                    )
                )
                for row in result.rows
            ],
            use_container_width=True,
        )
    else:
        st.info("The query completed successfully but returned no rows.")

    st.caption(f"Rows displayed: {len(result.rows)}")

    if result.truncated:
        st.warning("Results were limited by the configured maximum row count.")


def _run_query(
    question: str,
    schema: SchemaSnapshot,
    database_path: Path,
    skip_ambiguity_check: bool = False,
) -> None:
    """Run the generate, validate, and execute pipeline.

    Skip ambiguity detection only after explicit user clarification.
    """
    try:
        generator = create_sql_generator()

        details = run_sql_pipeline_with_details(
            question=question,
            schema=schema,
            db_path=database_path,
            generator=generator,
            limits=LimitsConfig.from_env(),
            skip_ambiguity_check=skip_ambiguity_check,
        )

        _clear_pending_clarification()
        _show_query_result(details)

    except SQLClarificationRequired as exc:
        st.session_state[PENDING_QUESTION_KEY] = question
        st.session_state[PENDING_CLARIFICATION_KEY] = exc.clarification_question
        st.rerun()

    except SQLQueryDenied as exc:
        _clear_pending_clarification()
        st.error("The generated SQL was rejected by the safety validator.")

        for violation in exc.validation.violations:
            st.write(f"- {violation.message}")

    except SQLExecutionError as exc:
        _clear_pending_clarification()
        _show_execution_error(exc)

    except SQLPipelineError as exc:
        _clear_pending_clarification()
        st.error(str(exc))

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


def render() -> None:
    """Render the SQL Analyst workspace."""
    st.subheader("SQL Analyst")
    st.caption("Ask questions about your database using natural language.")

    database_path = _select_database()

    if database_path is None:
        return

    schema = _select_schema(database_path)

    if schema is None or not schema.tables:
        return

    table_count = len(schema.tables)
    column_count = sum(len(table.columns) for table in schema.tables)

    st.caption(f"{table_count} approved table(s) • {column_count} approved column(s)")

    with st.expander("Approved database schema"):
        for table in schema.tables:
            st.write(f"**Table:** `{table.name}`")
            st.write(
                "**Allowed columns:** " + ", ".join(f"`{column.name}`" for column in table.columns)
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
