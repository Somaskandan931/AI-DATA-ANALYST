"""Tests for the allow-listed analysis operations (EDA-06, EDA-07)."""

from __future__ import annotations

import json
import math
import typing
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pydantic import ValidationError

from ai_data_analyst.analysis import (
    OPERATIONS,
    AnalysisArtifact,
    AnalysisPlan,
    CorrelationParams,
    DistributionParams,
    ExecutionTimeError,
    GroupedAggregationParams,
    OperationName,
    OutlierSummaryParams,
    PlanValidationError,
    SummaryStatsParams,
    execute_plan,
    typed_frame,
    validate_plan,
)
from ai_data_analyst.ingestion import IngestedCSV, load_csv_path
from ai_data_analyst.models import DatasetProfile
from ai_data_analyst.profiling import profile_ingested
from ai_data_analyst.security import LimitsConfig


@pytest.fixture(scope="module")
def ingested(sample_csv_path: Path) -> IngestedCSV:
    return load_csv_path(sample_csv_path)


@pytest.fixture(scope="module")
def profile(ingested: IngestedCSV) -> DatasetProfile:
    return profile_ingested(ingested)


@pytest.fixture(scope="module")
def frame(ingested: IngestedCSV, profile: DatasetProfile) -> pd.DataFrame:
    return typed_frame(ingested, profile)


def _run(frame: pd.DataFrame, profile: DatasetProfile, *steps: Any) -> tuple[AnalysisArtifact, ...]:
    return execute_plan(AnalysisPlan(steps=steps), frame, profile)


def _expected_column(expected_profile: dict[str, object], name: str) -> dict[str, Any]:
    columns = typing.cast(list[dict[str, Any]], expected_profile["columns"])
    return next(c for c in columns if c["name"] == name)


# --- typed view -------------------------------------------------------------------------


def test_typed_frame_does_not_modify_ingested_data(ingested: IngestedCSV, profile: DatasetProfile):
    before = ingested.frame.copy(deep=True)
    typed = typed_frame(ingested, profile)
    pd.testing.assert_frame_equal(ingested.frame, before)
    assert typed["demand_mwh"].dtype == "float64"
    assert str(typed["date"].dtype).startswith("datetime64")
    assert int(typed["temperature_c"].isna().sum()) == 12


def test_typed_frame_rejects_mismatched_profile(ingested: IngestedCSV, profile: DatasetProfile):
    other = profile.model_copy(update={"dataset_fingerprint": "0" * 64})
    with pytest.raises(ValueError, match="fingerprint"):
        typed_frame(ingested, other)


# --- plan shape and allow-list (EDA-07) --------------------------------------------------


def test_registry_is_exactly_the_declared_allow_list():
    assert set(OPERATIONS) == set(typing.get_args(OperationName))


def test_plan_rejects_unknown_operation():
    with pytest.raises(ValidationError):
        AnalysisPlan.model_validate({"steps": [{"operation": "exec", "code": "print(1)"}]})


def test_plan_rejects_unknown_fields_and_code_like_fields():
    with pytest.raises(ValidationError):
        AnalysisPlan.model_validate(
            {
                "steps": [
                    {"operation": "summary_stats", "columns": ["a"], "expr": "__import__('os')"}
                ]
            }
        )


def test_plan_rejects_empty_and_oversized_plans():
    with pytest.raises(ValidationError):
        AnalysisPlan(steps=())
    step = SummaryStatsParams(columns=("demand_mwh",))
    with pytest.raises(ValidationError):
        AnalysisPlan(steps=(step,) * 21)


@pytest.mark.parametrize(
    "build",
    [
        lambda: SummaryStatsParams(columns=()),
        lambda: SummaryStatsParams(columns=("a", "a")),
        lambda: CorrelationParams(columns=("a",)),
        lambda: CorrelationParams(columns=("a", "b"), method="kendall"),  # type: ignore[arg-type]
        lambda: DistributionParams(column="a", bins=1),
        lambda: DistributionParams(column="a", bins=101),
        lambda: OutlierSummaryParams(columns=("a",), iqr_factor=0),
        lambda: OutlierSummaryParams(columns=("a",), iqr_factor=float("nan")),
        lambda: GroupedAggregationParams(group_by=("a",), value_column="b", aggregations=()),
        lambda: GroupedAggregationParams(
            group_by=("a",), value_column="b", aggregations=("mean", "mean")
        ),
        lambda: GroupedAggregationParams(
            group_by=("a", "b", "c", "d"), value_column="e", aggregations=("sum",)
        ),
        lambda: GroupedAggregationParams(
            group_by=("a",),
            value_column="b",
            aggregations=("mode",),  # type: ignore[arg-type]
        ),
    ],
)
def test_invalid_parameters_are_rejected(build: Any):
    with pytest.raises(ValidationError):
        build()


