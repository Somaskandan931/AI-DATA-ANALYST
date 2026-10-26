import copy

import pytest
from pydantic import ValidationError

from ai_data_analyst.evaluation import (
    EvaluationResult,
    ProfileComparisonResult,
    ProfileMismatch,
    Tolerances,
    compare_profiles,
)
from ai_data_analyst.models import ColumnProfile, DatasetProfile

FINGERPRINT = "b" * 64


def _evaluation_result(**overrides: object) -> EvaluationResult:
    fields: dict[str, object] = {
        "metric_name": "accuracy",
        "value": 0.5,
        "sample_count": 1,
        "benchmark_version": "1.0",
    }
    fields.update(overrides)
    return EvaluationResult(**fields)


def _float_column(**overrides: object) -> ColumnProfile:
    fields: dict[str, object] = {
        "name": "x",
        "inferred_type": "float",
        "missing_count": 0,
        "unique_count": 1,
        "min": 0.0,
        "max": 2000.0,
        "mean": 1.0,
        "median": 1.0,
        "std": 0.0,
        "q1": 1.0,
        "q3": 1.0,
        "outlier_count": 0,
    }
    fields.update(overrides)
    return ColumnProfile(**fields)


def _date_column(**overrides: object) -> ColumnProfile:
    fields: dict[str, object] = {
        "name": "d",
        "inferred_type": "date",
        "missing_count": 0,
        "unique_count": 1,
        "min": "2025-01-01",
        "max": "2025-01-31",
    }
    fields.update(overrides)
    return ColumnProfile(**fields)


def _string_column(**overrides: object) -> ColumnProfile:
    fields: dict[str, object] = {
        "name": "s",
        "inferred_type": "string",
        "missing_count": 0,
        "unique_count": 1,
    }
    fields.update(overrides)
    return ColumnProfile(**fields)


def _profile(
    *columns: ColumnProfile,
    row_count: int = 1,
    duplicate_row_count: int = 0,
    fingerprint: str = FINGERPRINT,
) -> DatasetProfile:
    return DatasetProfile(
        dataset_fingerprint=fingerprint,
        row_count=row_count,
        column_count=len(columns),
        duplicate_row_count=duplicate_row_count,
        columns=columns,
    )


def test_expected_fixture_matches_itself(expected_profile):
    expected = DatasetProfile(**expected_profile)
    result = compare_profiles(expected, expected)
    assert result.matches
    assert result.mismatches == ()


def test_single_column_statistic_mismatch(expected_profile):
    data = copy.deepcopy(expected_profile)
    data["columns"][3]["mean"] = data["columns"][3]["mean"] + 1.0
    actual = DatasetProfile(**data)
    expected = DatasetProfile(**expected_profile)

    result = compare_profiles(actual, expected)

    assert [mismatch.field_path for mismatch in result.mismatches] == ["columns[3].mean"]
    assert result.mismatches[0].expected == expected.columns[3].mean
    assert result.mismatches[0].actual == actual.columns[3].mean
    assert not result.matches


def test_absolute_tolerance_at_boundary_matches():
    expected = _profile(_float_column(mean=1.0))
    actual = _profile(_float_column(mean=1.5))

    assert compare_profiles(actual, expected, Tolerances(absolute=0.5)).matches
    assert not compare_profiles(actual, expected, Tolerances(absolute=0.4999)).matches


def test_absolute_tolerance_just_over_boundary_is_a_mismatch():
    expected = _profile(_float_column(mean=1.0))
    actual = _profile(_float_column(mean=1.5000001))

    result = compare_profiles(actual, expected, Tolerances(absolute=0.5))

    assert [mismatch.field_path for mismatch in result.mismatches] == ["columns[0].mean"]


def test_relative_tolerance_boundary():
    expected = _profile(_float_column(mean=1000.0, median=1000.0, q1=1000.0, q3=1000.0))
    actual = _profile(_float_column(mean=1005.0, median=1000.0, q1=1000.0, q3=1000.0))

    assert compare_profiles(actual, expected, Tolerances(absolute=0.0, relative=0.005)).matches
    assert not compare_profiles(actual, expected, Tolerances(absolute=0.0, relative=0.004)).matches


def test_inferred_type_mismatch_is_exact():
    expected = _profile(_string_column(inferred_type="boolean"))
    actual = _profile(_string_column(inferred_type="string"))

    result = compare_profiles(actual, expected)

    assert [mismatch.field_path for mismatch in result.mismatches] == ["columns[0].inferred_type"]


def test_column_name_mismatch_is_exact_and_stops_that_column():
    expected = _profile(_float_column(name="x"))
    actual = _profile(_float_column(name="y"))

    result = compare_profiles(actual, expected)

    assert [mismatch.field_path for mismatch in result.mismatches] == ["columns[0].name"]
    assert result.mismatches[0].expected == "x"
    assert result.mismatches[0].actual == "y"


def test_count_mismatch_is_exact():
    expected = _profile(_string_column(missing_count=0, unique_count=1), row_count=2)
    actual = _profile(_string_column(missing_count=1, unique_count=1), row_count=2)

    result = compare_profiles(actual, expected)

    assert [mismatch.field_path for mismatch in result.mismatches] == ["columns[0].missing_count"]


def test_date_range_compares_exactly_as_strings():
    expected = _profile(_date_column(max="2025-01-31"))
    actual = _profile(_date_column(max="2025-02-01"))

    result = compare_profiles(actual, expected)

    assert [mismatch.field_path for mismatch in result.mismatches] == ["columns[0].max"]
    assert result.mismatches[0].expected == "2025-01-31"
    assert result.mismatches[0].actual == "2025-02-01"


