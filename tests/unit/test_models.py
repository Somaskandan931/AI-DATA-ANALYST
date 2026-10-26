import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_data_analyst.models import PROFILE_SCHEMA_VERSION, ColumnProfile, DatasetProfile

FINGERPRINT = "a" * 64


def _column(**overrides: object) -> ColumnProfile:
    fields: dict[str, object] = {
        "name": "a",
        "inferred_type": "string",
        "missing_count": 0,
        "unique_count": 1,
    }
    fields.update(overrides)
    return ColumnProfile(**fields)


def _profile(**overrides: object) -> DatasetProfile:
    fields: dict[str, object] = {
        "dataset_fingerprint": FINGERPRINT,
        "row_count": 1,
        "column_count": 1,
        "duplicate_row_count": 0,
        "columns": (_column(),),
    }
    fields.update(overrides)
    return DatasetProfile(**fields)


def test_profile_defaults_to_current_schema_version():
    assert _profile().schema_version == PROFILE_SCHEMA_VERSION


def test_expected_fixture_loads_from_dict(expected_profile):
    profile = DatasetProfile(**expected_profile)
    assert profile.schema_version == PROFILE_SCHEMA_VERSION
    assert profile.row_count == 485
    assert profile.column_count == 6


def test_expected_fixture_loads_from_json(expected_profile_path: Path):
    profile = DatasetProfile.model_validate_json(expected_profile_path.read_text(encoding="utf-8"))
    assert profile.row_count == 485
    assert [column.name for column in profile.columns] == [
        "record_id",
        "date",
        "region",
        "demand_mwh",
        "temperature_c",
        "holiday",
    ]


def test_json_round_trip_is_lossless(expected_profile, expected_profile_path: Path):
    profile = DatasetProfile(**expected_profile)
    reloaded = DatasetProfile.model_validate_json(profile.model_dump_json())
    assert reloaded == profile
    assert json.loads(profile.model_dump_json()) == expected_profile


def test_columns_are_an_immutable_tuple():
    profile = DatasetProfile(**json.loads(json.dumps(_profile().model_dump())))
    assert isinstance(profile.columns, tuple)


def test_mutating_columns_fails():
    profile = _profile()
    with pytest.raises(ValidationError):
        profile.columns = ()
    with pytest.raises(ValidationError):
        profile.columns[0].mean = 1.0


def test_column_count_must_match_columns():
    with pytest.raises(ValidationError):
        _profile(column_count=2)


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        ColumnProfile(
            name="a",
            inferred_type="string",
            missing_count=0,
            unique_count=1,
            surprise=1,
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_statistics_are_rejected(value: float):
    with pytest.raises(ValidationError):
        _column(inferred_type="float", mean=value)


def test_non_finite_min_max_are_rejected():
    with pytest.raises(ValidationError):
        _column(inferred_type="float", min=float("nan"))
    with pytest.raises(ValidationError):
        _column(inferred_type="float", max=float("-inf"))


@pytest.mark.parametrize("version", ["0.9", "1.1", "2.0", ""])
def test_wrong_schema_version_is_rejected(version: str):
    with pytest.raises(ValidationError):
        _profile(schema_version=version)


@pytest.mark.parametrize(
    "fingerprint",
    ["x", "A" * 64, "a" * 63, "a" * 65, "g" * 64],
)
def test_bad_fingerprint_is_rejected(fingerprint: str):
    with pytest.raises(ValidationError):
        _profile(dataset_fingerprint=fingerprint)


def test_duplicate_column_names_are_rejected():
    with pytest.raises(ValidationError):
        _profile(column_count=2, columns=(_column(), _column()))


@pytest.mark.parametrize("inferred_type", ["boolean", "date", "string"])
@pytest.mark.parametrize(
    "field_name",
    ["mean", "median", "std", "q1", "q3", "outlier_count"],
)
def test_numeric_statistics_on_non_numeric_column_are_rejected(inferred_type: str, field_name: str):
    with pytest.raises(ValidationError):
        _column(inferred_type=inferred_type, **{field_name: 1.0})


def test_numeric_statistics_on_float_column_are_accepted():
    column = _column(
        inferred_type="float",
        min=1.0,
        max=3.0,
        mean=2.0,
        median=2.0,
        std=1.0,
        q1=1.5,
        q3=2.5,
        outlier_count=0,
    )
    assert column.outlier_count == 0


def test_numeric_statistics_on_integer_column_are_accepted():
    column = _column(
        inferred_type="integer",
        min=1.0,
        max=3.0,
        mean=2.0,
        median=2.0,
        std=1.0,
        q1=1.0,
        q3=3.0,
        outlier_count=0,
    )
    assert column.q1 == 1.0


@pytest.mark.parametrize(
    ("q1", "median", "q3"),
    [(2.0, 1.0, 3.0), (1.0, 3.0, 2.0), (2.0, 2.0, 1.0)],
)
def test_quartiles_must_be_ordered(q1: float, median: float, q3: float):
    with pytest.raises(ValidationError):
        _column(inferred_type="float", q1=q1, median=median, q3=q3)


def test_equal_quartiles_are_accepted():
    column = _column(inferred_type="float", q1=2.0, median=2.0, q3=2.0)
    assert column.q1 == column.q3 == 2.0


def test_min_must_not_exceed_max():
    with pytest.raises(ValidationError):
        _column(inferred_type="float", min=2.0, max=1.0)


def test_equal_min_and_max_are_accepted():
    column = _column(inferred_type="float", min=2.0, max=2.0)
    assert column.min == column.max == 2.0


def test_missing_count_must_not_exceed_row_count():
    with pytest.raises(ValidationError):
        _profile(row_count=1, columns=(_column(missing_count=2, unique_count=0),))


def test_unique_count_must_not_exceed_non_missing_rows():
    with pytest.raises(ValidationError):
        _profile(row_count=2, columns=(_column(missing_count=1, unique_count=2),))


def test_duplicate_row_count_must_be_less_than_row_count():
    with pytest.raises(ValidationError):
        _profile(row_count=1, duplicate_row_count=1)


def test_duplicate_row_count_below_row_count_is_accepted():
    profile = _profile(
        row_count=2,
        duplicate_row_count=1,
        columns=(_column(missing_count=0, unique_count=2),),
    )
    assert profile.duplicate_row_count == 1


def test_empty_dataset_is_accepted():
    profile = _profile(
        row_count=0,
        duplicate_row_count=0,
        columns=(_column(missing_count=0, unique_count=0),),
    )
    assert profile.row_count == 0