def test_plan_round_trips_through_json():
    plan = AnalysisPlan(
        steps=(
            SummaryStatsParams(columns=("demand_mwh",)),
            DistributionParams(column="region"),
        )
    )
    assert AnalysisPlan.model_validate_json(plan.model_dump_json()) == plan


# --- validation against the dataset -----------------------------------------------------


@pytest.mark.parametrize(
    ("step", "fragment"),
    [
        (SummaryStatsParams(columns=("nope",)), "unknown column"),
        (SummaryStatsParams(columns=("region",)), "expected a numeric column"),
        (CorrelationParams(columns=("demand_mwh", "date")), "expected a numeric column"),
        (OutlierSummaryParams(columns=("holiday",)), "expected a numeric column"),
        (DistributionParams(column="nope"), "unknown column"),
        (
            GroupedAggregationParams(
                group_by=("temperature_c",), value_column="demand_mwh", aggregations=("mean",)
            ),
            "not groupable",
        ),
        (
            GroupedAggregationParams(
                group_by=("region",), value_column="region", aggregations=("count",)
            ),
            "must not also be",
        ),
        (
            GroupedAggregationParams(
                group_by=("region",), value_column="holiday", aggregations=("mean",)
            ),
            "only 'count'",
        ),
    ],
)
def test_validate_plan_rejects_steps_that_do_not_fit_the_dataset(
    profile: DatasetProfile, step: Any, fragment: str
):
    with pytest.raises(PlanValidationError, match=fragment):
        validate_plan(AnalysisPlan(steps=(step,)), profile)


def test_validation_failure_runs_nothing_and_reports_the_step(
    frame: pd.DataFrame, profile: DatasetProfile
):
    good = SummaryStatsParams(columns=("demand_mwh",))
    bad = SummaryStatsParams(columns=("missing_column",))
    with pytest.raises(PlanValidationError) as raised:
        _run(frame, profile, good, bad)
    assert raised.value.step == 1


# --- results match the independently computed expected profile ---------------------------


def test_summary_stats_match_expected_profile(
    frame: pd.DataFrame, profile: DatasetProfile, expected_profile: dict[str, object]
):
    (artifact,) = _run(frame, profile, SummaryStatsParams(columns=("demand_mwh", "temperature_c")))
    columns = typing.cast(dict[str, dict[str, Any]], artifact.result["columns"])
    for name in ("demand_mwh", "temperature_c"):
        expected = _expected_column(expected_profile, name)
        got = columns[name]
        for key in ("min", "max", "mean", "median", "std", "q1", "q3"):
            assert got[key] == pytest.approx(expected[key], abs=1e-6), (name, key)
        assert got["missing"] == expected["missing_count"]
        assert got["count"] == profile.row_count - expected["missing_count"]
    assert artifact.input_columns == ("demand_mwh", "temperature_c")
    assert any("missing values excluded" in w for w in artifact.warnings)


def test_outlier_summary_matches_expected_outlier_counts(
    frame: pd.DataFrame, profile: DatasetProfile, expected_profile: dict[str, object]
):
    (artifact,) = _run(
        frame, profile, OutlierSummaryParams(columns=("demand_mwh", "temperature_c"))
    )
    columns = typing.cast(dict[str, dict[str, Any]], artifact.result["columns"])
    for name in ("demand_mwh", "temperature_c"):
        assert (
            columns[name]["outlier_count"]
            == _expected_column(expected_profile, name)["outlier_count"]
        )
    assert columns["demand_mwh"]["outlier_count"] == 3


def test_wider_iqr_factor_flags_fewer_outliers(frame: pd.DataFrame, profile: DatasetProfile):
    narrow, wide = _run(
        frame,
        profile,
        OutlierSummaryParams(columns=("demand_mwh",), iqr_factor=1.5),
        OutlierSummaryParams(columns=("demand_mwh",), iqr_factor=10),
    )
    count = lambda a: a.result["columns"]["demand_mwh"]["outlier_count"]  # noqa: E731
    assert count(narrow) == 3
    assert count(wide) == 0


