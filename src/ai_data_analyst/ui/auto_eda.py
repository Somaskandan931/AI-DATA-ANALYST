"""Streamlit page for the Auto-EDA workspace (APP-01).

Pages hold widgets only; every action is a call into :mod:`ai_data_analyst.ui.workspace`.
Text that came from the uploaded file (column names, values) is shown with ``st.text``,
tables and widgets, never through Markdown or HTML, so it cannot become markup.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from ..analysis import (
    AnalysisStep,
    CleaningError,
    CleaningPlan,
    CleaningStep,
    ClusteringParams,
    CorrelationParams,
    DistributionParams,
    DropDuplicatesStep,
    DropMissingRowsStep,
    ExecutionTimeError,
    FilterRowsStep,
    GroupedAggregationParams,
    ImputeStep,
    OperationInputError,
    OutlierSummaryParams,
    PcaParams,
    PlanValidationError,
    SummaryStatsParams,
)
from ..chat import SUPPORTED_QUESTIONS, ChatAnswer, ChatError
from ..ingestion import IngestionError
from ..reporting import ReportError, chart_svg
from ..security import InMemoryAuditSink
from . import evidence, layout
from . import workspace as ws_api
from .theme import fresh_class
from .workspace import Workspace, WorkspaceError

SAMPLE_PATH = Path(__file__).resolve().parents[3] / "data" / "sample" / "electricity_demand.csv"
_KEY = "auto_eda_workspace"
_UPLOAD_KEY = "auto_eda_upload_id"
_AUDIT_KEY = "auto_eda_audit"
_NUMERIC = ("integer", "float")
_GROUPABLE = ("integer", "boolean", "date", "string")
_FILTER_ROWS = 3
_AGGREGATIONS = ("count", "mean", "median", "sum", "min", "max", "std")
_EXPECTED = (
    IngestionError,
    PlanValidationError,
    OperationInputError,
    ExecutionTimeError,
    CleaningError,
    WorkspaceError,
    ReportError,
    ChatError,
    ValidationError,
)
_T = TypeVar("_T")


def _guard(action: Callable[[], _T]) -> _T | None:
    """Run *action*; show an expected failure as an error message and return ``None``."""
    try:
        return action()
    except IngestionError as error:
        st.error(f"This file cannot be used ({error.code}): {error}")
    except _EXPECTED as error:
        st.error(str(error))
    return None


def _columns(workspace: Workspace, kinds: tuple[str, ...]) -> list[str]:
    return [c.name for c in workspace.profile.columns if c.inferred_type in kinds]


# ---- upload ---------------------------------------------------------------------------------


def _audit() -> InMemoryAuditSink:
    """The session's audit sink (events hold codes, hashes and counts only)."""
    sink = st.session_state.get(_AUDIT_KEY)
    if not isinstance(sink, InMemoryAuditSink):
        sink = st.session_state[_AUDIT_KEY] = InMemoryAuditSink()
    return sink


def _empty_state() -> None:
    """The first screen before a dataset exists; animate only on its first appearance."""
    fresh = fresh_class("auto-eda-empty", None)
    st.html(
        f"""
        <section class="fn-empty-hero {fresh}" aria-labelledby="fn-wordmark">
            <p class="fn-wordmark" id="fn-wordmark">Field Notes</p>
            <h2 class="fn-hero-title">A quiet workspace for your data.</h2>
            <p class="fn-hero-purpose">
                Profile, clean, and explain a dataset while keeping every number
                traceable to its source.
            </p>
        </section>
        """
    )


def _current_workspace() -> Workspace | None:
    """The dataset loaded in this session, if any."""
    workspace = st.session_state.get(_KEY)
    return workspace if isinstance(workspace, Workspace) else None


def _source_controls() -> Workspace | None:
    """Buttons and uploader that load or replace the dataset."""
    use_sample = st.button(
        "Use the sample dataset",
        type="primary",
        disabled=not SAMPLE_PATH.exists(),
    )
    uploaded = st.file_uploader("Upload a CSV file", type=["csv"])
    if uploaded is not None and st.session_state.get(_UPLOAD_KEY) != uploaded.file_id:
        loaded = _guard(lambda: ws_api.load_upload(uploaded.getvalue(), uploaded.name, _audit()))
        if loaded is not None:
            st.session_state[_KEY] = loaded
            st.session_state[_UPLOAD_KEY] = uploaded.file_id
    elif use_sample:
        loaded = _guard(lambda: ws_api.load_sample(SAMPLE_PATH, _audit()))
        if loaded is not None:
            st.session_state[_KEY] = loaded
            st.session_state[_UPLOAD_KEY] = None
    return _current_workspace()


