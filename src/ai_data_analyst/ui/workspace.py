"""Auto-EDA workspace state and actions (APP-01), independent of Streamlit.

Everything the page does goes through these functions, so it is unit tested without a browser.
They add no analysis logic: they call ingestion, profiling, analysis, chat and reporting, and
keep the results of one session consistent. All artifacts in a workspace describe the same
view of the data; changing the cleaning plan therefore discards them.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..analysis import (
    AnalysisArtifact,
    AnalysisPlan,
    AnalysisStep,
    CleanedView,
    CleaningPlan,
    cleaned_view,
    execute_plan,
    execute_plan_on_view,
    typed_frame,
    validate_cleaning,
)
from ..chat import ChatAnswer, answer_question
from ..ingestion import IngestedCSV, load_csv, load_csv_path
from ..models import DatasetProfile
from ..profiling import profile_ingested
from ..reporting import Report, build_report, render_html, render_markdown
from ..visualization import ChartSpec, charts_for_artifacts

MAX_ARTIFACTS = 20  # the report and plan types allow at most 20 steps
MAX_HISTORY = 50


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

    @property
    def frame(self) -> pd.DataFrame:
        """The data analysis runs on: the cleaned view if there is one, else the typed frame."""
        return self.view.frame if self.view is not None else self.typed


def _build(ingested: IngestedCSV, source_name: str) -> Workspace:
    profile = profile_ingested(ingested)
    return Workspace(
        source_name=source_name,
        ingested=ingested,
        profile=profile,
        typed=typed_frame(ingested, profile),
    )


def load_upload(content: bytes, filename: str) -> Workspace:
    """Validate and profile an upload. Raises ``IngestionError`` with a stable ``code``."""
    return _build(load_csv(content, filename), filename)


def load_sample(path: Path) -> Workspace:
    return _build(load_csv_path(path), path.name)


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
    return _remember(workspace, _execute(workspace, step))


def remove_artifact(workspace: Workspace, index: int) -> None:
    if not 0 <= index < len(workspace.artifacts):
        raise WorkspaceError("no such analysis")
    del workspace.artifacts[index]


def ask(workspace: Workspace, question: str) -> ChatAnswer:
    """Answer a question; a newly computed artifact joins the workspace (and the report)."""
    answer = answer_question(
        question,
        workspace.profile,
        artifacts=workspace.artifacts,
        data=workspace.view if workspace.view is not None else workspace.typed,
    )
    if answer.status == "computed" and answer.artifact is not None:
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
    report = build(workspace, title)
    return render_html(report), render_markdown(report)