def test_grouped_aggregation_matches_pandas_and_counts_non_missing(
    frame: pd.DataFrame, profile: DatasetProfile
):
    step = GroupedAggregationParams(
        group_by=("region",), value_column="demand_mwh", aggregations=("count", "mean", "max")
    )
    (artifact,) = _run(frame, profile, step)
    groups = typing.cast(list[dict[str, Any]], artifact.result["groups"])
    reference = frame.groupby("region")["demand_mwh"].agg(["count", "mean", "max"])
    assert [g["keys"]["region"] for g in groups] == sorted(reference.index)
    for group in groups:
        row = reference.loc[group["keys"]["region"]]
        assert group["count"] == int(row["count"])
        assert group["mean"] == pytest.approx(row["mean"], abs=1e-6)
        assert group["max"] == pytest.approx(row["max"], abs=1e-6)
    assert artifact.result["total_groups"] == 4
    assert artifact.result["truncated"] is False
    # Duplicate rows are data, not errors: all 485 rows are used (4 have a missing value).
    assert sum(g["count"] for g in groups) == 485 - 4


def test_grouped_aggregation_truncates_and_warns(frame: pd.DataFrame, profile: DatasetProfile):
    step = GroupedAggregationParams(
        group_by=("date",), value_column="demand_mwh", aggregations=("count",), max_groups=5
    )
    (artifact,) = _run(frame, profile, step)
    assert len(typing.cast(list[Any], artifact.result["groups"])) == 5
    assert artifact.result["total_groups"] == 120
    assert artifact.result["truncated"] is True
    assert artifact.result["groups"][0]["keys"] == {"date": "2025-01-01"}  # type: ignore[index]
    assert any("first 5 of 120" in w for w in artifact.warnings)


def test_grouped_aggregation_count_only_is_allowed_for_text_values(
    frame: pd.DataFrame, profile: DatasetProfile
):
    step = GroupedAggregationParams(
        group_by=("region",), value_column="holiday", aggregations=("count",)
    )
    (artifact,) = _run(frame, profile, step)
    groups = typing.cast(list[dict[str, Any]], artifact.result["groups"])
    assert sum(g["count"] for g in groups) == 485


def test_correlation_matches_pandas_and_is_symmetric(frame: pd.DataFrame, profile: DatasetProfile):
    (artifact,) = _run(frame, profile, CorrelationParams(columns=("demand_mwh", "temperature_c")))
    matrix = typing.cast(list[list[float]], artifact.result["matrix"])
    expected = frame[["demand_mwh", "temperature_c"]].corr().iloc[0, 1]
    assert matrix[0][1] == pytest.approx(expected, abs=1e-6)
    assert matrix[0][1] == matrix[1][0]
    assert matrix[0][0] == pytest.approx(1.0)
    counts = typing.cast(list[list[int]], artifact.result["pair_counts"])
    assert counts[0][0] == 485 - 4
    assert counts[1][1] == 485 - 12
    assert any("excluded pairwise" in w for w in artifact.warnings)
    assert artifact.provenance.rows_used == counts[0][1]


def test_spearman_correlation_runs(frame: pd.DataFrame, profile: DatasetProfile):
    (artifact,) = _run(
        frame,
        profile,
        CorrelationParams(columns=("demand_mwh", "temperature_c"), method="spearman"),
    )
    expected = frame[["demand_mwh", "temperature_c"]].corr(method="spearman").iloc[0, 1]
    assert artifact.result["matrix"][0][1] == pytest.approx(expected, abs=1e-6)  # type: ignore[index]


def test_distribution_histogram_counts_every_non_missing_value(
    frame: pd.DataFrame, profile: DatasetProfile
):
    (artifact,) = _run(frame, profile, DistributionParams(column="temperature_c", bins=8))
    counts = typing.cast(list[int], artifact.result["counts"])
    edges = typing.cast(list[float], artifact.result["bin_edges"])
    assert artifact.result["kind"] == "histogram"
    assert len(counts) == 8
    assert len(edges) == 9
    assert sum(counts) == 485 - 12
    assert artifact.result["missing"] == 12
    assert edges[0] == pytest.approx(9.4)
    assert edges[-1] == pytest.approx(31.3)


def test_distribution_of_a_category_is_ordered_and_limited(
    frame: pd.DataFrame, profile: DatasetProfile
):
    (artifact,) = _run(frame, profile, DistributionParams(column="region", top_n=2))
    values = typing.cast(list[dict[str, Any]], artifact.result["values"])
    reference = frame["region"].value_counts()
    assert artifact.result["kind"] == "categories"
    assert artifact.result["distinct"] == 4
    assert len(values) == 2
    assert values[0]["count"] >= values[1]["count"]
    assert values[0]["count"] == int(reference.max())
    assert any("2 most frequent of 4" in w for w in artifact.warnings)