# ---- rail -----------------------------------------------------------------------------------


def _rail(workspace: Workspace) -> None:
    """Source, dataset shape, working state and the inspector."""
    profile = workspace.profile
    layout.section_label("Source")
    st.text(workspace.source_name)
    layout.section_label("Dataset")
    st.text(f"{profile.row_count:,} rows · {profile.column_count:,} columns")
    layout.section_label("State")
    if workspace.view is None:
        st.text("No cleaning applied")
    else:
        st.text(f"Cleaning: {len(workspace.view.log)} step(s)")
    st.text(f"Analyses: {len(workspace.artifacts)}")
    st.text(f"Questions: {len(workspace.history)}")
    events = workspace.audit.events if isinstance(workspace.audit, InMemoryAuditSink) else ()
    layout.inspector(
        profile=profile,
        cleaning_log=workspace.view.log if workspace.view is not None else (),
        audit_events=events,
    )


def _overview(workspace: Workspace) -> None:
    """The compact overview cards; animate only when the dataset changes."""
    layout.section_label("Overview")
    fresh = fresh_class("auto-eda-overview", workspace.profile.dataset_fingerprint)
    layout.evidence_view(evidence.overview_view(workspace.profile), fresh=bool(fresh))


# ---- profile --------------------------------------------------------------------------------


def _profile_tab(workspace: Workspace) -> None:
    layout.page_header(
        "Profile",
        "Know the dataset",
        "Column types, missing values and the first rows, exactly as uploaded.",
    )
    profile = workspace.profile
    table = pd.DataFrame([col.model_dump() for col in profile.columns])
    for name in ("min", "max"):  # numbers for numeric columns, dates for date columns
        table[name] = table[name].map(lambda v: "" if v is None else str(v))
    st.dataframe(table, hide_index=True)
    st.caption("First rows exactly as uploaded")
    st.dataframe(workspace.ingested.frame.head(20))


# ---- cleaning -------------------------------------------------------------------------------


def _cleaning_tab(workspace: Workspace) -> None:
    layout.page_header(
        "Cleaning",
        "Shape the working copy",
        "Apply filters, de-duplication and fills; the upload itself never changes.",
    )
    st.caption(
        "Cleaning works on a copy; the upload is never changed. Applying a plan discards "
        "analyses computed on the previous view."
    )
    all_columns = [c.name for c in workspace.profile.columns]
    drop_duplicates = st.checkbox("Remove duplicate rows (keep the first)")
    drop_missing = st.multiselect("Remove rows with a missing value in", all_columns)
    impute = st.multiselect("Fill missing values in numeric columns", _columns(workspace, _NUMERIC))
    strategy = st.radio("Fill with", ("mean", "median"), horizontal=True)
    st.caption(
        "Keep only rows that match all of these conditions (leave Column empty to skip a row). "
        'Filters run first. A row with a missing value matches only "is missing".'
    )
    rows: list[tuple[str, str, str]] = []
    for index in range(_FILTER_ROWS):
        a, b, c = st.columns([2, 2, 3])
        column = a.selectbox(
            "Filter column",
            ["", *all_columns],
            key=f"filter_column_{index}",
            label_visibility="collapsed",
        )
        operator = b.selectbox(
            "Filter operator",
            list(ws_api.FILTER_OPERATORS),
            key=f"filter_operator_{index}",
            label_visibility="collapsed",
        )
        text = c.text_input(
            "Filter value",
            key=f"filter_value_{index}",
            label_visibility="collapsed",
            placeholder="value (dates as YYYY-MM-DD)",
        )
        rows.append((column, operator, text))
    left, right = st.columns(2)
    if left.button("Apply cleaning"):

        def apply() -> bool:
            steps: list[CleaningStep] = []
            conditions = tuple(
                ws_api.parse_filter_condition(workspace.profile, column, operator, text)
                for column, operator, text in rows
                if column
            )
            if conditions:
                steps.append(FilterRowsStep(conditions=conditions))
            if drop_duplicates:
                steps.append(DropDuplicatesStep())
            if drop_missing:
                steps.append(DropMissingRowsStep(columns=tuple(drop_missing)))
            steps.extend(ImputeStep(column=name, strategy=strategy) for name in impute)
            ws_api.set_cleaning(workspace, CleaningPlan(steps=tuple(steps)))
            return True

        if _guard(apply):  # on failure keep the page so the error stays visible
            st.rerun()
    if right.button("Use the data as uploaded"):
        ws_api.set_cleaning(workspace, CleaningPlan())
        st.rerun()
    view = workspace.view
    if view is None:
        st.info("No cleaning is applied.")
        return
    st.text(f"Rows: {view.rows_before} before, {view.rows_after} after")
    for line in view.log:
        st.text(f"- {line}")


