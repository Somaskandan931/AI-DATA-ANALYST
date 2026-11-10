"""Auto-EDA workspace state and actions (APP-01), independent of Streamlit.

Everything the page does goes through these functions, so it is unit tested without a browser.
They add no analysis logic: they call ingestion, profiling, analysis, chat and reporting, and
keep the results of one session consistent. All artifacts in a workspace describe the same
view of the data; changing the cleaning plan therefore discards them.
"""

from __future__ import annotations

import contextlib
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from ..analysis import (
    AnalysisArtifact,
    AnalysisPlan,
    AnalysisStep,
    CleanedView,
    CleaningPlan,
    ExecutionTimeError,
    FilterCondition,
    FilterOp,
    OperationInputError,
    PlanValidationError,
    cleaned_view,
    execute_plan,
    execute_plan_on_view,
    typed_frame,
    validate_cleaning,
)
from ..chat import ChatAnswer, answer_question
from ..ingestion import IngestedCSV, IngestionError, load_csv, load_csv_path
from ..models import DatasetProfile
from ..profiling import profile_ingested
from ..reporting import Report, ReportError, build_report, render_html, render_markdown
from ..security import (
    AuditEvent,
    AuditEventType,
    AuditModule,
    AuditOutcome,
    AuditSink,
    LimitsConfig,
    NullAuditSink,
    new_correlation_id,
    safe_emit,
)
from ..visualization import ChartSpec, charts_for_artifacts

MAX_ARTIFACTS = 20  # the report and plan types allow at most 20 steps
MAX_HISTORY = 50
FILTER_OPERATORS: dict[str, FilterOp] = {
    "equals": "eq",
    "does not equal": "ne",
    "is less than": "lt",
    "is at most": "le",
    "is greater than": "gt",
    "is at least": "ge",
    "is one of (comma-separated)": "in",
    "is not one of (comma-separated)": "not_in",
    "is missing": "is_missing",
    "is not missing": "is_not_missing",
}


class WorkspaceError(ValueError):
    """An action cannot be done in the current state (message is for the person using it)."""


@dataclass
class Workspace:
    source_name: str
    ingested: IngestedCSV
    profile: DatasetProfile
    typed: pd.DataFrame
    cleaning_plan: CleaningPlan = field(default_factory=CleaningPlan)
    view: CleanedView | None = None
    artifacts: list[AnalysisArtifact] = field(default_factory=list)
    history: list[tuple[str, ChatAnswer]] = field(default_factory=list)
    audit: AuditSink = field(default_factory=NullAuditSink)
    correlation_id: str = field(default_factory=new_correlation_id)

    @property
    def frame(self) -> pd.DataFrame:
        """The data analysis runs on: the cleaned view if there is one, else the typed frame."""
        return self.view.frame if self.view is not None else self.typed


def _emit(
    sink: AuditSink,
    event_type: AuditEventType,
    outcome: AuditOutcome,
    correlation_id: str,
    *,
    reasons: tuple[str, ...] = (),
    operation: str | None = None,
    fingerprint: str | None = None,
    row_count: int | None = None,
    started: float | None = None,
) -> None:
    """Emit one M1 audit event; a failing sink never changes the outcome."""
    duration = None if started is None else (time.perf_counter() - started) * 1000
    safe_emit(
        sink,
        AuditEvent(
            event_type=event_type,
            module=AuditModule.M1,
            outcome=outcome,
            timestamp=datetime.now(UTC),
            correlation_id=correlation_id,
            reason_codes=reasons,
            operation=operation,
            dataset_fingerprint=fingerprint,
            row_count=row_count,
            duration_ms=duration,
        ),
    )


def _build(ingested: IngestedCSV, source_name: str, audit: AuditSink) -> Workspace:
    profile = profile_ingested(ingested)
    workspace = Workspace(
        source_name=source_name,
        ingested=ingested,
        profile=profile,
        typed=typed_frame(ingested, profile),
        audit=audit,
    )
    _emit(
        audit,
        AuditEventType.UPLOAD_ACCEPTED,
        AuditOutcome.OK,
        workspace.correlation_id,
        fingerprint=profile.dataset_fingerprint,
        row_count=profile.row_count,
    )
    return workspace