def test_distribution_of_dates_uses_iso_strings(frame: pd.DataFrame, profile: DatasetProfile):
    (artifact,) = _run(frame, profile, DistributionParams(column="date", top_n=1))
    value = artifact.result["values"][0]["value"]  # type: ignore[index]
    assert value.startswith("2025-")


# --- artifacts: provenance, JSON safety, determinism -------------------------------------


def test_artifact_records_parameters_and_provenance(frame: pd.DataFrame, profile: DatasetProfile):
    step = CorrelationParams(columns=("demand_mwh", "temperature_c"), method="spearman")
    (artifact,) = _run(frame, profile, step)
    assert artifact.operation == "correlation"
    assert artifact.parameters == {
        "operation": "correlation",
        "columns": ["demand_mwh", "temperature_c"],
        "method": "spearman",
    }
    assert artifact.provenance.dataset_fingerprint == profile.dataset_fingerprint
    assert artifact.provenance.rows_in_dataset == 485
    assert {"pandas", "numpy", "scipy", "scikit-learn"} <= set(artifact.provenance.library_versions)


def test_results_serialise_to_strict_json_and_are_deterministic(
    frame: pd.DataFrame, profile: DatasetProfile
):
    steps = (
        SummaryStatsParams(columns=("demand_mwh",)),
        GroupedAggregationParams(
            group_by=("region", "holiday"), value_column="demand_mwh", aggregations=("mean", "std")
        ),
        CorrelationParams(columns=("demand_mwh", "temperature_c")),
        DistributionParams(column="demand_mwh"),
        OutlierSummaryParams(columns=("demand_mwh",)),
    )
    first = _run(frame, profile, *steps)
    second = _run(frame, profile, *steps)
    for artifact in first:
        json.loads(artifact.model_dump_json(), parse_constant=_reject_constant)
    assert [a.model_dump() for a in first] == [a.model_dump() for a in second]


def _reject_constant(name: str) -> None:
    raise AssertionError(f"non-finite JSON constant {name}")


def test_undefined_statistics_are_none_not_nan():
    csv = b"k,v,w\na,1,5\nb,2,5\nc,3,5\n"
    from ai_data_analyst.ingestion import load_csv

    loaded = load_csv(csv, "t.csv")
    prof = profile_ingested(loaded)
    constant = typed_frame(loaded, prof)
    (corr,) = _run(constant, prof, CorrelationParams(columns=("v", "w")))
    assert corr.result["matrix"][0][1] is None  # type: ignore[index]
    assert any("undefined" in w for w in corr.warnings)
    (stats,) = _run(constant, prof, SummaryStatsParams(columns=("w",)))
    assert stats.result["columns"]["w"]["std"] == 0.0  # type: ignore[index]
    assert all(
        not (isinstance(x, float) and math.isnan(x))
        for x in corr.result["matrix"][0]  # type: ignore[index]
    )


def test_all_missing_numeric_column_is_reported_not_fabricated():
    from ai_data_analyst.ingestion import load_csv

    loaded = load_csv(b"a,b\n1,\n2,\n", "t.csv")
    prof = profile_ingested(loaded)
    assert prof.columns[1].inferred_type == "string"  # no values => string, so it is rejected
    with pytest.raises(PlanValidationError):
        validate_plan(AnalysisPlan(steps=(SummaryStatsParams(columns=("b",)),)), prof)


# --- execution guards --------------------------------------------------------------------


def test_execute_plan_rejects_a_frame_that_does_not_match_the_profile(
    frame: pd.DataFrame, profile: DatasetProfile
):
    plan = AnalysisPlan(steps=(SummaryStatsParams(columns=("demand_mwh",)),))
    with pytest.raises(ValueError, match="row count"):
        execute_plan(plan, frame.iloc[:10], profile)


def test_execute_plan_enforces_time_limit_between_steps(
    frame: pd.DataFrame, profile: DatasetProfile, monkeypatch: pytest.MonkeyPatch
):
    from ai_data_analyst.analysis import operations

    ticks = iter([0.0, 100.0, 100.0, 100.0])
    monkeypatch.setattr(operations.time, "monotonic", lambda: next(ticks))
    plan = AnalysisPlan(steps=(SummaryStatsParams(columns=("demand_mwh",)),))
    with pytest.raises(ExecutionTimeError):
        execute_plan(plan, frame, profile, LimitsConfig(max_execution_seconds=1))