def test_all_mismatches_are_collected():
    expected = _profile(_float_column(mean=1.0))
    actual = _profile(_float_column(mean=2.0), row_count=2)

    result = compare_profiles(actual, expected)

    assert {mismatch.field_path for mismatch in result.mismatches} == {
        "row_count",
        "columns[0].mean",
    }
    assert len(result.mismatches) == 2


def test_fingerprint_mismatch_is_reported():
    expected = _profile(_string_column())
    actual = _profile(_string_column(), fingerprint="c" * 64)

    result = compare_profiles(actual, expected)

    assert [mismatch.field_path for mismatch in result.mismatches] == ["dataset_fingerprint"]


def test_extra_actual_column_is_reported():
    expected = _profile(_string_column(name="s"))
    actual = _profile(_string_column(name="s"), _string_column(name="t"))

    result = compare_profiles(actual, expected)

    assert {mismatch.field_path for mismatch in result.mismatches} == {
        "column_count",
        "columns[1].name",
    }
    assert result.mismatches[1].expected is None
    assert result.mismatches[1].actual == "t"


def test_missing_actual_column_is_reported():
    expected = _profile(_string_column(name="s"), _string_column(name="t"))
    actual = _profile(_string_column(name="s"))

    result = compare_profiles(actual, expected)

    assert {mismatch.field_path for mismatch in result.mismatches} == {
        "column_count",
        "columns[1].name",
    }
    assert result.mismatches[1].expected == "t"
    assert result.mismatches[1].actual is None


@pytest.mark.parametrize("field_name", ["absolute", "relative"])
@pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf")])
def test_tolerances_reject_invalid_values(field_name: str, value: float):
    with pytest.raises(ValidationError):
        Tolerances(**{field_name: value})


def test_evaluation_result_accepts_valid_metric():
    result = EvaluationResult(
        metric_name="profile_correctness",
        value=0.95,
        sample_count=20,
        benchmark_version="1.0",
    )
    assert result.value == 0.95


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_evaluation_result_rejects_non_finite_value(value: float):
    with pytest.raises(ValidationError):
        EvaluationResult(
            metric_name="accuracy",
            value=value,
            sample_count=1,
            benchmark_version="1.0",
        )


def test_evaluation_result_rejects_negative_sample_count():
    with pytest.raises(ValidationError):
        EvaluationResult(
            metric_name="accuracy",
            value=1.0,
            sample_count=-1,
            benchmark_version="1.0",
        )


@pytest.mark.parametrize("field_name", ["metric_name", "benchmark_version"])
def test_evaluation_result_rejects_empty_strings(field_name: str):
    with pytest.raises(ValidationError):
        _evaluation_result(**{field_name: ""})


def _profile_mismatch(**overrides: object) -> ProfileMismatch:
    fields: dict[str, object] = {"field_path": "columns[0].mean", "expected": 1.0, "actual": 1.5}
    fields.update(overrides)
    return ProfileMismatch(**fields)


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda **extra: _evaluation_result(**extra), id="EvaluationResult"),
        pytest.param(lambda **extra: Tolerances(**extra), id="Tolerances"),
        pytest.param(lambda **extra: _profile_mismatch(**extra), id="ProfileMismatch"),
        pytest.param(
            lambda **extra: ProfileComparisonResult(mismatches=(), **extra),
            id="ProfileComparisonResult",
        ),
    ],
)
def test_evaluation_models_reject_unknown_fields(build):
    with pytest.raises(ValidationError):
        build(surprise=1)


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda bad: _evaluation_result(value=bad), id="EvaluationResult"),
        pytest.param(lambda bad: Tolerances(absolute=bad), id="Tolerances"),
        pytest.param(
            lambda bad: _profile_mismatch(expected=bad),
            id="ProfileMismatch",
        ),
        pytest.param(
            lambda bad: ProfileComparisonResult(
                mismatches=({"field_path": "p", "expected": bad, "actual": 1.0},)
            ),
            id="ProfileComparisonResult",
        ),
    ],
)
def test_evaluation_models_reject_non_finite_numbers(build, bad_value: float):
    with pytest.raises(ValidationError):
        build(bad_value)


@pytest.mark.parametrize(
    "model",
    [
        pytest.param(_evaluation_result(), id="EvaluationResult"),
        pytest.param(Tolerances(), id="Tolerances"),
        pytest.param(_profile_mismatch(), id="ProfileMismatch"),
        pytest.param(
            ProfileComparisonResult(mismatches=(_profile_mismatch(),)),
            id="ProfileComparisonResult",
        ),
    ],
)
def test_evaluation_models_json_round_trip(model):
    round_tripped = type(model).model_validate_json(model.model_dump_json())
    assert round_tripped == model


@pytest.mark.parametrize(
    ("model", "field_name", "replacement"),
    [
        pytest.param(_evaluation_result(), "value", 1.0, id="EvaluationResult"),
        pytest.param(Tolerances(), "absolute", 0.0, id="Tolerances"),
        pytest.param(_profile_mismatch(), "field_path", "other", id="ProfileMismatch"),
        pytest.param(
            ProfileComparisonResult(mismatches=()),
            "mismatches",
            (),
            id="ProfileComparisonResult",
        ),
    ],
)
def test_evaluation_models_are_immutable(model, field_name: str, replacement):
    with pytest.raises(ValidationError):
        setattr(model, field_name, replacement)


def test_comparison_result_normalizes_mismatches_to_a_tuple():
    mismatch = {
        "field_path": "columns[0].mean",
        "expected": 1.0,
        "actual": 1.5,
    }
    result = ProfileComparisonResult(mismatches=[mismatch])
    assert isinstance(result.mismatches, tuple)
    assert isinstance(result.mismatches[0], ProfileMismatch)