def _load(read: Callable[[], IngestedCSV], source_name: str, audit: AuditSink) -> Workspace:
    try:
        ingested = read()
    except IngestionError as error:
        _emit(
            audit,
            AuditEventType.UPLOAD_REJECTED,
            AuditOutcome.DENIED,
            new_correlation_id(),
            reasons=(error.code,),
        )
        raise
    return _build(ingested, source_name, audit)


def load_upload(
    content: bytes,
    filename: str,
    audit: AuditSink | None = None,
    limits: LimitsConfig | None = None,
) -> Workspace:
    """Validate and profile an upload. Raises ``IngestionError`` with a stable ``code``.

    ``limits`` defaults to the environment-configured limits, so the Streamlit upload
    path honours ``AIDA_*`` overrides in the same way as SQL uploads.
    """
    active = LimitsConfig.from_env() if limits is None else limits
    return _load(
        lambda: load_csv(content, filename, limits=active),
        filename,
        audit or NullAuditSink(),
    )


def load_sample(path: Path, audit: AuditSink | None = None) -> Workspace:
    return _load(lambda: load_csv_path(path), path.name, audit or NullAuditSink())


def _filter_value(kind: str, text: str) -> str | int | float | bool:
    text = text.strip()
    if kind == "boolean":
        if text.lower() not in ("true", "false"):
            raise WorkspaceError(f"{text!r} is not true or false")
        return text.lower() == "true"
    if kind in ("integer", "float"):
        try:
            return int(text)
        except ValueError:
            pass
        try:
            number = float(text)
        except ValueError:
            raise WorkspaceError(f"{text!r} is not a number") from None
        if not math.isfinite(number):
            raise WorkspaceError(f"{text!r} is not a finite number")
        return number
    return text  # dates stay YYYY-MM-DD text; validation checks the format


def parse_filter_condition(
    profile: DatasetProfile, column: str, operator: str, text: str
) -> FilterCondition:
    """Turn the three filter widgets (column, operator label, value text) into a condition.

    The value text is typed by the column's inferred type. Raises :class:`WorkspaceError` for an
    unknown column or operator, or text that does not fit the type; the step itself is
    validated later by ``set_cleaning``.
    """
    kinds = {c.name: c.inferred_type for c in profile.columns}
    if column not in kinds:
        raise WorkspaceError(f"unknown column {column!r}")
    op = FILTER_OPERATORS.get(operator)
    if op is None:
        raise WorkspaceError(f"unknown filter operator {operator!r}")
    kind = kinds[column]
    if op in ("is_missing", "is_not_missing"):
        return FilterCondition(column=column, op=op)
    if op in ("in", "not_in"):
        parts = [part for part in text.split(",") if part.strip()]
        if not parts:
            raise WorkspaceError(f"enter at least one value for {column!r}")
        return FilterCondition(
            column=column, op=op, value=tuple(_filter_value(kind, part) for part in parts)
        )
    if not text.strip():
        raise WorkspaceError(f"enter a value for {column!r}")
    return FilterCondition(column=column, op=op, value=_filter_value(kind, text))


def set_cleaning(workspace: Workspace, plan: CleaningPlan) -> None:
    """Apply *plan* (empty means none) and discard artifacts computed on the old view.

    Raises ``PlanValidationError`` or ``CleaningError``; the workspace is unchanged then.
    """
    if not plan.steps:
        workspace.cleaning_plan, workspace.view = CleaningPlan(), None
    else:
        validate_cleaning(plan, workspace.profile)
        view = cleaned_view(workspace.ingested, workspace.profile, plan)
        workspace.cleaning_plan, workspace.view = plan, view
    workspace.artifacts.clear()
    workspace.history.clear()


def _execute(workspace: Workspace, step: AnalysisStep) -> AnalysisArtifact:
    plan = AnalysisPlan(steps=(step,))
    if workspace.view is not None:
        return execute_plan_on_view(plan, workspace.view, workspace.profile)[0]
    return execute_plan(plan, workspace.typed, workspace.profile)[0]


