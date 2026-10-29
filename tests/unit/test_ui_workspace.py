"""Auto-EDA workspace actions (APP-01) without Streamlit."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_data_analyst.analysis import (
    CleaningPlan,
    DistributionParams,
    DropDuplicatesStep,
    ImputeStep,
    PlanValidationError,
    SummaryStatsParams,
)
from ai_data_analyst.ingestion import IngestionError
from ai_data_analyst.ui import workspace as ws_api
from ai_data_analyst.ui.workspace import MAX_ARTIFACTS, Workspace, WorkspaceError


@pytest.fixture
def workspace(sample_csv_path: Path) -> Workspace:
    return ws_api.load_sample(sample_csv_path)


def test_upload_is_profiled_and_matches_the_sample(
    sample_csv_path: Path, workspace: Workspace
) -> None:
    uploaded = ws_api.load_upload(sample_csv_path.read_bytes(), "mine.csv")
    assert uploaded.profile == workspace.profile
    assert uploaded.source_name == "mine.csv"


@pytest.mark.parametrize(
    ("content", "filename", "code"),
    [
        (b"a,b\n1,2\n", "data.txt", "unsupported_extension"),
        (b"", "data.csv", "empty_file"),
        (b"a,a\n1,2\n", "data.csv", "duplicate_column"),
        (b"a,b\n1\n", "data.csv", "ragged_row"),
    ],
)
def test_bad_uploads_are_rejected_with_a_code(content: bytes, filename: str, code: str) -> None:
    with pytest.raises(IngestionError) as caught:
        ws_api.load_upload(content, filename)
    assert caught.value.code == code


def test_run_step_adds_and_deduplicates(workspace: Workspace) -> None:
    step = SummaryStatsParams(columns=("demand_mwh",))
    first = ws_api.run_step(workspace, step)
    again = ws_api.run_step(workspace, step)
    assert again is first and len(workspace.artifacts) == 1
    assert first.provenance.dataset_fingerprint == workspace.profile.dataset_fingerprint


def test_invalid_step_runs_nothing(workspace: Workspace) -> None:
    with pytest.raises(PlanValidationError):
        ws_api.run_step(workspace, SummaryStatsParams(columns=("region",)))
    with pytest.raises(PlanValidationError):
        ws_api.run_step(workspace, SummaryStatsParams(columns=("nope",)))
    assert workspace.artifacts == []


def test_session_is_capped(workspace: Workspace) -> None:
    for bins in range(2, 2 + MAX_ARTIFACTS):
        ws_api.run_step(workspace, DistributionParams(column="demand_mwh", bins=bins))
    with pytest.raises(WorkspaceError, match="at most"):
        ws_api.run_step(workspace, DistributionParams(column="demand_mwh", bins=99))
    assert len(workspace.artifacts) == MAX_ARTIFACTS


def test_cleaning_discards_artifacts_and_is_recorded(workspace: Workspace) -> None:
    ws_api.run_step(workspace, SummaryStatsParams(columns=("demand_mwh",)))
    ws_api.ask(workspace, "how many rows?")
    plan = CleaningPlan(
        steps=(DropDuplicatesStep(), ImputeStep(column="demand_mwh", strategy="median"))
    )
    ws_api.set_cleaning(workspace, plan)
    assert workspace.artifacts == [] and workspace.history == []
    assert workspace.view is not None
    assert (
        workspace.view.rows_after
        == workspace.profile.row_count - workspace.profile.duplicate_row_count
    )
    artifact = ws_api.run_step(workspace, SummaryStatsParams(columns=("demand_mwh",)))
    assert artifact.provenance.cleaning == workspace.view.log
    assert artifact.result["columns"]["demand_mwh"]["missing"] == 0  # type: ignore[index]
    ws_api.set_cleaning(workspace, CleaningPlan())
    assert workspace.view is None and workspace.artifacts == []


def test_failed_cleaning_leaves_the_workspace_unchanged(workspace: Workspace) -> None:
    ws_api.run_step(workspace, SummaryStatsParams(columns=("demand_mwh",)))
    with pytest.raises(PlanValidationError):
        ws_api.set_cleaning(
            workspace, CleaningPlan(steps=(ImputeStep(column="region", strategy="mean"),))
        )
    assert len(workspace.artifacts) == 1 and workspace.view is None


def test_chat_computes_once_and_feeds_the_report(workspace: Workspace) -> None:
    first = ws_api.ask(workspace, "average demand_mwh by region")
    second = ws_api.ask(workspace, "average demand_mwh by region")
    assert first.status == "computed" and second.status == "artifact"
    assert len(workspace.artifacts) == 1 and len(workspace.history) == 2
    html_text, markdown_text = ws_api.report_files(workspace, "My report")
    assert "My report" in html_text and "My report" in markdown_text
    assert "East" in markdown_text


def test_profile_answers_add_no_artifacts(workspace: Workspace) -> None:
    assert ws_api.ask(workspace, "how many rows?").status == "profile"
    assert workspace.artifacts == []


def test_report_is_deterministic_and_charts_trace_to_artifacts(workspace: Workspace) -> None:
    ws_api.run_step(workspace, DistributionParams(column="region"))
    assert ws_api.report_files(workspace) == ws_api.report_files(workspace)
    specs = ws_api.charts(workspace)
    assert specs and specs[0].source_step == 0


def test_remove_artifact(workspace: Workspace) -> None:
    ws_api.run_step(workspace, DistributionParams(column="region"))
    ws_api.remove_artifact(workspace, 0)
    assert workspace.artifacts == []
    with pytest.raises(WorkspaceError):
        ws_api.remove_artifact(workspace, 0)


def test_history_is_bounded(workspace: Workspace) -> None:
    for _ in range(ws_api.MAX_HISTORY + 5):
        ws_api.ask(workspace, "how many rows?")
    assert len(workspace.history) == ws_api.MAX_HISTORY
