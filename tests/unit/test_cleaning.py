"""EDA-04: the cleaning working view never modifies the ingested data and is fully logged."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from ai_data_analyst.analysis import (
    AnalysisPlan,
    CleaningError,
    CleaningPlan,
    DropDuplicatesStep,
    DropMissingRowsStep,
    ImputeStep,
    PlanValidationError,
    SummaryStatsParams,
    apply_cleaning,
    cleaned_view,
    execute_plan,
    execute_plan_on_view,
    typed_frame,
)
from ai_data_analyst.ingestion import IngestedCSV, load_csv, load_csv_path
from ai_data_analyst.models import DatasetProfile
from ai_data_analyst.profiling import profile_ingested


@pytest.fixture(scope="module")
def ingested(sample_csv_path: Path) -> IngestedCSV:
    return load_csv_path(sample_csv_path)


@pytest.fixture(scope="module")
def profile(ingested: IngestedCSV) -> DatasetProfile:
    return profile_ingested(ingested)


def _plan(*steps: Any) -> CleaningPlan:
    return CleaningPlan(steps=steps)


# --- raw data is never touched ----------------------------------------------------------


def test_cleaning_never_modifies_ingested_or_typed_data(
    ingested: IngestedCSV, profile: DatasetProfile
):
    raw_before = ingested.frame.copy(deep=True)
    typed = typed_frame(ingested, profile)
    typed_before = typed.copy(deep=True)
    plan = _plan(
        DropDuplicatesStep(),
        ImputeStep(column="temperature_c", strategy="median"),
        DropMissingRowsStep(columns=("demand_mwh",)),
    )
    view = apply_cleaning(plan, typed, profile)
    pd.testing.assert_frame_equal(ingested.frame, raw_before)
    pd.testing.assert_frame_equal(typed, typed_before)
    assert view.frame is not typed
    assert len(view.frame) < len(typed)


def test_an_empty_cleaning_plan_returns_an_equal_copy(
    ingested: IngestedCSV, profile: DatasetProfile
):
    typed = typed_frame(ingested, profile)
    view = apply_cleaning(CleaningPlan(), typed, profile)
    pd.testing.assert_frame_equal(view.frame, typed)
    assert view.frame is not typed
    assert view.log == ()
    assert view.rows_before == view.rows_after == profile.row_count


# --- each step against independently known values --------------------------------------


def test_drop_duplicates_removes_exactly_the_profiled_duplicates(
    ingested: IngestedCSV, profile: DatasetProfile, expected_profile: dict[str, object]
):
    view = cleaned_view(ingested, profile, _plan(DropDuplicatesStep()))
    assert expected_profile["duplicate_row_count"] == 5
    assert view.rows_before - view.rows_after == 5
    assert not view.frame.duplicated().any()
    assert view.log == ("Removed 5 duplicate rows (kept the first occurrence)",)
    # first occurrences are kept, in their original order
    assert view.frame["record_id"].is_unique


def test_drop_missing_rows_removes_rows_missing_any_listed_column(
    ingested: IngestedCSV, profile: DatasetProfile
):
    typed = typed_frame(ingested, profile)
    expected = int(typed[["demand_mwh", "temperature_c"]].isna().any(axis=1).sum())
    view = apply_cleaning(
        _plan(DropMissingRowsStep(columns=("demand_mwh", "temperature_c"))), typed, profile
    )
    assert view.rows_before - view.rows_after == expected > 0
    assert not view.frame[["demand_mwh", "temperature_c"]].isna().any().any()
    assert view.log == (
        f"Removed {expected} rows with a missing value in: demand_mwh, temperature_c",
    )


@pytest.mark.parametrize("strategy", ["mean", "median"])
def test_impute_fills_with_the_independently_computed_statistic(
    ingested: IngestedCSV, profile: DatasetProfile, strategy: str
):
    raw = [float(v) for v in ingested.frame["temperature_c"] if v is not None]
    fill = float(np.median(raw) if strategy == "median" else np.mean(raw))
    view = cleaned_view(
        ingested, profile, _plan(ImputeStep(column="temperature_c", strategy=strategy))
    )  # type: ignore[arg-type]
    column = view.frame["temperature_c"]
    assert not column.isna().any()
    assert view.rows_after == view.rows_before
    original = typed_frame(ingested, profile)["temperature_c"]
    assert (column[original.isna()] == fill).all()
    pd.testing.assert_series_equal(column[original.notna()], original[original.notna()])
    assert view.log == (
        f"Filled 12 missing values in 'temperature_c' with the {strategy} ({round(fill, 6)})",
    )


def test_steps_apply_in_order_and_each_is_logged(ingested: IngestedCSV, profile: DatasetProfile):
    view = cleaned_view(
        ingested,
        profile,
        _plan(
            DropDuplicatesStep(),
            DropMissingRowsStep(columns=("demand_mwh",)),
            ImputeStep(column="temperature_c", strategy="mean"),
        ),
    )
    assert len(view.log) == 3
    assert view.log[0].startswith("Removed 5 duplicate")
    assert view.log[1].startswith("Removed ") and "demand_mwh" in view.log[1]
    assert view.log[2].startswith("Filled ")
    assert view.rows_after == len(view.frame)


# --- plan shape and validation ----------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"steps": [{"kind": "run", "code": "df.drop()"}]},
        {"steps": [{"kind": "impute", "column": "a", "strategy": "mode"}]},
        {"steps": [{"kind": "impute", "column": "a", "strategy": "mean", "value": 1}]},
        {"steps": [{"kind": "drop_missing_rows", "columns": []}]},
        {"steps": [{"kind": "drop_missing_rows", "columns": ["a", "a"]}]},
        {"steps": [{"kind": "drop_duplicates"}] * 11},
        {"schema_version": "9.9", "steps": []},
        {"steps": [], "extra": 1},
    ],
)
def test_cleaning_plan_rejects_malformed_input(payload: dict[str, Any]):
    with pytest.raises(ValidationError):
        CleaningPlan.model_validate(payload)


def test_cleaning_plan_round_trips_through_json():
    plan = _plan(DropDuplicatesStep(), ImputeStep(column="a", strategy="median"))
    assert CleaningPlan.model_validate_json(plan.model_dump_json()) == plan


@pytest.mark.parametrize(
    ("step", "fragment"),
    [
        (DropMissingRowsStep(columns=("nope",)), "unknown column"),
        (ImputeStep(column="nope", strategy="mean"), "unknown column"),
        (ImputeStep(column="region", strategy="mean"), "not numeric"),
        (ImputeStep(column="date", strategy="median"), "not numeric"),
    ],
)
def test_invalid_cleaning_steps_are_rejected_before_anything_runs(
    ingested: IngestedCSV, profile: DatasetProfile, step: Any, fragment: str
):
    with pytest.raises(PlanValidationError, match=fragment) as raised:
        cleaned_view(ingested, profile, _plan(DropDuplicatesStep(), step))
    assert raised.value.step == 1


def test_imputing_a_column_with_no_values_fails_closed():
    ingested = load_csv(b"a,b\n1,\n2,\n", "d.csv")
    profile = profile_ingested(ingested)  # b is an all-missing string column
    with pytest.raises(PlanValidationError, match="not numeric"):
        cleaned_view(ingested, profile, _plan(ImputeStep(column="b", strategy="mean")))
    ingested = load_csv(b"a,b\n1,2\n2,3\n", "d.csv")
    profile = profile_ingested(ingested)
    frame = typed_frame(ingested, profile)
    emptied = _plan(
        DropMissingRowsStep(columns=("a",)),  # keeps everything
        ImputeStep(column="b", strategy="mean"),
    )
    assert apply_cleaning(emptied, frame, profile).rows_after == 2
    frame["b"] = np.nan  # an all-missing numeric column after earlier steps
    with pytest.raises(CleaningError, match="no non-missing values"):
        apply_cleaning(_plan(ImputeStep(column="b", strategy="mean")), frame, profile)


def test_cleaning_that_removes_every_row_fails_closed():
    ingested = load_csv(b"a,b\n1,\n2,\n", "d.csv")
    profile = profile_ingested(ingested)
    with pytest.raises(CleaningError, match="removed every row"):
        cleaned_view(ingested, profile, _plan(DropMissingRowsStep(columns=("b",))))


# --- integration with execution and provenance ------------------------------------------


def test_artifacts_from_a_cleaned_view_record_the_cleaning_log(
    ingested: IngestedCSV, profile: DatasetProfile
):
    view = cleaned_view(
        ingested,
        profile,
        _plan(DropDuplicatesStep(), DropMissingRowsStep(columns=("demand_mwh",))),
    )
    plan = AnalysisPlan(steps=(SummaryStatsParams(columns=("demand_mwh",)),))
    (artifact,) = execute_plan_on_view(plan, view, profile)
    assert artifact.provenance.cleaning == view.log
    assert artifact.provenance.rows_in_dataset == view.rows_after
    assert artifact.result["columns"]["demand_mwh"]["count"] == view.rows_after  # type: ignore[index]
    assert artifact.result["columns"]["demand_mwh"]["missing"] == 0  # type: ignore[index]


def test_default_execution_is_unchanged_and_records_no_cleaning(
    ingested: IngestedCSV, profile: DatasetProfile
):
    plan = AnalysisPlan(steps=(SummaryStatsParams(columns=("demand_mwh",)),))
    (artifact,) = execute_plan(plan, typed_frame(ingested, profile), profile)
    assert artifact.provenance.cleaning == ()
    assert artifact.provenance.rows_in_dataset == profile.row_count
    assert artifact.result["columns"]["demand_mwh"]["missing"] == 4  # type: ignore[index]


def test_cleaning_changes_the_computed_statistic_as_expected(
    ingested: IngestedCSV, profile: DatasetProfile
):
    plan = AnalysisPlan(steps=(SummaryStatsParams(columns=("temperature_c",)),))
    (raw,) = execute_plan(plan, typed_frame(ingested, profile), profile)
    view = cleaned_view(
        ingested, profile, _plan(ImputeStep(column="temperature_c", strategy="mean"))
    )
    (filled,) = execute_plan_on_view(plan, view, profile)
    before = raw.result["columns"]["temperature_c"]  # type: ignore[index]
    after = filled.result["columns"]["temperature_c"]  # type: ignore[index]
    assert after["count"] == before["count"] + 12 and after["missing"] == 0
    assert after["mean"] == pytest.approx(
        before["mean"], abs=1e-5
    )  # mean imputation keeps the mean
    assert after["std"] < before["std"]  # ...and shrinks the spread


def test_execute_plan_on_view_rejects_a_view_from_another_dataset(
    ingested: IngestedCSV, profile: DatasetProfile
):
    other = load_csv(b"demand_mwh\n1\n2\n", "d.csv")
    other_view = cleaned_view(other, profile_ingested(other), CleaningPlan())
    plan = AnalysisPlan(steps=(SummaryStatsParams(columns=("demand_mwh",)),))
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        execute_plan_on_view(plan, other_view, profile)


def test_a_view_of_another_dataset_with_the_same_row_count_is_rejected(
    ingested: IngestedCSV, profile: DatasetProfile
):
    rows = "\n".join(f"{i}" for i in range(profile.row_count))
    other = load_csv(f"demand_mwh\n{rows}\n".encode(), "d.csv")
    other_view = cleaned_view(other, profile_ingested(other), CleaningPlan())
    assert other_view.rows_after == profile.row_count
    plan = AnalysisPlan(steps=(SummaryStatsParams(columns=("demand_mwh",)),))
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        execute_plan_on_view(plan, other_view, profile)