# ---- analysis -------------------------------------------------------------------------------

_OPERATIONS = (
    "summary_stats",
    "grouped_aggregation",
    "correlation",
    "distribution",
    "outlier_summary",
    "clustering",
    "pca",
)


def _step_form(workspace: Workspace, operation: str) -> AnalysisStep | None:  # noqa: C901
    numeric = _columns(workspace, _NUMERIC)
    every = [c.name for c in workspace.profile.columns]
    with st.form(f"form_{operation}"):
        step: Callable[[], AnalysisStep]
        match operation:
            case "summary_stats":
                cols = st.multiselect("Numeric columns", numeric)

                def step() -> AnalysisStep:
                    return SummaryStatsParams(columns=tuple(cols))

            case "grouped_aggregation":
                groups = st.multiselect("Group by (up to 3)", _columns(workspace, _GROUPABLE))
                value = st.selectbox("Value column", every)
                aggs = st.multiselect("Aggregations", _AGGREGATIONS, default=["mean"])
                limit = st.number_input("Maximum groups", 1, 1000, 50)

                def step() -> AnalysisStep:
                    return GroupedAggregationParams(
                        group_by=tuple(groups),
                        value_column=str(value),
                        aggregations=tuple(aggs),
                        max_groups=int(limit),
                    )

            case "correlation":
                cols = st.multiselect("Numeric columns (2 to 20)", numeric)
                method = st.radio("Method", ("pearson", "spearman"), horizontal=True)

                def step() -> AnalysisStep:
                    return CorrelationParams(columns=tuple(cols), method=method)

            case "distribution":
                column = st.selectbox("Column", every)
                bins = st.number_input("Histogram bins", 2, 100, 10)
                top = st.number_input("Categories shown", 1, 100, 10)

                def step() -> AnalysisStep:
                    return DistributionParams(column=str(column), bins=int(bins), top_n=int(top))

            case "outlier_summary":
                cols = st.multiselect("Numeric columns", numeric)
                factor = st.number_input("IQR factor", 0.1, 10.0, 1.5, step=0.1)

                def step() -> AnalysisStep:
                    return OutlierSummaryParams(columns=tuple(cols), iqr_factor=float(factor))

            case "clustering":
                cols = st.multiselect("Numeric columns (2 to 10)", numeric)
                k = st.number_input("Clusters (k)", 2, 10, 3)
                standardize = st.checkbox("Standardize columns first", value=True)
                seed = st.number_input("Random seed", 0, 2**31 - 1, 0)

                def step() -> AnalysisStep:
                    return ClusteringParams(
                        columns=tuple(cols),
                        k=int(k),
                        standardize=standardize,
                        random_state=int(seed),
                    )

            case _:
                cols = st.multiselect("Numeric columns (2 to 20)", numeric)
                components = st.number_input("Components", 1, 10, 2)
                standardize = st.checkbox("Standardize columns first", value=True)

                def step() -> AnalysisStep:
                    return PcaParams(
                        columns=tuple(cols),
                        n_components=int(components),
                        standardize=standardize,
                    )

        submitted = st.form_submit_button("Run")
    return _guard(step) if submitted else None