def _remember(workspace: Workspace, artifact: AnalysisArtifact) -> AnalysisArtifact:
    for existing in workspace.artifacts:
        if existing.parameters == artifact.parameters:
            return existing
    if len(workspace.artifacts) >= MAX_ARTIFACTS:
        raise WorkspaceError(f"at most {MAX_ARTIFACTS} analyses per session; clear some first")
    workspace.artifacts.append(artifact)
    return artifact


def run_step(workspace: Workspace, step: AnalysisStep) -> AnalysisArtifact:
    """Validate and run one step; an identical earlier step is returned instead of repeated.

    Raises ``PlanValidationError``, ``OperationInputError`` or :class:`WorkspaceError`.
    """
    for existing in workspace.artifacts:
        if existing.parameters == step.model_dump(mode="json"):
            return existing
    started = time.perf_counter()
    try:
        artifact = _execute(workspace, step)
    except PlanValidationError:
        _audit_step(workspace, step.operation, AuditOutcome.DENIED, "plan_invalid", started)
        raise
    except (OperationInputError, ExecutionTimeError) as error:
        code = "execution_timeout" if isinstance(error, ExecutionTimeError) else "input_unsupported"
        _audit_step(workspace, step.operation, AuditOutcome.ERROR, code, started)
        raise
    _audit_step(workspace, step.operation, AuditOutcome.OK, None, started)
    return _remember(workspace, artifact)


def _audit_step(
    workspace: Workspace,
    operation: str,
    outcome: AuditOutcome,
    reason: str | None,
    started: float,
) -> None:
    denied = outcome is AuditOutcome.DENIED
    _emit(
        workspace.audit,
        AuditEventType.PLAN_REJECTED if denied else AuditEventType.PLAN_STEP_EXECUTED,
        outcome,
        workspace.correlation_id,
        reasons=() if reason is None else (reason,),
        operation=operation,
        fingerprint=workspace.profile.dataset_fingerprint,
        row_count=len(workspace.frame),
        started=started,
    )


def remove_artifact(workspace: Workspace, index: int) -> None:
    if not 0 <= index < len(workspace.artifacts):
        raise WorkspaceError("no such analysis")
    del workspace.artifacts[index]


def ask(workspace: Workspace, question: str) -> ChatAnswer:
    """Answer a question; a newly computed artifact joins the workspace (and the report)."""
    known = len(workspace.artifacts)
    started = time.perf_counter()
    answer = answer_question(
        question,
        workspace.profile,
        artifacts=workspace.artifacts,
        data=workspace.view if workspace.view is not None else workspace.typed,
    )
    if answer.status == "computed" and answer.artifact is not None:
        if not any(a.parameters == answer.artifact.parameters for a in workspace.artifacts[:known]):
            _audit_step(workspace, answer.artifact.operation, AuditOutcome.OK, None, started)
        # If the session is full the answer is still shown; it is just not added to the report.
        with contextlib.suppress(WorkspaceError):
            _remember(workspace, answer.artifact)
    workspace.history.append((question, answer))
    del workspace.history[:-MAX_HISTORY]
    return answer


def charts(workspace: Workspace) -> tuple[ChartSpec, ...]:
    return charts_for_artifacts(workspace.artifacts)


def build(workspace: Workspace, title: str | None = None) -> Report:
    """The report for the current artifacts (deterministic; no timestamp)."""
    if title is None:
        return build_report(
            workspace.profile, workspace.artifacts, source_name=workspace.source_name
        )
    return build_report(
        workspace.profile, workspace.artifacts, title=title, source_name=workspace.source_name
    )


def report_files(workspace: Workspace, title: str | None = None) -> tuple[str, str]:
    """``(html, markdown)`` for the current artifacts."""
    started = time.perf_counter()
    try:
        report = build(workspace, title)
        files = render_html(report), render_markdown(report)
    except ReportError:
        _emit(
            workspace.audit,
            AuditEventType.REPORT_GENERATED,
            AuditOutcome.ERROR,
            workspace.correlation_id,
            reasons=("report_invalid",),
            fingerprint=workspace.profile.dataset_fingerprint,
            started=started,
        )
        raise
    _emit(
        workspace.audit,
        AuditEventType.REPORT_GENERATED,
        AuditOutcome.OK,
        workspace.correlation_id,
        fingerprint=workspace.profile.dataset_fingerprint,
        started=started,
    )
    return files
