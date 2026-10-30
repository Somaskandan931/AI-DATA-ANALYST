"""Row filter step (FilterRowsStep): checked against plain pandas on the raw CSV."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pydantic import ValidationError

from ai_data_analyst.analysis import (
    CleaningError,
    CleaningPlan,
    FilterCondition,
    FilterRowsStep,
    PlanValidationError,
    SummaryStatsParams,
    apply_cleaning,
    cleaned_view,
    execute_plan_on_view,
    typed_frame,
    validate_cleaning,
)
from ai_data_analyst.ingestion import IngestedCSV, load_csv_path
from ai_data_analyst.models import DatasetProfile
from ai_data_analyst.profiling import profile_ingested


@pytest.fixture(scope="module")
def ingested(sample_csv_path: Path) -> IngestedCSV:
    return load_csv_path(sample_csv_path)


@pytest.fixture(scope="module")
def profile(ingested: IngestedCSV) -> DatasetProfile:
    return profile_ingested(ingested)


@pytest.fixture(scope="module")
def raw(sample_csv_path: Path) -> pd.DataFrame:
    return pd.read_csv(sample_csv_path)


def _filter(*conditions: tuple[Any, ...]) -> CleaningPlan:
    built = tuple(FilterCondition(column=c, op=o, value=v) for c, o, v in conditions)
    return CleaningPlan(steps=(FilterRowsStep(conditions=built),))


def _ids(ingested: IngestedCSV, profile: DatasetProfile, plan: CleaningPlan) -> list[str]:
    return cleaned_view(ingested, profile, plan).frame["record_id"].tolist()


# --- results equal independent pandas on the raw file ------------------------------------


@pytest.mark.parametrize(
    ("conditions", "mask"),
    [
        ([("demand_mwh", "gt", 1500)], lambda r: r.demand_mwh > 1500),
        ([("demand_mwh", "ge", 1106.7)], lambda r: r.demand_mwh >= 1106.7),
        ([("demand_mwh", "lt", 900)], lambda r: r.demand_mwh < 900),
        ([("demand_mwh", "le", 740.5)], lambda r: r.demand_mwh <= 740.5),
        ([("region", "eq", "North")], lambda r: r.region == "North"),
        ([("region", "ne", "North")], lambda r: r.region.notna() & (r.region != "North")),
        (
            [("region", "in", ("North", "South"))],
            lambda r: r.region.isin(["North", "South"]),
        ),
        (
            [("region", "not_in", ("North", "South"))],
            lambda r: r.region.notna() & ~r.region.isin(["North", "South"]),
        ),
        ([("temperature_c", "is_missing", None)], lambda r: r.temperature_c.isna()),
        ([("temperature_c", "is_not_missing", None)], lambda r: r.temperature_c.notna()),
        ([("date", "ge", "2025-03-01")], lambda r: r.date >= "2025-03-01"),
        ([("date", "lt", "2025-02-01")], lambda r: r.date < "2025-02-01"),
        ([("date", "eq", "2025-01-15")], lambda r: r.date == "2025-01-15"),
        (
            [("region", "eq", "East"), ("demand_mwh", "gt", 900), ("temperature_c", "ge", 20)],
            lambda r: (r.region == "East") & (r.demand_mwh > 900) & (r.temperature_c >= 20),
        ),
    ],
)
def test_filter_matches_pandas(
    ingested: IngestedCSV,
    profile: DatasetProfile,
    raw: pd.DataFrame,
    conditions: list[tuple[Any, ...]],
    mask: Any,
) -> None:
    expected = raw.loc[mask(raw).fillna(False).astype(bool), "record_id"].tolist()
    assert expected, "test case must select something"
    assert _ids(ingested, profile, _filter(*conditions)) == expected


def test_missing_values_satisfy_only_is_missing(
    ingested: IngestedCSV, profile: DatasetProfile, raw: pd.DataFrame
) -> None:
    missing_ids = set(raw.loc[raw.demand_mwh.isna(), "record_id"])
    assert missing_ids
    for op, value in (
        ("gt", -1.0),
        ("lt", 1e9),
        ("ge", 0),
        ("le", 1e9),
        ("eq", 1106.7),
        ("ne", 1.0),
    ):
        assert not missing_ids & set(_ids(ingested, profile, _filter(("demand_mwh", op, value))))
    assert not missing_ids & set(
        _ids(ingested, profile, _filter(("demand_mwh", "not_in", (1.0, 2.0))))
    )
    only = set(_ids(ingested, profile, _filter(("demand_mwh", "is_missing", None))))
    assert only == missing_ids


def test_log_row_counts_and_condition_text(ingested: IngestedCSV, profile: DatasetProfile) -> None:
    view = cleaned_view(
        ingested,
        profile,
        _filter(("region", "in", ("North", "South")), ("demand_mwh", "gt", 1500)),
    )
    assert view.rows_before == 485 and view.rows_after == len(view.frame)
    assert view.log == (
        f'Kept {view.rows_after} of 485 rows where region in ("North", "South") '
        "AND demand_mwh > 1500",
    )


def test_filter_composes_with_other_steps_in_order(
    ingested: IngestedCSV, profile: DatasetProfile, raw: pd.DataFrame
) -> None:
    from ai_data_analyst.analysis import DropMissingRowsStep

    plan = CleaningPlan(
        steps=(
            FilterRowsStep(conditions=(FilterCondition(column="region", op="eq", value="West"),)),
            DropMissingRowsStep(columns=("demand_mwh",)),
        )
    )
    view = cleaned_view(ingested, profile, plan)
    west = raw[(raw.region == "West") & raw.demand_mwh.notna()]
    assert view.rows_after == len(west)
    assert len(view.log) == 2 and view.log[0].startswith("Kept")


def test_analysis_on_filtered_view_uses_only_kept_rows_and_records_log(
    ingested: IngestedCSV, profile: DatasetProfile, raw: pd.DataFrame
) -> None:
    from ai_data_analyst.analysis import AnalysisPlan

    view = cleaned_view(ingested, profile, _filter(("region", "eq", "North")))
    artifact = execute_plan_on_view(
        AnalysisPlan(steps=(SummaryStatsParams(columns=("demand_mwh",)),)), view, profile
    )[0]
    assert artifact.provenance.cleaning == view.log
    assert artifact.provenance.rows_in_dataset == int((raw.region == "North").sum())


def test_filter_never_modifies_ingested_or_typed_frames(
    ingested: IngestedCSV, profile: DatasetProfile
) -> None:
    typed = typed_frame(ingested, profile)
    raw_before, typed_before = ingested.frame.copy(deep=True), typed.copy(deep=True)
    apply_cleaning(_filter(("region", "eq", "North")), typed, profile)
    pd.testing.assert_frame_equal(ingested.frame, raw_before)
    pd.testing.assert_frame_equal(typed, typed_before)


# --- rejection paths ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "op", "value", "message"),
    [
        ("salary", "eq", 1, "unknown column"),
        ("region", "gt", "A", "cannot order"),
        ("holiday", "lt", "yes", "cannot order"),
        ("demand_mwh", "gt", "1000", "does not fit"),
        ("demand_mwh", "eq", True, "does not fit"),
        ("region", "eq", 5, "does not fit"),
        ("date", "ge", "2025/03/01", "does not fit"),
        ("date", "ge", "2025-13-45", "does not fit"),
        ("date", "ge", "2025-3-1", "does not fit"),
        ("date", "ge", 20250301, "does not fit"),
        ("demand_mwh", "in", (1.0, "x"), "does not fit"),
    ],
)
def test_validation_rejects_values_that_do_not_fit_the_column(
    profile: DatasetProfile, column: str, op: str, value: Any, message: str
) -> None:
    with pytest.raises(PlanValidationError, match=message):
        validate_cleaning(_filter((column, op, value)), profile)


def test_filter_that_removes_every_row_fails_closed(
    ingested: IngestedCSV, profile: DatasetProfile
) -> None:
    with pytest.raises(CleaningError, match="removed every row"):
        cleaned_view(ingested, profile, _filter(("demand_mwh", "gt", 1e9)))


@pytest.mark.parametrize(
    ("op", "value"),
    [
        ("eq", None),
        ("eq", (1, 2)),
        ("gt", None),
        ("in", 5),
        ("in", ()),
        ("in", tuple(range(51))),
        ("is_missing", 1),
        ("is_not_missing", "x"),
        ("eq", float("inf")),
        ("eq", "x" * 201),
    ],
)
def test_condition_shape_is_validated(op: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        FilterCondition(column="demand_mwh", op=op, value=value)


def test_unknown_operator_extra_fields_and_empty_conditions_are_rejected() -> None:
    with pytest.raises(ValidationError):
        FilterCondition(column="x", op="like", value="a")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        FilterCondition(column="x", op="eq", value=1, expr="1==1")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        FilterRowsStep(conditions=())
    with pytest.raises(ValidationError):
        FilterRowsStep(
            conditions=tuple(FilterCondition(column="x", op="eq", value=1) for _ in range(11))
        )


def test_expression_like_strings_are_plain_values_not_code(
    ingested: IngestedCSV, profile: DatasetProfile
) -> None:
    payload = "North' or '1'=='1"
    with pytest.raises(CleaningError):  # no row has that exact value
        cleaned_view(ingested, profile, _filter(("region", "eq", payload)))


def test_plan_round_trips_through_json() -> None:
    plan = _filter(("region", "in", ("North", "South")), ("date", "ge", "2025-02-01"))
    assert CleaningPlan.model_validate_json(plan.model_dump_json()) == plan


# --- boolean columns ---------------------------------------------------------------------


def test_boolean_column_filters_and_rejects_non_bool(tmp_path: Path) -> None:
    path = tmp_path / "flags.csv"
    path.write_text("id,flag\na,true\nb,false\nc,\nd,true\n", encoding="utf-8")
    data = load_csv_path(path)
    prof = profile_ingested(data)
    assert {c.name: c.inferred_type for c in prof.columns}["flag"] == "boolean"
    assert _ids2(data, prof, ("flag", "eq", True)) == ["a", "d"]
    assert _ids2(data, prof, ("flag", "ne", True)) == ["b"]  # missing is not "not true"
    assert _ids2(data, prof, ("flag", "is_missing", None)) == ["c"]
    with pytest.raises(PlanValidationError, match="does not fit"):
        validate_cleaning(_filter(("flag", "eq", "true")), prof)


def _ids2(data: IngestedCSV, prof: DatasetProfile, cond: tuple[Any, ...]) -> list[str]:
    return cleaned_view(data, prof, _filter(cond)).frame["id"].tolist()


# --- workspace parsing, chat honesty, and the page ---------------------------------------


def test_parse_filter_condition_types_the_text_by_column(profile: DatasetProfile) -> None:
    from ai_data_analyst.ui import workspace as ws_api

    parse = ws_api.parse_filter_condition
    assert parse(profile, "demand_mwh", "is greater than", " 1500 ") == FilterCondition(
        column="demand_mwh", op="gt", value=1500
    )
    assert parse(profile, "demand_mwh", "is at most", "1500.5").value == 1500.5
    assert parse(profile, "region", "is one of (comma-separated)", "North, South ,").value == (
        "North",
        "South",
    )
    assert parse(profile, "date", "is at least", "2025-03-01").value == "2025-03-01"
    assert parse(profile, "temperature_c", "is missing", "ignored text").value is None


@pytest.mark.parametrize(
    ("column", "operator", "text", "message"),
    [
        ("salary", "equals", "1", "unknown column"),
        ("region", "matches", "x", "unknown filter operator"),
        ("demand_mwh", "equals", "abc", "not a number"),
        ("demand_mwh", "equals", "nan", "finite"),
        ("demand_mwh", "equals", "", "enter a value"),
        ("region", "is one of (comma-separated)", " , ", "at least one value"),
    ],
)
def test_parse_filter_condition_rejects_bad_input(
    profile: DatasetProfile, column: str, operator: str, text: str, message: str
) -> None:
    from ai_data_analyst.ui import workspace as ws_api

    with pytest.raises(ws_api.WorkspaceError, match=message):
        ws_api.parse_filter_condition(profile, column, operator, text)


def test_workspace_filter_flow_discards_artifacts_and_feeds_the_report(
    sample_csv_path: Path, raw: pd.DataFrame
) -> None:
    from ai_data_analyst.ui import workspace as ws_api

    workspace = ws_api.load_sample(sample_csv_path)
    ws_api.run_step(workspace, SummaryStatsParams(columns=("demand_mwh",)))
    ws_api.set_cleaning(workspace, _filter(("region", "eq", "North")))
    assert workspace.artifacts == [] and workspace.view is not None
    assert workspace.view.rows_after == int((raw.region == "North").sum())
    artifact = ws_api.run_step(workspace, SummaryStatsParams(columns=("demand_mwh",)))
    assert artifact.provenance.rows_in_dataset == workspace.view.rows_after
    html_text, markdown_text = ws_api.report_files(workspace, "Filtered")
    assert "Kept" in html_text and "Kept" in markdown_text
    ws_api.set_cleaning(workspace, CleaningPlan())
    assert workspace.view is None


def test_failed_filter_leaves_the_workspace_unchanged(sample_csv_path: Path) -> None:
    from ai_data_analyst.ui import workspace as ws_api

    workspace = ws_api.load_sample(sample_csv_path)
    ws_api.run_step(workspace, SummaryStatsParams(columns=("demand_mwh",)))
    with pytest.raises(CleaningError):
        ws_api.set_cleaning(workspace, _filter(("demand_mwh", "gt", 1e9)))
    assert len(workspace.artifacts) == 1 and workspace.view is None


def test_profile_answers_say_they_describe_the_upload_when_a_filter_is_active(
    sample_csv_path: Path,
) -> None:
    from ai_data_analyst.ui import workspace as ws_api

    workspace = ws_api.load_sample(sample_csv_path)
    plain = ws_api.ask(workspace, "how many rows?")
    assert plain.warnings == ()
    ws_api.set_cleaning(workspace, _filter(("region", "eq", "North")))
    answer = ws_api.ask(workspace, "how many rows?")
    assert answer.status == "profile" and "485" in answer.text
    assert len(answer.warnings) == 1
    assert "as uploaded, not the cleaned data" in answer.warnings[0]
    assert "Kept 122 of 485 rows" in answer.warnings[0]
    computed = ws_api.ask(workspace, "average demand_mwh by region")
    assert "Based on 122 rows" in computed.text


def test_page_applies_a_filter_and_shows_the_log_and_errors() -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    app = Path(__file__).resolve().parents[2] / "app.py"
    at = AppTest.from_file(str(app), default_timeout=60).run()
    at = next(b for b in at.button if b.label == "Use the sample dataset").click().run()
    at.selectbox(key="filter_column_0").select("region")
    at.text_input(key="filter_value_0").input("North")
    at = next(b for b in at.button if b.label == "Apply cleaning").click().run()
    assert not at.exception and not at.error
    texts = [t.value for t in at.text]
    assert any(t == "Rows: 485 before, 122 after" for t in texts)
    assert any('region = "North"' in t for t in texts)

    at.selectbox(key="filter_column_1").select("demand_mwh")
    at.text_input(key="filter_value_1").input("abc")
    at = next(b for b in at.button if b.label == "Apply cleaning").click().run()
    assert not at.exception
    assert any("not a number" in e.value for e in at.error)