def _results(workspace: Workspace) -> None:
    if not workspace.artifacts:
        st.info("No analyses yet. Run one above or ask a question in the Chat tab.")
        return
    report = _guard(lambda: ws_api.build(workspace))
    if report is None:
        return
    for result in report.results:
        with st.expander(result.title, expanded=False):
            method = report.methods[result.step]
            st.text(f"Rows used: {method.rows_used} of {method.rows_in_dataset}")
            for warning in workspace.artifacts[result.step].warnings:
                st.warning(warning)
            for label, value in result.facts:
                st.text(f"{label}: {value}")
            parameters = ", ".join(f"{name}={value}" for name, value in method.parameters)
            layout.computed_from(
                (
                    ("Operation", method.operation),
                    ("Parameters", parameters or "none"),
                    ("Rows used", f"{method.rows_used} of {method.rows_in_dataset}"),
                    ("Input columns", ", ".join(method.input_columns) or "none"),
                    ("Cleaning", "; ".join(method.cleaning) or "none"),
                )
            )
            for table in result.tables:
                st.caption(table.caption)
                st.dataframe(
                    pd.DataFrame(list(table.rows), columns=list(table.headers)),
                    hide_index=True,
                )
            for position in result.chart_indices:
                st.image(chart_svg(report.charts[position]))
            if st.button("Remove this analysis", key=f"remove_{result.step}"):
                ws_api.remove_artifact(workspace, result.step)
                st.rerun()


def _analysis_tab(workspace: Workspace) -> None:
    layout.page_header(
        "Analysis",
        "Ask a computed question",
        "Run one allow-listed operation and keep every number traceable to its inputs.",
    )
    operation = st.selectbox("Analysis", _OPERATIONS)
    step = _step_form(workspace, operation)
    if step is not None:
        _guard(lambda: ws_api.run_step(workspace, step))
    _results(workspace)


# ---- chat -----------------------------------------------------------------------------------


def _chat_tab(workspace: Workspace) -> None:
    layout.page_header(
        "Chat",
        "Ask in plain language",
        "Answers use only the profile and computed results; every number has evidence.",
    )
    with st.expander("What can I ask?"):
        for line in SUPPORTED_QUESTIONS:
            st.text(f"- {line}")
    st.caption(
        "Answers are built from the profile and computed results only; every number has "
        "evidence. Nothing is sent to a model."
    )
    for question, answer in workspace.history:
        with st.chat_message("user"):
            st.text(question)
        with st.chat_message("assistant"):
            _show_answer(answer)
    new_question = st.chat_input("Ask about this dataset")
    if new_question and _guard(lambda: ws_api.ask(workspace, new_question)) is not None:
        st.rerun()


def _show_answer(answer: ChatAnswer) -> None:
    st.text(answer.text)
    for note in answer.assumptions:
        st.caption(f"Assumption: {note}")
    for warning in answer.warnings:
        st.caption(f"Note: {warning}")
    if answer.evidence:
        with st.expander("Evidence"):
            st.dataframe(
                pd.DataFrame([e.model_dump() for e in answer.evidence]),
                hide_index=True,
            )


# ---- report ---------------------------------------------------------------------------------


def _report_tab(workspace: Workspace) -> None:
    layout.page_header(
        "Report",
        "Take the evidence with you",
        "Export the profile and the analyses run in this session.",
    )
    st.caption("The report contains the profile and the analyses run in this session.")
    title = st.text_input("Report title", value="Auto-EDA report", max_chars=200)
    files = _guard(lambda: ws_api.report_files(workspace, title.strip() or None))
    if files is None:
        return
    html_text, markdown_text = files
    st.text(f"{len(workspace.artifacts)} analyses included")
    left, right = st.columns(2)
    left.download_button("Download HTML", html_text, "report.html", "text/html")
    right.download_button("Download Markdown", markdown_text, "report.md", "text/markdown")


# ---- entry point ----------------------------------------------------------------------------


def render() -> None:
    """Draw the Auto-EDA workspace."""
    workspace = _current_workspace()
    if workspace is None:
        _empty_state()
        if _source_controls() is not None:
            st.rerun()
        return

    rail, canvas = layout.shell()
    with rail:
        if _source_controls() is not workspace:
            st.rerun()
        _rail(workspace)
    with canvas:
        _overview(workspace)
        tabs = st.tabs(["Profile", "Cleaning", "Analysis", "Chat", "Report"])
        for tab, draw in zip(
            tabs,
            (_profile_tab, _cleaning_tab, _analysis_tab, _chat_tab, _report_tab),
            strict=True,
        ):
            with tab:
                draw(workspace)
